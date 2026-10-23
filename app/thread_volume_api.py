# SPDX-License-Identifier: GPL-2.0-or-later
# Public packaging: device identities moved to site settings, 2026-10-23.
"""Volume-only HTTP in the existing control thread's network namespace."""
import ctypes as C,http.client,json,os,pathlib,socket,threading
from volume_api import validate
from volume_errors import VolumeReadUnavailable
class ThreadVolumeAPI:
    def __init__(self,front_ids,*,enter_namespace=None,port=3689):
        self.ids=frozenset(map(str,front_ids))
        if len(self.ids)!=2:raise ValueError('Exactly two front IDs required')
        self.enter_namespace=enter_namespace or self._enter_namespace
        self.thread_id=None;self.connection=None;self.port=port;self.failed=False
    def _enter_namespace(self):
        # Linux network namespace is per thread. Never change the main thread.
        if threading.current_thread() is threading.main_thread():raise RuntimeError('Refusing main-thread namespace change')
        fd=os.open('/run/netns/homeambient-fronts',os.O_RDONLY)
        try:
            libc=C.CDLL(None,use_errno=True)
            libc.setns.argtypes=[C.c_int,C.c_int];libc.setns.restype=C.c_int
            if libc.setns(fd,0x40000000)!=0:raise OSError(C.get_errno(),'Volume thread namespace entry failed')
        finally:os.close(fd)
    def close(self):
        if self.connection:self.connection.close();self.connection=None
    def __call__(self,path,data=None):
        validate(path,data,self.ids)
        if self.failed:raise RuntimeError('Volume API failure latched')
        if self.thread_id is not None and self.thread_id!=threading.get_ident():raise RuntimeError('Volume API called by another thread')
        if self.thread_id is None:
            self.enter_namespace();self.thread_id=threading.get_ident()
        try:
            if self.connection is None:
                self.connection=http.client.HTTPConnection('127.0.0.1',self.port,timeout=1.)
            connection=self.connection
            if connection.sock is None:
                connection.connect();connection.sock.setsockopt(socket.IPPROTO_TCP,socket.TCP_NODELAY,1)
            body=json.dumps(data).encode() if data is not None else None
            connection.request('PUT' if data is not None else 'GET','/api/'+path,body,{'Content-Type':'application/json'})
            response=connection.getresponse();raw=response.read(65537)
            if len(raw)>65536 or response.status not in [200,204]:raise RuntimeError('Unexpected volume API response')
            return json.loads(raw) if raw else None
        except Exception as error:
            self.close()
            if data is None:raise VolumeReadUnavailable(type(error).__name__+': '+str(error)) from error
            self.failed=True;raise
