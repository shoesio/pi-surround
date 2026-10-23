# SPDX-License-Identifier: GPL-2.0-or-later
# Public packaging: device identities moved to site settings, 2026-10-23.
"""Rediscover only the paired device identity when a DHCP address changes."""
async def resolve(saved,scan,trace):
 identity=saved['identifier'].upper()
 def matches(c):return str(c.identifier).upper()==identity
 found=[]
 try:found=await scan(hosts=[saved['address']],timeout=3)
 except (OSError,TimeoutError):pass
 valid=[c for c in found if matches(c)]
 if len(valid)==1:return valid[0]
 found=await scan(timeout=6);valid=[c for c in found if matches(c)]
 if len(valid)!=1:raise RuntimeError('Paired Apple TV identity not uniquely discovered')
 trace('apple_tv_address_rediscovered',address=str(valid[0].address))
 return valid[0]
