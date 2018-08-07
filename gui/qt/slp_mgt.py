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

from electroncash.i18n import _
import electroncash.web as web
from electroncash.address import Address
from electroncash.plugins import run_hook
from electroncash.util import FileImportFailed
from PyQt5.QtGui import *
from PyQt5.QtCore import *
from PyQt5.QtWidgets import (
    QAbstractItemView, QFileDialog, QMenu, QTreeWidgetItem)
from .util import *

from electroncash.util import format_satoshis
from .slp_add_token_dialog import SlpAddTokenDialog

class SlpMgt(MyTreeWidget):
    filter_columns = [0, 1,2]  # Key, Value

    def __init__(self, parent):
        MyTreeWidget.__init__(self, parent, self.create_menu, [_('Token ID'), _('Token Name'), _('Dec.'),_('Balance')], 0, [0])
        self.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.setSortingEnabled(True)
        self.editable_columns=[1]

    def on_permit_edit(self, item, column):
        # openalias items shouldn't be editable
        return item.text(1) != "openalias"

    def on_edited(self, item, column, prior):
        self.parent.add_token_type(item.text(0), item.text(1), int(item.text(2)), allow_overwrite=True)

    def create_menu(self, position):
        menu = QMenu()
        selected = self.selectedItems()
        current = self.currentItem()
        if current:
            menu.addAction(_("Details"), lambda: SlpAddTokenDialog(self.parent, token_id_hex = current.text(0), token_name=current.text(1) ))
        if selected:
            names = [item.text(0) for item in selected]
            keys = [item.text(0) for item in selected]
            column = self.currentColumn()
            column_title = self.headerItem().text(column)
            column_data = '\n'.join([item.text(column) for item in selected])
            menu.addAction(_("Copy {}").format(column_title), lambda: self.parent.app.clipboard().setText(column_data))
            menu.addAction(_("Delete"), lambda: self.parent.delete_slp_token(keys))
        menu.addAction(_("Add a new token type"), lambda: SlpAddTokenDialog(self.parent,))

        run_hook('create_contact_menu', menu, selected)
        menu.exec_(self.viewport().mapToGlobal(position))


    def get_balance_from_hash_id(self,slpTokenId):
        # implement by looking at UTXO for this token!
        # for now return dummy value.
        bal,dummy1,dummy2=self.parent.wallet.get_slp_token_balance(slpTokenId)
        return bal


    def on_update(self):
        self.clear()
        for i in self.parent.slp_token_list:
            hash_id=i["hash"]
            name=i["name"]
            if 'dec_prec' in i: # rename field
                i["decimals"] = i.pop("dec_prec")
            decimals = i["decimals"]
            calculated_balance= self.get_balance_from_hash_id(hash_id)
            balancestr = format_satoshis(calculated_balance, decimal_point=decimals, num_zeros=decimals)
            balancestr += ' '*(9-decimals)

            item = QTreeWidgetItem([str(hash_id),str(name),str(decimals),balancestr])
            item.setFont(0, QFont(MONOSPACE_FONT))
            #item.setTextAlignment(2, Qt.AlignRight)
            item.setTextAlignment(3, Qt.AlignRight)
            item.setFont(3, QFont(MONOSPACE_FONT))
            item.setData(0, Qt.UserRole, hash_id)
            self.addTopLevelItem(item)
