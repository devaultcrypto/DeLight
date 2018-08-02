from .transaction import Transaction
from .address import ScriptOutput
from .bitcoin import TYPE_SCRIPT
from .address import Script, ScriptError, OpCodes
from enum import Enum


def int_2_bytes_bigendian(number: int, byte_length: int = None):
    number = int(number)
    if byte_length is None: # autosize
        byte_length = (number.bit_length()+7)//8
    # Raises OverflowError if number is too big for this length
    return number.to_bytes(byte_length, 'big')


class OpreturnError(Exception):
    pass

def parseOpreturnToChunks(script: bytes, *,  allow_op_0: bool, allow_op_number: bool):
    """Extract pushed bytes after opreturn. Returns list of bytes() objects,
    one per push.

    Strict refusal of non-push opcodes; bad scripts throw OpreturnError."""
    try:
        ops = Script.get_ops(script)
    except ScriptError as e:
        raise OpreturnError from e

    if ops[0] != OpCodes.OP_RETURN:
        raise OpreturnError('No OP_RETURN')

    chunks = []
    for opitem in ops[1:]:
        op, data = opitem if isinstance(opitem, tuple) else (opitem, None)
        if op > OpCodes.OP_16:
            raise OpreturnError('Non-push opcode', op)
        if op > OpCodes.OP_PUSHDATA4:
            if op == 80:
                raise OpreturnError('Non-push opcode', op)
            if not allow_op_number:
                raise OpreturnError('OP_1NEGATE to OP_16 not allowed', op)
            if op == OpCodes.OP_1NEGATE:
                data = [0x81]
            else: # OP_1 - OP_16
                data = [op-80]
        if op == OpCodes.OP_0 and not allow_op_0:
            raise OpreturnError('OP_0 not allowed')
        chunks.append(b'' if data is None else bytes(data))
    return chunks



# Exceptions caused by malformed or unexpected data found in parsing.
class SlpParsingError(Exception):
    pass

class SlpUnsupportedSlpTokenType(SlpParsingError):
    # Cannot parse OP_RETURN due to unrecognized version
    # (may or may not be valid)
    pass

class SlpInvalidOutputMessage(SlpParsingError):
    # This exception (and subclasses) marks a message as definitely invalid
    # under SLP consensus rules. (either malformed SLP or just not SLP)
    pass


# Exceptions during creation of SLP message.
class SlpSerializingError(Exception):
    pass

class SlpTokenIdMissing(SlpSerializingError):
    pass

class OPReturnTooLarge(SlpSerializingError):
    pass


# This class represents a parsed op_return message that can be used by validator to look at SLP messages
class SlpMessage:
    lokad_id = b"\x00SLP"

    def __init__(self):
        self.token_type  = None
        self.transaction_type  = None
        self.op_return_fields = {}

    # This method attempts to parse a ScriptOutput object as an SLP message.
    # Bad scripts will throw a subclass of SlpParsingError; any other exception indicates a bug in this code.
    # - Unrecognized SLP versions will throw SlpUnsupportedSlpTokenType.
    # - It is a STRICT parser -- consensus-invalid messages will throw SlpInvalidOutputMessage.
    # - Non-SLP scripts will also throw SlpInvalidOutputMessage.
    @staticmethod
    def parseSlpOutputScript(outputScript: ScriptOutput):
        slpMsg = SlpMessage()
        try:
            chunks = parseOpreturnToChunks(outputScript.to_script(), allow_op_0 = False, allow_op_number = False)
        except OpreturnError as e:
            raise SlpInvalidOutputMessage('Bad OP_RETURN', *e.args) from e

        if len(chunks) < 3:
            raise SlpInvalidOutputMessage('Too short')

        if chunks[0] != SlpMessage.lokad_id:
            raise SlpInvalidOutputMessage('Not SLP')

        # check if the token version is supported
        slpMsg.token_type = SlpMessage.parseChunkToInt(chunks[1], 1, 2, True)
        if slpMsg.token_type != 1:
            raise SlpUnsupportedSlpTokenType(slpMsg.token_type)

        # (the following logic is all for version 1)
        try:
            slpMsg.transaction_type = chunks[2].decode('ascii')
        except UnicodeDecodeError:
            # This can occur if bytes > 127 present.
            raise SlpInvalidOutputMessage('Bad transaction type', chunks[2])

        # switch statement to handle different on transaction type
        if slpMsg.transaction_type == 'INIT':
            if len(chunks) != 10:
                raise SlpInvalidOutputMessage('INIT with incorrect number of parameters')
            # keep ticker, token name, document url, document hash as bytes
            # (their textual encoding is not relevant for SLP consensus)
            # but do enforce consensus length limits
            slpMsg.op_return_fields['ticker'] = chunks[3]
            if len(slpMsg.op_return_fields['ticker']) > 8:
                raise SlpInvalidOutputMessage('Ticker too long')
            slpMsg.op_return_fields['token_name'] = chunks[4]
            slpMsg.op_return_fields['token_doc_url'] = chunks[5]
            slpMsg.op_return_fields['token_doc_hash'] = chunks[6]
            if len(slpMsg.op_return_fields['token_doc_hash']) not in (0, 32):
                raise SlpInvalidOutputMessage('Token document hash is incorrect length')

            # decimals -- one byte in range 0-9
            slpMsg.op_return_fields['decimals'] = SlpMessage.parseChunkToInt(chunks[7], 1, 1, True)
            if slpMsg.op_return_fields['decimals'] > 9:
                raise SlpInvalidOutputMessage('Too many decimals')

            ## handle baton for additional minting, but may be empty
            v = slpMsg.op_return_fields['mint_baton_vout'] = SlpMessage.parseChunkToInt(chunks[8], 1, 1)
            if v is not None and v < 2:
                raise SlpInvalidOutputMessage('Mint baton cannot be on vout=0 or 1')

            # handle initial token quantity issuance
            slpMsg.op_return_fields['initial_token_mint_quantity'] = SlpMessage.parseChunkToInt(chunks[9], 8, 8, True)
        elif slpMsg.transaction_type == 'TRAN':
            if len(chunks) < 4:
                raise SlpInvalidOutputMessage('TRAN with too few parameters')
            if len(chunks[3]) != 32:
                raise SlpInvalidOutputMessage('token_id is wrong length')
            slpMsg.op_return_fields['token_id_hex'] = chunks[3].hex()

            # Note that we put an explicit 0 for  ['token_output'][0] since it
            # corresponds to vout=0, which is the OP_RETURN tx output.
            # ['token_output'][1] is the first token output given by the SLP
            # message, i.e., the number listed as `token_output_quantity1` in the
            # spec, which goes to tx output vout=1.
            slpMsg.op_return_fields['token_output'] = (0,) + \
                    tuple( SlpMessage.parseChunkToInt(field, 8, 8, True) for field in chunks[4:] )
            # maximum 19 allowed token outputs, plus 1 for the explicit [0] we inserted.
            if len(slpMsg.op_return_fields['token_output']) > 20:
                raise SlpInvalidOutputMessage('More than 19 output amounts')
        elif slpMsg.transaction_type == 'MINT':
            if len(chunks) != 6:
                raise SlpInvalidOutputMessage('MINT with incorrect number of parameters')
            if len(chunks[3]) != 32:
                raise SlpInvalidOutputMessage('token_id is wrong length')
            slpMsg.op_return_fields['token_id_hex'] = chunks[3].hex()
            v = slpMsg.op_return_fields['mint_baton_vout'] = SlpMessage.parseChunkToInt(chunks[8], 1, 1)
            if v is not None and v < 2:
                raise SlpInvalidOutputMessage('Mint baton cannot be on vout=0 or 1')
            slpMsg.op_return_fields['additional_token_quantity'] = SlpMessage.parseChunkToInt(chunks[5], 8, 8, True)
        elif slpMsg.transaction_type == 'COMM':
            raise NotImplementedError
        else:
            raise SlpInvalidOutputMessage('Bad transaction type', slpMsg.transaction_type)
        return slpMsg

    @staticmethod
    def parseChunkToInt(intBytes: bytes, minByteLen: int, maxByteLen: int, raise_on_Null: bool = False):
        # Parse data as unsigned-big-endian encoded integer.
        # For empty data different possibilities may occur:
        #      minByteLen <= 0 : return 0
        #      raise_on_Null == False and minByteLen > 0: return None
        #      raise_on_Null == True and minByteLen > 0:  raise SlpInvalidOutputMessage
        if len(intBytes) >= minByteLen and len(intBytes) <= maxByteLen:
            return int.from_bytes(intBytes, 'big', signed=False)
        if len(intBytes) == 0 and not raise_on_Null:
            return None
        raise SlpInvalidOutputMessage


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
    def buildInitOpReturnOutput_V1(self, ticker: str, token_name: str, token_document_url: str, token_document_hash_hex: str, decimals: int, baton_vout: int, initial_token_mint_quantity: int) -> tuple:
        script = []
        # OP_RETURN
        script.extend([0x6a])
        # lokad id
        lokad = bytes.fromhex(self.lokad_id)
        script.extend(self.getPushDataOpcode(lokad))
        script.extend(lokad)
        # token version/type
        tokenType = int_2_bytes_bigendian(self.token_version)
        script.extend(self.getPushDataOpcode(tokenType))
        script.extend(tokenType)
        # transaction type
        transType = b'INIT'
        script.extend(self.getPushDataOpcode(transType))
        script.extend(transType)
        # ticker (can be None)
        ticker = SlpTokenTransactionFactory.encodeStringToHex(ticker, 'utf-8', True)
        if ticker is not None:
            ticker = bytes.fromhex(ticker)
            script.extend(self.getPushDataOpcode(ticker))
            script.extend(ticker)
        else:
            script.extend([0x4c, 0x00])
        # name (can be None)
        name = SlpTokenTransactionFactory.encodeStringToHex(token_name, 'utf-8', True)
        if name is not None:
            name = bytes.fromhex(name)
            script.extend(self.getPushDataOpcode(name))
            script.extend(name)
        else:
            script.extend([0x4c, 0x00])
        # doc_url (can be None)
        doc_url = SlpTokenTransactionFactory.encodeStringToHex(token_document_url, 'ascii', True)
        if doc_url is not None:
            doc_url = bytes.fromhex(doc_url)
            script.extend(self.getPushDataOpcode(doc_url))
            script.extend(doc_url)
        else:
            script.extend([0x4c, 0x00])
        # doc_hash (can be None)
        doc_hash = SlpTokenTransactionFactory.encodeHexStringToHex(token_document_hash_hex, True)
        if doc_hash is not None:
            doc_hash = bytes.fromhex(doc_hash)
            script.extend(self.getPushDataOpcode(doc_hash))
            script.extend(doc_hash)
        else:
            script.extend([0x4c, 0x00])
        # decimals
        if decimals > 8 or decimals < 0:
            raise SlpSerializingError()
        decimals = int_2_bytes_bigendian(decimals, 1)
        script.extend(self.getPushDataOpcode(decimals))
        script.extend(decimals)
        # baton vout
        if baton_vout is not None:
            if baton_vout < 2:
                raise SlpSerializingError()
            baton_vout = int_2_bytes_bigendian(baton_vout, 1)
            script.extend(self.getPushDataOpcode(baton_vout))
            script.extend(baton_vout)
        else:
            script.extend([0x4c, 0x00])
        # init quantity
        qty = int_2_bytes_bigendian(initial_token_mint_quantity, 8)
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
        lokad = bytes.fromhex(self.lokad_id)
        script.extend(self.getPushDataOpcode(lokad))
        script.extend(lokad)
        # token version
        tokenType = int_2_bytes_bigendian(self.token_version)
        script.extend(self.getPushDataOpcode(tokenType))
        script.extend(tokenType)
        # transaction type
        transType = b'TRAN'
        script.extend(self.getPushDataOpcode(transType))
        script.extend(transType)
        # token id
        tokenId = bytes.fromhex(self.token_id_hex)
        script.extend(self.getPushDataOpcode(tokenId))
        script.extend(tokenId)
        # output quantities
        if len(output_qty_array) > 20:
            raise Exception("Cannot have more than 20 SLP Token outputs.")
        for qty in output_qty_array:
            if qty < 0:
                raise SlpSerializingError()
            q = int_2_bytes_bigendian(qty, 8)
            script.extend(self.getPushDataOpcode(q))
            script.extend(q)
        scriptBuffer = ScriptOutput(bytes(script))
        if len(scriptBuffer.script) > 223:
            raise OPReturnTooLarge(_("OP_RETURN message too large, needs to be under 220 bytes"))
        return (TYPE_SCRIPT, scriptBuffer, 0)

    @staticmethod
    def encodeStringToHex(stringData: str, encoding = 'utf-8', allow_None = False):
        if not allow_None and (stringData is None or stringData == ''):
            raise SlpSerializingError()
        if stringData is None or stringData == '':
            return None
        return stringData.encode(encoding).hex()

    @staticmethod
    def encodeHexStringToHex(stringData: str, allow_None = False):
        if not allow_None and (stringData is None or stringData == ''):
            raise SlpSerializingError()
        if stringData == '' or stringData is None:
            return None
        if len(stringData) % 2 != 0:
            raise Exception("Hexadecimal string must be of an even length.")
        return stringData

    @staticmethod
    def getPushDataOpcode(byteArray: [int]) -> [int]:
        length = len(byteArray)
        if length == 0:
            return [0x4c, 0x00]
        elif length < 76:
            return [ length ]
        elif length < 256:
            return [ 0x4c, length ]
        else:
            raise SlpSerializingError()

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
