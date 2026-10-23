# SPDX-License-Identifier: GPL-2.0-or-later
# Public packaging: device identities moved to site settings, 2026-10-23.
"""Trial-only native-control comparison, before the front sender owns speakers."""
import asyncio,math

async def prime(atv,*,read_command,owns_route,fronts_selected,trace,sleep=asyncio.sleep):
    original=float(read_command())
    if not math.isfinite(original) or not -26.25<=original<=0:
        raise RuntimeError('Native prime requires a quiet non-mute command')
    before=await asyncio.wait_for(atv.metadata.playing(),4)
    # Idle Apple TV menus have no programme to pause or prime. The caller
    # already requires a fresh current-handover source-volume confirmation.
    if before.device_state.name in ('Idle','Stopped') and not before.title and owns_route() and not fronts_selected():
        trace('native_prime_skipped',reason='idle_without_programme')
        return
    if before.device_state.name!='Paused' or not owns_route() or fronts_selected():
        raise RuntimeError('Native prime requires paused owned route and no front selection')
    target=original-1.875;down_pending=False;restore_attempted=False
    async def same_context():
        now=await asyncio.wait_for(atv.metadata.playing(),4)
        return owns_route() and not fronts_selected() and now.title==before.title and now.device_state.name=='Paused'
    async def wait_value(value):
        for _ in range(25):
            if abs(float(read_command())-value)<1e-6:return
            await sleep(.1)
        raise RuntimeError('Native prime source command not confirmed')
    try:
        trace('native_prime_down_begin')
        down_pending=True
        await asyncio.wait_for(atv.remote_control.volume_down(),4)
        await wait_value(target)
        if not await same_context():raise RuntimeError('Native prime context changed')
        await sleep(.3)
        # Restore only this comparison's exact still-current command.
        if abs(float(read_command())-target)>1e-6:raise RuntimeError('External volume changed')
        restore_attempted=True
        await asyncio.wait_for(atv.remote_control.volume_up(),4)
        await wait_value(original);down_pending=False
        if not await same_context():raise RuntimeError('Native prime context changed')
        trace('native_prime_completed')
    finally:
        if down_pending and not restore_attempted and abs(float(read_command())-target)<1e-6 and await same_context():
            restore_attempted=True
            await asyncio.wait_for(atv.remote_control.volume_up(),4)
            await wait_value(original)
            trace('native_prime_restored_after_failure')
