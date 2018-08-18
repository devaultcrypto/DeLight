import unittest
from pprint import pprint
from queue import Queue, Empty


from lib.address import ScriptOutput

from lib.transaction import Transaction

import json

from lib import slp
from lib import slp_validator_0x01

import requests
import os

scripttests_local = os.path.abspath('../slp-unit-test-data/script_tests.json')
scripttests_url = 'https://simpleledger.cash/slp-unit-test-data/script_tests.json'

txintests_local = os.path.abspath('../slp-unit-test-data/tx_input_tests.json')
txintests_url = 'https://simpleledger.cash/slp-unit-test-data/tx_input_tests.json'

errorcodes = {
    # no-error maps to None

    # various script format errors
    ('Bad OP_RETURN', 'Script error'): 1,
    # disallowed opcodes
    ('Bad OP_RETURN', 'Non-push opcode'): 2,
    ('Bad OP_RETURN', 'OP_1NEGATE to OP_16 not allowed'): 2,
    ('Bad OP_RETURN', 'OP_0 not allowed'): 2,

    # not OP_RETURN script / not SLP
    # (note in some implementations, parsers should never be given such non-SLP scripts in the first place. In such implementations, error code 3 tests may be skipped.)
    ('Bad OP_RETURN', 'No OP_RETURN'): 3,
    ('Empty OP_RETURN', ): 3,
    ('Not SLP',): 3,

    # 10- field bytesize is wrong
    ('Field has wrong length', ): 10,
    ('Ticker too long', ): 10,
    ('Token document hash is incorrect length',): 10,
    ('token_id is wrong length',): 10,

    # 11- improper value
    ('Too many decimals',): 11,
    ('Bad transaction type',): 11,
    ('Mint baton cannot be on vout=0 or 1',): 11,

    # 12- missing field / too few fields
    ('Missing output amounts', ): 12,
    ('Missing token_type', ): 12,
    ('Missing SLP command', ): 12,
    ('GENESIS with incorrect number of parameters', ): 12,
    ('SEND with too few parameters', ): 12,
    ('MINT with incorrect number of parameters', ): 12,

    # specific
    ('More than 19 output amounts',): 21,

    #SlpUnsupportedSlpTokenType : 255 below
    }

class SLPConsensusTests(unittest.TestCase):
    def test_opreturns(self):
        try:
            with open(scripttests_local) as f:
                testlist = json.load(f)
            print("Got script tests from %s; will not download."%(scripttests_local,))
        except IOError:
            print("Couldn't get script tests from %s; downloading from %s..."%(scripttests_local,scripttests_url))
            testlist = requests.get(scripttests_url).json()

        print("Starting %d tests on SLP's OP_RETURN parser"%len(testlist))
        for d in testlist:
            description = d['msg']
            scripthex = d['script']
            code = d['code']
            if scripthex is None:
                continue
            if hasattr(code, '__iter__'):
                expected_codes = tuple(code)
            else:
                expected_codes = (code, )

            with self.subTest(description=description, script=scripthex):
                sco = ScriptOutput(bytes.fromhex(scripthex))
                try:
                    msg = slp.SlpMessage.parseSlpOutputScript(sco)
                except Exception as e:
                    if isinstance(e, slp.SlpInvalidOutputMessage):
                        emsg = e.args
                        if errorcodes[emsg] not in expected_codes:
                            raise AssertionError("Invalidity reason %r (code: %d) not in expected reasons %r"%(emsg, errorcodes[emsg], expected_codes))
                    elif isinstance(e, slp.SlpUnsupportedSlpTokenType):
                        if 255 not in expected_codes:
                            raise AssertionError("SlpUnsupportedSlpTokenType exception raised (code 255) but not in expected reasons (%r)"%(expected_codes,))
                    else:
                        raise
                else:
                    # no exception
                    if None not in expected_codes:
                        raise AssertionError("Script was found valid but should have been invalid, for a reason code in %r."%(expected_codes,))

        pass


    def test_inputs(self):
        try:
            with open(txintests_local) as f:
                testlist = json.load(f)
            print("Got script tests from %s; will not download."%(txintests_local,))
        except IOError:
            print("Couldn't get script tests from %s; downloading from %s..."%(txintests_local,txintests_url))
            testlist = requests.get(txintests_url).json()

        print("Starting %d tests on SLP's input validation"%len(testlist))
        for test in testlist:
            description = test['description']

            given_validity  = {}
            #should_validity = {}
            txes = {}
            for d in test['when']:
                tx = Transaction(d['tx'])
                txid = tx.txid()
                txes[txid] = tx
                if d['valid'] is True:
                    given_validity[txid] = 1
                elif d['valid'] is False:
                    given_validity[txid] = 2
                else:
                    raise ValueError(d['valid'])

            for d in test['should']:
                tx = Transaction(d['tx'])
                txid = tx.txid()
                txes[txid] = tx
                d['txid'] = txid
                #if d['valid'] is True:
                    #should_validity[txid] = 1
                #elif d['valid'] is False:
                    #should_validity[txid] = 2
                #else:
                    #raise ValueError(d['valid'])

            for i, d in enumerate(test['should']):
                txid = d['txid']
                with self.subTest(description=description, i=i):
                    try:
                        graph, jobmgr = slp_validator_0x01.setup_job(txes[txid], reset=True)
                    except slp.SlpInvalidOutputMessage: # If output 0 is not OP_RETURN
                        self.assertEqual(d['valid'], False)
                        continue
                    job = slp_validator_0x01.ValidationJob(graph, [txid], None,
                                        txcachegetter=txes.__getitem__,
                                        validitycachegetter=given_validity.__getitem__,
                                        )
                    #if txid == '8a08b78ae434de0b1a26e56ae7e78bb11b20f8240eb3d97371fd46a609df7fc3':
                        #graph.debugging = True
                    q = Queue()
                    job.add_callback(q.put)
                    jobmgr.add_job(job)
                    try:
                        q.get(timeout=3) # unlimited timeout
                    except Empty:
                        raise RuntimeError("Timeout during validation unit test")

                    n = next(iter(job.nodes.values()))
                    if d['valid'] is True:
                        self.assertEqual(n.validity, 1)
                    elif d['valid'] is False:
                        self.assertIn(n.validity, (2,3))
                    else:
                        raise ValueError(d['valid'])

