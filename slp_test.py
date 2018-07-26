import unittest
from pprint import pprint

from lib import transaction
from lib.address import Address, ScriptOutput
from lib.bitcoin import TYPE_ADDRESS
from lib.keystore import xpubkey_to_address
from lib.util import bh2u
from lib.slp import SlpTokenTransactionFactory, SlpMessage, SlpTokenType, SlpTransactionType, int_2_hex_left_pad

class TestSlpTokenTransactionFactory(unittest.TestCase):

    def test_INIT_opreturn_building_and_parsing_to_a_new_SlpMessage(self):
        # first lets create a new incomming INIT transaction hexidecimal message from scratch...
        lokad_id = "00534c50"               # 04 00534c50
        token_type = 1                      # 01 01
        txn_type = "INIT"                   # 04 ______
        ticker = "TEST"                     # 04 ______ 
        name = "A Test Token"               # push(14) ______ 
        doc_url = "http://www.bitcoin.cash" # push(23) ______
        doc_hash_hex = None                 # 01 00
        init_qty = 2100000000000000         # 08 000775F05A074000
        # manually formulate the message
        asm_manual = "OP_RETURN" + " " + \
                    lokad_id + " " + \
                    int_2_hex_left_pad(token_type) + " " + \
                    SlpTokenTransactionFactory.encodeStringToHex(txn_type, 'utf-8') + " " + \
                    SlpTokenTransactionFactory.encodeStringToHex(ticker, 'utf-8') + " " + \
                    SlpTokenTransactionFactory.encodeStringToHex(name, 'utf-8') + " " + \
                    SlpTokenTransactionFactory.encodeStringToHex(doc_url, 'ascii') + " " + \
                    SlpTokenTransactionFactory.encodeHexStringToHex(doc_hash_hex) + " " + \
                    int_2_hex_left_pad(init_qty, 8)
        # make sure manually formed OP_RETURN is correct
        scriptBuffer_manual = ScriptOutput.from_string(asm_manual)
        expected_hex = scriptBuffer_manual.script.hex()
        expected_asm = scriptBuffer_manual.to_asm()
        if len(scriptBuffer_manual.script) > 223:
            raise Exception("OP_RETURN message too large, needs to be under 220 bytes")
        # form OP_RETURN script using the SLP method
        slpTokenFactory = SlpTokenTransactionFactory(token_version = token_type)
        scriptBuffer_factory = slpTokenFactory.buildInitOpReturnOutput_V1(ticker=ticker, token_name=name, token_document_url=doc_url, token_document_hash_hex=doc_hash_hex, initial_token_mint_quantity=init_qty)
        self.assertEqual(expected_hex, scriptBuffer_factory[1].script.hex())
        self.assertEqual(expected_asm, scriptBuffer_factory[1].to_asm())
        # parse raw OP_RETURN hex to an SlpMessage INIT
        scriptOutput = ScriptOutput(script = bytes.fromhex(expected_hex))
        asm = scriptOutput.to_asm()
        self.assertEqual(expected_asm, asm)
        slpMsg = SlpMessage.parseSlpOutputScript(scriptOutput)
        self.assertEqual("00534c50", slpMsg.lokad_id)
        self.assertEqual(SlpTokenType.TYPE_1.value, slpMsg.token_type)
        self.assertEqual(SlpTransactionType.INIT.value, slpMsg.transaction_type)
        self.assertEqual("TEST", slpMsg.op_return_fields['ticker'])
        self.assertEqual("A Test Token", slpMsg.op_return_fields['token_name'])
        self.assertEqual("http://www.bitcoin.cash", slpMsg.op_return_fields['token_doc_url'])
        self.assertEqual(None, slpMsg.op_return_fields['token_doc_hash_hex'])
        self.assertEqual(2100000000000000, slpMsg.op_return_fields['initial_token_mint_quantity'])
        print("INIT Message: " + asm)

    def test_TRAN_opreturn_building_and_parsing_to_a_new_SlpMessage(self):
        # first lets create a new incomming INIT transaction hexidecimal message from scratch...
        lokad_id = "00534c50"               # 04 00534c50
        token_type = 1                      # 01 01
        txn_type = "TRAN"                   # 04 ______
        token_id = "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
        comment = None
        quantities = [1,1,1,1,1, 1,1,1,1,1, 1,1,1,1,1, 1,1,1,1]
        # manually formulate the message
        asm_manual = "OP_RETURN" + " " + \
                    lokad_id + " " + \
                    int_2_hex_left_pad(token_type) + " " + \
                    SlpTokenTransactionFactory.encodeStringToHex(txn_type, 'utf-8') + " " + \
                    token_id + " " + \
                    SlpTokenTransactionFactory.encodeStringToHex(comment, 'utf-8')
        for q in quantities:
            asm_manual = asm_manual + " " + int_2_hex_left_pad(q, 8)
        # make sure manually formed OP_RETURN is correct
        scriptBuffer_manual = ScriptOutput.from_string(asm_manual)
        expected_hex = scriptBuffer_manual.script.hex()
        expected_asm = scriptBuffer_manual.to_asm()
        if len(scriptBuffer_manual.script) > 223:
            raise Exception("OP_RETURN message too large, needs to be under 223 bytes")
        # form OP_RETURN script using the SLP method
        slpTokenFactory = SlpTokenTransactionFactory(token_version = token_type, token_id_hex = token_id)
        scriptBuffer_factory = slpTokenFactory.buildTransferOpReturnOutput_V1(comment = comment, output_qty_array = quantities)
        self.assertEqual(expected_hex, scriptBuffer_factory[1].script.hex())
        self.assertEqual(expected_asm, scriptBuffer_factory[1].to_asm())
        # parse raw OP_RETURN hex to an SlpMessage TRAN
        scriptOutput = ScriptOutput(script = bytes.fromhex(expected_hex))
        asm = scriptOutput.to_asm()
        self.assertEqual(expected_asm, asm)
        slpMsg = SlpMessage.parseSlpOutputScript(scriptOutput)
        self.assertEqual("00534c50", slpMsg.lokad_id)
        self.assertEqual(SlpTokenType.TYPE_1.value, slpMsg.token_type)
        self.assertEqual(SlpTransactionType.TRAN.value, slpMsg.transaction_type)
        self.assertEqual(token_id, slpMsg.op_return_fields['token_id_hex'])
        self.assertEqual(1, slpMsg.op_return_fields['token_output_1'])
        self.assertEqual(1, slpMsg.op_return_fields['token_output_19'])
        print("TRAN Message:" + asm)

    def test_init_transaction(self):
        pass

    def test_tran_transaction(self):
        pass

class TestSlpMessage(unittest.TestCase):

    def test_message_parser(self):
        pass

class TestSlpEnums(unittest.TestCase):

    def test_parse_txn_type_from_hex(self):
        pass

    def test_parse_token_version_from_hex(self):
        pass

if __name__ == '__main__':
    unittest.main()