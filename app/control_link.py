# SPDX-License-Identifier: GPL-2.0-or-later
# Public packaging: device identities moved to site settings, 2026-10-23.
"""Reconnect the Apple TV control connection without changing audio routing."""
import asyncio
from pyatv.exceptions import BlockedStateError

TRANSIENT=(BlockedStateError,ConnectionError,OSError,asyncio.TimeoutError)

async def close_control(atv):
    if atv is None:return
    try:
        tasks=atv.close()
        if tasks:await asyncio.wait_for(asyncio.gather(*tasks,return_exceptions=True),timeout=3)
    except Exception:pass

async def read_route(atv,connect,trace,*,probe=False):
    current=atv
    last_error=None
    try:
        for attempt in range(4):
            try:
                if current is None:
                    current=await asyncio.wait_for(connect(),timeout=8)
                if probe:await asyncio.wait_for(current.metadata.playing(),timeout=5)
                actual=[d.identifier for d in current.audio.output_devices]
                if attempt:trace('control_reconnected',attempt=attempt)
                return current,actual
            except TRANSIENT as error:
                last_error=error
                trace('control_unavailable',attempt=attempt,error_type=type(error).__name__)
                await close_control(current)
                current=None
                if attempt<3:await asyncio.sleep(.5)
        raise last_error
    except BaseException:
        if current is not atv:await close_control(current)
        raise
