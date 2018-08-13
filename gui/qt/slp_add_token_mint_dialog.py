import copy
import datetime
from functools import partial
import json
import threading

from PyQt5.QtCore import *
from PyQt5.QtGui import *
from PyQt5.QtWidgets import *

from electroncash.address import Address, PublicKey
from electroncash.bitcoin import base_encode, TYPE_ADDRESS
from electroncash.i18n import _
from electroncash.plugins import run_hook

from electroncash.util import bfh
from .util import *

from electroncash.util import format_satoshis_nofloat
from electroncash.transaction import Transaction
from electroncash.slp import SlpMessage, SlpNoMintingBatonFound, SlpUnsupportedSlpTokenType, SlpInvalidOutputMessage, SlpTokenTransactionFactory

from .amountedit import SLPAmountEdit

dialogs = []  # Otherwise python randomly garbage collects the dialogs...

class SlpAddTokenMintDialog(QDialog, MessageBoxMixin):

    got_network_response_sig = pyqtSignal()

    @pyqtSlot()
    def got_network_response_slot(self):
        self.download_finished = True

        resp = self.json_response
        if resp.get('error'):
            return self.fail_genesis_info("Download error!\n%r"%(resp['error'].get('message')))
        raw = resp.get('result')

        tx = Transaction(raw)
        self.populate_genesis_data(tx)

    def __init__(self, main_window, token_id_hex):
        # We want to be a top-level window
        QDialog.__init__(self, parent=main_window)

        self.main_window = main_window
        self.wallet = main_window.wallet
        self.network = main_window.network
        self.app = main_window.app

        # IMPORTANT: set to None to guard tokens when Send tab may have a token selected
        self.wallet.send_slpTokenId = None

        self.genesis_tx = None

        self.setWindowTitle(_("Mint Additional Tokens"))

        vbox = QVBoxLayout()
        self.setLayout(vbox)

        msg = _('Unique identifier for the token.')
        vbox.addWidget(HelpLabel(_('Token ID:'), msg))
        self.token_id_e = ButtonsLineEdit()
        self.token_id_e.setFixedWidth(550)
        self.token_id_e.setText(token_id_hex)
        self.token_id_e.setDisabled(True)
        vbox.addWidget(self.token_id_e)

        self.view_tx_button = b = QPushButton(_("View Genesis Tx"))
        b.clicked.connect(self.view_tx)
        vbox.addWidget(self.view_tx_button)
        self.view_tx_button.setDisabled(True)

        msg = _('The number of existing tokens for this token.')
        vbox.addWidget(HelpLabel(_('Existing Token Quantity:'), msg))
        self.token_ex_qty = SLPAmountEdit('tokens', 0)
        self.token_ex_qty.setFixedWidth(125)
        self.token_ex_qty.setDisabled(True)
        vbox.addWidget(self.token_ex_qty)

        msg = _('The number of decimal places used in the token quantity.')
        vbox.addWidget(HelpLabel(_('Decimals:'), msg))
        self.token_dec = QDoubleSpinBox()
        self.token_dec.setRange(0, 9)
        self.token_dec.setDecimals(0)
        self.token_dec.setFixedWidth(50)
        self.token_dec.setDisabled(True)
        vbox.addWidget(self.token_dec)

        msg = _('The number of tokens created during token minting transaction, send to the receiver address provided below.')
        vbox.addWidget(HelpLabel(_('Additional Token Quantity:'), msg))
        self.token_qty_e = SLPAmountEdit('tokens', 0)
        self.token_qty_e.setFixedWidth(125)
        vbox.addWidget(self.token_qty_e)

        msg = _('The simpleledger formatted bitcoin address for the genesis receiver of all genesis tokens.')
        vbox.addWidget(HelpLabel(_('Token Receiver Address:'), msg))
        self.token_pay_to_e = ButtonsLineEdit()
        self.token_pay_to_e.setFixedWidth(400)
        vbox.addWidget(self.token_pay_to_e)

        self.token_fixed_supply_cb = cb = QCheckBox(_('Fixed Supply'))
        self.token_fixed_supply_cb.setChecked(True)
        vbox.addWidget(self.token_fixed_supply_cb)
        cb.clicked.connect(self.show_mint_baton_address)

        msg = _('The simpleledger formatted bitcoin address for the genesis baton receiver.')
        self.token_baton_label = HelpLabel(_('Mint Baton Address:'), msg)
        self.token_baton_label.setHidden(True)
        vbox.addWidget(self.token_baton_label)
        self.token_baton_to_e = ButtonsLineEdit()
        self.token_baton_to_e.setFixedWidth(400)
        self.token_baton_to_e.setHidden(True)
        vbox.addWidget(self.token_baton_to_e)

        hbox = QHBoxLayout()
        vbox.addLayout(hbox)

        self.cancel_button = b = QPushButton(_("Cancel"))
        self.cancel_button.setAutoDefault(False)
        self.cancel_button.setDefault(False)
        b.clicked.connect(self.close)
        b.setDefault(True)
        hbox.addWidget(self.cancel_button)

        hbox.addStretch(1)

        self.mint_button = b = QPushButton(_("MINT")) #if self.provided_token_name is None else _("Change"))
        b.clicked.connect(self.mint_token)
        self.mint_button.setAutoDefault(True)
        self.mint_button.setDefault(True)
        hbox.addWidget(self.mint_button)

        dialogs.append(self)
        self.show()
        self.token_qty_e.setFocus()
        self.got_network_response_sig.connect(self.got_network_response_slot, Qt.QueuedConnection)
        self.download_info()

    def download_info(self):
        txid = self.token_id_e.text()
        try:
            tx = self.wallet.transactions[txid]
        except KeyError:
            def callback(response):
                self.json_response = response
                self.got_network_response_sig.emit()

            requests = [ ('blockchain.transaction.get', [txid]), ]
            self.network.send(requests, callback)
        else:
            self.populate_genesis_data(tx)

    def populate_genesis_data(self, tx):
        self.genesis_tx = tx
        self.view_tx_button.setDisabled(False)

        txid = tx.txid()
        token_id = self.token_id_e.text()
        if txid != token_id:
            return self.fail_genesis_info(_('Received wrong transaction!'))

        try:
            slpMsg = SlpMessage.parseSlpOutputScript(tx.outputs()[0][1])
        except SlpUnsupportedSlpTokenType as e:
            return self.fail_genesis_info(_("Unsupported SLP token version/type - %r.")%(e.args[0],))
        except SlpInvalidOutputMessage as e:
            return self.fail_genesis_info(_("This transaction does not contain a valid SLP message.\nReason: %r.")%(e.args,))
        if slpMsg.transaction_type != 'INIT':
            return self.fail_genesis_info(_("This SLP transaction is not a genesis."))

        self.token_dec.setValue(slpMsg.op_return_fields['decimals'])
        self.token_qty_e.token_decimals = slpMsg.op_return_fields['decimals']
        self.token_ex_qty.setAmount(slpMsg.op_return_fields['initial_token_mint_quantity'] / (10 ** slpMsg.op_return_fields['decimals']))
        self.token_ex_qty.token_decimals = slpMsg.op_return_fields['decimals']


    def view_tx(self,):
        self.main_window.show_transaction(self.genesis_tx)

    def show_mint_baton_address(self):
        self.token_baton_to_e.setHidden(self.token_fixed_supply_cb.isChecked())
        self.token_baton_label.setHidden(self.token_fixed_supply_cb.isChecked())

    def parse_address(self, address):
        if "simpleledger" not in address:
            address="simpleledger:"+address
        return Address.from_string(address)

    def mint_token(self):
        mint_baton_vout = 2 if self.token_baton_to_e.text() != '' else None
        try:
            init_mint_qty = int(float(self.token_qty_e.text()) * (10 ** int(self.token_dec.value())))
            if init_mint_qty > (2 ** 64) - 1:
                self.show_message(_("Token output quantity is too large."))
                return
        except ValueError:
            self.show_message(_("Invalid token quantity entered."))
            return

        outputs = []

        try:
            msgFactory = SlpTokenTransactionFactory(1, self.token_id_e.text())
            slp_op_return_msg = msgFactory.buildMintOpReturnOutput_V1(mint_baton_vout, init_mint_qty)
            outputs.append(slp_op_return_msg)
        except OPReturnTooLarge:
            self.show_message(_("Optional string text causiing OP_RETURN greater than 223 bytes."))
            return
        except Exception as e:
            traceback.print_exc(file=sys.stdout)
            self.show_message(str(e))
            return

        try:
            addr = self.parse_address(self.token_pay_to_e.text())
            outputs.append((TYPE_ADDRESS, addr, 546))
        except:
            self.show_message(_("Must have Receiver Address in simpleledger format."))
            return
        
        if not self.token_fixed_supply_cb.isChecked():
            try:
                addr = self.parse_address(self.token_baton_to_e.text())
                outputs.append((TYPE_ADDRESS, addr, 546))
            except:
                self.show_message(_("Must have Baton Address in simpleledger format."))
                return

        coins = self.main_window.get_coins()
        fee = None
        try:
            baton_input = self.main_window.wallet.get_slp_token_baton(self.token_id_e.text())
        except SlpNoMintingBatonFound as e:
            self.show_message(_("No baton exists for this token."))
            return

        try:
            tx = self.main_window.wallet.make_unsigned_transaction(coins, outputs, self.main_window.config, fee, None)
        except NotEnoughFunds:
            self.show_message(_("Insufficient funds"))
            return
        except ExcessiveFee:
            self.show_message(_("Your fee is too high.  Max is 50 sat/byte."))
            return
        except BaseException as e:
            traceback.print_exc(file=sys.stdout)
            self.show_message(str(e))
            return

        # Find & Add baton to tx inputs
        try:
            baton_utxo = self.main_window.wallet.get_slp_token_baton(self.token_id_e.text())
        except SlpNoMintingBatonFound:
            self.show_message(_("There is no minting baton found for this token."))
            return

        tx.add_inputs([baton_utxo])
        for txin in tx._inputs:
            self.main_window.wallet.add_input_info(txin)

        # TODO: adjust change amount (based on amount added from baton)

        msg = []

        if self.main_window.wallet.has_password():
            msg.append("")
            msg.append(_("Enter your password to proceed"))
            password = self.main_window.password_dialog('\n'.join(msg))
            if not password:
                return
        else:
            password = None

        tx_desc = None

        def sign_done(success):
            if success:
                if not tx.is_complete():
                    self.main_window.show_transaction(tx)
                    self.main_window.do_clear()
                else:
                    self.main_window.broadcast_transaction(tx, tx_desc)

        self.main_window.sign_tx_with_password(tx, sign_done, password)

        self.mint_button.setDisabled(True)
        self.close()

    def closeEvent(self, event):
        event.accept()
        dialogs.remove(self)

    def update(self):
        return

    def fail_genesis_info(self, message):
        self.view_tx_button.setDisabled(False)