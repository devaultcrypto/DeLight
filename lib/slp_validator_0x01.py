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

def get_validator(tx):
    # extract constants (token_id, version_id).
    # obtain genesis (download if necessary.)
    # check version_id against genesis.

    # throw exception if bad / mismatched genesis?
    raise RuntimeError('todo')

class Validator_SLP_0x01:
    prevalidation = True # indicate we want to check validation when some inputs still active.

    def __init__(self, constants):
        self.constants = constants

    def get_info(self,tx):
        """
        Enforce internal consensus rules.

        Prune if mismatched constants (token_id, version_id) from this validator.
        """
        txouts = tx.outputs()
        if len(txouts) < 1 or txouts[0][0] != TYPE_SCRIPT:
            return ('prune', 0) # not SLP: no OP_RETURN in first output.

        # check lokad ID (all four forms of push)
        scriptbytes = = txouts[0][1].script
        if not (   scriptbytes.startswith(b'\x6a\x04\x00SLP')
                or scriptbytes.startswith(b'\x6a\x4c\x04\x00SLP')
                or scriptbytes.startswith(b'\x6a\x4d\x04\x00\x00SLP')
                or scriptbytes.startswith(b'\x6a\x4e\x04\x00\x00\x00\x00SLP')
                ):
            return ('prune', 0) # not SLP : lokad ID missing / mismatch

        # Consensus rule 2: OP_RETURN output must be 0.
        if txouts[0][2] != 0:
            return ('prune', 2)

        # Consensus rule 2: other outputs with OP_RETURN not allowed.
        other_scripts = [o[1] for o in txouts[1:] if o[0] == TYPE_SCRIPT]
        for sc in other_scripts:
            if sc.script.startswith(b'\x6a'):
                return ('prune', 2)

        try:
            slpMsg = slp.SlpMessage.parseSlpOutputScript(txouts[0][1])
        except Exception:
            return ('prune', 2) # internally invalid

        if slpMsg.transaction_type == 'TRAN':
            token_id = slpMsg.op_return_fields['token_id_hex']

            # Note: according to consensus rules, we compute sum before snipping extra outs.
            myinfo = sum(slpMsg.op_return_fields['token_output'])

            # for zero-token outputs, insert None (pruned)
            outputs = (None,) + tuple((amt if amt > 0 else None)
                                      for amt in slpMsg.op_return_fields['token_output'])
            vin_mask = (True,)*len(tx.inputs()) # need to examine all vins
        elif slpMsg.transaction_type == 'INIT':
            token_id = tx.txid()
            myinfo = 'INIT'
            # second output gets 'MINT' as baton signifier
            outputs = (None, slpMsg.op_return_fields['initial_token_mint_quantity'], 'MINT')
            vin_mask = (False,)*len(tx.inputs()) # don't need to examine any inputs.
        elif slpMsg.transaction_type == 'MINT':
            token_id = slpMsg.op_return_fields['token_id_hex']
            myinfo = 'MINT'
            outputs = (None, slpMsg.op_return_fields['additional_token_quantity'], 'MINT')
            vin_mask = (True,)*len(tx.inputs()) # need to examine all vins, even for baton.
        else:
            raise RuntimeError(slpMsg.transaction_type)

        constants = (token_id, slpMsg.token_type)
        if constants != self.constants:
            return ('prune', 0)  # mismatched token_id or version

        # resize outputs list to match tx outputs length
        outputs = outputs[:len(txouts)]
        outputs = outputs + (None,)*(len(txouts) - len(outputs))

        return vin_mask, myinfo, outputs


    def check_needed(self, myinfo, input_info):
        vin, validity, out_n = input_info
        if myinfo == 'MINT':
            # mints are only interested in the baton input
            return (out_n == 'MINT')

        # transfers are only interested in non-zero, non-pruned contribs.
        try:
            return (out_n > 0)
        except TypeError:
            return False


    def validate(self, myinfo, inputs_info):
        if myinfo == 'INIT':
            return (True, 1)   # genesis is always valid.
        elif myinfo == 'MINT':
            # TODO - check baton inputs
            if all(inp[2] == 1 for inp in inputs_info):
                return (True, 1) # baton is valid
            if len(inputs_info) == 0:
                return (False, 2) # no baton
            return None
        else:
            # TRAN ; myinfo is sum(outs)

            # Check whether, if all inputs were valid, there would be enough:
            insum_all = sum(inp[2] for inp in inputs_info)
            if insum_all < myinfo:
                return (False, 2)

            # Check whether the known valid inputs provide enough:
            insum_valid = sum(inp[2] for inp in inputs_info if inp[1] == 1)
            if insum_valid >= myinfo:
                return (True, 1)
            return None
