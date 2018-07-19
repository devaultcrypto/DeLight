from .transaction import Transaction

# This class has sole responsibility for creating SLP token transactions
class SlpTokenTransactionFactory():
    def __init__(protocol_version = '01', token_type = '01', token_id = None):
        self.protocol_version = protocol_version
        self.token_type = token_type
        self.token_id = token_id
        self.lokad_id = '00534c50'

    def buildInitTransaction(self, inputs, ascii_ticker, token_name, 
                            token_document_ascii_url, token_document_hash, 
                            initial_token_mint_quantity, max_final_token_supply = None):
        tx = Transaction()
        tx.add_inputs(inputs)

        # create outputs, op_return message + 
        outputs = []
        outputs.append(self.buildInitOpReturnOutput(ascii_ticker, token_name, token_document_ascii_url, token_document_hash, initial_token_mint_quantity, max_final_token_supply))
        outputs.append()  # change to init token holder

        tx.serialize_preimage()
        # set and return token_id from Init txn hash.
        txid = None
        return txid

    def buildMintTransaction(self, mint_quantity):
        if self.token_id == None:
            raise Exception("Cannot build Mint transaction without setting token_id property for Factory.")
        raise Exception("Not Implemented.")

    def buildTransferTransaction(self, comment, output_token_quantity_Array):
        if self.token_id == None:
            raise Exception("Cannot build Mint transaction without setting token_id property for Factory.")
        raise Exception("Not Implemented.")

    def buildIssuerCommitmentTransaction(self, for_bitcoin_block_height, for_bitcoin_block_hash, token_txn_set_commitment, txn_set_data_url):
        if self.token_id == None:
            raise Exception("Cannot build Mint transaction without setting token_id property for Factory.")
        raise Exception("Not Implemented.")

    def buildInitOpReturnOutput(self, ascii_ticker, token_name, token_document_ascii_url, token_document_hash, initial_token_mint_quantity, max_final_token_supply):
        script = "OP_RETURN " + self.lokad_id + " " + self.protocol_version + self.token_type + " INIT"
        script = script + " " + \
                    ascii_ticker + " " + \
                    token_name + " " + \
                    token_document_ascii_url + " " + \
                    token_document_hash + " " + \
                    initial_token_mint_quantity
        scriptBuffer = ScriptOutput.from_string(script)
        if len(scriptBuffer.script) > 223:
            raise OPReturnTooLarge(_("OP_RETURN message too large, needs to be under 220 bytes"))
        return (TYPE_SCRIPT, scriptBuffer, 0)


    def buildMintOpReturnOutput(self, additional_token_quantity):
        script = "OP_RETURN " + self.lokad_id + " " + self.protocol_version + self.token_type + " MINT"
        script = script + " " + self.token_id + " " + additional_token_quantity
        scriptBuffer = ScriptOutput.from_string(script)
        if len(scriptBuffer.script) > 223:
            raise OPReturnTooLarge(_("OP_RETURN message too large, needs to be under 220 bytes"))
        return (TYPE_SCRIPT, scriptBuffer, 0)

    def buildTransferOpReturnOutput(self, comment, output_qty_array):
        script = "OP_RETURN " + self.lokad_id + " " + self.protocol_version + self.token_type + " TRAN"
        script = script + " " + self.token_id
        if len(output_qty_array) > 20: 
            raise Exception("Cannot have more than 20 SLP Token outputs.")
        for qty in output_qty_array:
            script = script + " " + self.token_id + " " + qty
        scriptBuffer = ScriptOutput.from_string(script)
        if len(scriptBuffer.script) > 223:
            raise OPReturnTooLarge(_("OP_RETURN message too large, needs to be under 220 bytes"))
        return (TYPE_SCRIPT, scriptBuffer, 0)

    def buildCommitmentOpReturnOutput(self, for_bitcoin_block_height, for_bitcoin_block_hash, token_txn_set_commitment, txn_set_data_url):
        script = "OP_RETURN " + self.lokad_id + " " + self.protocol_version + self.token_type + " COMM"
        script = script + " " + self.token_id + " " + for_bitcoin_block_height + " " + for_bitcoin_block_height
        script = script + " " + token_txn_set_commitment + " " + txn_set_data_url
        scriptBuffer = ScriptOutput.from_string(script)
        if len(scriptBuffer.script) > 223:
            raise OPReturnTooLarge(_("OP_RETURN message too large, needs to be under 220 bytes"))
        return (TYPE_SCRIPT, scriptBuffer, 0)
