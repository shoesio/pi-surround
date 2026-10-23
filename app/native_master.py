# SPDX-License-Identifier: GPL-2.0-or-later
# Public packaging: device identities moved to site settings, 2026-10-23.
"""Native HomePod cluster is volume authority. No playback/routing operations."""
import asyncio,json,math,os,pathlib,time
ROOT=pathlib.Path('/opt/homeambient-plan-b');RT=pathlib.Path('/run/homeambient-plan-b');MODE=ROOT/'native-master.json'
from site_config import front_output_ids, native_homepod_ids
POD_IDS=native_homepod_ids()
def enabled():
 try:
  d=json.loads(MODE.read_text());return d.get('kind')=='native-master-v1' and d.get('enabled') is True and (d.get('expires') is None or time.time()<float(d['expires']))
 except (OSError,ValueError,TypeError):return False
def fraction(command):
 q=float(command)
 if not math.isfinite(q) or not (q==-144 or -30<=q<=0):raise ValueError('Invalid sender volume')
 return 0. if q==-144 else (q+30)/30

def rear_gain(master):return 0. if master<=0 else 10**(-30*(1-master)/20)

def front_volume(master,level):return max(0.,min(1.,master-(100-level)/100))

class SourceChanged(RuntimeError):pass

class Policy:
 """Native changes win over simultaneous source echoes; no nonlinear remap."""
 def __init__(self,native,command,level=100,grace=.12):
  self.grace=grace
  self.native=native;self.level=level;self.master=fraction(command) if level==0 else min(1.,native+(100-level)/100)
  self.command=float(command);self.pending=None;self.since=None
 def observe(self,native,command,now,level=None):
  command=float(command);fraction(command)
  if level is not None and level!=self.level:
   self.level=level;self.pending=None;return ('native',front_volume(self.master,level))
  changed=abs(native-self.native)>.005
  if changed:
   self.native=native
   if self.level>0:self.master=min(1.,native+(100-self.level)/100)
   self.command=command;self.pending=None
   return ('source',self.master) if abs(fraction(command)-self.master)>.005 else None
  if abs(command-self.command)>.00001:
   self.command=command
   if self.pending is None:self.since=now
   self.pending=fraction(command)
  if self.pending is not None and now-self.since>=self.grace:
   self.master=self.pending;self.pending=None
   target=front_volume(self.master,self.level)
   return ('native',target) if abs(target-native)>.001 else None
  return None
 def confirmed(self,native,command):
  self.native=native;self.command=float(command);self.pending=None

class NativeController:
 def __init__(self,atv,homepod,router,trace):
  self.atv=atv;self.homepod=homepod;self.router=router;self.trace=trace
  from volume_api import VolumeAPI
  self.front_ids=front_output_ids();self.stream_api=VolumeAPI(self.front_ids);self.last_stream_check=0.
  self.failures=0;self.last_reconnect=0.;self.audio=None;self.policy=None;self.error=None;self.hold_reason=None;self.task=None;self.gain_task=None
  self.command_path=pathlib.Path('/run/homeambient-volume/airplay-db');self.owned=False;self.observed=0.;self.current_gain=0.;self.last_ok=0.;self.last_event=None
 @classmethod
 async def prepare(cls,atv,router,trace):
  import pyatv
  from pyatv.const import Protocol
  configs=await pyatv.scan(asyncio.get_running_loop(),timeout=5)
  pods=[x for x in configs if str(x.identifier).upper() in POD_IDS]
  if not pods:raise RuntimeError('Known front HomePod not discovered')
  h=await asyncio.wait_for(pyatv.connect(pods[0],asyncio.get_running_loop(),protocol=Protocol.AirPlay),12)
  c=cls(atv,h,router,trace)
  try:
   c.audio=h.audio.get(Protocol.MRP)
   if c.audio is None:raise RuntimeError('Native volume control unavailable')
   native=await c.read_native();settings=json.loads((ROOT/'settings.json').read_text());level=settings['front_level']
   if isinstance(level,bool) or not isinstance(level,int) or not 0<=level<=100:raise ValueError('Invalid saved front level')
   c.initial_percent=round(native*100);c.initial_native=c.initial_percent/100
   c.policy=Policy(c.initial_native,c.command_path.read_text(),level,grace=0)
   trace('native_master_snapshot',native_percent=c.initial_percent)
   return c
  except BaseException:
   from control_link import close_control
   await close_control(h);raise
 async def reconnect(self):
  import pyatv
  from pyatv.const import Protocol
  from control_link import close_control
  configs=await pyatv.scan(asyncio.get_running_loop(),timeout=5)
  pods=[x for x in configs if str(x.identifier).upper() in POD_IDS]
  if not pods:raise RuntimeError('Native HomePod discovery unavailable')
  new=await asyncio.wait_for(pyatv.connect(pods[0],asyncio.get_running_loop(),protocol=Protocol.AirPlay),10)
  old=self.homepod;self.homepod=new;self.audio=new.audio.get(Protocol.MRP)
  await close_control(old)
 async def read_native(self):
  from pyatv.protocols.mrp import protobuf,messages
  m=messages.create(protobuf.GET_VOLUME_MESSAGE);protobuf.extract_inner(m).outputDeviceUID=self.audio.device_uid
  r=await asyncio.wait_for(self.audio.protocol.send_and_receive(m),2)
  b=protobuf.extract_inner(r)
  if r.errorCode or not b.HasField('volume') or not math.isfinite(b.volume) or not 0<=b.volume<=1:raise RuntimeError('Native volume readback invalid')
  return float(b.volume)
 async def write_source(self,master,expected_command=None):
  from pyatv.const import Protocol
  from pyatv.interface import OutputDevice
  baseline=float(self.command_path.read_text()) if expected_command is None else float(expected_command)
  target=master*30-30
  companion=self.atv.audio.get(Protocol.Companion)
  mrp=self.atv.audio.get(Protocol.MRP)
  writers=[]
  if companion:writers.append(lambda:companion.set_volume(master*100))
  if mrp:writers.append(lambda:mrp.set_volume(master*100,OutputDevice(self.router,volume=-1)))
  for write in writers:
   current=float(self.command_path.read_text())
   if abs(current-target)<.15:return current
   if expected_command is not None and abs(current-baseline)>.00001:raise SourceChanged("New source command during native echo")
   task=asyncio.create_task(write())
   try:
    for _ in range(20):
     await asyncio.sleep(.05)
     current=float(self.command_path.read_text())
     if abs(current-target)<.15:return current
     if expected_command is not None and abs(current-baseline)>.00001:raise SourceChanged('New source command during native echo')
   finally:
    if not task.done():task.cancel()
    await asyncio.gather(task,return_exceptions=True)
  raise RuntimeError('Selected Pi volume not confirmed')
 async def seed(self):
  # Front sessions are still unselected. Prove a distinct real command first.
  async def valid():
   p=await asyncio.wait_for(self.atv.metadata.playing(),3)
   owned={d.identifier for d in self.atv.audio.output_devices}=={self.router}
   paused=p.device_state.name in ('Paused','Idle','Stopped')
   self.trace('native_seed_checkpoint',playback_state=p.device_state.name,owns_route=owned,eligible=owned and paused)
   return owned and paused
  if not await valid():raise RuntimeError('Native seed requires paused/idle Pi-only route')
  # Initialise Apple's physical-key context before OwnTone owns the fronts.
  # Never assume a particular relative step; seed the observed original level.
  await asyncio.wait_for(self.atv.remote_control.volume_down(),3)
  await asyncio.sleep(.5)
  if not await valid():raise RuntimeError('Route changed during native key initialization')
  target=self.policy.master
  if target>0:
   await self.write_source(max(0,target-.0625))
  if not await valid():raise RuntimeError("Programme changed during native seed")
  await self.write_source(target)
  self.policy.confirmed(self.initial_native,self.command_path.read_text())
 async def sync_streams(self,target):
  percent=max(0,min(100,round(target*100)))
  outputs=(await asyncio.to_thread(self.stream_api,'outputs'))['outputs']
  if {str(o['id']) for o in outputs if o.get('selected')}!=self.front_ids:
   raise RuntimeError('Front streams not ready for volume relay')
  current={str(o['id']):o['volume'] for o in outputs}
  changed=[]
  for device in sorted(self.front_ids):
   if current[device]!=percent:
    await asyncio.to_thread(self.stream_api,'outputs/'+device,{'volume':percent});changed.append(device)
  self.last_stream_check=time.monotonic()
  if changed:self.trace('native_master_streams_mirrored',percent=percent,count=len(changed))
 async def write_native(self,target):
  # OwnTone's volume operation reaches both its PCM stream and native master.
  # Direct native-only writes leave the preview/movie stream gain stale.
  await self.sync_streams(target)
  expected=round(target*100)/100
  for _ in range(10):
   value=await self.read_native()
   if abs(value-expected)<=.01:return value
   await asyncio.sleep(.05)
  raise RuntimeError('Native volume write not confirmed')
 def observe_route(self,owned):self.owned=bool(owned);self.observed=time.monotonic()
 def set_gain(self,gain):
  self.current_gain=gain;path=RT/'coupled-rear-gain.json';tmp=path.with_suffix('.native-tmp')
  tmp.write_text(json.dumps(dict(gain=gain,timestamp=time.time())));tmp.chmod(0o644);os.replace(tmp,path)
 async def refresh_gain(self):
  # Native read/write latency must not expire the independent rear instruction.
  # Only publish the already-applied level: this task never raises the volume.
  while True:
   gain=self.current_gain
   if not self.owned or time.monotonic()-self.observed>3:
    gain=0.
   else:
    try:
     if fraction(self.command_path.read_text())==0:gain=0.
    except (OSError,ValueError):gain=0.
   self.set_gain(gain)
   await asyncio.sleep(.1)
 def start(self):
  self.gain_task=asyncio.create_task(self.refresh_gain())
  self.task=asyncio.create_task(self.run())
 def stop(self):
  if self.gain_task:self.gain_task.cancel()
  if self.task:self.task.cancel()
  else:asyncio.create_task(self.close())
  self.set_gain(0.)
 async def close(self):
  from control_link import close_control
  self.stream_api.close()
  await close_control(self.homepod)
 async def run(self):
  try:
   while True:
    checkpoint=(self.policy.native,self.policy.command,self.policy.master,self.policy.level)
    try:
     if not self.owned or time.monotonic()-self.observed>3:self.set_gain(0.);await asyncio.sleep(.2);continue
     value=await self.read_native();command=float(self.command_path.read_text());settings=json.loads((ROOT/'settings.json').read_text());level=settings['front_level']
     if isinstance(level,bool) or not isinstance(level,int) or not 0<=level<=100:raise ValueError('Invalid saved front level')
     previous_master=self.policy.master
     action=self.policy.observe(value,command,time.monotonic(),level)
     if action and enabled():
      kind,target=action
      self.trace('native_master_relay',destination=kind,percent=round(target*100,2))
      if kind=='native':value=await self.write_native(target)
      else:
       await self.sync_streams(value)
       value=await self.read_native()
       self.set_gain(rear_gain(self.policy.master))
       try:command=await self.write_source(min(1.,value+(100-level)/100) if level else target,command)
       except SourceChanged:
        self.trace('native_master_source_superseded')
      # Acknowledge only the input actually processed, never a newer key.
      self.policy.confirmed(value,command)
     if enabled() and time.monotonic()-self.last_stream_check>1:
      await self.sync_streams(value)
     if action and not enabled():
      self.policy.master=min(1.,value+(100-level)/100) if level else previous_master
      self.policy.confirmed(value,command)
     self.failures=0;self.last_ok=time.monotonic();self.hold_reason=None;self.error=None
     self.set_gain(rear_gain(self.policy.master))
     state=dict(timestamp=time.time(),native_percent=value*100,master_percent=self.policy.master*100,pi_command=float(self.command_path.read_text()),gain=self.current_gain,active_writes=enabled())
     tmp=RT/'native-master.tmp';tmp.write_text(json.dumps(state));tmp.replace(RT/'native-master.json')
    except Exception as e:
     self.failures+=1
     self.hold_reason=type(e).__name__+': '+str(e)
     if self.hold_reason!=self.last_event:self.trace('native_master_hold',reason=self.hold_reason);self.last_event=self.hold_reason
     # An unacknowledged key remains pending; retry it after transport recovery.
     # Otherwise a transient API failure consumes the command permanently.
     self.policy.native,self.policy.command,self.policy.master,self.policy.level=checkpoint
     self.policy.pending=None
     if not self.owned or time.monotonic()-self.observed>3 or fraction(self.command_path.read_text())==0:self.set_gain(0.)
     else:self.set_gain(self.current_gain)
     if self.failures>=3 and time.monotonic()-self.last_reconnect>10:
      self.last_reconnect=time.monotonic()
      try:
       if self.stream_api.failed:
        from volume_api import VolumeAPI
        self.stream_api.close();self.stream_api=VolumeAPI(self.front_ids)
       await self.reconnect()
      except Exception:pass
    await asyncio.sleep(.08)
  finally:
   if self.gain_task:
    self.gain_task.cancel()
    await asyncio.gather(self.gain_task,return_exceptions=True)
   self.set_gain(0.)
   await self.close()
