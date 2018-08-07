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


import webbrowser

from .util import *
import electroncash.web as web
from electroncash.i18n import _
from electroncash.util import timestamp_to_datetime, profiler
from electroncash.util import format_satoshis

from .slp_add_token_dialog import SlpAddTokenDialog

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
        headers = [ '', '',_('Date'), _('Token Name') , _('Amount') ]

        self.update_headers(headers)

    def get_domain(self):
        '''Replaced in address_dialog.py'''
        return self.wallet.get_addresses()

    @profiler
    def on_update(self):
        self.wallet = self.parent.wallet
        h = self.wallet.get_history(self.get_domain())
        slp_history =self.wallet.get_slp_history()

        tok_dict = {d['hash']:d for d in self.parent.slp_token_list}

        item = self.currentItem()
        current_tx = item.data(0, Qt.UserRole) if item else None
        self.clear()

        for h_item in slp_history:
            tx_hash, height, conf, timestamp, delta, token_id, validity= h_item
            status, status_str = self.wallet.get_tx_status(tx_hash, height, conf, timestamp)

            try:
                tinfo = tok_dict[token_id]
            except KeyError:
                unktoken = True
                tokenname = _("Unknown token ID (%.4s...), right click to add..."%(token_id,))
                deltastr = '%+d'%(delta,)
            else:
                unktoken = False
                tokenname=tinfo['name']
                deltastr = format_satoshis(delta, is_diff=True, decimal_point=tinfo['decimals'],)

                # right-pad with spaces so the decimal points line up
                d1,d2 = deltastr.rsplit('.',1)
                deltastr += " "*(9-len(d2))

            if unktoken and validity in (0,1):
                # If a token is not in our list of known token_ids, warn the user!
                icon=QIcon("icons/warning.png")
                icontooltip = _("Unknown token ID")
            elif validity == 0:
                # For in-progress validation, always show gears regardless of confirmation status.
                icon=QIcon("icons/warning.png")
                icontooltip = _("SLP validation in progress...")
            elif validity in (2,3):
                ## Option 1 - Show bad SLP txes with red warning and kill the amount.
                #icon=QIcon("icons/expired.png")
                #icontooltip = "SLP invalid!"
                #deltastr = "---"

                # Option 2 - Erase invalid transactions from SLP history gui
                continue
            elif validity == 1:
                # For SLP valid known txes, show the confirmation status (gears, few-confirmations, or green check)
                icon = QIcon("icons/" + TX_ICONS[status])
                icontooltip = _("SLP valid; ") + str(conf) + " confirmation" + ("s" if conf != 1 else "")
            else:
                raise ValueError(validity)

            entry = ['', '', status_str, tokenname, deltastr]
            item = SortableTreeWidgetItem(entry)
            item.setTextAlignment(4, Qt.AlignRight)
            item.setFont(4, QFont(MONOSPACE_FONT))
            if unktoken:
                item.setForeground(4, QBrush(QColor("#888888")))
            elif delta < 0:
                item.setForeground(4, QBrush(QColor("#BC1E1E")))
            self.insertTopLevelItem(0, item)
            item.setIcon(0, icon)
            item.setToolTip(0, icontooltip)
            item.setData(0, SortableTreeWidgetItem.DataRole, (status, conf))
            item.setData(0, Qt.UserRole, (tx_hash, token_id))
            if current_tx == tx_hash:
                self.setCurrentItem(item)

    def on_doubleclick(self, item, column):
        if self.permit_edit(item, column):
            super(HistoryList, self).on_doubleclick(item, column)
        else:
            tx_hash, token_id = item.data(0, Qt.UserRole)
            tx = self.wallet.transactions.get(tx_hash)
            self.parent.show_transaction(tx)

    def update_labels(self):
        raise NotImplementedError("this shouldn't get called!")
        #root = self.invisibleRootItem()
        #child_count = root.childCount()
        #for i in range(child_count):
            #item = root.child(i)
            #txid = item.data(0, Qt.UserRole)
            #label = self.wallet.get_label(txid)
            #item.setText(3, label)

    def update_item(self, tx_hash, height, conf, timestamp):
        raise NotImplementedError("this shouldn't get called!")
        #status, status_str = self.wallet.get_tx_status(tx_hash, height, conf, timestamp)
        #icon = QIcon(":icons/" +  TX_ICONS[status])
        #items = self.findItems(tx_hash, Qt.UserRole|Qt.MatchContains|Qt.MatchRecursive, column=1)
        #if items:
            #item = items[0]
            #item.setIcon(0, icon)
            #item.setData(0, SortableTreeWidgetItem.DataRole, (status, conf))
            #item.setText(2, status_str)

    def create_menu(self, position):
        self.selectedIndexes()
        item = self.currentItem()
        if not item:
            return
        column = self.currentColumn()
        tx_hash, token_id = item.data(0, Qt.UserRole)
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

        for d in self.parent.slp_token_list:
            if d['hash'] == token_id:
                break
        else:
            menu.addAction(_("Add new token type"), lambda: SlpAddTokenDialog(self.parent, token_id_hex = token_id))

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
