# SPDX-License-Identifier: GPL-2.0-or-later
# Public packaging: device identities moved to site settings, 2026-10-23.
"""Temporary numeric-only probe. No device/FIFO access; bounded background log."""
import ctypes as C
import json
import logging
from logging.handlers import RotatingFileHandler
import queue
import threading
import time
from pathlib import Path

class Probe:
    def __init__(self,library):
        self.library=library
        self.fn=library.ha_probe
        self.fn.argtypes=[C.c_void_p,C.c_size_t,C.c_void_p]
        self.fn.restype=None
        self.pending=queue.Queue(maxsize=128)
        self.thread=None
        self.stopped=threading.Event()
        self.marker=Path('/run/homeambient-plan-b/ui-probe-enabled')
        self.next_check=0
        self.enabled=False
        self.lost=0
    def observe(self,pcm,gain,rear_db):
        now=time.monotonic()
        if now>=self.next_check:
            self.next_check=now+.25
            try:self.enabled=0<=time.time()-self.marker.stat().st_mtime<180
            except OSError:self.enabled=False
        if not self.enabled:return
        if self.thread is None:
            self.thread=threading.Thread(target=self.run,name='ui-probe-log',daemon=True)
            self.thread.start()
        n=len(pcm)//16
        if not n:return
        data=C.create_string_buffer(pcm);values=(C.c_double*12)()
        self.fn(data,n,values)
        event=dict(monotonic=now,timestamp=time.time(),frames=n,input_rms=[round(v,3) for v in values[:8]],
                   corr_left=round(values[8],6),corr_right=round(values[9],6),
                   exact_duplicate=bool(values[10]),duplicate_ui=bool(values[11]),
                   applied_gain=gain,rear_trim_db=rear_db,lost=self.lost)
        try:self.pending.put_nowait(event)
        except queue.Full:self.lost+=1
    def run(self):
        handler=None
        try:
            try:import os;os.setpriority(os.PRIO_PROCESS,threading.get_native_id(),10)
            except (OSError,AttributeError):pass
            handler=RotatingFileHandler('/run/homeambient-plan-b/ui-probe.jsonl',maxBytes=4*1024*1024,backupCount=1)
            handler.setFormatter(logging.Formatter('%(message)s'))
            while not self.stopped.is_set() or not self.pending.empty():
                try:event=self.pending.get(timeout=.25)
                except queue.Empty:continue
                try:event['programme']=json.loads(Path('/run/homeambient-plan-b/programme-state.json').read_text())
                except (OSError,ValueError):event['programme']=None
                try:event['master_command']=float(Path('/run/homeambient-volume/airplay-db').read_text())
                except (OSError,ValueError):event['master_command']=None
                handler.handle(logging.LogRecord('ui-probe',logging.INFO,'',0,json.dumps(event),(),None))
        except Exception:
            self.enabled=False
        finally:
            if handler:handler.close()
    def close(self):
        self.stopped.set()
        if self.thread:self.thread.join(timeout=2)
