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

lokad_id = b"BFP\x00"

class ParseError(Exception):
    pass

class AuthenticationError(Exception):
    pass

class OpreturnError(Exception):
    pass

class InvalidOutput(ParseError):
    pass

# Exceptions during creation of SLP message.
class SerializingError(Exception):
    pass

def parse_bitcoinfile_output_script(outputScript: ScriptOutput):
    try:
        pushes = parseOpreturnToChunks(outputScript.to_script(), allow_op_0 = False, allow_op_number = False)
    except OpreturnError as e:
        raise InvalidOutput('Bad OP_RETURN', *e.args) from e

    if len(pushes) == 0:
        raise InvalidOutput('Empty OP_RETURN')

    if pushes[0] != lokad_id:
        raise InvalidOutput('Not BFP')

    if len(pushes) == 1:
        raise InvalidOutput('Missing version')

    # check if the token version is supported
    version = parseChunkToInt(pushes[1], 1, 2, True)
    if version != 0:
        raise InvalidOutput('Unsupported version')

    if len(pushes) == 2:
        raise InvalidOutput('Missing chunk_index')
    chunk_index = parseChunkToInt(pushes[2], 1, 1, True)

    if len(pushes) == 3:
        raise InvalidOutput('Missing chunk_count')
    chunk_count = parseChunkToInt(pushes[3], 1, 1, True)

    if len(pushes) == 4:
        raise InvalidOutput('Missing chunk_data')

    chunk_data = pushes[4]

    return version, chunk_index, chunk_count, chunk_data

def make_bitcoinfile_chunk_opreturn(data: bytes):
    pushes = []

    # file chunk data
    if data is None:
        pushes.append(b'')
    else:
        if not isinstance(data, (bytes, bytearray)):
            raise SerializingError()
        pushes.append(data)

    return chunksToOpreturnOutput(pushes)

def make_bitcoinfile_final_opreturn(version: int, chunk_count: int, data: bytes = None, filename = None, fileext = None, filesize: int = None, filehash: bytes = None):
    pushes = []

    # lokad id
    pushes.append(lokad_id)

    # version/type
    pushes.append(bytes((version,)))

    # file chunk count
    pushes.append(bytes((chunk_count,)))

    #filename
    if filename is None:
        pushes.append(b'')
    else:
        pushes.append(filename.encode('utf-8'))

    # fileext
    if fileext is None:
        pushes.append(b'')
    else: 
        pushes.append(fileext.encode('utf-8'))

    # filesize
    if filesize is None:
        pushes.append(b'')
    else:
        pushes.append(bytes((filesize,)))

    # filehash
    if filehash is None:
        pushes.append(b'')
    else: 
        hashbytes = bytes.fromhex(filehash)
        if len(hashbytes) not in (0, 32):
            raise SerializingError()
        pushes.append(hashbytes)

    # file chunk data
    if data is None:
        pushes.append(b'')
    else:
        if not isinstance(data, (bytes, bytearray)):
            raise SerializingError()
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

    Strict refusal of non-push opcodes; bad scripts throw OpreturnError."""
    try:
        ops = Script.get_ops(script)
    except ScriptError as e:
        raise OpreturnError('Script error') from e

    if ops[0] != OpCodes.OP_RETURN:
        raise OpreturnError('No OP_RETURN')

    chunks = []
    for opitem in ops[1:]:
        op, data = opitem if isinstance(opitem, tuple) else (opitem, None)
        if op > OpCodes.OP_16:
            raise OpreturnError('Non-push opcode')
        if op > OpCodes.OP_PUSHDATA4:
            if op == 80:
                raise OpreturnError('Non-push opcode')
            if not allow_op_number:
                raise OpreturnError('OP_1NEGATE to OP_16 not allowed')
            if op == OpCodes.OP_1NEGATE:
                data = [0x81]
            else: # OP_1 - OP_16
                data = [op-80]
        if op == OpCodes.OP_0 and not allow_op_0:
            raise OpreturnError('OP_0 not allowed')
        chunks.append(b'' if data is None else bytes(data))
    return chunks

def parseChunkToInt(intBytes: bytes, minByteLen: int, maxByteLen: int, raise_on_Null: bool = False):
    # Parse data as unsigned-big-endian encoded integer.
    # For empty data different possibilities may occur:
    #      minByteLen <= 0 : return 0
    #      raise_on_Null == False and minByteLen > 0: return None
    #      raise_on_Null == True and minByteLen > 0:  raise InvalidOutput
    if len(intBytes) >= minByteLen and len(intBytes) <= maxByteLen:
        return int.from_bytes(intBytes, 'big', signed=False)
    if len(intBytes) == 0 and not raise_on_Null:
        return None
    raise InvalidOutput('Field has wrong length')

def getUploadTxn(wallet, prev_tx, chunk_index, chunk_count, chunk_data, config, metadata):
    """
    NOTE: THIS METHOD ONLY WORKS WITH 1 TRANSACTION CURRENTLY, LIMITS SIZE TO 223 BYTES
    """

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

    final_op_return_no_chunk = make_bitcoinfile_final_opreturn(1, chunk_count, None, metadata['filename'], metadata['fileext'], metadata['filesize'], metadata['filehash'])

    if chunk_data == None:
        chunk_length = 0
    else:
        chunk_length = len(chunk_data)

    if chunk_index == chunk_count - 1 and chunk_can_fit_in_final_opreturn(final_op_return_no_chunk, chunk_length):
        op_return = make_bitcoinfile_final_opreturn(1, chunk_count, chunk_data, metadata['filename'], metadata['fileext'], metadata['filesize'], metadata['filehash'])
        miner_fee = estimate_miner_fee(1, 1, len(op_return[1].to_script()))
        dust_output = (amount - miner_fee) if (amount - miner_fee) >= 546 else 546
        askedoutputs = [ op_return, (TYPE_ADDRESS, address, dust_output) ]
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
    print(tx)
    return tx

def chunk_can_fit_in_final_opreturn(final_op_return_no_chunk, chunk_data_length:int = 0):
    if chunk_data_length == 0:
        return True
    op_return_length = len(final_op_return_no_chunk[1].to_script())
    op_return_capacity = 223 - 2 - op_return_length
    if op_return_capacity > chunk_data_length:
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

    # only spend coins from this address
    domain = None
    # config['confirmed_only'] is used in the following call:
    coins = wallet.get_spendable_coins(domain, config)
    fee = None
    change_addr = None
    tx = wallet.make_unsigned_transaction(coins, askedoutputs, config, fee, change_addr)

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
    final_op_return_no_chunk = make_bitcoinfile_final_opreturn(1, chunk_count, None, metadata['filename'], metadata['fileext'], metadata['filesize'], metadata['filehash'])
    byte_count += len(final_op_return_no_chunk[1].to_script())

    # cost of final transaction's input/outputs
    byte_count += 35
    byte_count += 148 + 1

    # cost of chunk trasnsaction op_returns
    byte_count += (whole_chunks_count + 1) * 3

    if not chunk_can_fit_in_final_opreturn(final_op_return_no_chunk, last_chunk_size):
        # add fees for an extra chunk transaction input/output
        byte_count += 149 + 35
        # cost of chunk op_return 
        byte_count += 3

    # output p2pkh
    byte_count += 35 * whole_chunks_count

    # dust input bytes (this is the initial payment for the file upload)
    byte_count += (148 + 1) * whole_chunks_count

    # other unaccounted per txn
    byte_count += 22 * (whole_chunks_count + (1 if last_chunk_size > 0 else 0))

    # dust output to be passed along each txn
    dust_amount = 546

    return byte_count * fee_rate + dust_amount

def downloadBitcoinFile():
    pass

