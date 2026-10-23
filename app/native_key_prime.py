# SPDX-License-Identifier: GPL-2.0-or-later
# Public packaging: device identities moved to site settings, 2026-10-23.
"""Exercise the global volume-key path before selecting OwnTone fronts.
This is route/control priming, never proof of a volume acknowledgement.
"""
import asyncio,math
async def prime_key(atv,*,read_command,read_identity,owns_route,fronts_selected,set_command,trace,sleep=asyncio.sleep):
 original=float(read_command())
 if not math.isfinite(original) or not -26.25<=original<=0:raise RuntimeError('Key prime requires non-mute tested level')
 before=await asyncio.wait_for(atv.metadata.playing(),4)
 async def valid():
  now=await asyncio.wait_for(atv.metadata.playing(),4)
  state=now.device_state.name
  return owns_route() and not fronts_selected() and now.title==before.title and (state=='Paused' or state in ('Idle','Stopped') and not now.title)
 if not await valid():raise RuntimeError('Key prime requires paused/idle owned route with unselected fronts')
 trace('native_key_prime_begin')
 await asyncio.wait_for(atv.remote_control.volume_down(),4)
 await sleep(1.)
 if not await valid():raise RuntimeError('Key prime context changed')
 observed=float(read_command())
 if not any(abs(observed-x)<2e-6 for x in [original,original-1.875]):raise RuntimeError('Unexpected command during key prime; do not restore')
 # A key may initialize the native control path without publishing a hook.
 # The subsequent seed stage independently proves the selected Pi level.
 if abs(observed-original)>2e-6:
  identity=read_identity()
  try:await asyncio.wait_for(set_command(original),5)
  except asyncio.TimeoutError:pass
  for _ in range(25):
   value=float(read_command())
   if not any(abs(value-x)<2e-6 for x in [observed,original]):raise RuntimeError('External command during key restoration')
   if read_identity()!=identity and abs(value-original)<2e-6:
    if not await valid():raise RuntimeError('Key prime context changed after restore')
    break
   await sleep(.1)
  else:raise RuntimeError('Key prime previous level not confirmed')
 trace('native_key_prime_completed',hook_changed=abs(observed-original)>2e-6)
