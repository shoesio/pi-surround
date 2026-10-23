# SPDX-License-Identifier: GPL-2.0-or-later
# Public packaging: device identities moved to site settings, 2026-10-23.
"""Read-only control transport failures, distinct from uncertain writes."""
class VolumeReadUnavailable(RuntimeError):
    pass
