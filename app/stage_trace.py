# SPDX-License-Identifier: GPL-2.0-or-later
# Public packaging: device identities moved to site settings, 2026-10-23.
"""Opt-in bounded PCM trace; audio callers only enqueue existing immutable bytes.

The low-priority worker owns request reads, file opens, writing and closing.
No playback controls, device APIs, gains, buffering or clocks are modified.
"""
import json
import math
import os
from pathlib import Path
import queue
import shutil
import threading
import time
import wave

RUNTIME = Path('/run/homeambient-plan-b')
REQUEST = RUNTIME/'stage-trace-request.json'
STORAGE = Path('/var/lib/homeambient-plan-b/diagnostics/pcm-traces')
CHANNELS = {'source':8, 'mixed':2, 'interpolated':2, 'render':2}

class StageTrace:
    def __init__(self, request=REQUEST, directory=STORAGE, capacity=128):
        self.request=Path(request);self.directory=Path(directory)
        self.pending=queue.Queue(maxsize=capacity)
        self.stopped=threading.Event();self.active=None;self.session=None
        self.seen=None;self.error=None;self.thread=None

    def start(self):
        self.thread=threading.Thread(target=self.run,name='rear-stage-trace',daemon=True)
        self.thread.start()

    def offer(self,stage,pcm,**metadata):
        """No file access, scans, PCM conversions or waiting for capacity."""
        active=self.active
        if active is None:return
        now=time.monotonic()
        if now>=active['deadline']:return
        if stage not in CHANNELS or not isinstance(pcm,bytes):return
        frames=len(pcm)//(2*CHANNELS[stage])
        if not frames or frames*2*CHANNELS[stage]!=len(pcm):return
        event=dict(stage=stage,timestamp=time.time(),monotonic=now,
                   frames=frames,**metadata)
        try:self.pending.put_nowait((active['id'],pcm,event))
        except queue.Full:active['lost_frames'][stage]+=frames

    def poll_request(self):
        try:
            data=json.loads(self.request.read_text())
            identifier=data['id'];seconds=data['seconds'];age=time.time()-data['timestamp']
            if (data.get('kind')!='rear-stage-trace-v1' or not isinstance(identifier,str)
                or not identifier.isdecimal() or len(identifier)>24
                or isinstance(seconds,bool) or not isinstance(seconds,(int,float))
                or not math.isfinite(seconds) or not 1<=seconds<=30
                or not 0<=age<120 or identifier==self.seen):return
        except (OSError,ValueError,KeyError,TypeError):return
        self.seen=identifier
        self.directory.mkdir(mode=0o700,parents=True,exist_ok=True)
        if RUNTIME.exists() and self.directory.stat().st_dev==RUNTIME.stat().st_dev:
            raise ValueError('PCM capture must not share the runtime filesystem')
        estimated=seconds*(48000*sum(CHANNELS.values())*2+250*2048)+65536
        required=max(128*1024*1024,math.ceil(2*estimated))
        if shutil.disk_usage(self.directory).free<required:
            raise OSError('Insufficient dedicated capture space; no PCM recording opened')
        path=self.directory/('stage-trace-'+identifier)
        path.mkdir(mode=0o700)
        files={};index=None
        try:
            for name,channels in CHANNELS.items():
                audio=wave.open(str(path/(name+'.wav')),'wb')
                audio.setnchannels(channels);audio.setsampwidth(2);audio.setframerate(48000)
                files[name]=audio
            index=(path/'index.jsonl').open('w')
        except BaseException:
            for audio in files.values():audio.close()
            if index:index.close()
            raise
        session=dict(id=identifier,directory=path,files=files,index=index,
                     frames={name:0 for name in CHANNELS},
                     max_frames=math.ceil(seconds*48000*1.01),
                     requested_seconds=seconds,started_timestamp=time.time(),events=0,
                     max_events=math.ceil(seconds*250*1.1))
        active=dict(id=identifier,deadline=time.monotonic()+seconds,
                    lost_frames={name:0 for name in CHANNELS})
        session['active']=active
        self.session=session;self.active=active

    def write_event(self,item):
        identifier,pcm,event=item;s=self.session
        if s is None or identifier!=s['id']:return
        stage=event['stage'];frames=event['frames']
        if s['frames'][stage]+frames>s['max_frames']:
            s['active']['lost_frames'][stage]+=frames
            return
        event['file_frame']=s['frames'][stage]
        encoded=json.dumps(event,separators=(',',':'))+'\n'
        if len(encoded)>8192 or s['events']>=s['max_events']:
            s['active']['lost_frames'][stage]+=frames
            return
        s['files'][stage].writeframesraw(pcm)
        s['index'].write(encoded)
        s['frames'][stage]+=frames;s['events']+=1

    def finish(self):
        s=self.session
        if s is None:return
        # Stop new offers before draining; late in-flight offers carry this id
        # and cannot be assigned to a later capture.
        self.active=None
        if self.error is None:
            while True:
                try:self.write_event(self.pending.get_nowait())
                except queue.Empty:break
                except Exception as error:
                    self.error=type(error).__name__+': '+str(error);break
        # An I/O error disables diagnostics; never keep retrying disk writes.
        while True:
            try:
                identifier,pcm,event=self.pending.get_nowait()
                s['active']['lost_frames'][event['stage']]+=event['frames']
            except queue.Empty:break
        for audio in s['files'].values():
            try:audio.close()
            except Exception as error:
                if self.error is None:self.error=type(error).__name__+': '+str(error)
        try:s['index'].close()
        except Exception as error:
            if self.error is None:self.error=type(error).__name__+': '+str(error)
        manifest=dict(id=s['id'],requested_seconds=s['requested_seconds'],
            started_timestamp=s['started_timestamp'],finished_timestamp=time.time(),
            frames=s['frames'],lost_frames=s['active']['lost_frames'],error=self.error,
            channels=CHANNELS,sample_rate=48000,
            scope='Source is receiver ALSA capture; mixed is after mixer/pause gating before queue; render is after interpolation/final gain and output-write completion. File offsets are linked by source_frame and pull metadata, not wall-clock alignment. No analogue measurement.')
        try:(s['directory']/'manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')
        except Exception as error:
            if self.error is None:self.error=type(error).__name__+': '+str(error)
        finally:self.session=None

    def run(self):
        try:
            try:os.setpriority(os.PRIO_PROCESS,threading.get_native_id(),15)
            except (OSError,AttributeError):pass
            next_poll=0
            while not self.stopped.is_set():
                now=time.monotonic()
                if self.active is not None and now>=self.active['deadline']:self.finish()
                if self.error is not None:break
                if self.session is None and now>=next_poll:
                    next_poll=now+1;self.poll_request()
                try:item=self.pending.get(timeout=.05)
                except queue.Empty:continue
                self.write_event(item)
        except Exception as error:
            self.error=type(error).__name__+': '+str(error)
        finally:
            try:self.finish()
            except Exception:self.active=None

    def close(self):
        self.stopped.set()
        if self.thread:self.thread.join(timeout=2)
