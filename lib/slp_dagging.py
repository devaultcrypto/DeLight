"""
Breadth-first DAG digger for colored coins.

We do a breadth-first DAG traversal starting with the transaction-of-interest
at the source, and digging into ancestors layer by layer. Along the way we
prune off some connections, invalidate+disconnect branches, etc.,
so our 'search DAG' is a subset of the transaction DAG. To hold this
dynamically changing search DAG, we have a TokenGraph class.

(It's much simpler to run a full node and validate as transactions appear, but
we have no such luxury in a light wallet.)


Threading
=========

Currently not threadsafe but designed with future multithreading in mind, and
the relevant 'with lock:' locations have been commented. Threading would allow
multiple workers doing downloading/computations on graph.

These principles have been followed in case threading ever gets added:
- TokenGraph never locked when it calls Node functions
- parent Nodes never locked when it calls child Node
- We assume no cycles (nor self-references), which should be essentially
  impossible due to the hash-chaining nature of transactions. If there are
  cycles (possible by using faked txids), the validator *will* deadlock,
  regardless of threading!
"""

import collections

INF_DEPTH=2147483646  # 'infinity' value for node depths. 2**31 - 2



class ValidatorGeneric:
    """
    The specific colored coin implementation will need to make a 'validator'
    object according to this template.

    Implementations should:
    - Define `get_info` and `validate` methods.
    - Set `prevalidation` to one of the following:
        False - only call validate() once per tx, when all inputs are concluded.
        True - call validate() repeatedly, starting when all inputs are downloaded.
        (only useful if this can provide early validity conclusions)
    """

    prevalidation = False

    def get_info(self,tx):
        """ This will be called with a Transaction object; use it to extract
        all information necessary during the validation process (after call,
        the Transaction object will be forgotten).

        Allowed return values:

        ('prune', validity) -- prune this tx immediately, remember only validity.
        (vin_mask, myinfo, outputs)
                -- information for active, *potentially* valid tx.

        The list `vin_mask = (True, False, False, True, ...)` tells which tx
        inputs may need to be considered for validation. (For any False, the
        input tx is not downloaded.)

        The list `outputs = (out_1, out_2, ...)` provides info that is needed
        to validate descendant transactions. (e.g., how many tokens).

        See `validate` for how these are used.


        Pruning is done by replacing node references with prunednodes[validity] .
        These will provide None as info for children.
        """
        raise NotImplementedError

    def check_needed(self, myinfo, input_info):
        """
        As each input gets downloaded and its get_info() gets computed, we
        check whether it is still needed by the validator.

        (This is used to disconnect unimportant branches.)

        Here we pass in `myinfo` from the tx, and `out_n` from the input
        tx's get_info(); if it was pruned then `out_n` will be None.
        """
        return True

    def validate(self, myinfo, inputs_info):
        """
        Run validation. Only gets called after filtering through check_needed.

        `myinfo` is direct from get_info().

        `input_info` is a list with same length as `vins` from get_info()

         [(vin_0, validity_0, out_n_0),
          (vin_1, validity_1, out_n_1),
          ...
          ]

        out_n_0 is the info from 0'th input's get_info() function,
        but may be None if pruned/invalid.

        Return:
            None if undecided, or
            (keepinfo, validity) if final judgement.

        keepinfo may be:
            False - prune, just save validity judgement.
            True  - save info and validity.
        validity may be:
            1 - valid
            2 - invalid

        Typically (False, 2) and (True, 1) but you *could* use (True, 2)
        if it's necessary for children to know info from invalid parents.
        """
        raise NotImplementedError



########
# Graph stuff below
########

class TokenGraph:
    """ Used with Node class to hold a dynamic DAG structure, used while
    traversing the transaction DAG. This dynamic DAG holds dependencies
    among *active* transactions (nonzero contributions with unknown validity)
    and so it's a subset of the transactions DAG.

    Why dynamic? As we go deeper we add connections, sometimes adding
    connections between previously-unconnected parts. We can also remove
    connections as needed for pruning.

    A key concept is the maintenance of a 'depth' value for each active node,
    which represents the shortest directed path from root to node. The depth
    is used to prioritize downloading in a breadth-first search.
    Nodes that are inactive or disconnected from root are assigned depth=INF_DEPTH.

    Graph updating occurs in three phases:
    Phase 1: Waiting nodes brought online with load_tx().
    Phase 2: Children get notified of parents' updates via ping(), which may
        further alter graph (as validity conclusions get reached).
    Phase 3: Depths updated via recalc_depth().

    At the end of Phase 3, the graph is stabilized with correct depth values.

    `root` is a special origin node fixed at depth=-1, with no children.
    The actual transaction(s) under consideration get added as parents of
    this root and hence they are depth=0.

    Rather than call-based recursion (cascades of notifications running up and
    down the DAG) we use a task scheduler, provided by `add_ping()`,
    `add_recalc_depth()` and `run_sched()`.
    """
    def __init__(self, validator):
        self.validator = validator

        self._nodes = dict() # txid -> Node

        self.root = NodeRoot()

        self.waiting_nodes = set()

        # requested callbacks
        self._sched_ping = set()
        self._sched_recalc_depth = set()

        # Threading rule: we never call node functions while locked.
        # self._lock = ... # threading not enabled.

    def get_node(self, txid, createonly=False):
        # with self._lock:
        try:
            node = self._nodes[txid]
        except KeyError:
            node = Node(txid, self)
            self._nodes[txid] = node
            self.waiting_nodes.add(node)
        else:
            if createonly:
                raise RuntimeError
        return node

    def replace_node(self, txid, replacement):
        self._nodes[txid] = replacement  # threadsafe

    def add_ping(self, node):
        self._sched_ping.add(node)  # threadsafe
    def add_recalc_depth(self, node, depthpriority):
        # currently ignoring depthpriority
        self._sched_recalc_depth.add(node)  # threadsafe

    def run_sched(self):
        """ run the pings scheduled by add_ping() one at a time, until the
        schedule list is empty (note: things can get added/re-added during run).

        then do the same for stuff added by add_recalc_depth().

        TODO: consider making this depth prioritized to reduce redundant work.
        """
        # should be threadsafe without lock (pop() is atomic)
        while True:
            try:
                node = self._sched_ping.pop()
            except KeyError:
                return
            node.ping()
        while True:
            try:
                node = self._sched_recalc_depth.pop()
            except KeyError:
                return
            node.recalc_depth()

    def start_tx(self, tx):
        """ Add a tx as a parent of the root node; loads node then returns node. """
        txid = tx.txid()
        node = self.get_node(txid, createonly=True)
        node.load_tx(tx)
        self.root.add_parent(node)
        return node


class Connection:
    # Connection represents a tx output <-> tx input connection
    # (we don't used namedtuple since we want 'parent' to be modifiable.)
    __slots__ = ('parent', 'child', 'vout', 'vin', 'checked')
    def __init__(self, parent,child,vout,vin):
        self.parent = parent
        self.child = child
        self.vout = vout
        self.vin = vin
        self.checked = False


class Node:
    """
    Nodes keep essential info about txes involved in the validation DAG.
    They have a list of Connections to parents (inputs) and to children
    (outputs).

    Connections to children are used to notify (via ping()) when:
    - Node data became available (changed from waiting to live)
    - Node conclusion reached (changed from active to inactive)
    - Connection pruned (parent effectively inactive)

    Connections to parents are used to notify them when our depth gets
    updated.

    When our node is active, it can either be in waiting state where the
    transaction data is not yet available (parents is None), or in live state
    (parents is a tuple of Connections).

    The node becomes inactive when a conclusion is reached: either
    pruned, invalid, or valid. When this occurs, the node replaces itself
    with a NodeInactive object (more compact).
    """
    def __init__(self, txid, graph):
        self.txid = txid
        self.graph = graph
        self.children = list()
        self.parents = None  # only None when in waiting state
        self.depth = INF_DEPTH
        self.active = True
        self.validity = 0    # 0 - unknown, 1 - valid, 2 - invalid
        self.myinfo = None   # self-info from get_info().
        self.outputs = None  # per-output info from get_info(). None if waiting/pruned/invalid.
        # self._lock = ... # threading not enabled.

    def __repr__(self,):
        if self.active:
            if self.parents is None:
                status='waiting'
            else:
                status='live'
        else:
            status='inactive'
        return "<%s %s txid=%r>"%(type(self).__name__, status, self.txid)


    ## Child connection adding/removing

    def add_child(self, connection):
        """ Called by children to subscribe notifications.

        (May not actually establish connection, if inactive, or vout is
        pruned. In that case, a ping is automatically scheduled.)
        """
        # with self._lock:
        if not self.active:
            connection.parent = self.replacement
            self.graph.add_ping(connection.child)
            return

        self.children.append(connection)
        newdepth = min(1 + connection.child.depth,
                       INF_DEPTH)
        olddepth = self.depth
        if newdepth < olddepth:
            # found a shorter path from root
            self.depth = newdepth
            for c in self.parents:
                if c.parent.depth == 1 + olddepth:
                    # parent may have been hanging off our depth value.
                    self.graph.add_recalc_depth(c.parent, newdepth)
        return

    def del_child(self, connection):
        """ called by children to remove connection
        """
        # with self._lock:
        self.children.remove(connection)

        if self.depth <= connection.child.depth+1:
            self.graph.add_sched(self.recalc_depth)


    ## Loading of info

    def load_tx(self, tx, cached_validity = None):
        """ Convert 'waiting' transaction to live one. """
        # with self._lock:
        if self.parents is not None:
            raise RuntimeError("double load!", self)

        if tx.txid() != self.txid:
            raise ValueError("TXID mismatch", tx.txid(), self.txid)

        validator = self.graph.validator
        ret = validator.get_info(tx)

        if len(ret) == 2:
            if ret[0] != 'prune':
                raise ValueError(ret)
            return self._inactivate_self(False, ret[1])

        vin_mask, self.myinfo, self.outputs = ret

        if len(self.outputs) != len(tx.outputs()):
            raise ValueError("length mismatch")

        if cached_validity is not None:
            return self._inactivate_self(True, cached_validity)

        # at this point we have exhausted options for inactivation.
        # build connections to parents
        txinputs = tx.inputs()
        if len(vin_mask) != len(txinputs):
            raise ValueError("length mismatch")

        parents = []
        for vin, (mask, inp) in enumerate(zip(vin_mask, txinputs)):
            if not mask:
                continue
            txid = inp['prevout_hash']
            vout = inp['prevout_n']

            p = self.graph.get_node(txid)
            c = Connection(p,self,vout,vin)
            p.add_child(c)
            parents.append(c)
        self.parents = tuple(parents)

        if len(self.parents) == 0:
            # no parents? ready to validate now! (e.g., genesis tx)
            self.graph.add_ping(self)
        else:
            # normally we just ping all children.
            for c in self.children:
                self.graph.add_ping(c.child)

    def load_pruned(self, cached_validity):
        # with self._lock:
        if self.parents is not None:
            raise RuntimeError("double load!", self)

        return self._inactivate_self(False, cached_validity)


    ## Internal utility stuff

    def _inactivate_self(self, keepinfo, validity):
        # Replace self with NodeInactive instance according to keepinfo and validity
        # no thread locking here, this only gets called internally.

        if keepinfo:
            replacement = NodeInactive(validity, self.outputs)
        else:
            replacement = prunednodes[validity] # use singletons

        # replace self in lookups
        self.graph.replace_node(self.txid, replacement)

        # unsubscribe from parents & forget
        if parents is not None:
            for c in self.parents:
                c.parent.del_child(c)
        self.parents = ()

        # replace self in child connections & forget
        for c in self.children:
            c.parent = replacement
            c.checked = False
            self.graph.add_ping(c.child)
        self.children = ()

        # At this point all permanent refs to us should be gone and we will soon be deleted.
        # Temporary refs may remain, for which we mimic the replacement.
        self.active = False
        self.depth = INF_DEPTH
        self.validity = replacement.validity
        self.outputs = replacement.outputs
        self.replacement = replacement

    def recalc_depth(self):
        # with self._lock:
        if not self.active:
            return
        depths = [c.child.depth for c in self.children]
        depths.append(INF_DEPTH-1)
        newdepth = 1 + min(depths)
        olddepth = self.depth
        if newdepth != olddepth:
            self.depth = newdepth
            depthpriority = 1 + min(olddepth, newdepth)
            for c in self.parents:
                self.graph.add_recalc_depth(c.parent, depthpriority)

    def get_out_info(self, c):
        # Get info for the connection and check if connection is needed.
        # Returns None if validator's check_needed returns False.
        # with self._lock:
        try:
            out = self.outputs[c.vout]
        except TypeError: # outputs is None or vout is None
            out = None

        waiting = (self.parents is None)

        if not c.checked and not waiting:
            if c.child.graph.validator.check_needed(c.child.myinfo, out):
                c.checked = True
            else:
                return None

        return (self.active, waiting, c.vin, self.validity, out)

    def ping(self, ):
        """ handle notification status update on one or more parents """
        # with self._lock:
        validator = self.graph.validator

        # get info, discarding unneeded parents.
        pinfo = []
        for c in tuple(self.parents):
            info = c.parent.get_out_info(c)
            if info is None:
                c.parent.del_child(c)
                self.parents.remove(c)
            else:
                pinfo.append(info)

        anyactive = any(info[0] for info in pinfo)

        if validator.prevalidation:
            if any(info[1] for info in pinfo):
                return
        else:
            if anyactive:
                return

        valinfo = [info[2:] for info in pinfo]
        ret = validator.validate(self.myinfo, valinfo)

        if ret is None: # undecided
            if not anyactive:
                raise RuntimeError("Undecided with finalized parents",
                                   self.txid, parent_info)
            return
        else: # decided
            self._inactivate_self(*ret)


class NodeRoot: # Special root, only one of these is created per TokenGraph.
    depth = -1
    def __init__(self, ):
        parents = []
    def add_parent(self, parent):
        c = Connection(parent, self, None, None)
        parent.add_child(c)
        parents.append(parent)
        return c
    def ping(self,):
        pass


# container used to replace Node with static result
class NodeInactive(collections.namedtuple('anon_namedtuple',
                                          ['validity', 'outputs'])):
    __slots__ = ()  # no dict needed
    active = False
    depth = INF_DEPTH

    def get_out_info(self, c):
        # Get info for the connection and check if connection is needed.
        # Returns None if validator's check_needed returns False.
        try:
            out = self.outputs[c.vout]
        except TypeError: # outputs is None or vout is None
            out = None

        if not c.checked:
            if c.child.graph.validator.check_needed(c.child.myinfo, out):
                c.checked = True
            else:
                return None

        return (False, False, c.vin, self.validity, out)

    def add_child(self, connection): # refuse connection and ping
        connection.child.graph.add_ping(connection.child)
    def del_child(self, connection): pass
    def recalc_depth(self): pass

# create singletons for pruning
prunednodes = [NodeInactive(v, None, None) for v in (0,1,2)]
