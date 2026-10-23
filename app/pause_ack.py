# SPDX-License-Identifier: GPL-2.0-or-later
# Public packaging: device identities moved to site settings, 2026-10-23.
"""Validate actual per-device response evidence for one bounded flush transaction."""
import re,math
EVENT=re.compile(r'HA_PAUSE_FLUSH (\w+) mono=([0-9.]+)(.*)')
FIELD=re.compile(r'(\w+)=([^\s]+)')
class Acknowledgements:
 def __init__(self,expected,started,timeout=2.):
  self.expected={str(x) for x in expected};self.started=started;self.deadline=started+timeout
  self.received=False;self.completed=False;self.requests={};self.responses={};self.error=None
 def feed(self,line):
  m=EVENT.search(line)
  if not m:return
  stage=m[1]
  try:stamp=float(m[2])
  except ValueError:return
  if not math.isfinite(stamp) or not self.started<=stamp<=self.deadline:return
  fields=dict(FIELD.findall(m[3]))
  try:
   if stage=='metadata_received':self.received=True
   elif stage=='metadata_completed':
    result=int(fields['result']);self.completed=result>=0
    if result<0:self.error='metadata flush returned an error'
   elif stage=='device_request' and fields['device'] in self.expected:
    if int(fields['eligible'])!=1:self.error='expected device was not streaming'
    else:self.requests[fields['device']]=stamp
   elif stage=='device_response' and fields['device'] in self.expected:
    device=fields['device'];request=float(fields['request_mono']);generation=int(fields['generation']);status=int(fields['status'])
    if not math.isfinite(request) or not self.started<=request<=stamp or generation<1:return
    if device not in self.requests or request<self.requests[device]-.001:return
    if status!=200:self.error='HomePod FLUSH response was not successful'
    else:self.responses[device]=dict(generation=generation,requested=request,acknowledged=stamp)
  except (ValueError,KeyError):return
 @property
 def acknowledged(self):return not self.error and self.received and self.completed and self.expected==self.responses.keys()
