# SPDX-License-Identifier: GPL-2.0-or-later
# Public packaging: device identities moved to site settings, 2026-10-23.
"""Control-plane recovery gating; no audio or device access."""
import math
class FrontRecoveryGate:
    def __init__(self,grace=6.0,state_max_age=6.0):
        if grace<5:raise ValueError('Must allow OwnTone its existing5s recovery window')
        self.grace=grace;self.state_max_age=state_max_age;self.missing_since=None
    def ready(self,*,now,healthy,playback_state,observed_at):
        if not all(math.isfinite(x) for x in [now,observed_at]):return False
        if healthy:
            self.missing_since=None;return False
        if self.missing_since is None or now<self.missing_since:self.missing_since=now
        fresh=0<=now-observed_at<=self.state_max_age
        return (fresh and playback_state=='Playing' and now-self.missing_since>=self.grace)
