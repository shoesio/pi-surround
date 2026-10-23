# SPDX-License-Identifier: GPL-2.0-or-later
# Public packaging: device identities moved to site settings, 2026-10-23.
"""One persistent local API worker; only the two front volume fields writable."""
import json,os,pathlib,selectors,subprocess,sys,threading,time

def validate(path,data,ids):
    if path=='outputs' and data is None:return
    if path not in {'outputs/'+i for i in ids} or not isinstance(data,dict) or set(data)!={'volume'}:
        raise ValueError('Only front volume operations allowed')
    value=data['volume']
    if isinstance(value,bool) or not isinstance(value,int) or not 0<=value<=100:
        raise ValueError('Volume must be an integer percent')

class VolumeAPI:
    def __init__(self,front_ids,*,worker_command=None,timeout=3.):
        self.ids=frozenset(map(str,front_ids))
        if len(self.ids)!=2:raise ValueError('Exactly two front IDs required')
        self.command=worker_command or ['ip','netns','exec','homeambient-fronts',sys.executable,str(pathlib.Path(__file__).with_name('volume_api_worker.py')),','.join(sorted(self.ids))]
        self.timeout=timeout;self.process=None;self.lock=threading.Lock();self.failed=False
    def close(self):
        process=self.process;self.process=None
        if process:
            if process.stdin:process.stdin.close()
            try:process.wait(timeout=1)
            except subprocess.TimeoutExpired:process.kill();process.wait(timeout=1)
            if process.stdout:process.stdout.close()
    def __call__(self,path,data=None):
        validate(path,data,self.ids)
        with self.lock:
            if self.failed:raise RuntimeError('Volume API failure latched')
            try:
                if self.process is None:self.process=subprocess.Popen(self.command,stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.DEVNULL,bufsize=0)
                process=self.process
                message=(json.dumps({'path':path,'data':data})+'\n').encode()
                assert len(message)<1024
                process.stdin.write(message)
                deadline=time.monotonic()+self.timeout;buffer=bytearray()
                with selectors.DefaultSelector() as selector:
                    selector.register(process.stdout,selectors.EVENT_READ)
                    while b'\n' not in buffer:
                        remaining=deadline-time.monotonic()
                        if remaining<=0 or not selector.select(remaining):raise TimeoutError('Volume API response timed out')
                        chunk=os.read(process.stdout.fileno(),4096)
                        if not chunk:raise ConnectionError('Volume API worker closed')
                        buffer.extend(chunk)
                        if len(buffer)>65536:raise ValueError('Volume API response too large')
                result=json.loads(buffer)
                if not result.get('ok'):raise RuntimeError('Volume API worker '+result.get('error_type','failure'))
                return result['result']
            except Exception:
                self.failed=True;self.close();raise
