#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-or-later
"""Conservative publication checks; reports locations, never matched secrets."""
import ast
import ipaddress
import json
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[1]
IGNORED = {'.git', '__pycache__', 'build', '.venv'}
FORBIDDEN_SUFFIXES = {'.so', '.dylib', '.o', '.a', '.wav', '.pcm', '.db', '.pcap', '.ipsw'}


def findings(root=ROOT):
    errors = []
    files = 0
    for p in sorted(root.rglob('*')):
        rel = p.relative_to(root)
        if any(part in IGNORED for part in rel.parts):
            continue
        if p.is_symlink():
            errors.append((str(rel), 'symlink requires review'))
            continue
        if not p.is_file():
            continue
        files += 1
        if p.suffix in FORBIDDEN_SUFFIXES or p.name in {'apple-tv.json', 'settings.json', 'network.env'}:
            errors.append((str(rel), 'private or generated payload filename'))
        try:
            text = p.read_text()
        except UnicodeError:
            errors.append((str(rel), 'non-text payload'))
            continue
        if p.suffix == '.py':
            try:
                ast.parse(text, filename=str(rel))
            except SyntaxError:
                errors.append((str(rel), 'Python syntax error'))
        if p.suffix == '.json' or p.name.endswith('.json.example'):
            try:
                json.loads(text)
            except ValueError:
                errors.append((str(rel), 'invalid JSON'))
        # Values are deliberately not included in output.
        if re.search(r'(?:[0-9A-Fa-f]{2}:){5}[0-9A-Fa-f]{2}', text):
            errors.append((str(rel), 'literal hardware/device address'))
        personal_path = '/' + 'Users' + r'/[^/\s]+/'
        if re.search(personal_path, text) or ('-----BEGIN ' + 'PRIVATE KEY-----') in text:
            errors.append((str(rel), 'personal path or private-key marker'))
        if re.search(r'(?i)https?://[^\s/@]+:[^\s/@]+@', text):
            errors.append((str(rel), 'URL containing credentials'))
        for value in re.findall(r'(?<![\w.])(?:\d{1,3}\.){3}\d{1,3}(?![\w.])', text):
            try:
                address = ipaddress.ip_address(value)
            except ValueError:
                continue
            allowed = address.is_loopback or any(address in ipaddress.ip_network(x)
                for x in ('192.0.2.0/24', '198.51.100.0/24', '203.0.113.0/24'))
            if not allowed:
                errors.append((str(rel), 'non-documentation IP address'))
    return files, errors


if __name__ == '__main__':
    count, errors = findings()
    for path, reason in errors:
        print(path + ': ' + reason)
    print(f'{count} text files checked; {len(errors)} findings')
    sys.exit(bool(errors))
