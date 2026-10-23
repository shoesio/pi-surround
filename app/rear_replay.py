# SPDX-License-Identifier: GPL-2.0-or-later
# Public packaging: device identities moved to site settings, 2026-10-23.
"""One-shot bounded diagnostic replay at the final PCM boundary."""
import json,pathlib,time,wave
REQUEST=pathlib.Path('/run/homeambient-plan-b/rear-replay-request.json')
AUDIO=pathlib.Path('/run/homeambient-plan-b/diagnostic-aba.wav')
class Replay:
 def __init__(self,pcm):
  if not pcm or len(pcm)%4 or len(pcm)>60*48000*4:raise ValueError('Bounded complete stereo PCM required')
  self.pcm=pcm;self.cursor=0;self.started=None;self.done=False;self.next_check=0
 def apply(self,original):
  if self.done:return original
  now=time.monotonic()
  if now>=self.next_check:
   self.next_check=now+.25
   if not REQUEST.exists():self.done=True;return original
  if self.started is None:self.started=time.time()
  n=min(len(original),len(self.pcm)-self.cursor);result=self.pcm[self.cursor:self.cursor+n];self.cursor+=n
  if self.cursor==len(self.pcm):self.done=True
  return result+bytes(len(original)-n)
 def status(self):return dict(frames=self.cursor//4,total_frames=len(self.pcm)//4,started_timestamp=self.started,done=self.done)
def from_request():
 try:
  d=json.loads(REQUEST.read_text());age=time.time()-float(d['timestamp'])
  if not 0<=age<120:return None
  with wave.open(str(AUDIO))as w:
   if (w.getnchannels(),w.getsampwidth(),w.getframerate())!=(2,2,48000)or w.getnframes()>60*48000:raise ValueError('Unexpected diagnostic format')
   pcm=w.readframes(w.getnframes())
  return Replay(pcm)
 except FileNotFoundError:return None
 except Exception as e:print(json.dumps(dict(kind='rear_replay_unavailable',reason=str(e))),flush=True);return None
