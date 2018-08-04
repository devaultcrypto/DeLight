#!/usr/bin/env python
#
# Electrum - lightweight Bitcoin client
# Copyright (C) 2015 Thomas Voegtlin
#
# Permission is hereby granted, free of charge, to any person
# obtaining a copy of this software and associated documentation files
# (the "Software"), to deal in the Software without restriction,
# including without limitation the rights to use, copy, modify, merge,
# publish, distribute, sublicense, and/or sell copies of the Software,
# and to permit persons to whom the Software is furnished to do so,
# subject to the following conditions:
#
# The above copyright notice and this permission notice shall be
# included in all copies or substantial portions of the Software.
#
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND,
# EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF
# MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE AND
# NONINFRINGEMENT. IN NO EVENT SHALL THE AUTHORS OR COPYRIGHT HOLDERS
# BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY, WHETHER IN AN
# ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM, OUT OF OR IN
# CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
# SOFTWARE.

'''



Wallet file expects slp_history in the format like so:

"slp_history": [
        {
            "delta": "50000",
            "tokentype": "333",
            "txid": "a5................your tx id...................................4d"
        },
        {
            "delta": "32000",
            "tokentype": "444",
            "txid": "41.................your tx id..................................7e"
        }
    ],



'''



import webbrowser

from .util import *
import electroncash.web as web
from electroncash.i18n import _
from electroncash.util import timestamp_to_datetime, profiler


TX_ICONS = [
    "warning.png",
    "warning.png",
    "unconfirmed.png",
    "unconfirmed.png",
    "clock1.png",
    "clock2.png",
    "clock3.png",
    "clock4.png",
    "clock5.png",
    "confirmed.png",
]

 

class HistoryList(MyTreeWidget):
    filter_columns = [2, 3, 4]  # Date, Description, Amount

    def __init__(self, parent=None):
        MyTreeWidget.__init__(self, parent, self.create_menu, [], 3)
        self.editable_columns=[]
        self.refresh_headers()
        self.setColumnHidden(1, True)
        self.setSortingEnabled(True)
        self.sortByColumn(0, Qt.AscendingOrder)

    def refresh_headers(self):
        headers = [ '', '',_('Date'), _('Token Type') , _('Amount') ]
          
        self.update_headers(headers)

    def get_domain(self):
        '''Replaced in address_dialog.py'''
        return self.wallet.get_addresses()
 
    @profiler
    def on_update(self):


        self.wallet = self.parent.wallet
        h = self.wallet.get_history(self.get_domain())
        slp_history =self.wallet.get_slp_history() 
        slp_token_list =  self.config.get('slp_tokens')
        tok_name_dict = {}
        item = self.currentItem() 
        current_tx = item.data(0, Qt.UserRole) if item else None
        self.clear()
        for tok in slp_token_list:
            tok_name_dict[tok["hash"]]=tok["name"]  
        for h_item in slp_history:  
            tx_hash, height, conf, timestamp, delta,tokentype,validity= h_item
            status, status_str = self.wallet.get_tx_status(tx_hash, height, conf, timestamp)
            icon = QIcon("icons/" + TX_ICONS[status])
            if validity!=1:
                icon=QIcon("icons/unconfirmed.png") 
            tokenname=tok_name_dict.get(tokentype) # use get format to avoid exception if none 
            if tokenname is None:
                tokenname="UNKNOWN"
            entry = ['', '', status_str, tokenname, delta]
            item = SortableTreeWidgetItem(entry)
            self.insertTopLevelItem(0, item)
            item.setIcon(0, icon) 
            item.setData(0, SortableTreeWidgetItem.DataRole, (status, conf))
            if tx_hash:
                item.setData(0, Qt.UserRole, tx_hash)
        if current_tx == tx_hash:
            self.setCurrentItem(item)

    def on_doubleclick(self, item, column):
        if self.permit_edit(item, column):
            super(HistoryList, self).on_doubleclick(item, column)
        else:
            tx_hash = item.data(0, Qt.UserRole)
            tx = self.wallet.transactions.get(tx_hash)
            self.parent.show_transaction(tx)

    def update_labels(self):
        root = self.invisibleRootItem()
        child_count = root.childCount()
        for i in range(child_count):
            item = root.child(i)
            txid = item.data(0, Qt.UserRole)
            label = self.wallet.get_label(txid)
            item.setText(3, label)

    def update_item(self, tx_hash, height, conf, timestamp):
        status, status_str = self.wallet.get_tx_status(tx_hash, height, conf, timestamp)
        icon = QIcon(":icons/" +  TX_ICONS[status])
        items = self.findItems(tx_hash, Qt.UserRole|Qt.MatchContains|Qt.MatchRecursive, column=1)
        if items:
            item = items[0]
            item.setIcon(0, icon)
            item.setData(0, SortableTreeWidgetItem.DataRole, (status, conf))
            item.setText(2, status_str)

    def create_menu(self, position):
        self.selectedIndexes()
        item = self.currentItem()
        if not item:
            return
        column = self.currentColumn() 
        tx_hash = item.data(0, Qt.UserRole) 
        if not tx_hash:
            return
        if column is 0:
            column_title = "ID"
            column_data = tx_hash
        else:
            column_title = self.headerItem().text(column)
            column_data = item.text(column)

        tx_URL = web.BE_URL(self.config, 'tx', tx_hash)
        height, conf, timestamp = self.wallet.get_tx_height(tx_hash)
        tx = self.wallet.transactions.get(tx_hash)
        is_relevant, is_mine, v, fee = self.wallet.get_wallet_delta(tx)
        is_unconfirmed = height <= 0
        pr_key = self.wallet.invoices.paid.get(tx_hash)

        menu = QMenu()

        menu.addAction(_("Copy {}").format(column_title), lambda: self.parent.app.clipboard().setText(column_data))
        if column in self.editable_columns:
            # We grab a fresh reference to the current item, as it has been deleted in a reported issue.
            menu.addAction(_("Edit {}").format(column_title),
                lambda: self.currentItem() and self.editItem(self.currentItem(), column))

        menu.addAction(_("Details"), lambda: self.parent.show_transaction(tx))
        if is_unconfirmed and tx:
            child_tx = self.wallet.cpfp(tx, 0)
            if child_tx:
                menu.addAction(_("Child pays for parent"), lambda: self.parent.cpfp(tx, child_tx))
        if pr_key:
            menu.addAction(QIcon(":icons/seal"), _("View invoice"), lambda: self.parent.show_invoice(pr_key))
        if tx_URL:
            menu.addAction(_("View on block explorer"), lambda: webbrowser.open(tx_URL))
        menu.exec_(self.viewport().mapToGlobal(position))
