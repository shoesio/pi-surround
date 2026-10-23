# SPDX-License-Identifier: GPL-2.0-or-later
# Public packaging: device identities moved to site settings, 2026-10-23.
import re
HEADER = re.compile(rb'<item><type>([0-9a-f]+)</type><code>([0-9a-f]+)</code>')
class Headers:
    def __init__(self): self.pending = b''
    def feed(self, data):
        buf = self.pending + data
        codes = []
        for m in HEADER.finditer(buf):
            if int(m[1],16) == int.from_bytes(b'ssnc','big'):
                codes.append(int(m[2],16).to_bytes(4,'big'))
        last = buf.rfind(b'<item>')
        self.pending = buf[last:][-128:] if last >= 0 and b'</code>' not in buf[last:] else buf[-6:]
        return codes

