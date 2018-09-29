"""
Creates and parses transactions that hold file data chunk at vout0 OP_RETURN.  Multi-chunk uploads are handled using 
    vout1 as a pointer to the location of the next file chunk.  Visit http://bitcoinfiles.com for more info.

Multi-part file chunks are committed to the blockchain as transactions using the following sequence:
1. File is partitioned into 220 byte chunks.
2. The last file chunk remainder will be placed within the Metadata OP_RETURN message if there is sufficient room
3. The file is identified using the txid of the txn containing the Metadata OP_RETURN message (longest point in txn chain)
4. The chunks are resolved by traversing a chain of transactions from the Metadata txn backwards until the first data chunk is found

Max message length to fit in 223 byte op_return relay limit: 204 bytes
"""
from .address import Address, ScriptOutput
from . import util
from . import bitcoin

from .transaction import Transaction
from .bitcoin import TYPE_SCRIPT, TYPE_ADDRESS
from .address import Script, ScriptError, OpCodes
from enum import Enum
from .network import Network

lokad_id = b"BFP\x00"

class BfpParsingError(Exception):
    pass

class BfpUnsupportedBfpMsgType(BfpParsingError):
    # Cannot parse OP_RETURN due to unrecognized version
    # (may or may not be valid)
    pass

class BfpOpreturnError(Exception):
    pass

class BfpInvalidOutput(BfpParsingError):
    pass

# Exceptions during creation of SLP message.
class BfpSerializingError(Exception):
    pass

class BfpInvalidOutputMessage(BfpParsingError):
    # This exception (and subclasses) marks a message as definitely invalid
    # under SLP consensus rules. (either malformed SLP or just not SLP)
    pass

def make_bitcoinfile_chunk_opreturn(data: bytes):
    pushes = []

    # file chunk data
    if data is None:
        pushes.append(b'')
    else:
        if not isinstance(data, (bytes, bytearray)):
            raise BfpSerializingError()
        pushes.append(data)

    return chunksToOpreturnOutput(pushes)

def make_bitcoinfile_metadata_opreturn(version: int, chunk_count: int, data: bytes = None, filename = None, fileext = None, filesize: int = None, filehash: bytes = None, prev_filehash: bytes = None, fileuri = None):
    pushes = []

    # lokad id
    pushes.append(lokad_id)

    # version/type
    pushes.append(version.to_bytes(1,'big'))

    # file chunk count
    pushes.append(chunk_count.to_bytes(1,'big'))

    #filename
    if filename is None or filename is '':
        pushes.append(b'')
    else:
        pushes.append(filename.encode('utf-8'))

    # fileext
    if fileext is None or fileext is '':
        pushes.append(b'')
    else: 
        pushes.append(fileext.encode('utf-8'))

    # filesize
    if filesize is None:
        pushes.append(b'')
    else:
        pushes.append(filesize.to_bytes(2,'big'))

    # filehash sha256
    if filehash is None or filehash is '':
        pushes.append(b'')
    else:
        hashbytes = bytes.fromhex(filehash)
        if len(hashbytes) not in (0, 32):
            raise BfpSerializingError()
        pushes.append(hashbytes)

    # previous sha256 filehash
    if prev_filehash is None or prev_filehash is '':
        pushes.append(b'')
    else: 
        hashbytes = bytes.fromhex(prev_filehash)
        if len(hashbytes) not in (0, 32):
            raise BfpSerializingError()
        pushes.append(hashbytes)

    # external URI
    if fileuri is None or fileuri is '':
        pushes.append(b'')
    else: 
        pushes.append(fileuri.encode('utf-8'))

    # file chunk data
    if data is None:
        pushes.append(b'')
    else:
        if not isinstance(data, (bytes, bytearray)):
            raise BfpSerializingError()
        pushes.append(data)
        
    return chunksToOpreturnOutput(pushes)

# utility for creation: use smallest push except not any of: op_0, op_1negate, op_1 to op_16
def pushChunk(chunk: bytes) -> bytes: # allow_op_0 = False, allow_op_number = False
    length = len(chunk)
    if length == 0:
        return b'\x4c\x00' + chunk
    elif length < 76:
        return bytes((length,)) + chunk
    elif length < 256:
        return bytes((0x4c,length,)) + chunk
    elif length < 65536: # shouldn't happen but eh
        return b'\x4d' + length.to_bytes(2, 'little') + chunk
    elif length < 4294967296: # shouldn't happen but eh
        return b'\x4e' + length.to_bytes(4, 'little') + chunk
    else:
        raise ValueError()

def chunksToOpreturnOutput(chunks: [bytes]) -> tuple:
    script = bytearray([0x6a,]) # start with OP_RETURN
    for c in chunks:
        script.extend(pushChunk(c))

    if len(script) > 223:
        raise OPReturnTooLarge('OP_RETURN message too large, cannot be larger than 223 bytes')

    return (TYPE_SCRIPT, ScriptOutput(bytes(script)), 0)

def parseOpreturnToChunks(script: bytes, *,  allow_op_0: bool, allow_op_number: bool):
    """Extract pushed bytes after opreturn. Returns list of bytes() objects,
    one per push.

    Strict refusal of non-push opcodes; bad scripts throw BfpOpreturnError."""
    try:
        ops = Script.get_ops(script)
    except ScriptError as e:
        raise BfpOpreturnError('Script error') from e

    if ops[0] != OpCodes.OP_RETURN:
        raise BfpOpreturnError('No OP_RETURN')

    chunks = []
    for opitem in ops[1:]:
        op, data = opitem if isinstance(opitem, tuple) else (opitem, None)
        if op > OpCodes.OP_16:
            raise BfpOpreturnError('Non-push opcode')
        if op > OpCodes.OP_PUSHDATA4:
            if op == 80:
                raise BfpOpreturnError('Non-push opcode')
            if not allow_op_number:
                raise BfpOpreturnError('OP_1NEGATE to OP_16 not allowed')
            if op == OpCodes.OP_1NEGATE:
                data = [0x81]
            else: # OP_1 - OP_16
                data = [op-80]
        if op == OpCodes.OP_0 and not allow_op_0:
            raise BfpOpreturnError('OP_0 not allowed')
        chunks.append(b'' if data is None else bytes(data))
    return chunks

def parseChunkToInt(intBytes: bytes, minByteLen: int, maxByteLen: int, raise_on_Null: bool = False):
    # Parse data as unsigned-big-endian encoded integer.
    # For empty data different possibilities may occur:
    #      minByteLen <= 0 : return 0
    #      raise_on_Null == False and minByteLen > 0: return None
    #      raise_on_Null == True and minByteLen > 0:  raise BfpInvalidOutput
    if len(intBytes) >= minByteLen and len(intBytes) <= maxByteLen:
        return int.from_bytes(intBytes, 'big', signed=False)
    if len(intBytes) == 0 and not raise_on_Null:
        return None
    raise BfpInvalidOutput('Field has wrong length')

def getUploadTxn(wallet, prev_tx, chunk_index, chunk_count, chunk_data, config, metadata, file_receiver: Address):
    """
    NOTE: THIS METHOD ONLY WORKS WITH 1 TRANSACTION CURRENTLY, LIMITS SIZE TO 223 BYTES
    """

    # this flag is returned to indicate which upload message was used in txn
    is_metadata_txn = False

    assert wallet.txin_type == 'p2pkh'

    if chunk_index == 0:
        out_type, address, amount = prev_tx.outputs()[0]
        assert out_type == 0
        vout = 0
    else:
        out_type, address, amount = prev_tx.outputs()[1]
        assert out_type == 0
        vout = 1

    coins = [{
        'address': address,
        'value': amount,
        'prevout_n': int(vout),
        'prevout_hash': prev_tx.txid(),
        'height': 0,
        'coinbase': False
    }]

    final_op_return_no_chunk = make_bitcoinfile_metadata_opreturn(1, chunk_count, None, metadata['filename'], metadata['fileext'], metadata['filesize'], metadata['file_sha256'], metadata['prev_file_sha256'], metadata['uri'])
    if chunk_data == None:
        chunk_length = 0
    else:
        chunk_length = len(chunk_data)

    # Check for scenario where last chunk can fit into Metadata message.  Chunk may be data or None.
    if chunk_index >= chunk_count - 1 and chunk_can_fit_in_final_opreturn(final_op_return_no_chunk, chunk_length):
        is_metadata_txn = True
        op_return = make_bitcoinfile_metadata_opreturn(1, chunk_count, chunk_data, metadata['filename'], metadata['fileext'], metadata['filesize'], metadata['file_sha256'], metadata['prev_file_sha256'], metadata['uri'])
        miner_fee = estimate_miner_fee(1, 1, len(op_return[1].to_script()))
        dust_output = (amount - miner_fee) if (amount - miner_fee) >= 546 else 546
        address = file_receiver if file_receiver != None else address
        assert isinstance(address, Address)
        askedoutputs = [ op_return, (TYPE_ADDRESS, address, dust_output) ]
        
    # Check for scenarios where Metadata message should not be used
    else:
        op_return = make_bitcoinfile_chunk_opreturn(chunk_data)
        miner_fee = estimate_miner_fee(1, 1, len(op_return[1].to_script()))
        dust_output = (amount - miner_fee) if (amount - miner_fee) >= 546 else 546
        askedoutputs = [ op_return, (TYPE_ADDRESS, address, dust_output) ]

    fee = None
    change_addr = None

    tx = wallet.make_unsigned_transaction_for_bitcoinfiles(coins, askedoutputs, config, fee, change_addr)

    # unfortunately, the outputs might be in wrong order due to BIPLI01
    # output sorting, so we remake it.
    outputs = tx.outputs()
    outputs = askedoutputs + [o for o in outputs if o not in askedoutputs]
    tx = Transaction.from_io(tx.inputs(), outputs, tx.locktime)
    return tx, is_metadata_txn

def chunk_can_fit_in_final_opreturn(final_op_return_no_chunk, chunk_data_length:int = 0):
    if chunk_data_length == 0:
        return True
    op_return_min_length = len(final_op_return_no_chunk[1].to_script())
    op_return_capacity = 223 - op_return_min_length
    if op_return_capacity >= chunk_data_length:
        return True
    return False

def get_push_data_length(data_count):
    if data_count > 75:
        return data_count + 1
    else: 
        return data_count + 2

def estimate_miner_fee(p2pkh_input_count, p2pkh_output_count, opreturn_size, feerate = 1):
    bytecount = (p2pkh_input_count * 148) + (p2pkh_output_count * 35) + opreturn_size + 22
    return bytecount * feerate

def getFundingTxn(wallet, address, amount, config):
    
    assert wallet.txin_type == 'p2pkh'

    askedoutputs = [ (TYPE_ADDRESS, address, amount), ]

    # set config key 'confirmed_only' temporarily to True
    domain = None
    org_confirmed_only = config.get('confirmed_only', False)
    config.set_key('confirmed_only', True)
    assert config.get('confirmed_only', False) == True

    coins = wallet.get_spendable_coins(domain, config)
    fee = None
    change_addr = None
    tx = wallet.make_unsigned_transaction(coins, askedoutputs, config, fee, change_addr)

    # Change key back to original setting
    config.set_key('confirmed_only', org_confirmed_only)
    assert config.get('confirmed_only', False) == org_confirmed_only

    # unfortunately, the outputs might be in wrong order due to BIPLI01
    # output sorting, so we remake it.
    outputs = tx.outputs()
    outputs = askedoutputs + [o for o in outputs if o not in askedoutputs]
    tx = Transaction.from_io(tx.inputs(), outputs, tx.locktime)

    return tx

def calculateUploadCost(file_size, metadata, fee_rate = 1):
    byte_count = file_size

    whole_chunks_count = int(file_size / 220)
    last_chunk_size = file_size % 220

    if last_chunk_size > 0:
        chunk_count = whole_chunks_count + last_chunk_size
    else:
        chunk_count = whole_chunks_count

    # cost of final transaction's op_return w/o any chunkdata
    final_op_return_no_chunk = make_bitcoinfile_metadata_opreturn(1, chunk_count, None, metadata['filename'], metadata['fileext'], metadata['filesize'], metadata['file_sha256'], metadata['prev_file_sha256'], metadata['uri'])
    byte_count += len(final_op_return_no_chunk[1].to_script())

    # cost of final transaction's input/outputs
    byte_count += 35
    byte_count += 148 + 1

    # cost of chunk trasnsaction op_returns
    byte_count += (whole_chunks_count + 1) * 3

    if not chunk_can_fit_in_final_opreturn(final_op_return_no_chunk, last_chunk_size):
        # add fees for an extra chunk transaction input/output
        byte_count += 149 + 35
        # opcode cost for chunk op_return 
        byte_count += 16

    # output p2pkh
    byte_count += 35 * (whole_chunks_count)

    # dust input bytes (this is the initial payment for the file upload)
    byte_count += (148 + 1) * whole_chunks_count

    # other unaccounted per txn
    byte_count += 22 * (whole_chunks_count + 1)

    # dust output to be passed along each txn
    dust_amount = 546

    return byte_count * fee_rate + dust_amount

class BfpMessage:
    lokad_id = lokad_id

    def __init__(self):
        self.msg_type = None
        self.op_return_fields = {}

    def __repr__(self,):
        return "<%s msg_type=%d %r %r>"%(type(self).__qualname__, self.msg_type, self.op_return_fields)

    # This method attempts to parse a ScriptOutput object as an BFP message.
    # Bad scripts will throw a subclass of BfpParsingError; any other exception indicates a bug in this code.
    # - Unrecognized SLP versions will throw BfpUnsupportedSlpTokenType.
    # - It is a STRICT parser -- consensus-invalid messages will throw BfpInvalidOutputMessage.
    # - Non-SLP scripts will also throw BfpInvalidOutputMessage.
    @staticmethod
    def parseBfpScriptOutput(outputScript: ScriptOutput):
        bfpMsg = BfpMessage()
        try:
            chunks = parseOpreturnToChunks(outputScript.to_script(), allow_op_0 = False, allow_op_number = False)
        except BfpOpreturnError as e:
            raise BfpInvalidOutputMessage('Bad OP_RETURN', *e.args) from e

        if len(chunks) == 0:
            raise BfpInvalidOutputMessage('Empty OP_RETURN')

        if chunks[0] != lokad_id:
            raise BfpInvalidOutputMessage('Not BFP')

        if len(chunks) == 1:
            raise BfpInvalidOutputMessage('Missing msg_type')

        bfpMsg.msg_type = parseChunkToInt(chunks[1], 1, 1, True)
        if bfpMsg.msg_type != 1:
            raise BfpUnsupportedBfpMsgType(bfpMsg.msg_type)

        if bfpMsg.msg_type == 1:

            if len(chunks) != 10:
                raise BfpInvalidOutputMessage('On-Chain file BFP message with incorrect number of parameters')

            try:
                bfpMsg.op_return_fields['chunk_count'] = parseChunkToInt(chunks[2], 1, 1, True)
            except:
                raise BfpInvalidOutputMessage('Bad chunk count')

            bfpMsg.op_return_fields['filename'] = chunks[3]
            bfpMsg.op_return_fields['fileext'] = chunks[4]
            bfpMsg.op_return_fields['size'] = parseChunkToInt(chunks[5], 0, 2, False)

            bfpMsg.op_return_fields['file_sha256'] = chunks[6]
            if len(bfpMsg.op_return_fields['file_sha256']) not in (0, 32):
                raise BfpInvalidOutputMessage('File Hash is incorrect length for sha256')

            bfpMsg.op_return_fields['prev_file_sha256'] = chunks[7]
            if len(bfpMsg.op_return_fields['prev_file_sha256']) not in (0, 32):
                raise BfpInvalidOutputMessage('Previous hash is incorrect length for sha256')
            
            bfpMsg.op_return_fields['uri'] = chunks[8]
            bfpMsg.op_return_fields['chunk_data'] = chunks[9]
        else:
            raise BfpInvalidOutputMessage('Not a BFP metadata message')
        return bfpMsg