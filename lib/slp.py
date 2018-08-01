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
    MINT = "MINT"
    TRAN = "TRAN"
    COMM = "COMM"

class SlpTokenType(Enum):
    TYPE_1 = 1

# This class represents a parsed op_return message that can be used by validator to look at SLP messages
class SlpMessage():
    def __init__(self):
        self.isChecked = False
        self.isSlpToken = False
        self.isSupportedTokenVersion = False
        self.lokad_id = "00534c50"
        self.token_type  = None
        self.transaction_type  = None
        self.op_return_fields = {}

    # This method attempts to parse a ScriptOutput object as an SLP message.
    # If it fails it will throw SlpInvalidOutputMessage or SlpUnsupportedSlpTokenType or SlpImproperlyFormattedTransaction
    @staticmethod
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
            slpMsg.op_return_fields['token_id_hex'] = SlpMessage.parseHex2HexString(split_asm[4], 32, 32, True)
            # Extract token output amounts.
            # Note that we put an explicit 0 for  ['token_output'][0] since it
            # corresponds to vout=0, which is the OP_RETURN tx output.
            # ['token_output'][1] is the first token output given by the SLP
            # message, i.e., the number listed as `token_output_quantity1` in the
            # spec, which goes to tx output vout=1.
            slpMsg.op_return_fields['token_output'] = [0] + \
                    [ SlpMessage.parseHex2Int(field, 8, 8) for field in split_asm[5:] ]
            # maximum 19 allowed token outputs, plus 1 for the explicit [0] we inserted.
            if len(slpMsg.op_return_fields['token_output']) > 20:
                raise SlpInvalidOutputMessage()
            return slpMsg
        elif slpMsg.transaction_type == SlpTransactionType.MINT.value:
            raise NotImplementedError()
        elif slpMsg.transaction_type == SlpTransactionType.COMM.value:
            raise NotImplementedError()

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
    def parseHex2String(stringHex: str, minByteLen: int = 1, maxByteLen: int = None, encoding: str = 'utf-8', raise_on_Null: bool = False) -> str:
        if stringHex == '<EMPTY>' and not raise_on_Null:
            return None
        elif stringHex == '<EMPTY>':
            raise SlpInvalidOutputMessage()
        if maxByteLen is not None:
            if len(stringHex) > (maxByteLen * 2):
                raise SlpInvalidOutputMessage()
        if len(stringHex) < (minByteLen * 2):
            raise SlpInvalidOutputMessage()
        try:
            decoded = bytes.fromhex(stringHex).decode('utf-8')
        except UnicodeDecodeError:
            raise SlpImproperlyFormattedTransaction()
        if decoded == '00':
            return None
        return decoded

    @staticmethod
    def parseHex2Int(intHex: str, minByteLen: int = 1, maxByteLen: int = 8):
        if maxByteLen is not None:
            if len(intHex) > (maxByteLen * 2):
                raise SlpInvalidOutputMessage()
        if len(intHex) < (minByteLen * 2):
            raise SlpInvalidOutputMessage()
        try:
            decoded = int(intHex, 16)
        except:
            raise Exception("An error occured while parsing integer")
        return decoded

    @staticmethod
    def parseHex2HexString(hexStr: str, minByteLen: int = 1, maxByteLen: int = 32, raise_on_Null: bool = False) -> str:
        if hexStr == '<EMPTY>' and not raise_on_Null:
            return None
        elif hexStr == '<EMPTY>':
            raise SlpInvalidOutputMessage()
        if minByteLen is not None:
            if len(hexStr) < (minByteLen * 2):
                raise SlpInvalidOutputMessage()
        if maxByteLen is not None:
            if len(hexStr) > (maxByteLen * 2):
                raise SlpInvalidOutputMessage()
        return hexStr

# This class has sole responsibility for creating NEW SLP token transactions
# Since there is currently only one token type, this implementation is
# currently void of any Token Type selection logic, which will be required
# if more than 1 token types are ever desired for Electron Cash.
class SlpTokenTransactionFactory():
    def __init__(self, token_version: int, token_id_hex: str = None):
        if issubclass(type(token_version), Enum):
            self.token_version = token_version.value
        elif issubclass(type(token_version), int):
            self.token_version = token_version
        else:
            raise SlpUnsupportedSlpTokenType

        self.token_id_hex = token_id_hex
        self.lokad_id = "00534c50"

    # Type 1 Token INIT Message
    def buildInitOpReturnOutput_V1(self, ticker: str, token_name: str, token_document_url: str, token_document_hash_hex: str, initial_token_mint_quantity: int) -> tuple:
        script = []
        # OP_RETURN
        script.extend([0x6a])
        # lokad id
        lokad = bytearray.fromhex(self.lokad_id)
        script.extend(self.getPushDataOpcode(lokad))
        script.extend(lokad)
        # token version/type
        tokenType = bytearray.fromhex(int_2_hex_left_pad(self.token_version))
        script.extend(self.getPushDataOpcode(tokenType))
        script.extend(tokenType)
        # transaction type
        transType = bytearray.fromhex(SlpTokenTransactionFactory.encodeStringToHex("INIT", 'utf-8'))
        script.extend(self.getPushDataOpcode(transType))
        script.extend(transType)
        # ticker (can be None)
        ticker = SlpTokenTransactionFactory.encodeStringToHex(ticker, 'utf-8', True)
        if ticker is not None:
            ticker = bytearray.fromhex(ticker)
            script.extend(self.getPushDataOpcode(ticker))
            script.extend(ticker)
        if ticker is None:
            script.extend([0x4c, 0x00])
        # name (can be None)
        name = SlpTokenTransactionFactory.encodeStringToHex(token_name, 'utf-8', True)
        if name is not None:
            name = bytearray.fromhex(name)
            script.extend(self.getPushDataOpcode(name))
            script.extend(name)
        if name is None:
            script.extend([0x4c, 0x00])
        # doc_url (can be None)
        doc_url = SlpTokenTransactionFactory.encodeStringToHex(token_document_url, 'ascii', True)
        if doc_url is not None:
            doc_url = bytearray.fromhex(doc_url)
            script.extend(self.getPushDataOpcode(doc_url))
            script.extend(doc_url)
        elif doc_url is None:
            script.extend([0x4c, 0x00])
        # doc_hash (can be None)
        doc_hash = SlpTokenTransactionFactory.encodeHexStringToHex(token_document_hash_hex, True)
        if doc_hash is not None:
            doc_hash = bytearray.fromhex(doc_hash)
            script.extend(self.getPushDataOpcode(doc_hash))
            script.extend(doc_hash)
        elif doc_hash is None:
            script.extend([0x4c, 0x00])
        # init quantity
        qty = bytearray.fromhex(int_2_hex_left_pad(initial_token_mint_quantity, 8))
        script.extend(self.getPushDataOpcode(qty))
        script.extend(qty)

        # TODO: handle max_final_token_supply -- future baton case
        #scriptBuffer = ScriptOutput.from_string(script)
        scriptBuffer = ScriptOutput(bytes(script))
        if len(scriptBuffer.script) > 223:
            raise OPReturnTooLarge(_("OP_RETURN message too large, needs to be under 220 bytes"))
        return (TYPE_SCRIPT, scriptBuffer, 0)

    # Type 1 Token TRAN Message
    def buildTransferOpReturnOutput_V1(self, output_qty_array: []) -> tuple:
        if self.token_id_hex == None:
            raise SlpTokenIdMissing
        script = []
        # OP_RETURN
        script.extend([0x6a])
        # lokad
        lokad = bytearray.fromhex(self.lokad_id)
        script.extend(self.getPushDataOpcode(lokad))
        script.extend(lokad)
        # token version
        tokenType = bytearray.fromhex(int_2_hex_left_pad(self.token_version))
        script.extend(self.getPushDataOpcode(tokenType))
        script.extend(tokenType)
        # transaction type
        transType = bytearray.fromhex(SlpTokenTransactionFactory.encodeStringToHex("TRAN", 'utf-8'))
        script.extend(self.getPushDataOpcode(transType))
        script.extend(transType)
        # token id
        tokenId = bytearray.fromhex(self.token_id_hex)
        script.extend(self.getPushDataOpcode(tokenId))
        script.extend(tokenId)
        # output quantities
        if len(output_qty_array) > 20:
            raise Exception("Cannot have more than 20 SLP Token outputs.")
        for qty in output_qty_array:
            if qty < 0:
                raise SlpInvalidOutputMessage()
            q = bytearray.fromhex(int_2_hex_left_pad(qty, 8))
            script.extend(self.getPushDataOpcode(q))
            script.extend(q)
        scriptBuffer = ScriptOutput(bytes(script))
        if len(scriptBuffer.script) > 223:
            raise OPReturnTooLarge(_("OP_RETURN message too large, needs to be under 220 bytes"))
        return (TYPE_SCRIPT, scriptBuffer, 0)

    @staticmethod
    def encodeStringToHex(stringData: str, encoding = 'utf-8', allow_None = False):
        if not allow_None and (stringData is None or stringData == ''):
            raise SlpInvalidOutputMessage()
        if stringData is None or stringData == '':
            return None
        return stringData.encode(encoding).hex()

    @staticmethod
    def encodeHexStringToHex(stringData: str, allow_None = False):
        if not allow_None and (stringData is None or stringData == ''):
            raise SlpInvalidOutputMessage()
        if stringData == '' or stringData is None:
            return None
        if len(stringData) % 2 is not 0:
            raise Exception("Hexidecimal string must be of an even length.")
        return stringData

    @staticmethod
    def getPushDataOpcode(byteArray: [int]) -> [int]:
        length = len(byteArray)
        if length is 0 or length is None:
            return [0x4c, 0x00]
        elif length > 0 and length < 76:
            return [ length ]
        elif length > 75:
            return [ 0x4c, length ]
        else:
            raise SlpInvalidOutputMessage()

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
