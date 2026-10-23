# SPDX-License-Identifier: GPL-2.0-or-later
# Public packaging: device identities moved to site settings, 2026-10-23.
"""Bounded stereo queue and independent ALSA playback for the monitor output.

Importing this module does not open an audio device. Hardware is opened only
when RearOutput.start() is explicitly called by the live router.
"""
from __future__ import annotations
from coupled_trial import configuration as coupled_configuration, GainReader
import ctypes as C
import ctypes.util
import errno
import json
import threading
import time
from pathlib import Path
import numpy as np
from native_dsp import interpolate as native_interp
from fast_render import RenderAttenuator
from stage_trace import StageTrace

RATE = 48000
BLOCK = 480
DEVICE_LATENCY_MS = 80


class DelayQueue:
    def __init__(self, delay_ms=500, max_ms=2500):
        if not 40 <= delay_ms <= 2400:
            raise ValueError('Rear delay must be 40..2400 ms')
        self.target = max(0,round((delay_ms - DEVICE_LATENCY_MS) * RATE / 1000))
        self.capacity = round(max(max_ms, delay_ms + 600) * RATE / 1000)
        self.data = np.zeros((self.capacity, 2), dtype=np.float64)
        self.head = self.size = 0
        self.phase = 0.0
        self.playing = False
        self.underflows = self.dropped = self.received = self.rendered = 0
        self.ratio = 1.0
        self.trace_enabled = False
        self.last_pull_trace = None
        self.lock = threading.Lock()

    def reset(self):
        with self.lock:
            self.head = self.size = 0
            self.phase = 0.0
            self.playing = False

    def push(self, pcm):
        if len(pcm) % 4:
            raise ValueError('Incomplete stereo frame')
        frames = np.frombuffer(pcm, dtype='<i2').reshape(-1, 2)
        with self.lock:
            self.received += len(frames)
            if len(frames) > self.capacity:
                self.dropped += len(frames) - self.capacity
                frames = frames[-self.capacity:]
            excess = max(0, self.size + len(frames) - self.capacity)
            if excess:
                self.head = (self.head + excess) % self.capacity
                self.size -= excess
                self.dropped += excess
                self.phase = 0.0
            tail = (self.head + self.size) % self.capacity
            first = min(len(frames), self.capacity - tail)
            self.data[tail:tail+first] = frames[:first]
            self.data[:len(frames)-first] = frames[first:]
            self.size += len(frames)

    def pull(self, count=BLOCK):
        with self.lock:
            if not self.playing:
                if self.size < self.target + count + 2:
                    if self.trace_enabled:
                        self.last_pull_trace=dict(state='priming',source_frame=None,phase=self.phase,ratio=self.ratio)
                    return bytes(count * 4)
                self.playing = True
            # HDMI and capture devices have independent sample clocks. Make
            # small continuous rate corrections instead of periodic skips.
            error = self.size - (self.target + count)
            wanted = 1 + max(-.002,min(.002,error / (RATE * 20)))
            self.ratio += .01 * (wanted - self.ratio)
            if self.trace_enabled:
                self.last_pull_trace=dict(state='playing',source_frame=self.received-self.size+self.phase,
                    phase=self.phase,ratio=self.ratio,queue_frames=self.size)
            positions = self.phase + np.arange(count) * self.ratio
            whole = positions.astype(np.int64)
            consumed = int(self.phase + count * self.ratio)
            if self.size <= max(int(whole[-1]) + 1, consumed):
                self.underflows += 1
                self.playing = False
                if self.trace_enabled:self.last_pull_trace['state']='underflow'
                return bytes(count * 4)
            native=native_interp(self.data,self.capacity,self.head,count,self.phase,self.ratio)
            if native is None:
                a = self.data[(self.head + whole) % self.capacity]
                b = self.data[(self.head + whole + 1) % self.capacity]
                output = a + (b - a) * (positions - whole)[:, None]
            self.phase += count * self.ratio - consumed
            self.head = (self.head + consumed) % self.capacity
            self.size -= consumed
            self.rendered += count
            return native if native is not None else np.clip(np.rint(output), -32768, 32767).astype('<i2').tobytes()

    def status(self):
        with self.lock:
            return dict(queue_ms=round(self.size / 48, 2), playing=self.playing,
                        received_frames=self.received, rendered_frames=self.rendered,
                        underflows=self.underflows, dropped_frames=self.dropped,
                        correction_ppm=round((self.ratio-1)*1e6, 1))


class Alsa:
    def __init__(self, device):
        self.lib = C.CDLL(ctypes.util.find_library('asound') or 'libasound.so.2')
        self.handle = C.c_void_p()
        signatures = {
            'snd_pcm_open': ([C.POINTER(C.c_void_p), C.c_char_p, C.c_int, C.c_int], C.c_int),
            'snd_pcm_set_params': ([C.c_void_p]+[C.c_int]*2+[C.c_uint]*2+[C.c_int,C.c_uint], C.c_int),
            'snd_pcm_writei': ([C.c_void_p,C.c_void_p,C.c_ulong], C.c_long),
            'snd_pcm_wait': ([C.c_void_p,C.c_int], C.c_int),
            'snd_pcm_recover': ([C.c_void_p,C.c_int,C.c_int], C.c_int),
            'snd_pcm_drop': ([C.c_void_p], C.c_int),
            'snd_pcm_prepare': ([C.c_void_p], C.c_int),
            'snd_pcm_close': ([C.c_void_p], C.c_int),
            'snd_strerror': ([C.c_int], C.c_char_p),
        }
        for name,(args,result) in signatures.items():
            f=getattr(self.lib,name); f.argtypes=args; f.restype=result
        self.check(self.lib.snd_pcm_open(C.byref(self.handle),device.encode(),0,1))
        try:
            # S16_LE=2, RW_INTERLEAVED=3, stereo48k, no software resampling.
            self.check(self.lib.snd_pcm_set_params(self.handle,2,3,2,RATE,0,DEVICE_LATENCY_MS*1000))
        except BaseException:
            self.close(); raise
        self.xruns = 0
        self.last_write_attempt = None
        self.max_write_gap_ms = 0.0
        self.last_xrun_detail = None

    def check(self, result):
        if result < 0:
            raise RuntimeError(self.lib.snd_strerror(result).decode())
        return result

    def reset(self):
        self.check(self.lib.snd_pcm_drop(self.handle))
        self.check(self.lib.snd_pcm_prepare(self.handle))

    def note_xrun(self, result, where, gap_ms):
        # Rare-event detail only: no logging, extra thread or PCM copy.
        self.xruns += 1
        self.last_xrun_detail = dict(timestamp=time.time(), monotonic=time.monotonic(),
            result=int(result), operation=where, write_gap_ms=round(gap_ms, 3))

    def write(self, pcm, stopped):
        offset=0
        while offset < len(pcm) and not stopped.is_set():
            block=C.create_string_buffer(pcm[offset:])
            now=time.monotonic()
            gap_ms=0.0 if self.last_write_attempt is None else (now-self.last_write_attempt)*1000
            self.max_write_gap_ms=max(self.max_write_gap_ms,gap_ms)
            self.last_write_attempt=now
            n=self.lib.snd_pcm_writei(self.handle,block,(len(pcm)-offset)//4)
            if n == -errno.EAGAIN or n == 0:
                waited=self.lib.snd_pcm_wait(self.handle,50)
                if waited < 0:
                    self.note_xrun(waited, "wait", gap_ms)
                    self.check(self.lib.snd_pcm_recover(self.handle,waited,1))
            elif n < 0:
                self.note_xrun(n, "write", gap_ms)
                self.check(self.lib.snd_pcm_recover(self.handle,n,1))
            else:
                offset += n*4

    def close(self):
        if self.handle.value:
            self.lib.snd_pcm_drop(self.handle)
            self.lib.snd_pcm_close(self.handle)
            self.handle=C.c_void_p()


class RearOutput:
    def __init__(self, device, delay_ms, status_path):
        self.device=device
        self.queue=DelayQueue(delay_ms)
        self.status_path=Path(status_path)
        self.stopped=threading.Event()
        self.reset_requested=threading.Event()
        self.reset_request=None
        self.reset_completed=None
        self.error=None
        self.thread=None
        self.render_attenuator=RenderAttenuator(BLOCK)
        self.stage_trace=StageTrace()
        self.requested_render_gain=1.0
        from rear_recording import from_request
        self.recording=from_request()
        self.coupled_trial=coupled_configuration()
        self.gain_reader=GainReader() if self.coupled_trial else None

    def set_render_gain(self, gain):
        """Control-thread target only; the ALSA worker owns ramp state."""
        if not np.isfinite(gain) or not 0 <= gain <= 1:
            raise ValueError("Render gain must be finite attenuation")
        self.requested_render_gain=float(gain)

    def start(self):
        self.stage_trace.start()
        if self.gain_reader:self.gain_reader.start()
        self.thread=threading.Thread(target=self.run,name='wired-rear',daemon=True)
        self.thread.start()

    def push(self, pcm):
        if self.error:
            raise RuntimeError('Wired rear failed: '+self.error)
        self.queue.push(pcm)

    def reset(self):
        before=self.queue.status()
        self.queue.reset()
        generation=1 if self.reset_request is None else self.reset_request['generation']+1
        self.reset_request=dict(generation=generation,monotonic=time.monotonic(),
                                queue_ms_before=before['queue_ms'])
        self.reset_requested.set()

    def run(self):
        sink=None
        try:
            sink=Alsa(self.device)
            last_report=0
            render_blocks=zero_blocks=zero_gain_blocks=render_peak=0
            max_gain_age=0.0
            trace_block_id=0
            while not self.stopped.is_set():
                if self.reset_requested.is_set():
                    self.reset_requested.clear()
                    request=self.reset_request
                    sink.reset()
                    self.reset_completed=dict(generation=request['generation'],
                        requested_monotonic=request['monotonic'],completed_monotonic=time.monotonic(),
                        queue_ms_before=request['queue_ms_before'],
                        queue_ms_after=self.queue.status()['queue_ms'])
                gain=self.gain_reader.gain() if self.gain_reader else self.requested_render_gain
                self.render_attenuator.set_gain(gain)
                self.queue.trace_enabled=self.stage_trace.active is not None
                queued_pcm=self.queue.pull()
                if self.queue.trace_enabled:
                    trace_block_id+=1
                    trace_gain_before=self.render_attenuator.current
                    trace_ramp_before=self.render_attenuator.remaining
                    self.stage_trace.offer('interpolated',queued_pcm,pull=self.queue.last_pull_trace,
                        block_id=trace_block_id)
                pcm=self.render_attenuator.apply(queued_pcm)
                sink.write(pcm,self.stopped)
                if self.queue.trace_enabled:
                    self.stage_trace.offer('render',pcm,pull=self.queue.last_pull_trace,
                        block_id=trace_block_id,gain_before=trace_gain_before,
                        ramp_before=trace_ramp_before,stopping=self.stopped.is_set(),
                        requested_gain=gain,actual_gain=self.render_attenuator.current,
                        gain_target=self.render_attenuator.target,
                        gain_ramp_remaining=self.render_attenuator.remaining,
                        alsa_xruns=sink.xruns,reset_request=self.reset_request,
                        reset_completed=self.reset_completed)
                if self.recording:
                    try:self.recording.offer(pcm,gain,sink.xruns)
                    except Exception:self.recording.stopped.set();self.recording=None
                # Observe actual post-queue, post-gain samples; never retain PCM.
                values=np.frombuffer(pcm,dtype='<i2')
                peak=max(abs(int(values.min())),abs(int(values.max()))) if len(values) else 0
                render_blocks+=1;zero_blocks+=int(peak==0);zero_gain_blocks+=int(gain==0.)
                render_peak=max(render_peak,peak)
                if self.gain_reader:
                    max_gain_age=max(max_gain_age,time.monotonic()-self.gain_reader.value[1])
                if time.monotonic()-last_report >= 1:
                    state=self.queue.status()
                    trace_state=self.stage_trace.active
                    state.update(stage_trace=dict(active_id=trace_state['id'] if trace_state else None,
                                                  error=self.stage_trace.error),
                                 reset_request=self.reset_request,reset_completed=self.reset_completed,
                                 device=self.device,alsa_xruns=sink.xruns,
                                 alsa_max_write_gap_ms=round(sink.max_write_gap_ms,3),
                                 alsa_last_xrun=sink.last_xrun_detail,
                                 render_window=dict(blocks=render_blocks,zero_blocks=zero_blocks,
                                     zero_gain_blocks=zero_gain_blocks,peak=render_peak,
                                     gain=gain,max_gain_cache_age_ms=round(max_gain_age*1000,3)),
                                 timestamp=time.time(),error=None)
                    self.status_path.parent.mkdir(parents=True,exist_ok=True)
                    temporary=self.status_path.with_suffix('.tmp')
                    temporary.write_text(json.dumps(state));temporary.replace(self.status_path)
                    last_report=time.monotonic()
                    render_blocks=zero_blocks=zero_gain_blocks=render_peak=0
                    max_gain_age=0.0
        except Exception as error:
            self.error=str(error)
            print('Wired rear failed: '+self.error,flush=True)
        finally:
            self.stage_trace.close()
            if self.recording:self.recording.close()
            if self.gain_reader:self.gain_reader.stop()
            if sink:sink.close()

    def close(self):
        self.stopped.set()
        if self.thread:self.thread.join(timeout=2)
