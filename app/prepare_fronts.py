# SPDX-License-Identifier: GPL-2.0-or-later
# Public packaging: device identities moved to site settings, 2026-10-23.
"""Start deselected OwnTone discovery before the controller's heavy imports.

Runs only as systemd ExecStartPre; never selects outputs or starts playback.
Any preparation failure falls back to the controller's existing startup path.
"""
import fcntl
import json
from pathlib import Path
import re
import sqlite3
import subprocess
import time

ROOT = Path('/opt/homeambient-plan-b')
RUNTIME = Path('/run/homeambient-plan-b')
DATABASE = Path('/var/lib/homeambient-plan-b/cache/database.db')
FRONTS = 'homeambient-planb-fronts.service'
CONFLICTS = ('shairport-sync', 'homeambient-rear-audio-server',
             'homeambient-fronts-restored', 'homeambient-speaker-ownership',
             'homeambient-front-delay')


def active(unit):
    return subprocess.run(['systemctl', 'is-active', '--quiet', unit],
                          timeout=3).returncode == 0


def prepare():
    config = json.loads((ROOT / 'settings.json').read_text())
    if not config.get('maintenance_approved') or config.get('centre_enabled') is not False:
        return 'skip_settings'
    text = (ROOT / 'owntone.conf').read_text()
    text = '\n'.join(line.split('#', 1)[0] for line in text.splitlines())
    if not re.search(r'\bpipe_autostart\s*=\s*false\b', text):
        return 'skip_autostart_not_disabled'
    with open('/run/homeambient-speaker-control.lock', 'a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        if active(FRONTS) or any(active(unit) for unit in CONFLICTS):
            return 'skip_existing_service'
        # OwnTone must be stopped while editing its persisted selection.
        with sqlite3.connect(DATABASE, timeout=2) as db:
            db.execute('UPDATE speakers SET selected=0')
            assert db.execute('SELECT COUNT(*) FROM speakers WHERE selected != 0').fetchone()[0] == 0
        RUNTIME.mkdir(parents=True, exist_ok=True)
        (RUNTIME / 'session-active').touch()
        subprocess.run(['systemctl', 'start', FRONTS], check=True, timeout=15)
        return 'discovery_started_without_selection'


def main():
    began = time.monotonic()
    try:
        result = prepare()
    except Exception as error:
        result = 'fallback_' + type(error).__name__
    print(json.dumps({'kind': 'startup_prewarm', 'result': result,
                      'timestamp': time.time(),
                      'elapsed_ms': round((time.monotonic() - began) * 1000, 2)}), flush=True)


if __name__ == '__main__':
    main()
