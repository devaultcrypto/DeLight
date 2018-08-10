
import copy
import datetime
from functools import partial
import json
import threading

from PyQt5.QtCore import *
from PyQt5.QtGui import *
from PyQt5.QtWidgets import *

from electroncash.address import Address, PublicKey
from electroncash.bitcoin import base_encode
from electroncash.i18n import _
from electroncash.plugins import run_hook

from electroncash.util import bfh
from .util import *

from electroncash.util import format_satoshis_nofloat
from electroncash.transaction import Transaction
from electroncash.slp import SlpMessage, SlpUnsupportedSlpTokenType, SlpInvalidOutputMessage

dialogs = []  # Otherwise python randomly garbage collects the dialogs...

class SlpAddTokenDialog(QDialog, MessageBoxMixin):

    got_network_response_sig = pyqtSignal()

    @pyqtSlot()
    def got_network_response_slot(self):
        self.download_finished = True

        resp = self.json_response
        if resp.get('error'):
            return self.fail_genesis_info("Download error!\n%r"%(resp['error'].get('message')))
        raw = resp.get('result')

        tx = Transaction(raw)
        self.handle_genesis_tx(tx)

    def __init__(self, main_window, token_id_hex=None, token_name=None):
        self.provided_token_name = token_name
        # We want to be a top-level window
        QDialog.__init__(self, parent=None)

        self.main_window = main_window
        self.wallet = main_window.wallet
        self.network = main_window.network
        self.app = main_window.app

        if self.provided_token_name:
            self.setWindowTitle(_("SLP Token Details"))
        else:
            self.setWindowTitle(_("Add SLP Token"))

        vbox = QVBoxLayout()
        self.setLayout(vbox)

        vbox.addWidget(QLabel(_('Token ID:')))

        self.token_id_e = ButtonsLineEdit()
        if token_id_hex is not None:
            self.token_id_e.addCopyButton(self.app)
        self.token_id_e.setFixedWidth(550)
        vbox.addWidget(self.token_id_e)


        hbox = QHBoxLayout()
        vbox.addLayout(hbox)

        hbox.addWidget(QLabel(_('Genesis transaction information:')))

        self.get_info_button = b = QPushButton(_("Download"))
        b.clicked.connect(self.download_info)
        hbox.addWidget(self.get_info_button)

        hbox.addStretch(1)

        self.token_info_e = QTextEdit()
        self.token_info_e.setReadOnly(True)
        self.token_info_e.setFixedWidth(550)
        self.token_info_e.setMinimumHeight(100)
        vbox.addWidget(self.token_info_e)

        hbox = QHBoxLayout()
        vbox.addLayout(hbox)

        warnpm = QIcon("icons/warning.png").pixmap(20,20)

        l = QLabel(); l.setPixmap(warnpm)
        hbox.addWidget(l)
        hbox.addWidget(QLabel(_('Avoid counterfeits—carefully compare the token ID with a trusted source.')))
        l = QLabel(); l.setPixmap(warnpm)
        hbox.addWidget(l)

        if self.provided_token_name is None:
            namelabel = QLabel(_('To use tokens with this ID, assign it a name.'))
            namelabel.setAlignment(Qt.AlignRight)
            vbox.addWidget(namelabel)

        hbox = QHBoxLayout()
        vbox.addLayout(hbox)

        self.cancel_button = b = QPushButton(_("Cancel"))
        self.cancel_button.setAutoDefault(False)
        self.cancel_button.setDefault(False)
        b.clicked.connect(self.close)
        b.setDefault(True)
        hbox.addWidget(self.cancel_button)

        hbox.addStretch(1)

        hbox.addWidget(QLabel(_('Name in wallet:')))
        self.token_name_e = QLineEdit()
        self.token_name_e.setFixedWidth(200)
        if self.provided_token_name is not None:
            self.token_name_e.setText(self.provided_token_name)
        hbox.addWidget(self.token_name_e)


        self.add_button = b = QPushButton(_("Add") if self.provided_token_name is None else _("Change"))
        b.clicked.connect(self.add_token)
        self.add_button.setAutoDefault(True)
        self.add_button.setDefault(True)
        b.setDisabled(True)
        hbox.addWidget(self.add_button)

        if token_id_hex is not None:
            self.token_id_e.setText(token_id_hex)
            self.download_info()

        self.got_network_response_sig.connect(self.got_network_response_slot, Qt.QueuedConnection)
        self.update()

        dialogs.append(self)
        self.show()

        self.token_name_e.setFocus()

    def closeEvent(self, event):
        #if (self.prompt_if_unsaved and not self.saved
            #and not self.question(_('This transaction is not saved. Close anyway?'), title=_("Warning"))):
            #event.ignore()
        #else:
            event.accept()
            dialogs.remove(self)

    def download_info(self):
        txid = self.token_id_e.text()

        self.token_id_e.setReadOnly(True)
        self.token_info_e.setText("Downloading...")
#        self.token_info_e.setHidden(False)
        self.get_info_button.setDisabled(True)

        try:
            tx = self.wallet.transactions[txid]
        except KeyError:
            def callback(response):
                self.json_response = response
                self.got_network_response_sig.emit()

            requests = [ ('blockchain.transaction.get', [txid]), ]
            self.network.send(requests, callback)
        else:
            self.handle_genesis_tx(tx)

    def handle_genesis_tx(self, tx):
        txid = tx.txid()
        token_id = self.token_id_e.text()
        if txid != token_id:
            raise RuntimeError('mismatched token ID')
        self.newtoken_token_id = token_id

        try:
            slpMsg = SlpMessage.parseSlpOutputScript(tx.outputs()[0][1])
        except SlpUnsupportedSlpTokenType as e:
            return self.fail_genesis_info(_("Unsupported SLP token version/type - %r.")%(e.args[0],))
        except SlpInvalidOutputMessage as e:
            return self.fail_genesis_info(_("This transaction does not contain a valid SLP message.\nReason: %r.")%(e.args,))
        if slpMsg.transaction_type != 'INIT':
            return self.fail_genesis_info(_("This SLP transaction is not a genesis."))


        f_fieldnames = QTextCharFormat()
        f_fieldnames.setFont(QFont(MONOSPACE_FONT))
        f_normal = QTextCharFormat()

        self.token_info_e.clear()
        cursor = self.token_info_e.textCursor()

        fields = [
            ('ticker', _('ticker'), 'utf8'),
            ('token_name', _('name'), 'utf8'),
            ('token_doc_url', _('doc url'), 'ascii'),
            ('token_doc_hash', _('doc hash'), 'hex'),
                 ]

        cursor.insertText(_('Issuer-declared strings in genesis:'))
        cursor.insertBlock()
        for k,n,e in fields:
            data = slpMsg.op_return_fields[k]
            if e == 'hex':
                friendlystring = None
            else:
                # Attempt to make a friendly string, or fail to hex
                try:
                    # Ascii only
                    friendlystring = data.decode(e) # raises UnicodeDecodeError with bytes > 127.

                    # Count ugly characters (that need escaping in python strings' repr())
                    uglies = 0
                    for b in data:
                        if b < 0x20 or b == 0x7f:
                            uglies += 1
                    # Less than half of characters may be ugly.
                    if 2*uglies >= len(data):
                        friendlystring = None
                except UnicodeDecodeError:
                    friendlystring = None

            if len(data) == 0:
                showstr = '(empty)'
            elif friendlystring is None:
                showstr = data.hex()
            else:
                showstr = repr(friendlystring)

            cursor.insertText(' '*(10 - len(n)) + n + ': ', f_fieldnames)
            cursor.insertText(showstr, f_normal)
            cursor.insertBlock()

        self.newtoken_decimals = slpMsg.op_return_fields['decimals']
        cursor.insertText(_('Decimals:') + ' ' + str(self.newtoken_decimals))
        cursor.insertBlock()

        numtokens = format_satoshis_nofloat(slpMsg.op_return_fields['initial_token_mint_quantity'],
                                    num_zeros=self.newtoken_decimals,
                                    decimal_point=self.newtoken_decimals,)
        mbv = slpMsg.op_return_fields['mint_baton_vout']
        if mbv is None or mbv > len(tx.outputs()):
            issuance_type = _('Initial issuance type: fixed supply')
        else:
            issuance_type = _('Initial issuance type: flexible supply')

        cursor.insertText(_('Initial issuance:') + ' ' + numtokens)
        cursor.insertBlock()
        cursor.insertText(issuance_type)

        #cursor.insertBlock()

        self.newtoken_genesis_tx      = tx
        self.newtoken_genesis_message = slpMsg

        self.add_button.setDisabled(False)

    def fail_genesis_info(self, message):
        self.token_info_e.setText(message)
        self.add_button.setDisabled(True)
        self.token_id_e.setReadOnly(False)
        self.get_info_button.setDisabled(False)

    def add_token(self):
        # Make sure to throw an error dialog if name exists, hash exists, ...
        token_name = self.token_name_e.text()
        ow = (self.provided_token_name is not None)
        ret = self.main_window.add_token_type('SLP1', self.newtoken_token_id, token_name, self.newtoken_decimals,
                                              error_callback = self.show_error, allow_overwrite=ow)
        if ret:
            self.add_button.setDisabled(True)
            self.close()
        else:
            # couldn't add for some reason...
            pass

    def update(self):
        return
