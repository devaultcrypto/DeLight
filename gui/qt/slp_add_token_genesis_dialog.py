
import copy
import datetime
from functools import partial
import json
import threading
import sys

from PyQt5.QtCore import *
from PyQt5.QtGui import *
from PyQt5.QtWidgets import *

from electroncash.address import Address, PublicKey
from electroncash.bitcoin import base_encode, TYPE_ADDRESS
from electroncash.i18n import _
from electroncash.plugins import run_hook

from .util import *

from electroncash.util import bfh, format_satoshis_nofloat, format_satoshis_plain_nofloat, NotEnoughFunds, ExcessiveFee
from electroncash.transaction import Transaction
from electroncash.slp import SlpMessage, SlpUnsupportedSlpTokenType, SlpInvalidOutputMessage, buildGenesisOpReturnOutput_V1

from .amountedit import SLPAmountEdit
from .transaction_dialog import show_transaction

dialogs = []  # Otherwise python randomly garbage collects the dialogs...

class SlpAddTokenGenesisDialog(QDialog, MessageBoxMixin):

    def __init__(self, main_window):
        #self.provided_token_name = token_name
        # We want to be a top-level window
        QDialog.__init__(self, parent=main_window)

        self.main_window = main_window
        self.wallet = main_window.wallet
        self.network = main_window.network
        self.app = main_window.app


        self.setWindowTitle(_("Create a New Token"))

        vbox = QVBoxLayout()
        self.setLayout(vbox)

        grid = QGridLayout()
        grid.setColumnStretch(1, 1)
        vbox.addLayout(grid)
        row = 0

        msg = _('An optional name string embedded in the token genesis transaction.')
        grid.addWidget(HelpLabel(_('Token Name (optional):'), msg), row, 0)
        self.token_name_e = QLineEdit()
        grid.addWidget(self.token_name_e, row, 1)
        row += 1

        msg = _('An optional ticker symbol string embedded into the token genesis transaction.')
        grid.addWidget(HelpLabel(_('Ticker Symbol (optional):'), msg), row, 0)
        self.token_ticker_e = QLineEdit()
        self.token_ticker_e.setFixedWidth(110)
        self.token_ticker_e.textChanged.connect(self.upd_token)
        grid.addWidget(self.token_ticker_e, row, 1)
        row += 1

        msg = _('An optional URL string embedded into the token genesis transaction.')
        grid.addWidget(HelpLabel(_('Document URL or contact email (optional):'), msg), row, 0)
        self.token_url_e = QLineEdit()
        self.token_url_e.setFixedWidth(450)
        self.token_url_e.textChanged.connect(self.upd_token)
        grid.addWidget(self.token_url_e, row, 1)
        row += 1

        msg = _('An optional hash hexidecimal bytes embedded into the token genesis transaction for hashing the document file contents at the URL provided above.')
        grid.addWidget(HelpLabel(_('Document Hash (optional):'), msg), row, 0)
        self.token_dochash_e = QLineEdit()
        self.token_dochash_e.setInputMask("HHHHHHHHHHHHHHHHHHHHHHHHHHHHHHHHHHHHHHHHHHHHHHHHHHHHHHHHHHHHHHHH")
        self.token_dochash_e.setFixedWidth(450)
        self.token_dochash_e.textChanged.connect(self.upd_token)
        grid.addWidget(self.token_dochash_e, row, 1)
        row += 1

        msg = _('Sets the number of decimals of divisibility for this token (embedded into genesis).') + '\n\n'\
              + _('Each 1 token is divisible into 10^(decimals) base units, and internally in the protocol the token amounts are represented as 64-bit integers measured in these base units.')
        grid.addWidget(HelpLabel(_('Decimal Places:'), msg), row, 0)
        self.token_ds_e = QDoubleSpinBox()
        self.token_ds_e.setRange(0, 9)
        self.token_ds_e.setDecimals(0)
        self.token_ds_e.setFixedWidth(50)
        self.token_ds_e.valueChanged.connect(self.upd_token)
        grid.addWidget(self.token_ds_e, row, 1)
        row += 1

        msg = _('The number of tokens created during token genesis transaction, send to the receiver address provided below.')
        grid.addWidget(HelpLabel(_('Token Quantity:'), msg), row, 0)
        self.token_qty_e = SLPAmountEdit('', 0)
        self.token_qty_e.setFixedWidth(200)
        self.token_qty_e.textChanged.connect(self.check_token_qty)
        grid.addWidget(self.token_qty_e, row, 1)
        row += 1

        msg = _('The \'simpleledger:\' formatted bitcoin address for the genesis receiver of all genesis tokens.')
        grid.addWidget(HelpLabel(_('Token Receiver Address:'), msg), row, 0)
        self.token_pay_to_e = ButtonsLineEdit()
        self.token_pay_to_e.setFixedWidth(450)
        grid.addWidget(self.token_pay_to_e, row, 1)
        row += 1

        self.token_fixed_supply_cb = cb = QCheckBox(_('Fixed Supply'))
        self.token_fixed_supply_cb.setChecked(True)
        grid.addWidget(self.token_fixed_supply_cb, row, 1)
        cb.clicked.connect(self.show_mint_baton_address)
        row += 1

        msg = _('The \'simpleledger:\' formatted bitcoin address for the "minting baton" receiver.') + '\n\n'\
              + _('After the genesis transaction, further unlimited minting operations can be performed by the owner of the "minting baton" transaction output. This baton can be repeatedly used for minting operations but it cannot be duplicated.')
        self.token_baton_label = HelpLabel(_('Address for Baton:'), msg)
        self.token_baton_label.setHidden(True)
        grid.addWidget(self.token_baton_label, row, 0)
        self.token_baton_to_e = ButtonsLineEdit()
        self.token_baton_to_e.setFixedWidth(450)
        self.token_baton_to_e.setHidden(True)
        grid.addWidget(self.token_baton_to_e, row, 1)
        row += 1

        hbox = QHBoxLayout()
        vbox.addLayout(hbox)

        self.cancel_button = b = QPushButton(_("Cancel"))
        self.cancel_button.setAutoDefault(False)
        self.cancel_button.setDefault(False)
        b.clicked.connect(self.close)
        b.setDefault(True)
        hbox.addWidget(self.cancel_button)

        hbox.addStretch(1)

        self.preview_button = EnterButton(_("Preview"), self.do_preview)
        self.create_button = b = QPushButton(_("Create New Token")) #if self.provided_token_name is None else _("Change"))
        b.clicked.connect(self.create_token)
        self.create_button.setAutoDefault(True)
        self.create_button.setDefault(True)
        hbox.addWidget(self.preview_button)
        hbox.addWidget(self.create_button)

        dialogs.append(self)
        self.show()
        self.token_name_e.setFocus()

    def do_preview(self):
        self.create_token(preview = True)

    def upd_token(self,):
        self.token_qty_e.set_token(self.token_ticker_e.text(), int(self.token_ds_e.value()))

        # force update (will truncate excess decimals)
        self.token_qty_e.numbify()
        self.token_qty_e.update()

    def show_mint_baton_address(self):
        self.token_baton_to_e.setHidden(self.token_fixed_supply_cb.isChecked())
        self.token_baton_label.setHidden(self.token_fixed_supply_cb.isChecked())

    def parse_address(self, address):
        if "simpleledger" not in address:
            address="simpleledger:"+address
        return Address.from_string(address)

    def create_token(self, preview=False):
        token_name = self.token_name_e.text() if self.token_name_e.text() != '' else None
        ticker = self.token_ticker_e.text() if self.token_ticker_e.text() != '' else None
        token_document_url = self.token_url_e.text() if self.token_url_e.text() != '' else None
        token_document_hash_hex = self.token_dochash_e.text() if self.token_dochash_e.text() != '' else None
        decimals = int(self.token_ds_e.value())
        mint_baton_vout = 2 if self.token_baton_to_e.text() != '' else None

        init_mint_qty = self.token_qty_e.get_amount()
        if init_mint_qty is None:
            self.show_message(_("Invalid token quantity entered."))
            return
        if init_mint_qty > (2 ** 64) - 1:
            maxqty = format_satoshis_plain_nofloat((2 ** 64) - 1, decimals)
            self.show_message(_("Token output quantity is too large. Maximum %s.")%(maxqty,))
            return

        if token_document_hash_hex != None:
            if len(token_document_hash_hex) != 64:
                self.show_message(_("Token document hash must be a 32 byte hexidecimal string or left empty."))
                return
                    
        outputs = []
        try:
            slp_op_return_msg = buildGenesisOpReturnOutput_V1(ticker, token_name, token_document_url, token_document_hash_hex, decimals, mint_baton_vout, init_mint_qty)
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

        # IMPORTANT: set wallet.sedn_slpTokenId to None to guard tokens during this transaction
        self.main_window.token_type_combo.setCurrentIndex(0)
        assert self.main_window.wallet.send_slpTokenId == None

        coins = self.main_window.get_coins()
        fee = None

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

        if preview:
            show_transaction(tx, self.main_window, None, False, self)
            return

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
                    show_transaction(tx, self.main_window, None, False, self)
                    self.main_window.do_clear()
                else:
                    self.main_window.broadcast_transaction(tx, tx_desc)

                token_id = tx.txid()
                if self.token_name_e.text() == '':
                    token_name = tx.txid()[0:10]
                else:
                    token_name = self.token_name_e.text()[0:20]

                ow = (token_name is not None)
                ret = self.main_window.add_token_type('SLP1', token_id, token_name, decimals,
                                                    error_callback = self.show_error, allow_overwrite=ow)

        self.main_window.sign_tx_with_password(tx, sign_done, password)

        self.create_button.setDisabled(True)
        self.close()

    def closeEvent(self, event):
        event.accept()
        try:
            dialogs.remove(self)
        except ValueError:
            pass

    def update(self):
        return

    def check_token_qty(self):
        try:
            if self.token_qty_e.get_amount() > (10 ** 19):
                self.show_warning(_('If you issue this much, users will may find it awkward to transfer large amounts as each transaction output may only take up to ~2 x 10^(19-decimals) tokens, thus requiring multiple outputs for very large amounts.'))
        except:
            pass
