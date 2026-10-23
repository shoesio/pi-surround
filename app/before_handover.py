# SPDX-License-Identifier: GPL-2.0-or-later
# Public packaging: device identities moved to site settings, 2026-10-23.
"""Use a fresh normal-route playback snapshot when transfer has already paused."""
import math

def recover(before,normal,*,manually_selected,router,now,max_age=3.):
    if not manually_selected or not before or before.get('state')!='Paused' or not isinstance(normal,dict):return before,False
    previous=normal.get('playback')
    if not isinstance(previous,dict) or previous.get('state')!='Playing':return before,False
    routes=normal.get('outputs')
    if not isinstance(routes,list) or not routes or router in routes:return before,False
    edge=normal.get('handover')
    reference=now
    if edge is not None:
        if not isinstance(edge,dict) or edge.get('router')!=router:return before,False
        try:
            reference=float(edge['observed_at']);launch_age=float(now)-reference
        except (TypeError,ValueError,KeyError):return before,False
        if not math.isfinite(launch_age) or not 0<=launch_age<=15:return before,False
    try:age=float(reference)-float(previous['observed_at'])
    except (TypeError,ValueError,KeyError):return before,False
    if not math.isfinite(age) or not 0<=age<=max_age:return before,False
    a,b=before.get('identity'),previous.get('identity')
    if not isinstance(a,(list,tuple)) or not isinstance(b,(list,tuple)) or not a or tuple(a)!=tuple(b):return before,False
    return dict(previous,identity=tuple(b)),True
