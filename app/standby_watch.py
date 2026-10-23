# SPDX-License-Identifier: GPL-2.0-or-later
# Public packaging: device identities moved to site settings, 2026-10-23.
"""Observe Apple TV selection; activate only after explicit receiver selection."""
import asyncio,json,math,subprocess,time
from pathlib import Path
from pyatv.const import DeviceState
from handover_policy import snapshot
from wired_session import connect,owner_allowed,ROOT,RUNTIME
UNIT='homeambient-planb-session.service'
async def watch():
 router=json.loads((ROOT/'settings.json').read_text())['router_id']
 while True:
  atv=None
  try:
   atv=await connect();last=None
   while True:
    playing=await asyncio.wait_for(atv.metadata.playing(),timeout=6)
    mode=RUNTIME/'programme-state.tmp'
    mode.write_text(json.dumps({'timestamp':time.time(),'ui_mode':playing.device_state==DeviceState.Idle and not playing.title}))
    mode.replace(RUNTIME/'programme-state.json')
    outputs=[d.identifier for d in atv.audio.output_devices]
    active=subprocess.run(['systemctl','is-active','--quiet',UNIT]).returncode==0
    selected=router in outputs
    if outputs and router not in outputs and not active:
     try:
      volume=float(atv.audio.volume)
      if not math.isfinite(volume) or not 0<=volume<=100:volume=None
     except (ValueError,TypeError,NotImplementedError):volume=None
     tmp=RUNTIME/'standby-normal-output.tmp'
     tmp.write_text(json.dumps({'outputs':outputs,'volume':volume,'playback':snapshot(playing)}));tmp.replace(RUNTIME/'standby-normal-output.json')
    if selected and last!=tuple(outputs) and not active:
     if (RUNTIME/'standby-normal-output.json').exists():
      normal=json.loads((RUNTIME/'standby-normal-output.json').read_text())
      normal['handover']={'router':router,'observed_at':time.monotonic()}
      tmp=RUNTIME/'standby-normal-output.tmp'
      tmp.write_text(json.dumps(normal));tmp.replace(RUNTIME/'standby-normal-output.json')
      subprocess.run(['systemctl','start',UNIT],check=True,timeout=15)
     else:print('No previous normal output snapshot; refusing automatic activation',flush=True)
    last=tuple(outputs)
    await asyncio.sleep(1)
  except Exception as e:
   print(type(e).__name__+': '+str(e),flush=True)
   await asyncio.sleep(5)
  finally:
   if atv:
    tasks=atv.close()
    if tasks:await asyncio.gather(*tasks,return_exceptions=True)
asyncio.run(watch())
