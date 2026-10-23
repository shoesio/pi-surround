# SPDX-License-Identifier: GPL-2.0-or-later
# Public packaging: device identities moved to site settings, 2026-10-23.
"""Private stdin/stdout HTTP worker. No listening socket or transport commands."""
import http.client,json,sys,socket
from volume_api import validate
ids=frozenset(sys.argv[1].split(','));assert len(ids)==2
port=int(sys.argv[2]) if len(sys.argv)>2 else 3689
connection=http.client.HTTPConnection('127.0.0.1',port,timeout=1.)
try:
    for line in sys.stdin.buffer:
        try:
            if len(line)>1024:raise ValueError('Oversized operation')
            request=json.loads(line);path=request['path'];data=request['data'];validate(path,data,ids)
            body=json.dumps(data).encode() if data is not None else None
            if connection.sock is None:
                connection.connect()
                connection.sock.setsockopt(socket.IPPROTO_TCP,socket.TCP_NODELAY,1)
            connection.request('PUT' if data is not None else 'GET','/api/'+path,body,{'Content-Type':'application/json'})
            response=connection.getresponse();raw=response.read(65537)
            if len(raw)>65536 or response.status not in [200,204]:raise RuntimeError('Unexpected API response')
            result=json.loads(raw) if raw else None
            output={'ok':True,'result':result}
        except Exception as error:
            output={'ok':False,'error_type':type(error).__name__}
        sys.stdout.write(json.dumps(output)+'\n');sys.stdout.flush()
        if not output['ok']:break # Never retry an uncertain mutation.
finally:connection.close()
