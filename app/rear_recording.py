# SPDX-License-Identifier: GPL-2.0-or-later
# Public packaging: device identities moved to site settings, 2026-10-23.
"""Bounded diagnostic PCM tap. Never opens an audio device or blocks its caller."""
import json,os,pathlib,queue,threading,time,wave
REQUEST=pathlib.Path('/run/homeambient-plan-b/rear-recording-request.json')
class Recorder:
 def __init__(self,directory,seconds=60):
  if not 1<=seconds<=90:raise ValueError('Recording must be 1..90 seconds')
  self.directory=pathlib.Path(directory);self.directory.mkdir(exist_ok=False)
  self.seconds=seconds;self.max_frames=round(seconds*48000)
  self.pending=queue.Queue(maxsize=128);self.stopped=threading.Event();self.started=None
  self.offered_frames=0;self.lost_frames=0;self.written_frames=0;self.error=None
  self.done=threading.Event();self.thread=threading.Thread(target=self.run,name='rear-recording',daemon=True)
  self.thread.start()
 def offer(self,pcm,gain,xruns):
  if self.stopped.is_set():return
  now=time.monotonic()
  if self.started is None:self.started=now
  if now-self.started>=self.seconds or self.offered_frames>=self.max_frames:
   self.stopped.set();return
  available=min(len(pcm)//4,self.max_frames-self.offered_frames)
  if not available:return
  self.offered_frames+=available
  # Immutable data already rendered and submitted by the audio worker.
  row=dict(timestamp=time.time(),monotonic=now,frames=available,gain=gain,alsa_xruns=xruns,
           stream_frame=self.offered_frames-available,lost_frames=self.lost_frames)
  try:self.pending.put_nowait((pcm[:available*4],row))
  except queue.Full:self.lost_frames+=available
 def close(self):
  self.stopped.set()
  # Called only during shutdown/test, never from the audio-write path.
  self.thread.join(timeout=2)
 def run(self):
  try:
   try:os.setpriority(os.PRIO_PROCESS,threading.get_native_id(),15)
   except (OSError,AttributeError):pass
   with wave.open(str(self.directory/'rear.wav'),'wb') as audio,(self.directory/'index.jsonl').open('w') as index:
    audio.setnchannels(2);audio.setsampwidth(2);audio.setframerate(48000)
    while not self.stopped.is_set() or not self.pending.empty():
     try:pcm,row=self.pending.get(timeout=.1)
     except queue.Empty:
      if self.started is not None and time.monotonic()-self.started>=self.seconds:self.stopped.set()
      continue
     row['recording_frame']=self.written_frames
     audio.writeframesraw(pcm);index.write(json.dumps(row)+'\n');self.written_frames+=len(pcm)//4
  except Exception as e:
   self.error=type(e).__name__+': '+str(e);self.stopped.set()
  finally:
   result=dict(frames=self.written_frames,seconds=self.written_frames/48000,
               offered_frames=self.offered_frames,lost_frames=self.lost_frames,error=self.error,
               started_monotonic=self.started,finished_timestamp=time.time(),
               scope='Final post-queue/post-gain PCM after output-write completion; not analogue or acoustic capture. Index timestamps are write-completion observations, not exact presentation times. Gaps/recovery may not be represented as silence in the concatenated WAV.')
   try:(self.directory/'manifest.json').write_text(json.dumps(result,indent=2)+'\n')
   except OSError:pass
   print(json.dumps(dict(kind='rear_recording_completed',directory=str(self.directory),**result)),flush=True)
   self.done.set()
def from_request():
 try:
  d=json.loads(REQUEST.read_text())
  if not 0<=time.time()-float(d['timestamp'])<120:return None
  identifier=d['id']
  if not identifier.isdecimal():raise ValueError('Numeric recording identifier required')
  return Recorder(REQUEST.parent/('rear-capture-'+identifier),float(d.get('seconds',60)))
 except FileNotFoundError:return None
 except Exception as e:
  print(json.dumps(dict(kind='rear_recording_unavailable',reason=type(e).__name__+': '+str(e))),flush=True);return None
