# SPDX-License-Identifier: GPL-2.0-or-later
# Public packaging: device identities moved to site settings, 2026-10-23.
"""Propagate explicit source Pause to native output cancellation, never retime PCM."""
import errno,json,os,pathlib,stat,time
from pause_ack import Acknowledgements
from pause_bridge_headers import Headers
FLUSH=b'<item><type>73736e63</type><code>70666c73</code><length>0</length></item>\n'
from site_config import front_output_ids
EXPECTED=front_output_ids()
class PauseCancel:
 def __init__(self,front_fifo,runtime='/run/homeambient-plan-b',source='/tmp/shairport-sync-metadata',log='/var/lib/homeambient-plan-b/cache/owntone.log'):
  self.runtime=pathlib.Path(runtime);self.source=source;self.destination=front_fifo+'.metadata';self.log_path=pathlib.Path(log)
  self.reader=self.writer=self.log=None;self.headers=Headers();self.paused=False;self.gated=False;self.disabled=False
  self.pending=None;self.defer_until=None;self.next_check=0;self.next_read=0;self.generation=0
 def event(self,stage,**kw):print(json.dumps(dict(kind='pause_cancel',stage=stage,timestamp=time.time(),monotonic=time.monotonic(),**kw)),flush=True)
 def close(self):
  for f in [self.reader,self.writer]:
   if f is not None:os.close(f)
  if self.log:self.log.close()
  self.reader=self.writer=self.log=None;self.paused=self.gated=False;self.pending=None;self.disabled=True
 def enabled(self,now):
  try:
   trial=self.runtime/'pause-cancel-trial.json'
   if trial.exists():
    d=json.loads(trial.read_text())
    return d['version']==1 and d['enabled'] is True and 0<d['expires_monotonic']-now<=900
   d=json.loads(pathlib.Path('/opt/homeambient-plan-b/transport-control.json').read_text())
   return d.get('kind')=='pause-cancel-v1' and d.get('enabled') is True
  except (OSError,ValueError,KeyError,TypeError):return False
 def ready(self):
  try:
   d=json.loads((self.runtime/'session.json').read_text())
   return 0<=time.time()-d['timestamp']<3 and d['mode']=='surround' and d.get('fronts_selected')==2 and d.get('front_playing') is True
  except (OSError,ValueError,KeyError,TypeError):return False
 def transport(self,codes,now):
  codes=[c for c in codes if c in (b'paus',b'pres',b'prsm',b'pbeg',b'pend')]
  if not codes:return
  c=codes[-1]
  if c in (b'paus',b'pend'):
   if not self.paused:
    self.paused=True;self.defer_until=now+.06
    self.event('pause_seen')
  else:
   self.paused=False;self.defer_until=None
   if not self.pending:self.gated=False
   self.event('resume_seen',code=c.decode())
 def tick(self,rear,clear_pending,now):
  if self.pending:
   for _ in range(12):
    line=self.log.readline(2048)
    if not line:break
    if 'HA_PAUSE_FLUSH' in line:self.pending.feed(line)
   if self.pending.error or now>self.pending.deadline:
    self.event('failed',reason=self.pending.error or 'front_ack_timeout');self.close();return
   if self.pending.acknowledged:
    # Do not infer success from FIFO bytes: both native responses are required.
    clear_pending();rear.reset();self.generation+=1
    self.event('fronts_acknowledged_rear_reset',generation=self.generation,responses=self.pending.responses)
    self.pending=None;self.gated=self.paused
   return
  if self.defer_until is None or now<self.defer_until:return
  self.defer_until=None
  if not self.ready():self.event('pause_ignored_not_ready');return
  if self.writer is None or self.log is None:self.event('pause_ignored_no_reader');return
  self.log.seek(0,2)
  try:
   if os.write(self.writer,FLUSH)!=len(FLUSH):raise RuntimeError('partial flush write')
  except (OSError,RuntimeError) as e:self.event('failed',reason=type(e).__name__);self.close();return
  self.pending=Acknowledgements(EXPECTED,now,.5);self.gated=True
  clear_pending();self.event('flush_requested')
 def poll(self,rear,clear_pending):
  if self.disabled:return
  now=time.monotonic()
  try:
   if now>=self.next_check:
    self.next_check=now+.1
    if not self.enabled(now):self.event('disabled');self.close();return
   if self.reader is None:
    if not stat.S_ISFIFO(os.stat(self.source).st_mode):raise RuntimeError('source not FIFO')
    self.reader=os.open(self.source,os.O_RDONLY|os.O_NONBLOCK)
   if self.writer is None:
    try:
     if not stat.S_ISFIFO(os.stat(self.destination).st_mode):raise RuntimeError('destination not FIFO')
     self.writer=os.open(self.destination,os.O_WRONLY|os.O_NONBLOCK);self.log=self.log_path.open()
     self.log.seek(0,2);self.event('attached')
    except OSError as e:
     if e.errno not in (errno.ENXIO,errno.ENOENT):raise
   if now>=self.next_read:
    self.next_read=now+.01;codes=[]
    for _ in range(4):
     try:b=os.read(self.reader,8192)
     except BlockingIOError:break
     if not b:break
     codes.extend(self.headers.feed(b))
    self.transport(codes,now)
   self.tick(rear,clear_pending,now)
  except Exception as e:self.event('failed',reason=type(e).__name__);self.close()
