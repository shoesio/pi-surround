# SPDX-License-Identifier: GPL-2.0-or-later
# Public packaging: device identities moved to site settings, 2026-10-23.
"""One bounded resume for a programme paused during front recovery.

No audio, volume, routing, service or calibration operations. As with startup
resume, an intentional Pause during the short recovery window is ambiguous.
"""
import asyncio
import math
import time
from handover_policy import snapshot

class RecoveryPlayback:
    def __init__(self, window=20.0, state_max_age=6.0, settle=2.0):
        self.window=window;self.state_max_age=state_max_age;self.settle=settle
        self.before=None;self.began=None;self.healthy_since=None;self.unhealthy=False

    def _current(self,now,current,observed_at,owns_route):
        return bool(self.before and current and owns_route
                    and all(math.isfinite(x) for x in [now,observed_at])
                    and 0<=now-self.began<=self.window
                    and 0<=now-observed_at<=self.state_max_age
                    and self.before['identity']==current['identity'])

    def update(self,*,now,healthy,current,observed_at,owns_route):
        if not owns_route or (self.before and
                (now<self.began or now-self.began>self.window)):
            self.before=None
        if self.before and current and self.before['identity']!=current['identity']:
            self.before=None
        if not healthy:
            self.healthy_since=None
            first=not self.unhealthy;self.unhealthy=True
            if first and not self.before and owns_route and current and current['state']=='Playing' and 0<=now-observed_at<=self.state_max_age:
                self.before=dict(current);self.began=now
                return 'armed'
            return None
        self.unhealthy=False
        if self.healthy_since is None:self.healthy_since=now
        if not self._current(now,current,observed_at,owns_route):return None
        stable=now-self.healthy_since
        if current['state']=='Paused' and stable>=self.settle:return 'resume'
        # A recovered stream that stayed Playing needs no transport action.
        if current['state']=='Playing' and stable>=self.state_max_age:self.before=None
        return None

    def allow_paused_repair(self,*,now,current,observed_at,owns_route):
        return bool(self._current(now,current,observed_at,owns_route)
                    and current['state']=='Paused')

    async def resume(self,atv,router,owner_check,trace,clock=time.monotonic):
        before=self.before;began=self.began
        self.before=None  # At most one attempt, including timeout/error.
        if not before:return False
        try:
            current=snapshot(await asyncio.wait_for(atv.metadata.playing(),timeout=3))
            if not (current and current['state']=='Paused'
                    and current['identity']==before['identity']
                    and 0<=clock()-began<=self.window
                    and owner_check([d.identifier for d in atv.audio.output_devices],router)):
                trace('front_recovery_resume_skipped',reason='guard_changed');return False
            trace('front_recovery_resume_requested')
            await asyncio.wait_for(atv.remote_control.play(),timeout=4)
            trace('front_recovery_resume_sent');return True
        except Exception as error:
            trace('front_recovery_resume_unavailable',error_type=type(error).__name__)
            return False
