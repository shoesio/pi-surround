# SPDX-License-Identifier: GPL-2.0-or-later
"""Site identities are private configuration, never constants in public code."""
import json
import os
from pathlib import Path


def settings():
    path = Path(os.environ.get('PI_SURROUND_SETTINGS', '/opt/homeambient-plan-b/settings.json'))
    return json.loads(path.read_text())


def identities(key):
    values = settings()[key]
    if (not isinstance(values, list) or len(values) != 2
            or any(not isinstance(x, str) or not x or 'REPLACE' in x for x in values)
            or len(set(values)) != 2):
        raise ValueError('Configure two distinct ' + key)
    return set(values)


def front_output_ids():
    return identities('front_output_ids')


def native_homepod_ids():
    return {x.upper() for x in identities('native_homepod_ids')}
