import unittest
from pprint import pprint

from lib.address import ScriptOutput

import json
from lib import slp

import requests



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

class SLPParserTest(unittest.TestCase):
    def test_opreturns(self):
        opret_file = requests.get('https://simpleledger.cash/slp-unit-test-data/script_tests.json').json()

        print("Starting %d tests on SLP's OP_RETURN parser"%len(opret_file))
        for d in opret_file:
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

    #def test_even(self):
        #"""
        #Test that numbers between 0 and 5 are all even.
        #"""
        #for i in range(0, 6):
            #with self.subTest(i=i):
                #self.assertEqual(i % 2, 0)

