#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-or-later
"""Fetch pinned upstream sources and apply patches locally. Never installs."""
import hashlib
import io
import json
from pathlib import Path
import subprocess
import tarfile
from urllib.request import urlopen

ROOT = Path(__file__).resolve().parents[1]
BUILD = ROOT / 'build' / 'sources'


def run(*args, cwd=None):
    subprocess.run(args, cwd=cwd, check=True)


def unpack(data, target):
    with tarfile.open(fileobj=io.BytesIO(data)) as archive:
        # Refuse all links/special files, and remove the single archive root.
        for member in archive:
            parts = Path(member.name).parts
            if len(parts) < 2:
                continue
            path = target.joinpath(*parts[1:])
            if not path.resolve().is_relative_to(target.resolve()):
                raise ValueError('Unsafe upstream archive path')
            if member.isdir():
                path.mkdir(parents=True, exist_ok=True)
            elif member.isfile():
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(archive.extractfile(member).read())
                path.chmod(0o755 if member.mode & 0o111 else 0o644)
            else:
                raise ValueError('Unexpected upstream link/special file')


def main():
    # No overwrite: a failed or edited checkout needs inspection first.
    BUILD.mkdir(parents=True, exist_ok=False)
    provenance = json.loads((ROOT / 'provenance.json').read_text())
    receiver = BUILD / 'shairport-sync'
    run('git', 'init', str(receiver))
    run('git', 'remote', 'add', 'origin', 'https://github.com/mikebrady/shairport-sync.git', cwd=receiver)
    run('git', 'fetch', '--depth=1', 'origin', provenance['receiver_base'], cwd=receiver)
    run('git', 'checkout', '--detach', 'FETCH_HEAD', cwd=receiver)
    run('git', 'apply', '--check', str(ROOT / 'patches/shairport-sync.patch'), cwd=receiver)
    run('git', 'apply', str(ROOT / 'patches/shairport-sync.patch'), cwd=receiver)
    with urlopen('https://codeload.github.com/owntone/owntone-server/tar.gz/refs/tags/29.3', timeout=60) as response:
        data = response.read()
    if hashlib.sha256(data).hexdigest() != provenance['owntone_base_archive_sha256']:
        raise ValueError('OwnTone archive checksum changed; inspect before proceeding')
    owntone = BUILD / 'owntone'
    unpack(data, owntone)
    run('git', 'apply', '--check', str(ROOT / 'patches/owntone.patch'), cwd=owntone)
    run('git', 'apply', str(ROOT / 'patches/owntone.patch'), cwd=owntone)
    nqptp = BUILD / 'nqptp'
    run('git', 'init', str(nqptp))
    run('git', 'remote', 'add', 'origin', 'https://github.com/mikebrady/nqptp.git', cwd=nqptp)
    run('git', 'fetch', '--depth=1', 'origin', provenance['nqptp_base'], cwd=nqptp)
    run('git', 'checkout', '--detach', 'FETCH_HEAD', cwd=nqptp)
    print('Pinned, patched sources prepared in build/sources; nothing compiled or installed.')


if __name__ == '__main__':
    main()
