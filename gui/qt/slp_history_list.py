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
from electroncash.util import format_satoshis_nofloat

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


    def slp_validity_slot(self, txid, validity):
        # This gets pinged by the SLP validator when a validation job finishes.
        # (see lib/wallet.py : slp_check_validation() )
        if validity in (2,3):
            # If validator found 'invalid', then we need to update balances,
            # which requires recalculating / refreshing the whole list.
            self.update()
        else:
            # If validator found 'valid' then the balances are OK, so just
            # update the relevant items (note: may be multiple matches.).
            for tx_hash,item in self.allitems:
                if tx_hash == txid:
                    self.update_item_state(item)

    def __init__(self, parent=None):
        MyTreeWidget.__init__(self, parent, self.create_menu, [], 4)
        self.slp_validity_signal = parent.slp_validity_signal
        self.slp_validity_signal.connect(self.slp_validity_slot, Qt.QueuedConnection)
        self.editable_columns=[]
        self.refresh_headers()
        self.setColumnHidden(1, True)
        self.setSortingEnabled(True)
        self.sortByColumn(0, Qt.AscendingOrder)
        self.allitems = []

    def refresh_headers(self):
        headers = [ '', '',_('Date'), _('Amount'), _('Token') ]

        self.update_headers(headers)

    def get_domain(self):
        '''Replaced in address_dialog.py'''
        return self.wallet.get_addresses()

    @profiler
    def on_update(self):
        self.wallet = self.parent.wallet
        h = self.wallet.get_history(self.get_domain())
        slp_history =self.wallet.get_slp_history()

        item = self.currentItem()
        current_tx = item.data(0, Qt.UserRole) if item else None
        self.clear()

        self.allitems = []
        for h_item in slp_history:
            tx_hash, height, conf, timestamp, delta, token_id = h_item
            status, status_str = self.wallet.get_tx_status(tx_hash, height, conf, timestamp)

            entry = ['', tx_hash, status_str, '', '']
            item = SortableTreeWidgetItem(entry)
            item.setData(0, SortableTreeWidgetItem.DataRole, (status, conf))
            item.setData(0, Qt.UserRole, tx_hash)
            item.setData(4, Qt.UserRole, token_id)
            item.setData(3, Qt.UserRole, delta)

            item.setTextAlignment(3, Qt.AlignRight)
            item.setFont(3, QFont(MONOSPACE_FONT))

            self.update_item_state(item)

            self.insertTopLevelItem(0, item)
            if current_tx == tx_hash:
                self.setCurrentItem(item)

            self.allitems.append((tx_hash,item))

    def on_doubleclick(self, item, column):
        tx_hash = item.data(0, Qt.UserRole)
        tx = self.wallet.transactions.get(tx_hash)
        self.parent.show_transaction(tx)

    def update_item_state(self, item):
        tx_hash = item.data(0, Qt.UserRole)
        status, conf = item.data(0, SortableTreeWidgetItem.DataRole)
        token_id = item.data(4, Qt.UserRole)
        delta = item.data(3, Qt.UserRole)

        try:
            validity = self.wallet.tx_tokinfo[tx_hash]['validity']
        except KeyError: # Can happen if non-token tx (if burning tokens)
            validity = None

        try:
            tinfo = self.wallet.token_types[token_id]
        except KeyError:
            unktoken = True
            tokenname = _("%.4s... (unknown - right click to add)"%(token_id,))
            deltastr = '%+d'%(delta,)
        else:
            unktoken = False
            tokenname=tinfo['name']
            deltastr = format_satoshis_nofloat(delta, is_diff=True, decimal_point=tinfo['decimals'],)

            # right-pad with spaces so the decimal points line up
            d1,d2 = deltastr.rsplit('.',1)
            deltastr += "\u2014"*(9-len(d2))

        if unktoken and validity in (None,0,1):
            # If a token is not in our list of known token_ids, warn the user.
            icon=QIcon(":icons/warning.png")
            icontooltip = _("Unknown token ID")
        elif validity == 0:
            # For in-progress validation, always show gears regardless of confirmation status.
            icon=QIcon(":icons/unconfirmed.png")
            icontooltip = _("SLP unvalidated")
        elif validity in (None,2,3):
            icon=QIcon(":icons/expired.png")
            if validity is None:
                icontooltip = "non-SLP (tokens burned!)"
            else:
                icontooltip = "SLP invalid (tokens burned!)"
        elif validity == 1:
            # For SLP valid known txes, show the confirmation status (gears, few-confirmations, or green check)
            icon = QIcon(":icons/" + TX_ICONS[status])
            icontooltip = _("SLP valid; ") + str(conf) + " confirmation" + ("s" if conf != 1 else "")
        else:
            raise ValueError(validity)

        if unktoken:
            item.setForeground(3, QBrush(QColor("#888888")))
            item.setForeground(4, QBrush(QColor("#888888")))
        elif delta < 0:
            item.setForeground(3, QBrush(QColor("#BC1E1E")))

        item.setIcon(0, icon)
        item.setToolTip(0, icontooltip)
        item.setText(4, tokenname)
        item.setText(3, deltastr)

    def update_item_netupdate(self, tx_hash, height, conf, timestamp):
        wallet = getattr(self,'wallet', None)
        if not wallet:
            return
        status, status_str = wallet.get_tx_status(tx_hash, height, conf, timestamp)
        for itx_hash,item in self.allitems:
            if itx_hash == tx_hash:
                item.setData(0, SortableTreeWidgetItem.DataRole, (status, conf))
                item.setText(2, status_str)
                self.update_item_state(item)

    def create_menu(self, position):
        self.selectedIndexes()
        item = self.currentItem()
        if not item:
            return
        column = self.currentColumn()
        tx_hash = item.data(0, Qt.UserRole)
        token_id = item.data(4, Qt.UserRole)
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

        if not self.wallet.token_types.get(token_id):
            menu.addAction(_("Add this token"), lambda: SlpAddTokenDialog(self.parent, token_id_hex = token_id))

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
