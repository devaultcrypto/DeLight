"""
Validate SLP token transactions with declared version 0x01.

-Caching support (todo)
-Proxy support (todo)

This uses the graph searching mechanism from slp_dagging.py
"""

from .transaction import Transaction
from . import slp
from . import network
from . import slp_dagging
from .bitcoin import TYPE_SCRIPT
import threading


# Global db for shared graphs (each token_id has its own graph).
graph_db_lock = threading.Lock()
graph_db = dict()   # token_id -> TokenGraph
def get_graph(token_id):
    with graph_db_lock:
        try:
            return graph_db[token_id]
        except KeyError:
            print("SLP:starting graph for token_id=%r"%( token_id,))
            val = Validator_SLP_0x01(token_id)
            graph = slp_dagging.TokenGraph(val)
            graph_db[token_id] = graph
            return graph


def make_job(tx, wallet, network, **kwargs):
    """
    Basic validation job maker for a single transaction.
    """
    slpMsg = slp.SlpMessage.parseSlpOutputScript(tx.outputs()[0][1])
    token_id = slpMsg.op_return_fields['token_id_hex']

    graph = get_graph(token_id)
    job = slp_dagging.ValidationJob(graph, [tx.txid()], network,
                                    txcachegetter=wallet.transactions.__getitem__,
                                    **kwargs)
    return job


class Validator_SLP_0x01:
    prevalidation = True # indicate we want to check validation when some inputs still active.

    def __init__(self, token_id):
        self.token_id = token_id

    def get_info(self,tx):
        """
        Enforce internal consensus rules (check all rules that don't involve
        information from inputs).

        Prune if mismatched token_id from this validator or SLP version other than 1.
        """
        txouts = tx.outputs()
        if len(txouts) < 1 or txouts[0][0] != TYPE_SCRIPT:
            return ('prune', 0) # not SLP: regular address in first output.

        # check op_return with lokad ID (all four forms of push)
        scriptbytes = txouts[0][1].script
        if not (   scriptbytes.startswith(b'\x6a\x04\x00SLP')
                or scriptbytes.startswith(b'\x6a\x4c\x04\x00SLP')
                or scriptbytes.startswith(b'\x6a\x4d\x04\x00\x00SLP')
                or scriptbytes.startswith(b'\x6a\x4e\x04\x00\x00\x00\x00SLP')
                ):
            return ('prune', 0) # not SLP : not op_return, or lokad ID missing / mismatch

        # Parse the SLP
        try:
            slpMsg = slp.SlpMessage.parseSlpOutputScript(txouts[0][1])
        except Exception:
            return ('prune', 2) # internally invalid

        if slpMsg.token_type != 1:
            return ('prune', 0) # not SLP 0x01


        # Consensus rule 2: OP_RETURN output must be 0.
        if txouts[0][2] != 0:
            return ('prune', 2)

        # Consensus rule 2: other outputs with OP_RETURN not allowed.
        other_scripts = [o[1] for o in txouts[1:] if o[0] == TYPE_SCRIPT]
        for sc in other_scripts:
            if sc.script.startswith(b'\x6a'):
                return ('prune', 2)

        if slpMsg.transaction_type == 'TRAN':
            token_id = slpMsg.op_return_fields['token_id_hex']

            # need to examine all inputs
            vin_mask = (True,)*len(tx.inputs())

            # myinfo is the output sum
            # Note: according to consensus rules, we compute sum before truncating extra outputs.
#            print("DEBUG SLP:getinfo %.10s outputs: %r"%(tx.txid(), slpMsg.op_return_fields['token_output']))
            myinfo = sum(slpMsg.op_return_fields['token_output'])

            # outputs straight from the token fields.
            outputs = tuple(slpMsg.op_return_fields['token_output'])
        elif slpMsg.transaction_type == 'INIT':
            token_id = tx.txid()

            vin_mask = (False,)*len(tx.inputs()) # don't need to examine any inputs.

            myinfo = 'INIT'

            # second output gets 'MINT' as baton signifier
            outputs = (None, slpMsg.op_return_fields['initial_token_mint_quantity'], 'MINT')
        elif slpMsg.transaction_type == 'MINT':
            token_id = slpMsg.op_return_fields['token_id_hex']

            vin_mask = (True,)*len(tx.inputs()) # need to examine all vins, even for baton.

            myinfo = 'MINT'

            outputs = (None, slpMsg.op_return_fields['additional_token_quantity'], 'MINT')
        else:
            raise RuntimeError(slpMsg.transaction_type)

        if token_id != self.token_id:
            return ('prune', 0)  # mismatched token_id

        # truncate / expand outputs list to match tx outputs length
        outputs = outputs[:len(txouts)]
        outputs = outputs + (None,)*(len(txouts) - len(outputs))

        return vin_mask, myinfo, outputs


    def check_needed(self, myinfo, out_n):
        if myinfo == 'MINT':
            # mints are only interested in the baton input
            return (out_n == 'MINT')
        if myinfo == 'INIT':
            # genesis shouldn't have any parents, so this should not happen.
            raise RuntimeError('Unexpected', out_n)

        # TRAN txes are only interested in integer, non-zero input contributions.
        if out_n is None or out_n == 'MINT':
            return False
        else:
            return (out_n > 0)


    def validate(self, myinfo, inputs_info):
        print("DEBUG SLP:validate called: %r   %r"%(myinfo, inputs_info))
        if myinfo == 'INIT':
            if len(inputs_info) != 0:
                raise RuntimeError('Unexpected', inputs_info)
            return (True, 1)   # genesis is always valid.
        elif myinfo == 'MINT':
            if not all(inp[3] == 'MINT'): # non-MINT inputs should be pruned.
                raise RuntimeError('Unexpected', inputs_info)
            if len(inputs_info) == 0:
                return (False, 2) # no baton? invalid.
            if all(inp[2] == 1 for inp in inputs_info):
                # multiple 'valid' baton inputs are possible with double spending.
                # technically 'valid' though miners will never confirm.
                return (True, 1)
            return None
        else:
            # TRAN ; myinfo is sum(outs)

            # Check whether, there could be enough to satisfy outputs.
            insum_all = sum(inp[2] for inp in inputs_info)
            if insum_all < myinfo:
                print("DEBUG SLP: invalid! outsum=%d,  possible inputs=%d"%(myinfo, insum_all))
                return (False, 2)

            # Check whether the known valid inputs provide enough tokens to satisfy outputs:
            insum_valid = sum(inp[2] for inp in inputs_info if inp[1] == 1)
            if insum_valid >= myinfo:
                print("DEBUG SLP: valid! outsum=%d,  known valid inputs=%d"%(myinfo, insum_valid))
                return (True, 1)
            return None
