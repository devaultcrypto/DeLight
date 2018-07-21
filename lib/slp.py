from .transaction import Transaction
from enum import Enum

# This class has sole responsibility for creating NEW SLP token transactions
class SlpTokenTransactionFactory():
    def __init__(token_version: SlpTokenVersion = SlpTokenVersion.TYPE_1,
                    token_id_hex: str = None):
        self.token_version = token_version
        self.token_id_hex = token_id_hex
        self.lokad_id: str = '00534c50'

    def buildInitTransaction(self, inputs, output_mint_reciever, output_baton_reciever, ticker: str, token_name: str, token_document_ascii_url: str,  token_document_hash_hex: str, initial_token_mint_quantity: int, max_final_token_supply: int = None) -> Transaction:
        tx = Transaction()
        tx.add_inputs(inputs)
        vouts = []
        vouts.append(self.buildInitOpReturnOutput(ticker, token_name, token_document_ascii_url, token_document_hash_hex, initial_token_mint_quantity, max_final_token_supply))
        vouts.append(output_mint_reciever)
        if output_baton_reciever is not None:
            vouts.append(output_baton_reciever)
        return tx

    def buildTransferTransaction(self, inputs, outputs, comment: str, output_token_quantity_array: []int) -> Transaction:
        if self.token_id == None:
            raise SlpTokenIdMissing
        tx = Transaction()
        tx.add_inputs(inputs)
        vouts = []
        vouts.append(self.buildTransferOpReturnOutput(comment, output_token_quantity_array))
        vouts.extend(outputs)
        return tx

    # def buildMintTransaction(self, mint_quantity: int) -> SlpTransaction:
    #     if self.token_id == None:
    #         raise SlpTokenIdMissing
    #     raise Exception("Not Implemented.")

    # def buildIssuerCommitmentTransaction(self, for_bitcoin_block_height: int, for_bitcoin_block_hash: bytearray, 
    #                                             token_txn_set_commitment: bytearray, txn_set_data_url: str) -> Transaction:
    #     if self.token_id == None:
    #         raise SlpTokenIdMissing
    #     raise Exception("Not Implemented.")

    def buildInitOpReturnOutput(self, ticker: str, token_name: str, 
                                token_document_ascii_url: str, token_document_hash_hex: str, 
                                initial_token_mint_quantity: int, max_final_token_supply: int = None) -> Transaction:
        script = "OP_RETURN " + \
                    self.lokad_id + " " + \
                    self.token_version + \
                    " INIT " + \
                    ticker.encode('utf-8') + " " + \
                    token_name.encode('utf-8') + " " + \
                    token_document_ascii_url.encode('ascii') + " " + \
                    token_document_hash_hex + " " + \
                    int_to_be_hex(initial_token_mint_quantity)

        # TODO: handle max_final_token_supply -- future baton case
        scriptBuffer = ScriptOutput.from_string(script)
        if len(scriptBuffer.script) > 223:
            raise OPReturnTooLarge(_("OP_RETURN message too large, needs to be under 220 bytes"))
        return (TYPE_SCRIPT, scriptBuffer, 0)

    def buildTransferOpReturnOutput(self, comment, output_qty_array):
        script = "OP_RETURN " + \
                    self.lokad_id + " " + \
                    self.token_version.hex() + \
                    " TRAN " + \
                    self.token_id_hex

        if len(output_qty_array) > 20: 
            raise Exception("Cannot have more than 20 SLP Token outputs.")
        for qty in output_qty_array:
            script = script + " " + self.token_id + " " + qty
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

class SlpMessage():
    def __init__(self):
        self.isChecked = False
        self.isSlpToken = False
        self.isSupportedTokenVersion = False

        self.lokad_id: str = '00534c50'

        self.token_version: SlpTokenVersion = None
        self.transaction_type: SlpTransactionType = None
        self.output_fields = {}

    # This method attempts to parse a ScriptOutput object as an SLP message.
    # If it fails it will throw SlpInvalidOutputMessage or SlpUnsupportedSlpTokenType or SlpImproperlyFormattedTransaction
    @staticmethod
    def parseSlpOutputScript(outputScript: ScriptOutput) -> SlpMessage:
        slpMsg = SlpMessage()

        # convert raw script to ASM Human-readable format w/o pushdata commands
        asm = outputScript.to_asm()

        # Split asm format with spaces
        split_asm = asm.split(' ')

        # check script is OP_RETURN
        if split_asm[0] is not 'OP_RETURN':
            raise SlpInvalidOutputMessage()

        # check that the locad ID is correct
        if split_asm[1] is not self.lokad_id:
            raise SlpInvalidOutputMessage()

        # check if the token version is supported
        slpMsg.token_version = SlpTokenVersion.parsefromHex(split_asm[2])

        # check if the slp transaction type is valid
        slpMsg.transaction_type = SlpTransactionType.parseFromHex(split_asm[3])

        slpMsg.isSlpToken = True

        if slpMsg.token_version is SlpTokenVersion.TYPE_1:
            slpMsg.isSupportedTokenVersion = True
        else:
            raise SlpUnsupportedSlpTokenType()

        # switch statement to handle different on transaction type
        if slpMsg.transaction_type is SlpTransactionType.INIT:

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

            # handle ascii ticker
            try:
                slpMsg.output_fields['ticker'] = split_asm[4].decode('utf-8')
            except UnicodeDecodeError:
                raise SlpImproperlyFormattedTransaction()

            # handle token name
            try:
                slpMsg.output_fields['token_name'] = split_asm[5].decode('utf-8')
            except UnicodeDecodeError:
                raise SlpImproperlyFormattedTransaction()

            # handle token docuemnt url
            try:
                slpMsg.output_fields['token_doc_url'] = split_asm[6].decode('utf-8')
            except UnicodeDecodeError:
                raise SlpImproperlyFormattedTransaction() 

            # handle token docuemnt hash
            try:
                slpMsg.output_fields['token_doc_hash'] = binascii.bh2b(split_asm[7])
            except:
                raise SlpImproperlyFormattedTransaction() 

            # handle initial token quantity issuance
            try:
                slpMsg.output_fields['initial_token_mint_quantity'] = int(split_asm[8], 16)
            except UnicodeDecodeError:
                raise SlpImproperlyFormattedTransaction() 

        elif slpMsg.transaction_type is SlpTransactionType.TRAN:

            # "OP_RETURN " + \
            # self.lokad_id + " " + \
            # self.token_version + \
            # " TRAN " + \
            # self.token_id
            # <QUANTITIES HERE>

            try:
                slpMsg.output_fields['token_id_hex'] = split_asm[4]
            except:
                raise SlpImproperlyFormattedTransaction() 

            outputs = len(split_asm) - 5

            for (field, i) in split_asm:
                if i > 4:
                    try:
                        slpMsg.output_fields['token_output_' + str(i-4)] = int(field, 16)
                    except: 
                        raise SlpImproperlyFormattedTransaction()

    @staticmethod
    def isSlpTransferOutputMessage(output):
        pass

    @staticmethod
    def hex_to_int():
        pass

    @staticmethod
    def int_to_hex():
        pass

class SlpTokenVersion(Enum):
    TYPE_1 = 1

    @staticmethod
    def parseFromHex(versionHex: str) -> int:
        if len(versionHex) > 4:
            raise SlpInvalidOutputMessage()
        decoded = int(versionHex, 16)
        if decoded is SlpTokenVersion.TYPE_1:
            return decoded
        else: 
            raise SlpInvalidOutputMessage()

class SlpTransactionType(Enum):
    INIT = "INIT"
    #MINT = "MINT"
    TRAN = "TRAN"
    #COMM = "COMM"

    @staticmethod
    def parseFromHex(typeHex: str) -> str:
        decoded = typeHex.decode('ascii')
        if decoded is SlpTransactionType.INIT:
            return decoded
        elif decoded is SlpTransactionType.TRAN:
            return decoded
        else:
            raise SlpInvalidOutputMessage()

class SlpInvalidOutputMessage(Exception):
    pass

class SlpUnsupportedSlpTokenType(Exception):
    pass

class SlpTokenIdMissing(Exception):
    pass