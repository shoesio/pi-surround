# SPDX-License-Identifier: GPL-2.0-or-later
# Public packaging: device identities moved to site settings, 2026-10-23.
"""Output-volume experiment. Importing this module never contacts a device.

The mixer stays at a fixed, explicit reference command. Output controls can
only attenuate its resulting PCM. This preserves that reference mix, including
its nonlinear limiter, rather than pretending gain commutes with the mixer.
OwnTone's integer volume is a protocol setting, not an acoustic calibration.
Native HomePod/system gain is deliberately outside this experiment.
"""
from dataclasses import dataclass
import math
import numpy as np


def master_gain(command):
    """The currently installed router curve, unchanged."""
    if not math.isfinite(command):
        raise ValueError('Non-finite command')
    if command <= -100:
        return 0.0
    normalized = (max(-30., min(0., command)) + 30.) / 30.
    return normalized * normalized


@dataclass(frozen=True)
class Plan:
    requested_gain: float
    output_gain: float
    owntone_percent: int
    limited: bool
    reason: str


class AttenuationTrial:
    def __init__(self, reference_db):
        if not math.isfinite(reference_db) or not -30 < reference_db <= 0:
            raise ValueError('A finite, audible reference command is required')
        self.reference_db = reference_db
        self.reference_gain = master_gain(reference_db)

    def plan(self, command):
        requested = master_gain(command) / self.reference_gain
        # Avoid the unverified receiver mute behaviour at percent zero. This
        # is a restricted experiment, not a replacement for the mute control.
        floor = 10 ** (-29.7 / 20)
        bounded = max(floor, min(1., requested))
        percentage = max(1, min(100, round((20 * math.log10(bounded) + 30) / .3)))
        gain = 10 ** ((-30 + .3 * percentage) / 20)
        limited = requested < floor or requested > 1
        reason = 'below_test_range' if requested < floor else ('above_reference' if requested > 1 else 'within_test_range')
        return Plan(requested, gain, percentage, limited, reason)


class RenderAttenuator:
    """Apply gain to already dequeued stereo PCM; never touch queue state."""
    def __init__(self, frames=480):
        if not isinstance(frames, int) or frames < 1:
            raise ValueError('Positive ramp length required')
        self.frames = frames
        self.current = self.target = 1.
        self.remaining = 0

    def set_gain(self, gain):
        if not math.isfinite(gain) or not 0 <= gain <= 1:
            raise ValueError('Only finite attenuation is allowed')
        if gain != self.target:
            self.target = gain
            self.remaining = self.frames

    def apply(self, pcm):
        if len(pcm) % 4:
            raise ValueError('Incomplete stereo frame')
        if not pcm or (self.current == self.target == 1):
            return pcm
        samples = np.frombuffer(pcm, dtype='<i2').reshape(-1, 2)
        gains = np.full(len(samples), self.target, dtype=np.float64)
        n = min(len(samples), self.remaining)
        if n:
            step = (self.target - self.current) / self.remaining
            gains[:n] = self.current + step * np.arange(1, n + 1)
            self.current = float(gains[n - 1])
            self.remaining -= n
        if not self.remaining:
            self.current = self.target
        return np.rint(samples * gains[:, None]).astype('<i2').tobytes()


class OutputCoordinator:
    """One owner for a trial's two front stream controls and rear render gain.

    The injected API must implement OwnTone GET outputs and PUT outputs/<id>.
    This is not an atomic operation across network devices. Readbacks confirm
    control state only. Failed writes trigger best-effort rollback and latch
    a fault; they never start playback, select outputs or retry indefinitely.
    """
    def __init__(self, trial, api, front_ids, rear, *, independent_stream_verified=False):
        self.independent_stream_verified = independent_stream_verified is True
        self.trial, self.api, self.rear = trial, api, rear
        self.front_ids = frozenset(front_ids)
        if len(self.front_ids) != 2:
            raise ValueError('Exactly the two front output IDs are required')
        self.last_percent = 100
        self.fault = None

    def _verify(self, percent):
        outputs = self.api('outputs')['outputs']
        selected = {str(o['id']) for o in outputs if o.get('selected')}
        if selected != self.front_ids:
            raise RuntimeError('Output membership changed')
        by_id = {str(o['id']): o for o in outputs}
        if any(by_id[i].get('volume') != percent for i in self.front_ids):
            raise RuntimeError('Front control readback mismatch')

    def apply(self, command):
        if not self.independent_stream_verified:
            raise RuntimeError("Independent stream gain is unverified; native coupling requires a different gain model")
        if self.fault:
            raise RuntimeError('Trial fault is latched: ' + self.fault)
        plan = self.trial.plan(command)
        # Unsupported requests are rejected without writes, not silently
        # clamped. A production design must implement full-range/mute first.
        if plan.limited:
            raise ValueError(plan.reason)
        self._verify(self.last_percent)
        if plan.owntone_percent == self.last_percent:
            return plan
        previous = self.last_percent
        try:
            for output in sorted(self.front_ids):
                self.api('outputs/' + output, {'volume': plan.owntone_percent})
            self._verify(plan.owntone_percent)
        except Exception as error:
            failures = []
            for output in sorted(self.front_ids):
                try:
                    self.api('outputs/' + output, {'volume': previous})
                except Exception as rollback_error:
                    failures.append(type(rollback_error).__name__)
            try:
                self._verify(previous)
            except Exception as verify_error:
                failures.append(type(verify_error).__name__)
            self.fault = type(error).__name__ + '; rollback=' + (','.join(failures) or 'readback_verified')
            raise RuntimeError(self.fault) from error
        self.rear.set_gain(plan.output_gain)
        self.last_percent = plan.owntone_percent
        return plan
