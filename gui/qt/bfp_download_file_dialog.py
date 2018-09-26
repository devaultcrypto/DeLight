import copy
import datetime
from functools import partial
import json
import threading
import html

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
from electroncash.bitcoinfiles import BfpMessage, BfpUnsupportedBfpMsgType, BfpInvalidOutputMessage, parseOpreturnToChunks

dialogs = []  # Otherwise python randomly garbage collects the dialogs...

class BfpDownloadFileDialog(QDialog, MessageBoxMixin):

    got_network_response_meta_sig = pyqtSignal()
    got_network_response_chunk_sig = pyqtSignal(str, int)

    @pyqtSlot()
    def got_network_response_slot(self):
        self.download_finished = True

        resp = self.json_response
        if resp.get('error'):
            return self.fail_metadata_info("Download metadata error!\n%r"%(resp['error'].get('message')))
        raw = resp.get('result')

        tx = Transaction(raw)
        self.handle_metadata_tx(tx)

    @pyqtSlot()
    def got_network_response_chunk_slot(self, response, chunk_index):
        if response.get('error'):
            return self.fail_metadata_info("Download chunk data error!\n%r"%(resp['error'].get('message')))
        raw = resp.get('result')

        tx = Transaction(raw)
        self.handle_chunk_tx(tx, chunk_index)

    def __init__(self, main_window):
        # We want to be a top-level window
        QDialog.__init__(self, parent=None)

        self.main_window = main_window
        self.wallet = main_window.wallet
        self.network = main_window.network
        self.app = main_window.app

        self.setWindowTitle(_("Download File via BFP"))

        vbox = QVBoxLayout()
        self.setLayout(vbox)

        vbox.addWidget(QLabel(_('File URI:')))
        self.file_id_e = ButtonsLineEdit()
        self.file_id_e.setFixedWidth(550)
        vbox.addWidget(self.file_id_e)

        hbox = QHBoxLayout()
        vbox.addLayout(hbox)

        hbox.addWidget(QLabel(_('File metadata information:')))

        self.get_info_button = b = QPushButton(_("Get Info"))
        b.clicked.connect(self.download_metadata_info)
        hbox.addWidget(b)

        self.download_button = b = QPushButton(_("Download File"))
        b.clicked.connect(self.download_file)
        b.setDisabled(True)
        hbox.addWidget(b)

        self.view_tx_button = b = QPushButton(_("View Tx"))
        b.clicked.connect(self.view_tx)
        b.setDisabled(True)
        hbox.addWidget(b)
        hbox.addStretch(1)

        self.file_info_e = QTextBrowser()
        #self.token_info_e.setReadOnly(True)
        self.file_info_e.setOpenExternalLinks(True)
        self.file_info_e.setFixedWidth(550)
        self.file_info_e.setMinimumHeight(100)
        vbox.addWidget(self.file_info_e)

        hbox = QHBoxLayout()
        vbox.addLayout(hbox)

        self.cancel_button = b = QPushButton(_("Cancel"))
        self.cancel_button.setAutoDefault(False)
        self.cancel_button.setDefault(False)
        b.clicked.connect(self.close)
        b.setDefault(True)
        hbox.addWidget(self.cancel_button)

        self.got_network_response_meta_sig.connect(self.got_network_response_slot, Qt.QueuedConnection)
        self.got_network_response_chunk_sig.connect(self.got_network_response_chunk_slot, Qt.QueuedConnection)
        self.update()

        dialogs.append(self)
        self.show()

        self.file_metadata_tx = None

    def closeEvent(self, event):
        #if (self.prompt_if_unsaved and not self.saved
            #and not self.question(_('This transaction is not saved. Close anyway?'), title=_("Warning"))):
            #event.ignore()
        #else:
            event.accept()
            dialogs.remove(self)

    def download_file(self):
        self.txn_downloads = []
        self.file = None
        self.chunk_count = self.file_metadata_message.op_return_fields['chunk_count']

        if self.chunk_count > 0:
            if self.file_metadata_message.op_return_fields['chunk_data'] != b'':
                self.txn_downloads.append({ 'txid': self.file_metadata_tx.txid(), 'data': self.file_metadata_message.op_return_fields['chunk_data'] })
            
            if self.chunk_count > 1:
                self.txn_downloads.append({ 'txid': self.file_metadata_tx.inputs()[0]['prevout_hash'], 'data': None} )
                assert self.file_metadata_tx.inputs()[0]['prevout_n'] == 1
            
            index = len(self.txn_downloads)-1
            self.download_chunk_data(self.txn_downloads[index]['txid'], index)
        else:
            raise Exception("There is no data in this file.")

    def download_chunk_data(self, txid, chunk_index):
        try: 
            tx = self.wallet.transactions[txid]
        except KeyError:
            def callback(response):
                self.got_network_response_chunk_sig.emit(response, chunk_index)
        else:
            self.handle_chunk_tx(tx, chunk_index)                

    def handle_chunk_tx(self, tx, chunk_index):
        try: 
            data = parseOpreturnToChunks(tx.outputs()[0][1].to_script(), allow_op_0 = False, allow_op_number = False)
        except Exception as e:
            raise e
            return self.fail_metadata_info(_("This transaction does not contain any chunk data"))
 
        if len(data) != 1:
            return self.fail_metadata_info(_("This transaction does not contain any chunk data"))
        self.txn_downloads[chunk_index]['data'] = data[0]
        if chunk_index < self.chunk_count - 1:
            self.txn_downloads.append({ 'txid': tx.inputs()[0]['prevout_hash'], 'data': None })
            assert tx.inputs()[0]['prevout_n'] == 1
            index = len(self.txn_downloads)-1
            self.download_chunk_data(self.txn_downloads[index]['txid'], index)
        else:
            self.txn_downloads.reverse()
            self.file = b''
            for d in self.txn_downloads:
                self.file += d['data']
            name = QFileDialog.getSaveFileName(self, 'Save File')[0]
            if name != '':
                file = open(name,'wb')
                file.write(self.file)
                file.close()

    def download_metadata_info(self):
        txid = self.file_id_e.text()

        self.file_info_e.setText("Downloading...")
        self.get_info_button.setDisabled(True)
        self.download_button.setDisabled(True)
        self.view_tx_button.setDisabled(True)

        try:
            tx = self.wallet.transactions[txid]
        except KeyError:
            def callback(response):
                self.json_response = response
                self.got_network_response_meta_sig.emit()

            requests = [ ('blockchain.transaction.get', [txid]), ]
            self.network.send(requests, callback)
        else:
            self.handle_metadata_tx(tx)

    def handle_metadata_tx(self, tx):
        self.file_metadata_tx      = tx
        self.view_tx_button.setDisabled(False)

        txid = tx.txid()
        file_id = self.file_id_e.text().strip()
        if file_id and txid != file_id:
            return self.fail_metadata_info(_('TXID does not match file ID!'))
        #self.new_file_id = txid
        #self.file_id_e.setText(self.new_file_id)

        try:
            bfpMsg = BfpMessage.parseBfpScriptOutput(tx.outputs()[0][1])
        except BfpUnsupportedBfpMsgType as e:
            return self.fail_metadata_info(_("Unsupported SLP token version/type - %r.")%(e.args[0],))
        except BfpInvalidOutputMessage as e:
            return self.fail_metadata_info(_("This transaction does not contain a valid BFP message.\nReason: %r.")%(e.args,))
        if bfpMsg.msg_type != 1:
            return self.fail_metadata_info(_("This is a BFP transaction, however it is not a downloadable file."))

        f_fieldnames = QTextCharFormat()
        f_fieldnames.setFont(QFont(MONOSPACE_FONT))
        f_normal = QTextCharFormat()

        self.file_info_e.clear()
        cursor = self.file_info_e.textCursor()

        fields = [
            ('filename', _('name'), 'utf8', None),
            ('fileext', _('ext'), 'utf8', None),
            ('size', _('size'), 'int', None),
            ('uri', _('uri'), 'utf8', 'html'),
            ('chunk_count', _('chunk count'), 'int', None),
            ('hash', _('hash'), 'hex', None),
                 ]

        cursor.insertText(_('File Metadata:'))
        cursor.insertBlock()
        for k,n,e,f in fields:
            data = bfpMsg.op_return_fields[k]
            if e == 'hex':
                friendlystring = None
            elif e == 'int':
                if data != b'':
                    friendlystring = str(data)
                    data = friendlystring
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
                f=None
            elif friendlystring is None:
                showstr = data.hex()
                f=None
            else:
                showstr = repr(friendlystring)

            cursor.insertText(' '*(10 - len(n)) + n + ': ', f_fieldnames)
            if f == 'html':
                enc_url  = html.escape(friendlystring)
                enc_text = html.escape(showstr)
                cursor.insertHtml('<a href="%s" title="%s">%s</a>'%(enc_url, enc_url, enc_text))
            else:
                cursor.insertText(showstr, f_normal)
            cursor.insertBlock()
        cursor.insertBlock()
        #cursor.insertBlock()

        self.file_metadata_message = bfpMsg
        self.download_button.setEnabled(True)

    def fail_metadata_info(self, message):
        self.file_info_e.setText(message)
        self.file_id_e.setReadOnly(False)
        self.get_info_button.setDisabled(False)

    def view_tx(self,):
        self.main_window.show_transaction(self.file_metadata_tx)

    def update(self):
        return