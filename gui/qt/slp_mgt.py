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
from .util import MyTreeWidget


class SlpMgt(MyTreeWidget):
    filter_columns = [0, 1,2]  # Key, Value

    def __init__(self, parent):
        MyTreeWidget.__init__(self, parent, self.create_menu, [_('Hash Id'), _('Token Name'), _('Decimals'),_('Balance')], 0, [0])
        self.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.setSortingEnabled(True)
        self.editable_columns=[1]

    def on_permit_edit(self, item, column):
        # openalias items shouldn't be editable
        return item.text(1) != "openalias"

    def on_edited(self, item, column, prior):
        if column == 0:  # Remove old contact if renamed
            self.parent.contacts.pop(prior)
        self.parent.set_slp_token(item.text(0), item.text(1),item.text(2))

    
    def create_menu(self, position):
        menu = QMenu()
        selected = self.selectedItems()
        if not selected:
            menu.addAction(_("New token type"), lambda: self.parent.new_slp_token_dialog()) 
        else:
            names = [item.text(0) for item in selected]
            keys = [item.text(0) for item in selected]
            column = self.currentColumn()
            column_title = self.headerItem().text(column)
            column_data = '\n'.join([item.text(column) for item in selected])
            menu.addAction(_("Copy {}").format(column_title), lambda: self.parent.app.clipboard().setText(column_data))
            menu.addAction(_("Delete"), lambda: self.parent.delete_slp_token(keys))

        run_hook('create_contact_menu', menu, selected)
        menu.exec_(self.viewport().mapToGlobal(position))


    def get_balance_from_hash_id(self):
        # implement by looking at UTXO for this token!
        # for now return dummy value.
        bal=1000
        return bal


    def on_update(self):
        self.clear() 
        for i in self.parent.slp_token_list:
            hash_id=i["hash"]
            name=i["name"]
            dec_prec = i["dec_prec"] 
            calculated_balance= self.get_balance_from_hash_id()
            item = QTreeWidgetItem([str(hash_id),str(name),str(dec_prec),str(calculated_balance)])
            item.setData(0, Qt.UserRole, hash_id)
            self.addTopLevelItem(item)
        run_hook('update_slp_mgt_tab', self)
