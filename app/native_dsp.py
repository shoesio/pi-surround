# SPDX-License-Identifier: GPL-2.0-or-later
# Public packaging: device identities moved to site settings, 2026-10-23.
"""Optional native arithmetic; no devices are opened by this module."""
import ctypes as C
from pathlib import Path
try:lib=C.CDLL(str(Path(__file__).with_name('libwiredmix.so')))
except OSError:lib=None
if lib:
    lib.ha_mix.argtypes=[C.c_void_p,C.c_size_t]+[C.c_double]*4+[C.c_void_p]*2
    lib.ha_mix.restype=None
    lib.ha_interp.argtypes=[C.c_void_p]+[C.c_int]*3+[C.c_double]*2+[C.c_void_p]
    lib.ha_interp.restype=None

def mix(payload,centre,lfe,gain,rear_db):
    if lib is None:return None
    if len(payload)%16:raise ValueError('Incomplete eight-channel frame')
    n=len(payload)//16
    inp=C.create_string_buffer(payload)
    front=C.create_string_buffer(n*4);rear=C.create_string_buffer(n*4)
    lib.ha_mix(inp,n,centre,lfe,gain,rear_db,front,rear)
    return front.raw,rear.raw

def interpolate(data,capacity,head,count,phase,ratio):
    if lib is None:return None
    out=C.create_string_buffer(count*4)
    lib.ha_interp(data.ctypes.data,capacity,head,count,phase,ratio,out)
    return out.raw


def mix3(payload,centre,lfe,gain,rear_db,centre_db):
    if lib is None or not hasattr(lib,'ha_mix3'):return None
    if len(payload)%16:raise ValueError('Incomplete eight-channel frame')
    lib.ha_mix3.argtypes=[C.c_void_p,C.c_size_t]+[C.c_double]*5+[C.c_void_p]*3
    lib.ha_mix3.restype=None
    n=len(payload)//16;inp=C.create_string_buffer(payload)
    front=C.create_string_buffer(n*4);rear=C.create_string_buffer(n*4);middle=C.create_string_buffer(n*4)
    lib.ha_mix3(inp,n,centre,lfe,gain,rear_db,centre_db,front,rear,middle)
    return front.raw,rear.raw,middle.raw
