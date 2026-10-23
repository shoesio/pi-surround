# SPDX-License-Identifier: GPL-2.0-or-later
# Public packaging: device identities moved to site settings, 2026-10-23.
"""Allocation-bounded output attenuation. No devices, queues or clocks touched."""
import ctypes as C,math,pathlib
class State(C.Structure):
    _fields_=[('current',C.c_double),('target',C.c_double),('remaining',C.c_uint32)]
class RenderAttenuator:
    def __init__(self,frames=480):
        if not isinstance(frames,int) or frames<1:raise ValueError('Positive ramp length required')
        self.frames=frames;self.state=State(1.,1.,0);self.capacity=0;self.buffer=None
        self.lib=C.CDLL(str(pathlib.Path(__file__).with_name('liblate_gain.so')))
        self.fn=self.lib.late_gain
        self.fn.argtypes=[C.c_char_p,C.c_void_p,C.c_size_t,C.POINTER(State)];self.fn.restype=None
    @property
    def current(self):return self.state.current
    @property
    def target(self):return self.state.target
    @property
    def remaining(self):return self.state.remaining
    def set_gain(self,gain):
        if not math.isfinite(gain) or not 0<=gain<=1:raise ValueError('Only finite attenuation allowed')
        if gain!=self.state.target:self.state.target=gain;self.state.remaining=self.frames
    def apply(self,pcm):
        if len(pcm)%4:raise ValueError('Incomplete stereo frame')
        if not pcm or self.current==self.target==1:return pcm
        if len(pcm)>self.capacity:self.capacity=len(pcm);self.buffer=C.create_string_buffer(self.capacity)
        self.fn(pcm,self.buffer,len(pcm)//4,C.byref(self.state))
        return self.buffer.raw[:len(pcm)]
