# SPDX-License-Identifier: GPL-2.0-or-later
# Public packaging: device identities moved to site settings, 2026-10-23.
"""Device-free shared-master candidate, with an injected volume-only backend.

Programme DSP uses a fixed headroom reference; HomePod master volume is the
only variable front gain. Rear gain changes after its queue. Old bus balance
is deliberately not reconstructed. This module has no live backend or daemon.
"""
from dataclasses import dataclass
from volume_errors import VolumeReadUnavailable
import math
import threading

# Fixed digital headroom reference; +6.02 dB over the previous 1/16.
FIXED_PROGRAMME_GAIN=1/8
QUIET_ANCHOR_COMMAND=-26.25
QUIET_ANCHOR_PERCENT=60

@dataclass(frozen=True)
class Plan:
    command:float
    homepod_percent:int
    rear_gain:float
    muted:bool

def plan(command, *, rear_db_at_zero=-30.0, anchor_command=QUIET_ANCHOR_COMMAND, front_level=100):
    if isinstance(front_level,bool) or not isinstance(front_level,int) or not 0<=front_level<=100:
        raise ValueError('Invalid saved front level')
    command=float(command)
    if not math.isfinite(command) or not (command==-144 or -30<=command<=0):
        raise ValueError('Invalid sender volume command')
    if not math.isfinite(rear_db_at_zero) or not -60<=rear_db_at_zero<=-10:
        raise ValueError('Invalid rear response curve')
    if not math.isfinite(anchor_command) or not -30<anchor_command<0:
        raise ValueError('Invalid quiet anchor')
    # A quiet trial anchor, not an acoustic HomePod calibration. Do not claim
    # this rear response equals the hardware curve. Balance is adjustable.
    if command in (-144.,-30.):return Plan(command,0,0.,True)
    fraction=(command+30)/30
    anchor=(anchor_command+30)/30
    exponent=math.log(QUIET_ANCHOR_PERCENT/100)/math.log(anchor)
    percent=max(1,min(100,round(100*fraction**exponent)))
    rear_gain=10**(rear_db_at_zero*(1-percent/100)/20)
    return Plan(command,0 if front_level==0 else max(0,percent+front_level-100),rear_gain,False)

class LatestCommand:
    """Bounded mailbox; button bursts replace stale work rather than queue it."""
    def __init__(self):self._lock=threading.Lock();self._latest=None;self._seq=0
    def submit(self,command):
        value=plan(command)  # Reject invalid input before mutating mailbox.
        with self._lock:
            self._seq+=1;self._latest=(self._seq,value)
    def take(self):
        with self._lock:
            result=self._latest;self._latest=None;return result

class FrontsUnavailable(RuntimeError):
    """Read-only preflight: expected front sessions are temporarily absent."""

class ContextUnavailable(RuntimeError):
    """Read-only preflight: ownership/rear observations require revalidation."""

class CoupledMaster:
    """Serialize the coupled pair and rear writes, without transport actions.

    API must offer only GET outputs and PUT outputs/<id> volume. A separate
    supervisor supplies route ownership and rear freshness. No attempt is
    made to recover playback, route changes, devices, or a latched failure.
    """
    def __init__(self,api,front_ids,rear,*,initial_percent,route_owned,rear_fresh,
                 trial_ceiling=60,anchor_command=QUIET_ANCHOR_COMMAND,front_level=100):
        self.api=api;self.ids=frozenset(str(x) for x in front_ids);self.rear=rear
        if len(self.ids)!=2:raise ValueError('Exactly two front IDs required')
        if not isinstance(initial_percent,int) or not 0<=initial_percent<=100:
            raise ValueError('Invalid initial level')
        if not isinstance(trial_ceiling,int) or not 0<=trial_ceiling<=100:
            raise ValueError('Invalid ceiling')
        self.front_level=front_level
        self.anchor_command=anchor_command
        plan(anchor_command,anchor_command=anchor_command)
        self.percent=initial_percent;self.route_owned=route_owned
        self.rear_fresh=rear_fresh;self.ceiling=trial_ceiling;self.fault=None
        self._lock=threading.Lock()

    def _verify(self,percent,*,preflight=False):
        if not self.route_owned() or not self.rear_fresh():
            raise (ContextUnavailable if preflight else RuntimeError)('Route or rear freshness changed')
        try:outputs=self.api('outputs')['outputs']
        except VolumeReadUnavailable:
            if preflight:raise ContextUnavailable('Volume status read unavailable')
            raise
        selected={str(x['id']) for x in outputs if x.get('selected')}
        if selected!=self.ids:raise (FrontsUnavailable if preflight else RuntimeError)('Speaker membership changed')
        by_id={str(x['id']):x for x in outputs}
        if any(by_id[i]['volume']!=percent for i in self.ids):
            raise RuntimeError('Coupled front readback mismatch')

    def apply(self,command):
        proposed=plan(command,anchor_command=self.anchor_command,front_level=self.front_level)
        if proposed.homepod_percent>self.ceiling:
            raise ValueError('Outside quiet trial range; no writes made')
        with self._lock:
            if self.fault:raise RuntimeError('Latched fault: '+self.fault)
            try:
                self._verify(self.percent,preflight=True)
                # A mute request quiets the rear first; no queue clear/refill.
                if proposed.muted:self.rear.set_gain(0.)
                if proposed.homepod_percent!=self.percent:
                    for output in sorted(self.ids):
                        self.api('outputs/'+output,{'volume':proposed.homepod_percent})
                    self._verify(proposed.homepod_percent)
                self.rear.set_gain(proposed.rear_gain)
                self.percent=proposed.homepod_percent
                return proposed
            except (FrontsUnavailable,ContextUnavailable):
                # No volume PUT has occurred: this is not a failed write.
                raise
            except Exception as error:
                self.fault=type(error).__name__+': '+str(error)
                # Do not restore a higher native level after a failed decrease
                # or repeatedly contact a HomePod whose state is uncertain.
                self.rear.set_gain(0.)
                raise RuntimeError(self.fault) from error

    def reconcile_saved_level(self,command,level):
        """Known HA intent: preserve membership and coalesce legacy volume writes."""
        proposed=plan(command,anchor_command=self.anchor_command,front_level=level)
        if proposed.homepod_percent>self.ceiling:raise ValueError('Outside quiet trial range')
        with self._lock:
            if self.fault:raise RuntimeError('Latched fault: '+self.fault)
            try:
                if not self.route_owned() or not self.rear_fresh():raise RuntimeError('Route or rear freshness changed')
                outputs=self.api('outputs')['outputs']
                selected={str(x['id']) for x in outputs if x.get('selected')}
                if selected!=self.ids:raise RuntimeError('Speaker membership changed')
                current={str(x['id']):x['volume'] for x in outputs}
                if any(current[i]!=proposed.homepod_percent for i in self.ids):
                    for output in sorted(self.ids):self.api('outputs/'+output,{'volume':proposed.homepod_percent})
                    self._verify(proposed.homepod_percent)
                self.front_level=level;self.percent=proposed.homepod_percent
                self.rear.set_gain(proposed.rear_gain)
                return proposed
            except Exception as error:
                self.fault=type(error).__name__+': '+str(error);self.rear.set_gain(0.)
                raise RuntimeError(self.fault) from error
