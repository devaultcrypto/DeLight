from .transaction import Transaction
from .address import ScriptOutput
from .bitcoin import TYPE_SCRIPT
from enum import Enum

def int_2_hex_left_pad(number: int, byte_length: int = None):
    hex_val = hex(number).split('0x')[1]
    if byte_length is None and len(hex_val) % 2 is 1 :
        return "0" + hex_val
    elif byte_length > 0 and byte_length * 2 > len(hex_val):
        while byte_length * 2 > len(hex_val):
            hex_val = "0" + hex_val
        return hex_val
    elif byte_length * 2 < len(hex_val):
        raise Exception("The number provided results in too many bytes.")
    elif byte_length * 2 == len(hex_val):
        return hex_val
    else:
        raise Exception("Unhandled case.")

class SlpInvalidOutputMessage(Exception):
    pass

class SlpUnsupportedSlpTokenType(Exception):
    pass

class SlpTokenIdMissing(Exception):
    pass

class SlpTransactionType(Enum):
    INIT = "INIT"
    #MINT = "MINT"
    TRAN = "TRAN"
    #COMM = "COMM"

class SlpTokenType(Enum):
    TYPE_1 = 1

# This class represents a parsed op_return message that can be used by validator to look at SLP messages
class SlpMessage():
    def __init__(self):
        self.isChecked = False
        self.isSlpToken = False
        self.isSupportedTokenVersion = False
        self.lokad_id: str = '00534c50'
        self.token_type: SlpTokenType = None
        self.transaction_type: SlpTransactionType = None
        self.op_return_fields = {}

    # This method attempts to parse a ScriptOutput object as an SLP message.
    # If it fails it will throw SlpInvalidOutputMessage or SlpUnsupportedSlpTokenType or SlpImproperlyFormattedTransaction
    def parseSlpOutputScript(outputScript: ScriptOutput):
        slpMsg = SlpMessage()
        # convert raw script to ASM Human-readable format w/o pushdata commands
        asm = outputScript.to_asm()
        # Split asm format with spaces
        split_asm = asm.split(' ')
        # check script is OP_RETURN
        if split_asm[0] != 'OP_RETURN':
            raise SlpInvalidOutputMessage()
        # check that the locad ID is correct
        if split_asm[1] != slpMsg.lokad_id:
            raise SlpInvalidOutputMessage()
        # check if the token version is supported
        slpMsg.token_type = SlpMessage.parseHex2TokenVersion(split_asm[2])
        # check if the slp transaction type is valid
        slpMsg.transaction_type = SlpMessage.parseHex2TransactionType(split_asm[3])
        slpMsg.isSlpToken = True
        if slpMsg.token_type is SlpTokenType.TYPE_1.value:
            slpMsg.isSupportedTokenVersion = True
        else:
            raise SlpUnsupportedSlpTokenType()
        # switch statement to handle different on transaction type
        if slpMsg.transaction_type == SlpTransactionType.INIT.value:
            # TEMPLATE FROM ABOVE:
            # "OP_RETURN " + \
            # self.lokad_id + " " + \
            # self.token_version + \
            # " INIT " + \
            # ticker + " " + \
            # token_name + " " + \
            # token_document_ascii_url + " " + \
            # token_document_hash + " " + \
            # initial_token_mint_quantity
            # handle ticker
            slpMsg.op_return_fields['ticker'] = SlpMessage.parseHex2String(split_asm[4], 1, 8, 'utf-8')
            # handle token name
            slpMsg.op_return_fields['token_name'] = SlpMessage.parseHex2String(split_asm[5], 1, 100, 'utf-8')
            # handle token docuemnt url
            slpMsg.op_return_fields['token_doc_url'] = SlpMessage.parseHex2String(split_asm[6], 1, 100, 'ascii')
            # handle token docuemnt hash
            slpMsg.op_return_fields['token_doc_hash_hex'] = SlpMessage.parseHex2HexString(split_asm[7], 32, 32)
            # handle initial token quantity issuance
            slpMsg.op_return_fields['initial_token_mint_quantity'] = SlpMessage.parseHex2Int(split_asm[8], 8, 8)
            slpMsg.isChecked = True
            return slpMsg

        elif slpMsg.transaction_type == SlpTransactionType.TRAN.value:
            # "OP_RETURN " + \
            # self.lokad_id + " " + \
            # self.token_version + \
            # " TRAN " + \
            # self.token_id
            # comment
            # <QUANTITIES HERE>

            slpMsg.op_return_fields['token_id_hex'] = SlpMessage.parseHex2HexString(split_asm[4], 32, 32, True)
            slpMsg.op_return_fields['comment'] = SlpMessage.parseHex2String(split_asm[5], 1, 27)
            outputs = len(split_asm) - 6
            for (field, i) in split_asm:
                if i > 5:
                    try:
                        slpMsg.op_return_fields['token_output_' + str(i-5)] = SlpMessage.parseHex2Int(field, 8, 8)
                    except: 
                        raise SlpImproperlyFormattedTransaction()
            return slpMsg

    @staticmethod
    def parseHex2TransactionType(typeHex: str) -> str:
        decoded = bytes.fromhex(typeHex).decode('ascii')
        if decoded == SlpTransactionType.INIT.value:
            return decoded
        elif decoded == SlpTransactionType.TRAN.value:
            return decoded
        else:
            raise SlpInvalidOutputMessage()

    @staticmethod
    def parseHex2TokenVersion(versionHex: str) -> int:
        if len(versionHex) > 4 or len(versionHex) < 2:
            raise SlpInvalidOutputMessage()
        if versionHex == '00':
            raise SlpInvalidOutputMessage()
        decoded = int(versionHex, 16)
        if decoded is SlpTokenType.TYPE_1.value:
            return decoded
        else: 
            raise SlpInvalidOutputMessage()

    @staticmethod
    def parseHex2String(stringHex: str, minByteLen: int = 1, maxByteLen: int = None, encoding: str = 'utf-8', raise_on_0x00: bool = False) -> str:
        if maxByteLen is not None:
            if len(stringHex) > maxByteLen * 2:
                raise SlpInvalidOutputMessage()
        if len(stringHex) < minByteLen * 2:
            raise SlpInvalidOutputMessage()
        if stringHex == '00' and raise_on_0x00:
            raise SlpInvalidOutputMessage()
        elif stringHex == '00':
            return None
        try:
            decoded = bytes.fromhex(stringHex).decode('utf-8')
        except UnicodeDecodeError:
            raise SlpImproperlyFormattedTransaction()
        if decoded == '00':
            return None
        return decoded

    @staticmethod
    def parseHex2Int(intHex: str, minByteLen: int = 1, maxByteLen: int = 8, raise_on_0x00: bool = False):
        if maxByteLen is not None:
            if len(intHex) > maxByteLen * 2:
                raise SlpInvalidOutputMessage()
        if len(intHex) < minByteLen * 2:
            raise SlpInvalidOutputMessage()
        if intHex == '00' and raise_on_0x00:
            raise SlpInvalidOutputMessage()
        elif intHex == '00':
            return 0
        try: 
            decoded = int(intHex, 16)
        except:
            raise Exception("An error occured while parsing integer")
        return decoded

    @staticmethod
    def parseHex2HexString(hexStr: str, minByteLen: int = 1, maxByteLen: int = 32, raise_on_0x00: bool = False):
        if hexStr == '00' and raise_on_0x00:
            raise SlpInvalidOutputMessage()
        elif hexStr == '00':
            return None
        if minByteLen is not None:
            if len(hexStr) * 2 < minByteLen:
                raise SlpInvalidOutputMessage()
        if maxByteLen is not None:
            if len(hexStr) * 2 > maxByteLen:
                raise SlpInvalidOutputMessage()
        return hexStr

# This class has sole responsibility for creating NEW SLP token transactions
# Since there is currently only one token type, this implementation is 
# currently void of any Token Type selection logic, which will be required
# if more than 1 token types are ever desired for Electron Cash.
class SlpTokenTransactionFactory():
    def __init__(self, token_version: int = SlpTokenType.TYPE_1, token_id_hex: str = None):
        self.token_version = token_version
        self.token_id_hex = token_id_hex
        self.lokad_id: str = '00534c50'

    # Token Version agnostic INIT Transaction Builder
    def buildInitTransaction(self, inputs, output_mint_reciever, ticker: str, token_name: str, token_document_ascii_url: str,  token_document_hash_hex: str, initial_token_mint_quantity: int) -> Transaction:
        tx = Transaction()
        tx.add_inputs(inputs)
        vouts = []
        vouts.append(self.buildInitOpReturnOutput_V1(ticker, token_name, token_document_ascii_url, token_document_hash_hex, initial_token_mint_quantity))
        vouts.append(output_mint_reciever)
        return tx

    # Token Version agnostic INIT Transaction Builder
    def buildTransferTransaction(self, inputs, outputs, comment: str, output_token_quantity_array: [int]) -> Transaction:
        if self.token_id == None:
            raise SlpTokenIdMissing
        tx = Transaction()
        tx.add_inputs(inputs)
        vouts = []
        vouts.append(self.buildTransferOpReturnOutput_V1(comment, output_token_quantity_array))
        vouts.extend(outputs)
        return tx

    # Type 1 Token INIT Message
    def buildInitOpReturnOutput_V1(self, ticker: str, token_name: str, token_document_url: str, token_document_hash: int, initial_token_mint_quantity: int) -> tuple:
        script = "OP_RETURN " + \
                    self.lokad_id + " " + \
                    int_2_hex_left_pad(self.token_version) + " " + \
                    "INIT".encode('utf-8').hex() + " " + \
                    ticker.encode('utf-8').hex() + " " + \
                    token_name.encode('utf-8').hex() + " " + \
                    token_document_url.encode('ascii').hex() + " " + \
                    int_2_hex_left_pad(token_document_hash) + " " + \
                    int_2_hex_left_pad(initial_token_mint_quantity, 8)

        # TODO: handle max_final_token_supply -- future baton case
        scriptBuffer = ScriptOutput.from_string(script)
        if len(scriptBuffer.script) > 223:
            raise OPReturnTooLarge(_("OP_RETURN message too large, needs to be under 220 bytes"))
        return (TYPE_SCRIPT, scriptBuffer, 0)

    # Type 1 Token TRAN Message
    def buildTransferOpReturnOutput_V1(self, comment: str, output_qty_array: []) -> tuple:

        if self.token_id_hex == None:
            raise SlpTokenIdMissing

        script = "OP_RETURN " + \
                self.lokad_id + " " + \
                int_2_hex_left_pad(self.token_version) + " " + \
                "TRAN".encode('utf-8').hex() + " " + \
                self.token_id_hex + " " + \
                comment.encode('utf-8').hex() + " " \

        if len(output_qty_array) > 20: 
            raise Exception("Cannot have more than 20 SLP Token outputs.")
        for qty in output_qty_array:
            script = script + " " + int_2_hex_left_pad(qty, 8)
        scriptBuffer = ScriptOutput.from_string(script)
        if len(scriptBuffer.script) > 223:
            raise OPReturnTooLarge(_("OP_RETURN message too large, needs to be under 220 bytes"))
        return (TYPE_SCRIPT, scriptBuffer, 0)

    # def buildMintOpReturnOutput(self, additional_token_quantity):
    #     script = "OP_RETURN " + self.lokad_id + " " + self.token_version + " MINT"
    #     script = script + " " + self.token_id + " " + additional_token_quantity
    #     scriptBuffer = ScriptOutput.from_string(script)
    #     if len(scriptBuffer.script) > 223:
    #         raise OPReturnTooLarge(_("OP_RETURN message too large, needs to be under 220 bytes"))
    #     return (TYPE_SCRIPT, scriptBuffer, 0)

    # def buildCommitmentOpReturnOutput(self, for_bitcoin_block_height, for_bitcoin_block_hash, token_txn_set_commitment, txn_set_data_url):
    #     script = "OP_RETURN " + self.lokad_id + " " + self.token_version + " COMM"
    #     script = script + " " + self.token_id + " " + for_bitcoin_block_height + " " + for_bitcoin_block_height
    #     script = script + " " + token_txn_set_commitment + " " + txn_set_data_url
    #     scriptBuffer = ScriptOutput.from_string(script)
    #     if len(scriptBuffer.script) > 223:
    #         raise OPReturnTooLarge(_("OP_RETURN message too large, needs to be under 220 bytes"))
    #     return (TYPE_SCRIPT, scriptBuffer, 0)