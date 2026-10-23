# SPDX-License-Identifier: GPL-2.0-or-later
# Public packaging: device identities moved to site settings, 2026-10-23.
"""Observe existing saved controls without writing or changing their interface."""
import json,pathlib
class SavedFrontLevel:
    def __init__(self,path):
        self.path=pathlib.Path(path);self.identity=None;self.level=None;self.poll()
    def poll(self):
        stat=self.path.stat();identity=(stat.st_dev,stat.st_ino,stat.st_mtime_ns)
        if identity==self.identity:return None
        level=json.loads(self.path.read_text())['front_level']
        if isinstance(level,bool) or not isinstance(level,int) or not 0<=level<=100:raise ValueError('Invalid saved front level')
        self.identity=identity;self.level=level;return level
