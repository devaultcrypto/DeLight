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

import sys
import threading
import queue
import traceback
import weakref
import collections
from .transaction import Transaction

INF_DEPTH=2147483646  # 'infinity' value for node depths. 2**31 - 2

class DoubleLoadException(Exception):
    pass

class ValidatorGeneric:
    """
    The specific colored coin implementation will need to make a 'validator'
    object according to this template.

    Implementations should:
    - Define `get_info`, `check_needed`, and `validate` methods.
    - Define `validity_states` dictionary.
    - Set `prevalidation` to one of the following:
        False - only call validate() once per tx, when all inputs are concluded.
        True - call validate() repeatedly, starting when all inputs are downloaded.
        (only useful if this can provide early validity conclusions)
    """

    prevalidation = False

    validity_states = {
        0: 'Unknown',
        1: 'Valid',
        2: 'Invalid',
        }

    def get_info(self,tx):
        """ This will be called with a Transaction object; use it to extract
        all information necessary during the validation process (after call,
        the Transaction object will be forgotten).

        Allowed return values:

        ('prune', validity) -- prune this tx immediately, remember only validity.
        (vin_mask, myinfo, outputs)
                -- information for active, *potentially* valid tx.

        The list `vin_mask = (True, False, False, True, ...)` tells which tx
        inputs are to be considered for validation.

        The list `outputs = (out_1, out_2, ...)` provides info that is needed
        to validate descendant transactions. (e.g., how many tokens).

        `vin_mask` and `outputs` must have lengths matching the tx inputs/outputs.

        See `validate` for how these are used.


        Pruning is done by replacing node references with prunednodes[validity] .
        These will provide None as info for children.
        """
        raise NotImplementedError

    def check_needed(self, myinfo, out_n):
        """
        As each input gets downloaded and its get_info() gets computed, we
        check whether it is still relevant for validation.

        (This is used to disconnect unimportant branches.)

        Here we pass in `myinfo` from the tx, and `out_n` from the input
        tx's get_info(); if it was pruned then `out_n` will be None.
        """
        raise NotImplementedError

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
# Validation jobbing mechanics (downloading txes, building graph
########

def emptygetter(i):
    raise KeyError

class ValidationJob:
    """
    Manages a job whose actions are held in mainloop().

    This implementation does a basic breadth-first search.
    """
    download_timeout = 5
    downloads = 0

    currentdepth = 0
    debugging_graph_state = False

    stopping = False
    running = False

    def __init__(self, graph, txids, network,
                 txcachegetter=None, validitycachegetter=None,
                 download_limit=None, depth_limit=None):
        """
        graph should be a TokenGraph instance with the appropriate validator.

        txids is a list of the desired transactions.

        network is a lib.network.Network object, will be used to download when
        transactions can't be found in the cache.

        txcachegetter (optional) called as txcachegetter(txid_hex), and should
        raise KeyError when a tx is not found in cache. A good value here
        would be wallet.transactions.__getitem__ .

        validitycachegetter (optional) called as validitycachegetter(txid_hex),
        and likewise should raise KeyError, otherwise return a validity value
        that will be passed to load_tx.

        download_limit is enforced by stopping search when the `downloads`
        attribute exceeds this limit. (may exceed it by several, since
        downloads are requested in parallel)

        depth_limit sets the maximum graph depth to dig to.
        """
        self.graph = graph
        self.txids = tuple(txids)
        self.network = network
        self.txcachegetter = txcachegetter if txcachegetter else emptygetter
        self.validitycachegetter = validitycachegetter if validitycachegetter else emptygetter
        self.download_limit = download_limit
        if depth_limit is None:
            self.depth_limit = INF_DEPTH - 1
        else:
            self.depth_limit = depth_limit
        self.callbacks = []

        self._statelock = threading.Lock()

    def __repr__(self,):
        if self.running:
            state = 'running'
        else:
            try:
                state = 'stopped:%r'%(self.stop_reason,)
            except AttributeError:
                state = 'waiting'
        return "<%s object (%s) for txids=%r>"%(type(self).__qualname__, state, self.txids)

    ## Job state management

    def run(self,):
        """ Wrapper for mainloop() to manage run state. """
        with self._statelock:
            if self.running:
                raise RuntimeError("Job running already", self)
            self.stopping = False
            self.running = True
        try:
            retval = self.mainloop()
        except:
            retval = 'crashed'
            raise
        finally:
            with self._statelock:
                self.stop_reason = retval
                self.running = False
                self.stopping = False
                cbl = tuple(self.callbacks) # make copy while locked
            for cbr in cbl:
                cb = cbr() # indirect
                if cb is None:
                    # cleanup
                    try:
                        self.callbacks.remove(cbr)
                    except ValueError:
                        pass
                else:
                    cb(self)
        return self.stop_reason

    def stop(self,):
        """ Call from another thread, to request stopping (this function
        returns immediately, however it may take time to finish the current
        set of micro-tasks.)

        If not running then this is ignored and False returned.
        Otherwise, True is returned."""
        with self._statelock:
            if self.running:
                self.stopping = True
                return True
            else:
                return False

    #@property
    #def runstatus(self,):
        #with self._statelock:
            #if self.stopping:
                #return "stopping"
            #elif self.running:
                #return "running"
            #else:
                #return "stopped"

    def add_callback(self, cb, way='direct'):
        """
        Callback will be called with cb(job) upon stopping. May be called
        multiple times (if job restarted); will be called immediately as
        well if job was already stopped.

        `way` may be
        - 'direct': store direct reference to `cb`.
        - 'weak'  : store weak reference to `cb`
        - 'weakmethod' : store WeakMethod reference to `cb`.

         (Use 'weakmethod' for bound methods! See weakref documentation.
        """
        if way == 'direct':
            cbr = lambda: cb
        elif way == 'weak':
            cbr = weakref.ref(cb)
        elif way == 'weakmethod':
            cbr = weakref.WeakMethod(cb)
        else:
            raise ValueError(way)
        with self._statelock:
            self.callbacks.append(cbr)
            try:
                _ = self.stop_reason
                was_stopped = True
            except AttributeError:
                was_stopped = False
        if was_stopped:
            cb(self)

    ## Validation logic (breadth-first traversal)

    @property
    def nodes(self,):
        # get target nodes
        return {t:self.graph.get_node(t) for t in self.txids}

    def mainloop(self,):
        """ Breadth-first search """

        nodes = self.nodes.values()

        self.graph.root.set_parents(nodes)
        self.graph.run_sched()

        def dl_callback(tx):
            #will be called by self.get_txes
            txid = tx.txid()
            node = self.graph.get_node(txid)
            try:
                val = self.validitycachegetter(txid)
            except KeyError:
                val = None
            try:
                node.load_tx(tx, cached_validity=val)
            except DoubleLoadException:
                pass

        while True:
            if self.stopping:
                self.graph.debug("stop requested")
                return "stopped"

            if not any(n.active for n in nodes):
                self.graph.debug("target nodes finished")
                return True

            # fetch all finite-depth nodes
            waiting = self.graph.get_waiting(maxdepth=self.depth_limit - 1)
            if len(waiting) == 0: # No waiting nodes at all ==> completed.
                self.graph.debug("exhausted graph without conclusion.")
                return "inconclusive"

            interested_txids = {n.txid for n in waiting
                                if (n.depth <= self.currentdepth)}
            if len(interested_txids) == 0: # Exhausted this depth
                self.currentdepth += 1
                if self.currentdepth > self.depth_limit:
                    self.graph.debug("reached depth stop.")
                    return "depth limit reached"
                self.graph.debug("moving to depth = %d", self.currentdepth)
                continue

            # Download and load up results; this is the main command that
            # will take time in this loop.
            txids_missing = self.get_txes(interested_txids, dl_callback)

            # do graph maintenance (ping() validation, depth recalculations)
            self.graph.run_sched()

            # print entire graph (could take a lot of time!)
            if self.debugging_graph_state:
                self.graph.debug("Active graph state:")
                n_active = 0
                for txid,n in self.graph._nodes.items():
                    if not n.active:
                        continue
                    self.graph.debug("    %.10s...[%8s] depth=%s"%(txid, n.status, str(n.depth) if n.depth != INF_DEPTH else 'INF_DEPTH'))
                    n_active += 1
                if n_active == 0:
                    self.graph.debug("    (empty)")

            txids_gotten = interested_txids.difference(txids_missing)
            if len(txids_gotten) == 0:
                return "missing txes"
        raise RuntimeError('loop ended')


    def get_txes(self, txid_iterable, callback, errors='print'):
        """
        Get multiple txes 'in parallel' (requests all sent at once), and
        block while waiting.

        As they are received, we call `callback(tx)` in the current thread.

        Returns a set of txids that could not be obtained, for whatever
        reason.

        `errors` may be 'ignore' or 'raise' or 'print'.
        """

        txid_set = set(txid_iterable)
        requests = []

        # First try to get from cache:
        cached = []
        for txid in sorted(txid_set):
            try:
                tx = self.txcachegetter(txid)
            except KeyError:
                requests.append(('blockchain.transaction.get', [txid]))
            else:
                cached.append(tx)

        q = queue.Queue()
        if len(requests) > 0:
            self.network.send(requests, q.put)

        # Now start processing cached txes:
        for tx in cached:
            txid = tx.txid()
            try:
                txid_set.remove(txid)
            except KeyError:
                raise RuntimeError("Cache mistake -- wrong txid!!", txid)
            else:
                callback(tx)

        # And start processing downloaded txes:
        for _ in requests: # fetch as many responses as were requested.
            try:
                resp = q.get(True, self.download_timeout)
            except queue.Empty: # timeout
                break
            if resp.get('error'):
                if errors=="print":
                    print("Tx request error:", resp.get('error'))
                elif errors=="raise":
                    raise RuntimeError("Tx request error", resp.get('error'))
                else:
                    raise ValueError(errors)
                continue
            raw = resp.get('result')
            self.downloads += 1
            tx = Transaction(raw)
            txid = tx.txid()
            try:
                txid_set.remove(txid)
            except KeyError:
                if errors=="print":
                    print("Received un-requested txid! Ignoring.", txid)
                elif errors=="raise":
                    raise RuntimeError("Received un-requested txid!", txid)
                else:
                    raise ValueError(errors)
            else:
                callback(tx)

        return txid_set


class ValidationJobManager:
    """
    A single thread that processes validation jobs sequentially.
    """
    def __init__(self, threadname="ValidationJobManager"):
        # ---
        self.jobs_lock = threading.Lock()
        # the following things are locked
        self.job_current = None
        self.jobs_pending  = []   # list of jobs waiting to run.
        self.jobs_finished = []   # list of jobs finished normally.
        self.jobs_paused   = []   # list of jobs that stopped without finishing.
        self.all_jobs = weakref.WeakSet()
        self.wakeup = threading.Event()  # for kicking the mainloop to wake up if it has fallen asleep
        # ---

        self._killing = False  # set by .kill()

        # Kick off the thread
        self.thread = threading.Thread(target=self.mainloop, name=threadname, daemon=True)
        self.thread.start()

    def add_job(self, job):
        """ Throws ValueError if job is already pending. """
        with self.jobs_lock:
            if job in self.all_jobs:
                raise ValueError
            self.all_jobs.add(job)
            self.jobs_pending.append(job)
        self.wakeup.set()

    def pause_job(self, job):
        """
        Returns True if job was running or pending.
        Returns False otherwise.
        """
        with self.jobs_lock:
            if job is self.job_current:
                if job.stop():
                    return True
                else:
                    # rare situation
                    # - running job just stopped.
                    return False
            else:
                try:
                    self.jobs_pending.remove(job)
                except ValueError:
                    return False
                else:
                    self.jobs_paused.append(job)
                    return True

    def unpause_job(self, job):
        """ Take a paused job and put it back into pending.

        Throws ValueError if job is not in paused list. """
        with self.jobs_lock:
            self.jobs_paused.remove(job)
            self.jobs_pending.append(job)
        self.wakeup.set()

    def kill(self, ):
        """Request to stop running job (if any) and to after end thread.
        Irreversible."""
        self._killing = True
        self.wakeup.set()
        try:
            self.job_current.stop()
        except:
            pass

    def mainloop(self,):
        try:
            if threading.current_thread() is not self.thread:
                raise RuntimeError('wrong thread')
            while True:
                if self._killing:
                    return
                with self.jobs_lock:
                    self.wakeup.clear()
                    try:
                        self.job_current = self.jobs_pending.pop(0)
                    except IndexError:
                        # prepare to sleep, outside lock
                        self.job_current = None
                if self.job_current is None:
                    self.wakeup.wait()
                    continue

                try:
                    retval = self.job_current.run()
                except BaseException as e:
                    print("vvvvv validation job error traceback", file=sys.stderr)
                    traceback.print_exc()
                    print("^^^^^ validation job %r error traceback"%(self.job_current,), file=sys.stderr)
                    self.jobs_paused.append(self.job_current)
                else:
                    if retval is True:
                        self.jobs_finished.append(self.job_current)
                    else:
                        self.jobs_paused.append(self.job_current)
        except:
            traceback.print_exc()
            print("Thread %s crashed :("%(self.thread.name,), file=sys.stderr)


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

    The terms "parent" and "child" refer to the ancestry of a tx -- child
    transactions contain (in inputs) a set of pointers to their parents.

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
    debugging = False

    def __init__(self, validator):
        self.validator = validator

        self._nodes = dict() # txid -> Node

        self.root = NodeRoot(self)

        self._waiting_nodes = []

        # requested callbacks
        self._sched_ping = set()
        self._sched_recalc_depth = set()

        # create singletons for pruning
        self.prunednodes = {v:NodeInactive(v, None) for v in validator.validity_states.keys()}

        # Threading rule: we never call node functions while locked.
        # self._lock = ... # threading not enabled.

    def reset(self, ):
        # copy nodes and reset self
        prevnodes = self._nodes
        TokenGraph.__init__(self, self.validator)

        # nuke Connections to encourage prompt GC
        for n in prevnodes.values():
            try:
                n.conn_children = []
                n.conn_parents = []
            except:
                pass

    def debug(self, formatstr, *args):
        if self.debugging:
            print("DEBUG-DAG: " + formatstr%args, file=sys.stderr)

    def get_node(self, txid):
        # with self._lock:
        try:
            node = self._nodes[txid]
        except KeyError:
            node = Node(txid, self)
            self._nodes[txid] = node
            self._waiting_nodes.append(node)
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

    def get_waiting(self, maxdepth=INF_DEPTH):
        """ Return a list of waiting nodes (that haven't had load_tx called
        yet). Optional parameter specifying maximum depth. """
        # with self._lock:
        # First, update the _waiting_nodes list.
        waiting_actual = [node for node in self._waiting_nodes
                          if node.waiting]
        self._waiting_nodes = waiting_actual

        if maxdepth == INF_DEPTH:
            return list(waiting_actual) # return copy
        else:
            return [node for node in waiting_actual
                    if node.depth <= maxdepth]



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
    transaction data is not yet available, or in a live state.

    The node becomes inactive when a conclusion is reached: either
    pruned, invalid, or valid. When this occurs, the node replaces itself
    with a NodeInactive object (more compact).
    """
    def __init__(self, txid, graph):
        self.txid = txid
        self.graph = graph
        self.conn_children = list()
        self.conn_parents = ()
        self.depth = INF_DEPTH
        self.waiting = True
        self.active = True
        self.validity = 0    # 0 - unknown, 1 - valid, 2 - invalid
        self.myinfo = None   # self-info from get_info().
        self.outputs = None  # per-output info from get_info(). None if waiting/pruned/invalid.
        # self._lock = ... # threading not enabled.

    @property
    def status(self):
        if self.waiting:
            return 'waiting'
        if self.active:
            return 'live'
        else:
            return 'inactive'

    def __repr__(self,):
        return "<%s %s txid=%r>"%(type(self).__qualname__, self.status, self.txid)


    ## Child connection adding/removing

    def add_child(self, connection):
        """ Called by children to subscribe notifications.

        (If inactive, a ping will be scheduled.)
        """
        # with self._lock:
        if not self.active:
            connection.parent = self.replacement
            self.graph.add_ping(connection.child)
            return
        if connection.parent is not self:
            raise RuntimeError('mismatch')

        self.conn_children.append(connection)
        newdepth = min(1 + connection.child.depth,
                       INF_DEPTH)
        olddepth = self.depth
        if newdepth < olddepth:
            # found a shorter path from root
            self.depth = newdepth
            for c in self.conn_parents:
                if c.parent.depth == 1 + olddepth:
                    # parent may have been hanging off our depth value.
                    self.graph.add_recalc_depth(c.parent, newdepth)
        return

    def del_child(self, connection):
        """ called by children to remove connection
        """
        # with self._lock:
        self.conn_children.remove(connection)

        if self.depth <= connection.child.depth+1:
            self.graph.add_recalc_depth(self, self.depth)


    ## Loading of info

    def load_tx(self, tx, cached_validity = None):
        """ Convert 'waiting' transaction to live one. """
        # with self._lock:
        if not self.waiting:
            raise DoubleLoadException(self)

        if tx.txid() != self.txid:
            raise ValueError("TXID mismatch", tx.txid(), self.txid)

        validator = self.graph.validator
        ret = validator.get_info(tx)

        if len(ret) == 2:
            self.graph.debug("%.10s... judged upon loading: %s",
                             self.txid, self.graph.validator.validity_states.get(ret[1],ret[1]))
            if ret[0] != 'prune':
                raise ValueError(ret)
            return self._inactivate_self(False, ret[1])

        vin_mask, self.myinfo, self.outputs = ret

        if len(self.outputs) != len(tx.outputs()):
            raise ValueError("output length mismatch")

        if cached_validity is not None:
            self.graph.debug("%.10s... cached judgement: %s",
                             self.txid, self.graph.validator.validity_states.get(cached_validity,cached_validity))
            return self._inactivate_self(True, cached_validity)

        # at this point we have exhausted options for inactivation.
        # build connections to parents
        txinputs = tx.inputs()
        if len(vin_mask) != len(txinputs):
            raise ValueError("input length mismatch")

        conn_parents = []
        for vin, (mask, inp) in enumerate(zip(vin_mask, txinputs)):
            if not mask:
                continue
            txid = inp['prevout_hash']
            vout = inp['prevout_n']

            p = self.graph.get_node(txid)
            c = Connection(p,self,vout,vin)
            p.add_child(c)
            conn_parents.append(c)
        self.conn_parents = conn_parents

        self.waiting = False

        self.graph.add_ping(self)
        if len(self.conn_parents) != 0:
            # (no parents? children will be pinged after validation)
            for c in self.conn_children:
                self.graph.add_ping(c.child)

    def load_pruned(self, cached_validity):
        # with self._lock:
        if not self.waiting:
            raise DoubleLoadException(self)

        self.graph.debug("%.10s... load pruned: %s",
                         self.txid, self.graph.validator.validity_states.get(cached_validity,cached_validity))

        return self._inactivate_self(False, cached_validity)


    ## Internal utility stuff

    def _inactivate_self(self, keepinfo, validity):
        # Replace self with NodeInactive instance according to keepinfo and validity
        # no thread locking here, this only gets called internally.

        if keepinfo:
            replacement = NodeInactive(validity, self.outputs)
        else:
            replacement = self.graph.prunednodes[validity] # use singletons

        # replace self in lookups
        self.graph.replace_node(self.txid, replacement)

        # unsubscribe from parents & forget
        for c in self.conn_parents:
            c.parent.del_child(c)
        self.conn_parents = ()

        # replace self in child connections & forget
        for c in self.conn_children:
            c.parent = replacement
            c.checked = False
            self.graph.add_ping(c.child)
        self.conn_children = ()

        # At this point all permanent refs to us should be gone and we will soon be deleted.
        # Temporary refs may remain, for which we mimic the replacement.
        self.waiting = False
        self.active = False
        self.depth = replacement.depth
        self.validity = replacement.validity
        self.outputs = replacement.outputs
        self.replacement = replacement

    def recalc_depth(self):
        # with self._lock:
        if not self.active:
            return
        depths = [c.child.depth for c in self.conn_children]
        depths.append(INF_DEPTH-1)
        newdepth = 1 + min(depths)
        olddepth = self.depth
        if newdepth != olddepth:
            self.depth = newdepth
            depthpriority = 1 + min(olddepth, newdepth)
            for c in self.conn_parents:
                self.graph.add_recalc_depth(c.parent, depthpriority)

    def get_out_info(self, c):
        # Get info for the connection and check if connection is needed.
        # Returns None if validator's check_needed returns False.
        # with self._lock:
        try:
            out = self.outputs[c.vout]
        except TypeError: # outputs is None or vout is None
            out = None

        if not c.checked and not self.waiting:
            if c.child.graph.validator.check_needed(c.child.myinfo, out):
                c.checked = True
            else:
                return None

        return (self.active, self.waiting, c.vin, self.validity, out)

    def ping(self, ):
        """ handle notification status update on one or more parents """
        # with self._lock:

        if not self.active:
            return
        validator = self.graph.validator

        # get info, discarding unneeded parents.
        pinfo = []
        for c in tuple(self.conn_parents):
            info = c.parent.get_out_info(c)
            if info is None:
                c.parent.del_child(c)
                self.conn_parents.remove(c)
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
                                   self.txid, self.myinfo, valinfo)
            return
        else: # decided
            self.graph.debug("%.10s... judgement based on inputs: %s",
                             self.txid, self.graph.validator.validity_states.get(ret[1],ret[1]))
            self._inactivate_self(*ret)


class NodeRoot: # Special root, only one of these is created per TokenGraph.
    depth = -1

    def __init__(self, graph):
        self.graph = graph
        self.conn_parents = []
    def set_parents(self, parent_nodes):
        # Remove existing parent connections
        for c in tuple(self.conn_parents):
            c.parent.del_child(c)
            self.conn_parents.remove(c)
        # Add new ones
        for p in parent_nodes:
            c = Connection(p, self, None, None)
            p.add_child(c)
            self.conn_parents.append(c)
            return c
    def ping(self,):
        pass


# container used to replace Node with static result
class NodeInactive(collections.namedtuple('anon_namedtuple',
                                          ['validity', 'outputs'])):
    __slots__ = ()  # no dict needed
    active = False
    waiting = False
    depth = INF_DEPTH
    txid = None
    status = "inactive"

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

    def load_tx(self, tx, cached_validity = None):
        raise DoubleLoadException(self)
    def add_child(self, connection): # refuse connection and ping
        connection.child.graph.add_ping(connection.child)
    def del_child(self, connection): pass
    def recalc_depth(self): pass
