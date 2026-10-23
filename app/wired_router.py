#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-or-later
# Public packaging: device identities moved to site settings, 2026-10-23.
"""Split Home Ambient's eight-channel ALSA loopback into front and rear buses.

Input channel order is fixed by the companion Shairport Sync configuration:
FL, FR, FC, LFE, BL, BR, SL, SR. Shairport's locally patched SL/SR outputs
are the already-tuned, dialogue-free rear bus.

Front output is 48 kHz stereo PCM16 in a named pipe watched by OwnTone.
Rear output is independently buffered 48 kHz stereo PCM16 to the analogue rear output.
"""

from __future__ import annotations
from coupled_trial import configuration as coupled_configuration
from coupled_master import FIXED_PROGRAMME_GAIN

import argparse
import errno
import json
import math
import os
import selectors
import signal
import socket
import stat
import subprocess
import time
from pathlib import Path

import numpy as np
from wired_rear import RearOutput
from pause_cancel import PauseCancel


SAMPLE_RATE = 48_000
INPUT_CHANNELS = 8
INPUT_FRAME_BYTES = INPUT_CHANNELS * 2
PERIOD_FRAMES = 960
READ_BYTES = PERIOD_FRAMES * INPUT_FRAME_BYTES
REAR_FRAME_BYTES = 2 * 2
# Keep at most half a second waiting in userspace. If an iPad stops reading for
# longer than that, retaining stale samples only creates audible desync; drop
# the oldest complete stereo frames and continue the live connection instead.
MAX_REAR_PENDING_BYTES = (SAMPLE_RATE // 2) * REAR_FRAME_BYTES
MAX_FRONT_PENDING_BYTES = int(SAMPLE_RATE * 0.08) * REAR_FRAME_BYTES
FRONT_PREROLL_BYTES = int(SAMPLE_RATE * 0.02) * REAR_FRAME_BYTES
MASTER_VOLUME_PATH = Path("/run/homeambient-volume/airplay-db")
REAR_TRIM_PATH = Path("/run/homeambient-surround/rear-trim-db")


def master_gain() -> float:
    """Translate Apple TV's -30..0 command to the old HomePod 0..100 curve.

    This is deliberately applied once, before the front/rear split.  The old
    arrangement independently mapped the same command to OwnTone percentages
    for the fronts and a different dB curve for the rears, so their relative
    loudness moved every time the remote was used.
    """
    try:
        value = float(MASTER_VOLUME_PATH.read_text().strip())
    except (OSError, ValueError):
        return 0.01
    if not math.isfinite(value) or value <= -100:
        return 0.0
    normalized = max(0.0, min(1.0, (max(-30.0, min(0.0, value)) + 30.0) / 30.0))
    # A linear 0..100 mapping jumps from inaudible to medium on the first few
    # Apple TV remote presses. Squaring it provides a useful quiet range while
    # retaining full output at 0 dB and one identical gain for both buses.
    return normalized * normalized


PROGRAMME_STATE_PATH = Path('/run/homeambient-plan-b/programme-state.json')
UI_VOLUME_PATH = Path('/opt/homeambient-plan-b/ui-volume-db')

def interface_gain() -> float:
    """Reduce idle menu audio only; stale/unknown playback state leaves gain alone."""
    try:
        state=json.loads(PROGRAMME_STATE_PATH.read_text())
        age=time.time()-float(state['timestamp'])
        if not 0<=age<5 or state.get('ui_mode') is not True:return 1.0
        db=float(UI_VOLUME_PATH.read_text())
        if not math.isfinite(db):return 1.0
        return 10**(max(-40.0,min(0.0,db))/20)
    except (OSError,ValueError,TypeError,KeyError):return 1.0


def configured_rear_trim(default: float) -> float:
    """Read the user calibration outside the real-time path."""
    try:
        value = float(REAR_TRIM_PATH.read_text().strip())
        return max(-12.0, min(38.0, value)) if math.isfinite(value) else default
    except (OSError, ValueError):
        return default


def ensure_fifo(path: str) -> None:
    try:
        mode = os.stat(path).st_mode
        if not stat.S_ISFIFO(mode):
            raise RuntimeError(f"{path} exists but is not a FIFO")
    except FileNotFoundError:
        os.mkfifo(path, 0o666)


def open_fifo_writer(path: str) -> int | None:
    try:
        return os.open(path, os.O_WRONLY | os.O_NONBLOCK)
    except OSError as error:
        if error.errno in (errno.ENXIO, errno.ENOENT):
            return None
        raise


def mix_buses_numpy(
    payload: bytes,
    centre_gain: float,
    lfe_gain: float,
    gain: float,
    rear_trim_db: float,
) -> tuple[bytes, bytes]:
    samples = np.frombuffer(payload, dtype="<i2").reshape((-1, INPUT_CHANNELS))

    work = np.rint(samples.astype(np.float64) * gain).astype(np.int32)

    front = np.empty((work.shape[0], 2), dtype=np.int32)
    centre = np.rint(work[:, 2] * centre_gain).astype(np.int32)
    lfe = np.rint(work[:, 3] * lfe_gain).astype(np.int32)

    # Keep the existing front stereo/UI treatment. Rear channels always use
    # their configured trim: waveform correlation cannot establish UI intent.
    def _corr(a, b):
        a = a.astype(np.float64)
        b = b.astype(np.float64)

        # Ignore near-silence.
        if np.sqrt(np.mean(a * a)) < 150 or np.sqrt(np.mean(b * b)) < 150:
            return 0.0

        a -= np.mean(a)
        b -= np.mean(b)

        denom = np.sqrt(np.sum(a * a) * np.sum(b * b))
        if denom < 1.0:
            return 0.0

        return float(np.sum(a * b) / denom)

    corr_fl_sl = _corr(samples[:, 0], samples[:, 6])
    corr_fr_sr = _corr(samples[:, 1], samples[:, 7])
    duplicated_stereo = (
        corr_fl_sl > 0.995 and
        corr_fr_sr > 0.995
    )


    if duplicated_stereo:
        front[:, 0] = work[:, 0]
        front[:, 1] = work[:, 1]
    else:
        front[:, 0] = work[:, 0] + centre + np.rint(lfe * 1.5).astype(np.int32)
        front[:, 1] = work[:, 1] + centre + np.rint(lfe * 1.5).astype(np.int32)
        front *= 2

    np.clip(front, -32768, 32767, out=front)

    front_pcm = front.astype("<i2").tobytes()
    # Fixed acoustic calibration for the modest wired rear speaker. This is
    # independent of Apple TV's master level, so front/rear balance remains
    # constant while the remote is used. A soft limiter protects the output
    # if a rare hot rear effect arrives at a high master volume.
    # Surround L/R retain their existing rear trim.
    rear = (samples[:, 6:8].astype(np.float64) * gain) * (10 ** (rear_trim_db / 20))

    # Also send LFE equally to both rear channels.
    # The HomePods now provide most of the system's LFE weight.
    # Keep only a 25% LFE contribution in the rear Orbitsound.
    rear_lfe = work[:, 3].astype(np.float64) * lfe_gain * 0.25
    rear[:, 0] += rear_lfe
    rear[:, 1] += rear_lfe

    rear = rear / (1 + np.abs(rear) / 32767.0)
    rear_pcm = np.ascontiguousarray(np.rint(rear).astype("<i2")).tobytes()
    return front_pcm, rear_pcm


def mix_buses(payload,centre_gain,lfe_gain,gain,rear_trim_db):
    from native_dsp import mix
    result=mix(payload,centre_gain,lfe_gain,gain,rear_trim_db)
    return result if result is not None else mix_buses_numpy(payload,centre_gain,lfe_gain,gain,rear_trim_db)


CENTRE_RUNTIME = Path('/run/homeambient-plan-b/centre.json')
CENTRE_FIFO = '/var/lib/homeambient-centre/media/centre.pcm'

def centre_health():
    try:
        data=json.loads(CENTRE_RUNTIME.read_text())
        if data.get('active') is True and 0<=time.time()-data['timestamp']<2:
            return True,float(data.get('trim_db',0))
    except (OSError,ValueError,TypeError,KeyError):pass
    return False,0.0

def mix_centre(payload,centre,lfe,gain,rear_db,trim):
    from native_dsp import mix3
    result=mix3(payload,centre,lfe,gain,rear_db,trim)
    if result is None:raise RuntimeError('Native centre mixer unavailable')
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument('--capture-device', default='hw:HomeAmbient,1,0')
    parser.add_argument('--front-fifo', required=True)
    parser.add_argument('--rear-device', default='plughw:vc4hdmi0,0')
    parser.add_argument('--rear-delay-ms', type=float, default=500)
    parser.add_argument('--rear-status', default='/run/homeambient-wired/rear.json')
    parser.add_argument('--centre-gain', type=float, default=1.0)
    parser.add_argument('--lfe-gain', type=float, default=1.0)
    parser.add_argument('--rear-trim-db', type=float, default=-3.0)
    args=parser.parse_args()
    signal.signal(signal.SIGPIPE,signal.SIG_IGN)
    ensure_fifo(args.front_fifo)
    rear=RearOutput(args.rear_device,args.rear_delay_ms,args.rear_status)
    capture=subprocess.Popen(['/usr/bin/arecord','-q','-D',args.capture_device,
        '-t','raw','-f','S16_LE','-r','48000','-c','8',
        '--period-size=960','--buffer-size=3840'],stdout=subprocess.PIPE,bufsize=0)
    assert capture.stdout is not None
    fd=capture.stdout.fileno();os.set_blocking(fd,False)
    selector=selectors.DefaultSelector();selector.register(fd,selectors.EVENT_READ)
    front_fd=None;front_pending=bytearray();remainder=b''
    ensure_fifo(CENTRE_FIFO)
    centre_fd=None;centre_pending=bytearray();centre_retry=0
    retry=0;last_capture=None;next_control=0;next_signal=0;signal_frames=0
    coupled=coupled_configuration()
    target=applied=FIXED_PROGRAMME_GAIN if coupled else master_gain()*interface_gain()
    trim=args.rear_trim_db
    stopping=False
    def stop(_signal,_frame):
        nonlocal stopping
        stopping=True
    signal.signal(signal.SIGTERM,stop);signal.signal(signal.SIGINT,stop)
    from native_dsp import lib as diagnostic_library
    from ui_probe import Probe
    ui_probe=Probe(diagnostic_library)
    bridge=PauseCancel(args.front_fifo)
    def clear_pending():
        front_pending.clear();centre_pending.clear()
    rear.start()
    print(f'Wired router started: rear={args.rear_device}, target delay={args.rear_delay_ms}ms',flush=True)
    try:
        while not stopping:
            now=time.monotonic()
            if rear.error:raise RuntimeError(rear.error)
            bridge.poll(rear,clear_pending)
            if now>=next_control:
                target=FIXED_PROGRAMME_GAIN if coupled else master_gain()*interface_gain()
                trim=configured_rear_trim(args.rear_trim_db)
                next_control=now+.25
            centre_ready,centre_trim=centre_health()
            try:
                cs=json.loads(CENTRE_RUNTIME.read_text())
                centre_feed=cs.get('feed') is True and 0<=time.time()-cs['timestamp']<(2 if cs.get('active') else 15)
            except (OSError,ValueError,TypeError,KeyError):centre_feed=False
            if not centre_feed:
                if centre_fd is not None:os.close(centre_fd);centre_fd=None
                centre_pending.clear()
            elif centre_fd is None and now>=centre_retry:
                centre_fd=open_fifo_writer(CENTRE_FIFO);centre_retry=now+.25
            if centre_fd is not None and centre_pending:
                try:
                    n=os.write(centre_fd,centre_pending)
                    if n:del centre_pending[:n]
                except BlockingIOError:pass
                except OSError:
                    os.close(centre_fd);centre_fd=None;centre_pending.clear()
            if front_fd is None and now>=retry:
                front_fd=open_fifo_writer(args.front_fifo);retry=now+1
                if front_fd is not None:
                    front_pending.extend(bytes(FRONT_PREROLL_BYTES))
                    print('Front FIFO connected',flush=True)
            if front_fd is not None and front_pending:
                try:
                    n=os.write(front_fd,front_pending)
                    if n:del front_pending[:n]
                except BlockingIOError:pass
                except OSError:
                    os.close(front_fd);front_fd=None;front_pending.clear()
                    print('Front FIFO disconnected',flush=True)
            # Flush pending front data even when the next capture block hasn't
            # arrived. A full pipe never stalls the independent rear worker.
            if not selector.select(.005):continue
            try:payload=os.read(fd,READ_BYTES)
            except BlockingIOError:continue
            if not payload:
                if capture.poll() is not None:raise RuntimeError('Capture process exited')
                continue
            now=time.monotonic()
            if last_capture is not None and now-last_capture>max(.75,args.rear_delay_ms/1000+.25):
                rear.reset();remainder=b'';front_pending.clear();centre_pending.clear()
                print(f'Source gap {(now-last_capture)*1000:.0f}ms; reset rear timeline',flush=True)
            last_capture=now
            payload=remainder+payload
            complete=len(payload)//INPUT_FRAME_BYTES*INPUT_FRAME_BYTES
            remainder=payload[complete:];payload=payload[:complete]
            if not payload:continue
            following=applied+max(-.08,min(.08,target-applied))
            if rear.stage_trace.active is not None:
                rear.stage_trace.offer('source',payload,source_frame=signal_frames,
                    programme_gain=(applied+following)/2,rear_trim_db=trim)
            ui_probe.observe(payload,(applied+following)/2,trim)
            used_centre_bus=False
            if centre_ready and centre_fd is not None and len(centre_pending)<MAX_FRONT_PENDING_BYTES:
                used_centre_bus=True
                front_pcm,rear_pcm,centre_pcm=mix_centre(payload,args.centre_gain,args.lfe_gain,
                    (applied+following)/2,trim,centre_trim)
                centre_pending.extend(centre_pcm)
            else:
                if centre_fd is not None:
                    centre_pending.extend(bytes(len(payload)//INPUT_FRAME_BYTES*4))
                    if len(centre_pending)>MAX_FRONT_PENDING_BYTES:
                        centre_pending.clear()
                # The exact established mixer is retained for off/unhealthy states.
                front_pcm,rear_pcm=mix_buses(payload,args.centre_gain,args.lfe_gain,
                                            (applied+following)/2,trim)
            if bridge.gated:
                front_pcm=bytes(len(front_pcm));rear_pcm=bytes(len(rear_pcm));centre_pending.clear()
            if rear.stage_trace.active is not None:
                rear.stage_trace.offer('mixed',rear_pcm,source_frame=signal_frames,
                    programme_gain=(applied+following)/2,rear_trim_db=trim,
                    centre_gain=args.centre_gain,lfe_gain=args.lfe_gain,
                    centre_bus=used_centre_bus,
                    pause_gated=bridge.gated)
            applied=following
            signal_frames+=len(payload)//INPUT_FRAME_BYTES
            if now>=next_signal and Path('/run/homeambient-plan-b/signal-test-enabled').exists():
                next_signal=now+.25
                def levels(data,channels):
                    x=np.frombuffer(data,dtype='<i2').reshape(-1,channels).astype(np.float64)
                    return [round(float(v),2) for v in np.sqrt(np.mean(x*x,axis=0))]
                metrics=dict(timestamp=time.time(),frames=signal_frames,master_gain=round(applied,6),
                    input_rms=levels(payload,8),front_rms=levels(front_pcm,2),rear_rms=levels(rear_pcm,2),
                    front_pending_ms=len(front_pending)/192.0)
                target_status=Path('/run/homeambient-plan-b/signal.json')
                temporary=target_status.with_suffix('.tmp')
                temporary.write_text(json.dumps(metrics));temporary.replace(target_status)
            rear.push(rear_pcm)
            if front_fd is not None:
                front_pending.extend(front_pcm)
                if len(front_pending)>MAX_FRONT_PENDING_BYTES:
                    excess=(len(front_pending)-MAX_FRONT_PENDING_BYTES+3)//4*4
                    del front_pending[:excess]
                    print(f'Front queue overflow: dropped {excess//4} frames',flush=True)
    finally:
        bridge.close();ui_probe.close();rear.close();selector.close()
        if centre_fd is not None:os.close(centre_fd)
        if front_fd is not None:os.close(front_fd)
        capture.terminate()
        try:capture.wait(timeout=2)
        except subprocess.TimeoutExpired:capture.kill();capture.wait()

if __name__=='__main__':main()
