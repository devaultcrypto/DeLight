# Electron Cash - lightweight Bitcoin Cash client
# Copyright (C) 2011 thomasv@gitorious
# Copyright (C) 2017 Neil Booth
#
# Permission is hereby granted, free of charge, to any person
# obtaining a copy of this software and associated documentation files
# (the "Software"), to deal in the Software without restriction,
# including without limitation the rights to use, copy, modify, merge,
# publish, distribute, sublicense, and/or sell copies of the Software,
# and to permit persons to whom the Software is furnished to do so,
# subject to the following conditions:
#
# The above copyright notice and this permission notice shall be
# included in all copies or substantial portions of the Software.
#
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND,
# EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF
# MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE AND
# NONINFRINGEMENT. IN NO EVENT SHALL THE AUTHORS OR COPYRIGHT HOLDERS
# BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY, WHETHER IN AN
# ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM, OUT OF OR IN
# CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
# SOFTWARE.

import json, pkgutil

def _read_json_dict(filename):
    try:
        data = pkgutil.get_data(__name__, filename)
        r = json.loads(data.decode('utf-8'))
    except:
        r = {}
    return r

class AbstractNet:
    TESTNET = False
    POW_TARGET_SPACING = 120


class MainNet(AbstractNet):
    TESTNET = False
    WIF_PREFIX = 0x80
    ADDRTYPE_P2PKH = 0
    ADDRTYPE_P2PKH_BITPAY = 28
    ADDRTYPE_P2SH = 5
    ADDRTYPE_P2SH_BITPAY = 40
    CASHADDR_PREFIX = "devault"
    HEADERS_URL = "http://devault.com/files/blockchain_headers"
    GENESIS = "0000000038e62464371566f6a8d35c01aa54a7da351b2dbf85d92f30357f3a90"
    DEFAULT_PORTS = {'t': '50001', 's': '50002'}
    DEFAULT_SERVERS = _read_json_dict('servers.json')  # DO NOT MODIFY IN CLIENT CODE
    TITLE = 'DeVault Cash'

    # Note to Jonald or anyone reading this: the below is misleadingly named.  It's not a simple
    # MERKLE_ROOT but a MERKLE_PROOF which is basically the hashes of all MERKLE_ROOTS up until and including
    # this block. Consult the ElectrumX documentation.
    # To get this value you need to connect to an ElectrumX server you trust and issue it a protocol command.
    # blockchain.block.header (see ElectrumX docs)
    VERIFICATION_BLOCK_MERKLE_ROOT = "47caa1d479807d32131ce1df843cf66c8a06603404377b3713a8bf1669e4ab09"
    VERIFICATION_BLOCK_HEIGHT = 20000

    # Version numbers for BIP32 extended keys
    # standard: xprv, xpub
    XPRV_HEADERS = {
        'standard': 0x0488ade4,
    }

    XPUB_HEADERS = {
        'standard': 0x0488b21e,
    }


class TestNet(AbstractNet):
    TESTNET = True
    WIF_PREFIX = 0xef
    ADDRTYPE_P2PKH = 111
    ADDRTYPE_P2PKH_BITPAY = 111  # Unsure
    ADDRTYPE_P2SH = 196
    ADDRTYPE_P2SH_BITPAY = 196  # Unsure
    CASHADDR_PREFIX = "dvtest"
    HEADERS_URL = "http://devault.com/files/testnet_headers"
    GENESIS = "00000000ed6c30b2e78a0eff7d20692c14099ce8eb04e205fcc08c474cfd6675"
    DEFAULT_PORTS = {'t':'51001', 's':'51002'}
    DEFAULT_SERVERS = _read_json_dict('servers_testnet.json')  # DO NOT MODIFY IN CLIENT CODE
    TITLE = 'DeVault Cash Testnet'

    VERIFICATION_BLOCK_MERKLE_ROOT = "c3cc7a7b6fe5e0ff19b750ae200ae93664b3abf09bf510e26e15ba338afe1f1a"
    VERIFICATION_BLOCK_HEIGHT = 1273800

    # Version numbers for BIP32 extended keys
    # standard: tprv, tpub
    XPRV_HEADERS = {
        'standard': 0x04358394,
    }

    XPUB_HEADERS = {
        'standard': 0x043587cf,
    }


# All new code should access this to get the current network config.
net = MainNet

def set_mainnet():
    global net
    net = MainNet

def set_testnet():
    global net
    net = TestNet


# Compatibility
def _instancer(cls):
    return cls()

@_instancer
class NetworkConstants:
    ''' Compatibility class for old code such as extant plugins.

    Client code can just do things like:
    NetworkConstants.ADDRTYPE_P2PKH, NetworkConstants.DEFAULT_PORTS, etc.

    We have transitioned away from this class. All new code should use the
    'net' global variable above instead. '''
    def __getattribute__(self, name):
        return getattr(net, name)

    def __setattr__(self, name, value):
        raise RuntimeError('NetworkConstants does not support setting attributes! ({}={})'.format(name,value))
        #setattr(net, name, value)
