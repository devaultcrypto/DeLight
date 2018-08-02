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
#            print("DEBUG SLP: starting graph for token_id=%r"%( token_id,))
            val = Validator_SLP_0x01(token_id)
            graph = slp_dagging.TokenGraph(val)
#            graph.debugging = True
            graph_db[token_id] = graph
            return graph
def kill_graph(token_id):
    del graph_db[token_id]


def make_job(tx, wallet, network, debug=False, reset=False, **kwargs):
    """
    Basic validation job maker for a single transaction.
    """
    slpMsg = slp.SlpMessage.parseSlpOutputScript(tx.outputs()[0][1])
    if slpMsg.transaction_type == 'INIT':
        token_id = tx.txid()
    else:
        token_id = slpMsg.op_return_fields['token_id_hex']

    if reset:
        try:
            kill_graph(token_id)
        except KeyError:
            pass
    graph = get_graph(token_id)
    graph.debugging = bool(debug)
    job = slp_dagging.ValidationJob(graph, [tx.txid()], network,
                                    txcachegetter=wallet.transactions.__getitem__,
                                    **kwargs)
    return job


class Validator_SLP_0x01:
    prevalidation = True # indicate we want to check validation when some inputs still active.

    validity_states = {
        0: 'Unknown',
        1: 'Valid',
        2: 'Invalid: not SLP / malformed SLP',
        3: 'Invalid: insufficient valid inputs'
        }

    def __init__(self, token_id):
        self.token_id = token_id

    def get_info(self,tx):
        """
        Enforce internal consensus rules (check all rules that don't involve
        information from inputs).

        Prune if mismatched token_id from this validator or SLP version other than 1.
        """
        txouts = tx.outputs()
        if len(txouts) < 1:
            return ('prune', 2) # not SLP: regular address in first output.

        # We take for granted that parseSlpOutputScript here will catch all
        # consensus-invalid op_return messages. In this procedure we check the
        # remaining internal rules, having to do with the overall transaction.
        try:
            slpMsg = slp.SlpMessage.parseSlpOutputScript(txouts[0][1])
        except slp.SlpUnsupportedSlpTokenType as e:
            return ('prune', 0)
        except slp.SlpInvalidOutputMessage as e:
#            print("DEBUG SLP: %.10s... invalid: %r"%(tx.txid(), e))
            return ('prune', 2)

        # Parse the SLP
        if slpMsg.token_type != 1:
            return ('prune', 0) # not SLP 0x01

        # Consensus rule 2: OP_RETURN output amount must be 0.
        if txouts[0][2] != 0:
            return ('prune', 2)

        # Consensus rule 2: other outputs with OP_RETURN not allowed.
        other_scripts = [o[1] for o in txouts[1:] if o[0] == TYPE_SCRIPT]
        for sc in other_scripts:
            if sc.script.startswith(b'\x6a'):
                #print("DEBUG SLP: %.10s... invalid: %r"%(tx.txid(), e))
                return ('prune', 2)

        if slpMsg.transaction_type == 'TRAN':
            token_id = slpMsg.op_return_fields['token_id_hex']

            # need to examine all inputs
            vin_mask = (True,)*len(tx.inputs())

            # myinfo is the output sum
            # Note: according to consensus rules, we compute sum before truncating extra outputs.
#            print("DEBUG SLP:getinfo %.10s outputs: %r"%(tx.txid(), slpMsg.op_return_fields['token_output']))
            myinfo = sum(slpMsg.op_return_fields['token_output'])

            # outputs straight from the token amounts
            outputs = slpMsg.op_return_fields['token_output']
        elif slpMsg.transaction_type == 'INIT':
            token_id = tx.txid()

            vin_mask = (False,)*len(tx.inputs()) # don't need to examine any inputs.

            myinfo = 'INIT'

            # place 'MINT' as baton signifier on the designated output
            mintvout = slpMsg.op_return_fields['mint_baton_vout']
            if mintvout is None:
                outputs = [None,None]
            else:
                outputs = [None]*(mintvout-1) + ['MINT']
            outputs[1] = slpMsg.op_return_fields['initial_token_mint_quantity']
        elif slpMsg.transaction_type == 'MINT':
            token_id = slpMsg.op_return_fields['token_id_hex']

            vin_mask = (True,)*len(tx.inputs()) # need to examine all vins, even for baton.

            myinfo = 'MINT'

            # place 'MINT' as baton signifier on the designated output
            mintvout = slpMsg.op_return_fields['mint_baton_vout']
            if mintvout is None:
                outputs = [None,None]
            else:
                outputs = [None]*(mintvout-1) + ['MINT']
            outputs[1] = slpMsg.op_return_fields['additional_token_quantity']
        else:
            raise RuntimeError(slpMsg.transaction_type)

        if token_id != self.token_id:
            return ('prune', 0)  # mismatched token_id

        # truncate / expand outputs list to match tx outputs length
        outputs = tuple(outputs[:len(txouts)])
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
        if myinfo == 'INIT':
            if len(inputs_info) != 0:
                raise RuntimeError('Unexpected', inputs_info)
            return (True, 1)   # genesis is always valid.
        elif myinfo == 'MINT':
            if not all(inp[3] == 'MINT'): # non-MINT inputs should be pruned.
                raise RuntimeError('Unexpected', inputs_info)
            if len(inputs_info) == 0:
                return (False, 3) # no baton? invalid.
            if all(inp[2] == 1 for inp in inputs_info):
                # multiple 'valid' baton inputs are possible with double spending.
                # technically 'valid' though miners will never confirm.
                return (True, 1)
            return None
        else:
            # TRAN --- myinfo is an integer sum(outs)

            # Check whether there could be enough to satisfy outputs.
            insum_all = sum(inp[2] for inp in inputs_info)
            if insum_all < myinfo:
                #print("DEBUG SLP: invalid! outsum=%d,  possible inputs=%d"%(myinfo, insum_all))
                return (False, 3)

            # Check whether the known valid inputs provide enough tokens to satisfy outputs:
            insum_valid = sum(inp[2] for inp in inputs_info if inp[1] == 1)
            if insum_valid >= myinfo:
                #print("DEBUG SLP: valid! outsum=%d,  known valid inputs=%d"%(myinfo, insum_valid))
                return (True, 1)
            return None
