"""
NOTE: Despite the following description this method currently only works for single chunk files, no metadata

Creates a transaction that holds a BFP file data chunk at vout0.  Multi-chunk uploads are handled using 
    vout1 as a point to the location of the next chunk.

Multi-part file chunks are committed to the blockchain as transactions using the following sequence:
1. File is partitioned into 2XX byte chunks
2. The file is identified on the blockchain using the txid to the last committed data chunk (longest point in txn chain)
3. The chunks are resolved by traversing a chain of transactions backwards until the first data chunk is found
    - txn input vin0 is always used to point to a previous chunk
4. Chunk index 0 is reserved for storing optional file metadata (i.e., chunk_index = 0, chunk_count = X, name = "", fileext = "", hash = bytes, byte_count = X)

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

def make_bitcoinfile_opreturn(version: int, chunk_index: int, chunk_count: int, data: bytes):
    pushes = []
    script = bytearray((0x6a,))  # OP_RETURN

    # lokad id
    pushes.append(lokad_id)

    # version/type
    pushes.append(bytes((version,)))

    # file chunk number
    pushes.append(bytes((chunk_index,)))

    # file chunk count
    pushes.append(bytes((chunk_count,)))

    # file data 
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

def getUploadTxn(wallet, prev_tx, chunk_index, chunk_count, chunk_data, config):
    """
    NOTE: THIS METHOD ONLY DOES 1 TRANSACTION CURRENTLY, LIMITS SIZE TO 223 BYTES
    """

    assert wallet.txin_type == 'p2pkh'

    vout, address, amount = prev_tx.outputs()[0]

    askedoutputs = [ make_bitcoinfile_opreturn(0, chunk_index, chunk_count, chunk_data),
                    (TYPE_ADDRESS, address, 546) ]

    coins = [{
        'address': address,
        'value': amount,
        'prevout_n': int(vout),
        'prevout_hash': prev_tx.txid(),
        'height': 0,
        'coinbase': False
    }]

    fee = None
    change_addr = None

    tx = wallet.make_unsigned_transaction_for_bitcoinfiles(coins, askedoutputs, config, fee, change_addr)

    # unfortunately, the outputs might be in wrong order due to BIPLI01
    # output sorting, so we remake it.
    outputs = tx.outputs()
    outputs = askedoutputs + [o for o in outputs if o not in askedoutputs]
    tx = Transaction.from_io(tx.inputs(), outputs, tx.locktime)

    return tx

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

def calculateUploadCost(file_size, metadata_fields = {}, fee_rate = 1):
    # op_return length
    byte_count = file_size
    byte_count += 18

    # output p2pkh
    byte_count += 34

    # dust input bytes (this is the initial payment for the file upload)
    byte_count += 148 + 1

    # dust outputs
    dust_amount = 546

    # other unaccounted per txn
    byte_count += 15

    return byte_count * fee_rate + dust_amount

def downloadBitcoinFile():
    pass