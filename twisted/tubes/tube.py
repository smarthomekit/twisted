# -*- test-case-name: twisted.tubes.test.test_tube -*-
# -*- test-case-name: twisted.tubes.test.test_tube.SeriesTest.test_diverterInYourDiverterSoYouCanDivertWhileYouDivert -*-
# Copyright (c) Twisted Matrix Laboratories.
# See LICENSE for details.

"""
See L{Tube}.
"""

from __future__ import print_function

import itertools

from zope.interface import implementer

from twisted.internet.defer import Deferred

from twisted.python import log
from twisted.python.failure import Failure
from twisted.python.components import proxyForInterface

from twisted.tubes.itube import (IDrain, ITube, IFount, IPause,
                                 IDivertable, AlreadyUnpaused)



def tube(cls):
    """
    L{tube} is a class decorator which declares a given class to be an
    implementer of L{ITube} and fills out any methods or attributes which are
    not present on the decorated type with null-implementation methods (those
    which return None) and None attributes.

    @param cls: A class with some or all of the attributes or methods described
        by L{ITube}.
    @type cls: L{type}

    @return: C{cls}
    @rtype: L{type} which implements L{ITube}
    """

    # This is better than a superclass, because:

    # - you can't do a separate 'isinstance(Tube)' check instead of
    #   ITube.providedBy like you're supposed to

    # - you can't just instantiate Tube directly, that is pointless
    #   functionality so we're not providing it

    # - it avoids propagating a bad example that other codebases will copy to
    #   depth:infinity, rather than depth:1 where subclassing is actually sort
    #   of okay

    # - it provides a more straightforward and reliable mechanism for
    #   future-proofing code.  If you're inheriting from a superclass and you
    #   want it to do something to warn users, upgrade an interface, and so on,
    #   you have to try to cram a new meta-type into the user's hierarchy so a
    #   function gets invoked at the right time.  If you're invoking this class
    #   decorator, then it just gets invoked like a normal function, and we can
    #   put some code in here that examines the type and does whatever it wants
    #   to do, because the @ syntax simply called it as a function.

    # It still shares some issues with inheritance, such as:

    # - the direction of visibility within the hierarchy is still wrong.  you
    #   can still do 'self.someMethodIDidntImplement()' and get a result.

    # - it destructively modifies the original class, so what you see isn't
    #   quite what you get.  a cleaner compositional approach would simply wrap
    #   an object around another object (but that would mean inventing a new
    #   incompletely-specified type that floats around at runtime, rather than
    #   a utility to help you completely implement ITube at import time)

    def started(self):
        """
        A null implementation of started.
        """

    def stopped(self, reason):
        """
        A null implementation of stopped.
        """

    def received(self, item):
        """
        A null implementation of received
        """

    fillers = [('started', started),
               ('stopped', stopped),
               ('received', received),
               ('inputType', None),
               ('outputType', None)]

    notHere = object()

    for name, value in fillers:
        if getattr(cls, name, notHere) is notHere:
            setattr(cls, name, value)

    return implementer(ITube)(cls)

class _SiphonPiece(object):
    """
    Shared functionality between L{_SiphonFount} and L{_SiphonDrain}
    """
    def __init__(self, siphon):
        self._siphon = siphon


    @property
    def _tube(self):
        return self._siphon._tube



@implementer(IPause)
class _Pause(object):
    def __init__(self, pauser):
        self.pauser = pauser
        self.alive = True


    def unpause(self):
        if self.alive:
            self.pauser.pauses -= 1
            if self.pauser.pauses == 0:
                self.pauser.actuallyResume()
            self.alive = False
        else:
            raise AlreadyUnpaused()



class _Pauser(object):

    def __init__(self, actuallyPause, actuallyResume):
        self.actuallyPause = actuallyPause
        self.actuallyResume = actuallyResume
        self.pauses = 0


    def pauseFlow(self):
        """
        @see: L{IFount.pauseFlow}
        """
        if not self.pauses:
            self.actuallyPause()
        self.pauses += 1
        return _Pause(self)



@implementer(IFount)
class _SiphonFount(_SiphonPiece):
    """
    Implementation of L{IFount} for L{_Siphon}.

    @ivar fount: the implementation of the L{IDrain.fount} attribute.  The
        L{IFount} which is flowing to this L{_Siphon}'s L{IDrain}
        implementation.

    @ivar drain: the implementation of the L{IFount.drain} attribute.  The
        L{IDrain} to which this L{_Siphon}'s L{IFount} implementation is
        flowing.
    """
    drain = None

    def __init__(self, siphon):
        super(_SiphonFount, self).__init__(siphon)
        self._pauser = _Pauser(self._actuallyPause, self._actuallyResume)


    def __repr__(self):
        """
        Nice string representation.
        """
        return "<Fount for {0}>".format(repr(self._siphon._tube))


    @property
    def outputType(self):
        return self._tube.outputType


    def flowTo(self, drain):
        """
        Flow data from this siphon to the given drain.
        """
        if self.drain:
            # FIXME: direct test for this.  The behavior here ought to be that
            # when we make it so that our drain is no longer actually our
            # drain, it stops telling us to pause/stop/etc.  Open question:
            # what if it had already paused us?  Can we simply discard that
            # now?  Note that this flowingFrom may re-entrantly call this
            # flowTo again, which is probably nonsense, but ugh, what should
            # even happen then...
            self.drain.flowingFrom(None)
        self.drain = drain
        if drain is None:
            return
        result = self.drain.flowingFrom(self)
        if self._siphon._pauseBecauseNoDrain:
            pbnd = self._siphon._pauseBecauseNoDrain
            self._siphon._pauseBecauseNoDrain = None
            pbnd.unpause()
        self._siphon._unbufferIterator()
        return result


    def pauseFlow(self):
        """
        Pause the flow from the fount, or remember to do that when the
        fount is attached, if it isn't yet.
        """
        return self._pauser.pauseFlow()


    def _actuallyPause(self):
        fount = self._siphon._tdrain.fount
        self._siphon._currentlyPaused = True
        if fount is not None and self._siphon._pauseBecausePauseCalled is None:
            self._siphon._pauseBecausePauseCalled = fount.pauseFlow()


    def _actuallyResume(self):
        """
        Resume the flow from the fount to this L{_Siphon}.
        """
        self._siphon._currentlyPaused = False

        self._siphon._unbufferIterator()
        if self._siphon._currentlyPaused:
            return

        if self._siphon._pauseBecausePauseCalled:
            # TODO: validate that the siphon's fount is always set consisetntly
            # with _pauseBecausePauseCalled.
            fp = self._siphon._pauseBecausePauseCalled
            self._siphon._pauseBecausePauseCalled = None
            fp.unpause()


    def stopFlow(self):
        """
        Stop the flow from the fount to this L{_Siphon}.
        """
        self._siphon._flowWasStopped = True
        fount = self._siphon._tdrain.fount
        if fount is None:
            return
        fount.stopFlow()



@implementer(IPause)
class _PlaceholderPause(object):

    def unpause(self):
        """
        No-op.
        """



@implementer(IDrain)
class _SiphonDrain(_SiphonPiece):
    """
    Implementation of L{IDrain} for L{_Siphon}.
    """
    fount = None

    def __repr__(self):
        """
        Nice string representation.
        """
        return '<Drain for {0}>'.format(self._siphon._tube)


    @property
    def inputType(self):
        return self._tube.inputType


    def flowingFrom(self, fount):
        """
        This siphon will now have 'receive' called.
        """
        if fount is not None:
            out = fount.outputType
            in_ = self.inputType
            if out is not None and in_ is not None:
                if not in_.isOrExtends(out):
                    raise TypeError()
        self.fount = fount
        if self._siphon._pauseBecausePauseCalled:
            pbpc = self._siphon._pauseBecausePauseCalled
            self._siphon._pauseBecausePauseCalled = None
            pbpc.unpause()
            if fount is None:
                pauseFlow = _PlaceholderPause
            else:
                pauseFlow = fount.pauseFlow
            self._siphon._pauseBecausePauseCalled = pauseFlow()
        if fount is not None:
            if self._siphon._flowWasStopped:
                fount.stopFlow()
            # Is this the right place, or does this need to come after
            # _pauseBecausePauseCalled's check?
            if not self._siphon._everStarted:
                self._siphon._everStarted = True
                self._siphon._deliverFrom(self._tube.started)
        nextFount = self._siphon._tfount
        nextDrain = nextFount.drain
        if nextDrain is None:
            return nextFount
        return nextFount.flowTo(nextDrain)


    def receive(self, item):
        """
        An item was received.  Pass it on to the tube for processing.
        """
        def thingToDeliverFrom():
            return self._tube.received(item)
        self._siphon._deliverFrom(thingToDeliverFrom)


    def flowStopped(self, reason):
        """
        This siphon has now stopped.
        """
        self._siphon._flowStoppingReason = reason
        self._siphon._deliverFrom(lambda: self._tube.stopped(reason))



def series(start, *tubes):
    """
    Connect up a series of objects capable of transforming inputs to outputs;
    convert a sequence of L{ITube} objects into a sequence of connected
    L{IFount} and L{IDrain} objects.  This is necessary to be able to C{flowTo}
    an object implementing L{ITube}.

    This function can best be understood by understanding that::

        x = a
        a.flowTo(b).flowTo(c)

    is roughly analagous to::

        x = series(a, b, c)

    with the additional feature that C{series} will convert C{a}, C{b}, and
    C{c} to the requisite L{IDrain} objects first.

    @param start: The initial element in the chain; the object that will
        consume inputs passed to the result of this call to C{series}.
    @type start: an L{ITube}, or anything adaptable to L{IDrain}.

    @param tubes: Each element of C{plumbing}.
    @type tubes: a L{tuple} of L{ITube}s or objects adaptable to L{IDrain}.

    @return: An L{IDrain} that can consume inputs of C{start}'s C{inputType},
        and whose C{flowingFrom} will return an L{IFount} that will produce
        outputs of C{plumbing[-1]} (or C{start}, if plumbing is empty).
    @rtype: L{IDrain}

    @raise TypeError: if C{start}, or any element of C{plumbing} is not
        adaptable to L{IDrain}.
    """
    with _registryActive(_tubeRegistry):
        result = IDrain(start)
        currentFount = result.flowingFrom(None)
        drains = map(IDrain, tubes)
    for drain in drains:
        currentFount = currentFount.flowTo(drain)
    return result



from zope.interface.adapter import AdapterRegistry
from twisted.python.components import _addHook, _removeHook
from contextlib import contextmanager

@contextmanager
def _registryActive(registry):
    """
    A context manager that activates and deactivates a zope adapter registry
    for the duration of the call.

    For example, if you wanted to have a function that could adapt L{IFoo} to
    L{IBar}, but doesn't expose that adapter outside of itself::

        def convertToBar(maybeFoo):
            with _registryActive(_registryAdapting((IFoo, IBar, fooToBar))):
                return IBar(maybeFoo)

    @note: This isn't thread safe, so other threads will be affected as well.

    @param registry: The registry to activate.
    @type registry: L{AdapterRegistry}

    @rtype:
    """
    hook = _addHook(registry)
    yield
    _removeHook(hook)



class _Siphon(object):
    """
    A L{_Siphon} is an L{IDrain} and possibly also an L{IFount}, and provides
    lots of conveniences to make it easy to implement something that does fancy
    flow control with just a few methods.

    @ivar _tube: the L{Tube} which will receive values from this siphon and
        call C{deliver} to deliver output to it.  (When set, this will
        automatically set the C{siphon} attribute of said L{Tube} as well, as
        well as un-setting the C{siphon} attribute of the old tube.)

    @ivar _currentlyPaused: is this L{_Siphon} currently paused?  Boolean:
        C{True} if paused, C{False} if not.

    @ivar _pauseBecausePauseCalled: an L{IPause} from the upstream fount,
        present because pauseFlow has been called.

    @ivar _flowStoppingReason: If this is not C{None}, then call C{flowStopped}
        on the downstream L{IDrain} at the next opportunity, where "the next
        opportunity" is when the last L{Deferred} yielded from L{ITube.stopped}
        has fired.

    @ivar _everStarted: Has this L{_Siphon} ever called C{started} on its
        L{Tube}?
    @type _everStarted: L{bool}
    """

    _currentlyPaused = False
    _pauseBecausePauseCalled = None
    _tube = None
    _pendingIterator = None
    _flowWasStopped = False
    _everStarted = False

    def __init__(self, tube):
        """
        Initialize this L{_Siphon} with the given L{Tube} to control its
        behavior.
        """
        self._tfount = _SiphonFount(self)
        self._tdrain = _SiphonDrain(self)
        assert not getattr(tube, "__marked__", False)
        tube.__marked__ = True
        self._tube = tube


    def __repr__(self):
        """
        Nice string representation.
        """
        return '<_Siphon for {0}>'.format(repr(self._tube))


    _pauseBecauseNoDrain = None

    def _deliverFrom(self, deliverySource):
        assert self._pendingIterator is None, \
            repr(list(self._pendingIterator)) + " " + \
            repr(deliverySource) + " " + \
            repr(self._pauseBecauseNoDrain)
        try:
            iterableOrNot = deliverySource()
        except:
            f = Failure()
            log.err(f, "Exception raised when delivering from {0!r}"
                    .format(deliverySource))
            self._tdrain.fount.stopFlow()
            downstream = self._tfount.drain
            if downstream is not None:
                downstream.flowStopped(f)
            return
        if iterableOrNot is None:
            return 0
        self._pendingIterator = iter(iterableOrNot)
        if self._tfount.drain is None:
            if self._pauseBecauseNoDrain is None:
                self._pauseBecauseNoDrain = self._tfount.pauseFlow()

        self._unbufferIterator()

    _unbuffering = False
    _flowStoppingReason = None

    def _unbufferIterator(self):
        if self._unbuffering:
            return
        if self._pendingIterator is None:
            return
        whatever = object()
        self._unbuffering = True
        while not self._currentlyPaused:
            value = next(self._pendingIterator, whatever)
            if value is whatever:
                self._pendingIterator = None
                if self._flowStoppingReason is not None:
                    self._tfount.drain.flowStopped(self._flowStoppingReason)
                break
            if isinstance(value, Deferred):
                anPause = self._tfount.pauseFlow()

                def whenUnclogged(result):
                    pending = self._pendingIterator
                    self._pendingIterator = itertools.chain(iter([result]),
                                                            pending)
                    anPause.unpause()

                from twisted.python import log
                value.addCallback(whenUnclogged).addErrback(log.err, "WHAT")
            else:
                self._tfount.drain.receive(value)
        self._unbuffering = False



@implementer(IFount)
class _FakestFount(object):
    outputType = None
    drain = None

    def flowTo(self, drain):
        self.drain = drain
        return drain.flowingFrom(self)


    def pauseFlow(self):
        return _PlaceholderPause()


    def stopFlow(self):
        pass



@tube
class _DrainingTube(object):
    """
    
    """

    def __init__(self, items, eventualUpstream, eventualDownstream):
        """
        
        """
        self._items = list(items)
        self._eventualUpstream = eventualUpstream
        self._hangOn = self._eventualUpstream.pauseFlow()
        self._eventualDownstream = eventualDownstream


    def __repr__(self):
        """
        
        """
        return ("<Draining Tube {}>".format(repr(self._items)))


    def started(self):
        """
        
        """
        while self._items:
            item = self._items.pop(0)
            yield item
        self._eventualUpstream.flowTo(self._eventualDownstream)
        self._hangOn.unpause()


    def received(self, what):
        """
        
        """
        print("WHY DID I RECEIVE ANYTHING", what)



@implementer(IFount)
class _DrainingFount(object):
    """
    
    """
    def __init__(self, items, fount):
        """
        
        """
        self._items = iter(items)
        self._fount = fount
        self._pauser = _Pauser()
        self.pauseFlow = self._pauser.pauseFlow


    def flowTo(self, drain):
        """
        
        """
        self._drain = drain
        result = self._drain.flowingFrom(self)
        self._drain.receive(next(self._items))
        return result



def _registryAdapting(*fromToAdapterTuples):
    """
    Construct a Zope Interface adapter registry.

    For example, if you want to construct an adapter registry that can convert
    C{IFoo} to C{IBar} with C{fooToBar}.

    @param fromToAdapterTuples: A sequence of tuples of C{(fromInterface,
        toInterface, adapterCallable)}, where C{fromInterface} and
        C{toInterface} are L{Interface}s, and C{adapterCallable} is a callable
        that takes one argument which provides C{fromInterface} and returns an
        object providing C{toInterface}.
    @type fromToAdapterTuples: C{tuple} of 3-C{tuple}s of C{(Interface,
        Interface, callable)}

    @rtype: L{AdapterRegistry}
    """
    result = AdapterRegistry()
    for From, to, adapter in fromToAdapterTuples:
        result.register([From], to, '', adapter)
    return result



def _tube2drain(tube):
    return _Siphon(tube)._tdrain



_tubeRegistry = _registryAdapting(
    (ITube, IDrain, _tube2drain),
)



class Diverter(proxyForInterface(IDrain, "_drain")):
    """
    
    """

    def __init__(self, divertable):
        """
        
        """
        assert IDivertable.providedBy(divertable)
        self._divertable = divertable
        self._friendSiphon = _Siphon(divertable)
        self._drain = self._friendSiphon._tdrain


    def __repr__(self):
        """
        
        """
        return "<Diverter for {}>".format(self._drain)


    def divert(self, drain):
        """
        Divert the flow from the fount which is flowing into this siphon's
        drain to the given drain, reassembling any buffered output from this
        siphon's tube first.
        """
        unpending = self._friendSiphon._pendingIterator

        pendingPending = self._divertable.reassemble(unpending) or []
        upstream = self._friendSiphon._tdrain.fount
        f = _FakestFount()
        dt = series(_DrainingTube(pendingPending, upstream, drain))
        again = f.flowTo(dt)
        again.flowTo(drain)
