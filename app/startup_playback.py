# SPDX-License-Identifier: GPL-2.0-or-later
# Public packaging: device identities moved to site settings, 2026-10-23.
"""One planned startup pause, with guarded recovery after a failed startup."""
import asyncio,time
from handover_policy import snapshot

class StartupPlayback:
    def __init__(self):
        self.before=None
        self.pause_requested=False
        self.pause_confirmed=False
        self.completed=False
        self.failure_resume_attempted=False

    async def pause(self,atv,before,trace):
        self.before=before
        if not before or before['state']!='Playing':
            trace('startup_pause_skipped',reason='not_previously_playing');return False
        current=snapshot(await asyncio.wait_for(atv.metadata.playing(),timeout=3))
        if not current or current['identity']!=before['identity'] or current['state']!='Playing':
            trace('startup_pause_skipped',reason='programme_or_state_changed');return False
        self.pause_requested=True
        trace('startup_pause_requested')
        await asyncio.wait_for(atv.remote_control.pause(),timeout=4)
        # A metadata read immediately following the command can still be cached.
        deadline=time.monotonic()+3
        while time.monotonic()<deadline:
            current=snapshot(await asyncio.wait_for(atv.metadata.playing(),timeout=1))
            if not current or current['identity']!=before['identity']:
                raise RuntimeError('Programme changed while pausing startup')
            if current['state']=='Paused':
                self.pause_confirmed=True;trace('startup_pause_confirmed');return True
            await asyncio.sleep(.1)
        raise RuntimeError('Startup pause was not confirmed')

    async def resume_failed_startup(self,atv,*,original_route,actual_route,trace):
        if self.completed or not self.pause_requested or self.failure_resume_attempted:
            return False
        if not original_route or set(original_route)!=set(actual_route):
            trace('failed_startup_resume_skipped',reason='route_not_restored');return False
        current=snapshot(await asyncio.wait_for(atv.metadata.playing(),timeout=3))
        if not current or not self.before or current['identity']!=self.before['identity'] or current['state']!='Paused':
            trace('failed_startup_resume_skipped',reason='programme_or_state_changed');return False
        self.failure_resume_attempted=True
        trace('failed_startup_resume_requested')
        await asyncio.wait_for(atv.remote_control.play(),timeout=4)
        trace('failed_startup_resume_sent');return True
