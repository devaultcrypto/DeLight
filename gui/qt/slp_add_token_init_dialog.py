
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

from electroncash.util import format_satoshis
from electroncash.transaction import Transaction
from electroncash.slp import SlpMessage, SlpUnsupportedSlpTokenType, SlpInvalidOutputMessage, SlpTokenTransactionFactory

dialogs = []  # Otherwise python randomly garbage collects the dialogs...

class SlpAddTokenInitDialog(QDialog, MessageBoxMixin):

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

        vbox.addWidget(QLabel(_('Token Name:')))
        self.token_name_e = ButtonsLineEdit()
        self.token_name_e.addCopyButton(self.app)
        self.token_name_e.setFixedWidth(200)
        vbox.addWidget(self.token_name_e)

        vbox.addWidget(QLabel(_('Token Ticker:')))
        self.token_ticker_e = ButtonsLineEdit()
        self.token_ticker_e.setFixedWidth(75)
        vbox.addWidget(self.token_ticker_e)

        vbox.addWidget(QLabel(_('Intial Token Quantity:')))
        self.token_qty_e = ButtonsLineEdit()
        self.token_qty_e.setFixedWidth(75)
        vbox.addWidget(self.token_qty_e)

        vbox.addWidget(QLabel(_('Token Receiver Address:')))
        self.token_pay_to_e = ButtonsLineEdit()
        self.token_pay_to_e.addCopyButton(self.app)
        self.token_pay_to_e.setFixedWidth(400)
        vbox.addWidget(self.token_pay_to_e)

        vbox.addWidget(QLabel(_('Mint Baton Address:')))
        self.token_baton_to_e = ButtonsLineEdit()
        self.token_baton_to_e.addCopyButton(self.app)
        self.token_baton_to_e.setFixedWidth(400)
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

        self.init_button = b = QPushButton(_("Create New Token")) #if self.provided_token_name is None else _("Change"))
        b.clicked.connect(self.create_token)
        self.init_button.setAutoDefault(True)
        self.init_button.setDefault(True)
        hbox.addWidget(self.init_button)

        dialogs.append(self)
        self.show()

        self.token_name_e.setFocus()

    def parse_address(self, address):
        if "simpleledger" not in address:
            address="simpleledger:"+address
        return Address.from_string(address)

    def create_token(self):
        token_name = self.token_name_e.text() if self.token_name_e.text() != '' else None
        ticker = self.token_ticker_e.text() if self.token_ticker_e.text() != '' else None
        token_document_url = None
        token_document_hash = None
        decimals = 0
        mint_baton_vout = 2 if self.token_baton_to_e.text() != '' else None
        try:
            init_mint_qty = int(self.token_qty_e.text())
        except Exception as e:
            self.main_window.show_message(_("Must have initial token quantity entered."))
            return

        outputs = []
        msgFactory = SlpTokenTransactionFactory(1)
        slp_op_return_msg = msgFactory.buildInitOpReturnOutput_V1(ticker, token_name, token_document_url, token_document_hash, decimals, mint_baton_vout, init_mint_qty)
        outputs.append(slp_op_return_msg)

        addr = self.parse_address(self.token_pay_to_e.text())
        outputs.append((TYPE_ADDRESS, addr, 546))

        if self.token_baton_to_e.text() != '':
            addr = self.parse_address(self.token_baton_to_e.text())
            outputs.append((TYPE_ADDRESS, addr, 546))

        coins = self.main_window.get_coins()
        fee = None

        try:
            tx = self.main_window.wallet.make_unsigned_transaction(coins, outputs, self.main_window.config, fee, None)
        except NotEnoughFunds:
            self.main_window.show_message(_("Insufficient funds"))
            return
        except NotEnoughFundsSlp:
            self.main_window.show_message(_("Insufficient valid token funds"))
            return
        except ExcessiveFee:
            self.main_window.show_message(_("Your fee is too high.  Max is 50 sat/byte."))
            return
        except BaseException as e:
            traceback.print_exc(file=sys.stdout)
            self.main_window.show_message(str(e))
            return

        # confirmation dialog
        msg = []

        x_fee = run_hook('get_tx_extra_fee', self.main_window.wallet, tx)
        if x_fee:
            x_fee_address, x_fee_amount = x_fee
            msg.append( _("Additional fees") + ": " + self.main_window.format_amount_and_units(x_fee_amount) )

        confirm_rate = 2 * self.main_window.config.max_fee_rate()

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

        self.init_button.setDisabled(True)
        self.close()

    def closeEvent(self, event):
        event.accept()
        dialogs.remove(self)

    def update(self):
        return
