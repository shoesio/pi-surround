# SPDX-License-Identifier: GPL-2.0-or-later
# Public packaging: device identities moved to site settings, 2026-10-23.
"""Verify a new receiver session despite sender deduplication of equal volumes."""
import asyncio,math

async def seed(atv,*,read_command,read_identity,owns_route,fronts_selected,set_command,trace,sleep=asyncio.sleep):
    original=float(read_command())
    if not math.isfinite(original) or not -26.25<=original<=0:
        raise RuntimeError('Native seed requires a tested non-mute command')
    before=await asyncio.wait_for(atv.metadata.playing(),4)
    state=before.device_state.name
    def permitted(now):
        if state=='Paused':return now.device_state.name=='Paused' and now.title==before.title
        return state in ('Idle','Stopped') and not before.title and now.device_state.name in ('Idle','Stopped') and not now.title
    async def same_context():
        now=await asyncio.wait_for(atv.metadata.playing(),4)
        return owns_route() and not fronts_selected() and permitted(now)
    if not await same_context():raise RuntimeError('Native seed requires paused/idle owned route and no front selection')
    async def write_and_confirm(target,allowed):
        if not await same_context():raise RuntimeError('Native seed context changed')
        current=float(read_command())
        if not math.isfinite(current) or not any(abs(current-x)<2e-6 for x in allowed):
            raise RuntimeError('External source volume changed; no retry')
        identity=read_identity()
        try:await asyncio.wait_for(set_command(target),5)
        except asyncio.TimeoutError:pass # Actual hook, not MRP completion, is evidence.
        for _ in range(25):
            value=float(read_command())
            if not math.isfinite(value) or not any(abs(value-x)<2e-6 for x in [*allowed,target]):
                raise RuntimeError('External source volume changed; no retry')
            if read_identity()!=identity and abs(value-target)<2e-6:
                if not await same_context():raise RuntimeError('Native seed context changed')
                return True
            await sleep(.1)
        return False
    # An equal-value command can be suppressed by Apple TV. At most two
    # distinct quieter values handle an unknown sender cache without increasing
    # programme loudness or selecting a HomePod. Restore only our confirmed value.
    targets=[max(-30.,original-1.875),max(-30.,original-3.75)]
    trace('native_seed_begin',source_command=original)
    for target in dict.fromkeys(targets):
        if not await write_and_confirm(target,[original]):continue
        trace('native_seed_quieter_verified',source_command=target)
        if not await write_and_confirm(original,[target]):
            raise RuntimeError('Native seed original level restoration not confirmed')
        trace('native_seed_verified',source_command=original)
        return
    raise RuntimeError('No fresh quieter sender command; do not select fronts')

def hook_is_current(path,source_started_monotonic,command):
    """A matching real hook since this receiver start avoids any extra write."""
    import json,pathlib
    start=float(source_started_monotonic)
    if not math.isfinite(start) or start<=0:return False
    for candidate in (pathlib.Path(path),pathlib.Path(str(path)+'.1')):
        try:
            with candidate.open('rb') as stream:
                stream.seek(0,2);length=stream.tell();stream.seek(max(0,length-16384))
                lines=stream.read().splitlines()
            for raw in reversed(lines):
                try:event=json.loads(raw);stamp=float(event['monotonic']);value=float(event['command'])
                except (ValueError,KeyError,TypeError):continue
                if math.isfinite(stamp) and math.isfinite(value):
                    return stamp>=start and abs(value-float(command))<2e-6
        except OSError:continue
    return False
