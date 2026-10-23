# SPDX-License-Identifier: GPL-2.0-or-later
# Public packaging: device identities moved to site settings, 2026-10-23.
"""One-shot startup resume policy, with no device access of its own."""
import time

def snapshot(playing):
    title=getattr(playing,'title',None)
    if not title:return None
    return {'state':playing.device_state.name,
            'identity':(title,getattr(playing,'series_name',None),getattr(playing,'season_number',None),
                        getattr(playing,'episode_number',None),getattr(playing,'total_time',None)),
            'position':getattr(playing,'position',None),'observed_at':time.monotonic()}

def should_resume(before,current,*,owns_route,elapsed,front_elapsed,already_attempted=False):
    return bool(before and current and not already_attempted and owns_route
                and before['state']=='Playing' and current['state']=='Paused'
                and before['identity']==current['identity']
                and 0<=elapsed<=45 and 0<=front_elapsed<=12)

async def resume_after_handover(atv,before,router,*,began,front_began,owner_check,trace):
    import asyncio
    if not before or before['state']!='Playing':
        trace('handover_resume_skipped',reason='not_previously_playing')
        return 'not_previously_playing'
    try:
        def eligible(current):
            return should_resume(before,current,
                owns_route=owner_check([d.identifier for d in atv.audio.output_devices],router),
                elapsed=time.monotonic()-began,front_elapsed=time.monotonic()-front_began)
        current=snapshot(await asyncio.wait_for(atv.metadata.playing(),timeout=3))
        if not eligible(current):
            trace('handover_resume_skipped',reason='guard_not_met');return 'guard_not_met'
        await asyncio.sleep(.75)
        current=snapshot(await asyncio.wait_for(atv.metadata.playing(),timeout=3))
        if not eligible(current):
            trace('handover_resume_skipped',reason='guard_changed');return 'guard_changed'
        trace('handover_resume_requested')
        await asyncio.wait_for(atv.remote_control.play(),timeout=4)
        confirmed=await asyncio.wait_for(atv.metadata.playing(),timeout=3)
        trace('handover_resume_sent',state=confirmed.device_state.name)
        return 'sent'
    except Exception as error:
        trace('handover_resume_unavailable',error_type=type(error).__name__)
        return 'unavailable'
