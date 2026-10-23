# SPDX-License-Identifier: GPL-2.0-or-later
import ctypes as C
import importlib.util
import json
import math
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]


def module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


class ConfigurationTests(unittest.TestCase):
    def test_publication_scanner_rejects_private_payload(self):
        audit = module('audit', ROOT / 'scripts/audit_release.py')
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / 'apple-tv.json').write_text(json.dumps({'address': '.'.join(['10', '1', '2', '3'])}))
            _, errors = audit.findings(root)
            self.assertTrue(any('payload filename' in reason for _, reason in errors))
            self.assertTrue(any('IP address' in reason for _, reason in errors))

    def test_unconfigured_identity_fails_closed(self):
        config = module('site_config', ROOT / 'app/site_config.py')
        with patch.dict(os.environ, {'PI_SURROUND_SETTINGS': str(ROOT / 'config/settings.json.example')}):
            with self.assertRaises(ValueError):
                config.front_output_ids()
        settings = json.loads((ROOT / 'config/settings.json.example').read_text())
        self.assertFalse(settings['maintenance_approved'])
        self.assertFalse(settings['centre_enabled'])
        self.assertEqual(settings['rear_trim_db'], 0)

    def test_distinct_site_identity_sets(self):
        config = module('site_config', ROOT / 'app/site_config.py')
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / 'test.json'
            p.write_text(json.dumps({'front_output_ids': ['1', '2'], 'native_homepod_ids': ['alpha', 'beta']}))
            with patch.dict(os.environ, {'PI_SURROUND_SETTINGS': str(p)}):
                self.assertEqual(config.front_output_ids(), {'1', '2'})
                self.assertEqual(config.native_homepod_ids(), {'ALPHA', 'BETA'})
                p.write_text(json.dumps({'front_output_ids': ['1', '1']}))
                with self.assertRaises(ValueError):
                    config.front_output_ids()


class MixerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        path = Path(cls.tmp.name) / 'mixer.so'
        subprocess.run(['cc', '-O3', '-Wall', '-Wextra', '-Werror', '-shared', '-fPIC',
                        str(ROOT / 'native/wired_dsp.c'), '-lm', '-o', str(path)], check=True)
        cls.lib = C.CDLL(str(path))
        cls.lib.ha_mix.argtypes = [C.c_void_p, C.c_size_t] + [C.c_double] * 4 + [C.c_void_p] * 2
        cls.lib.ha_mix.restype = None

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def mix(self, frames, rear_db=18):
        n = len(frames)
        data = (C.c_int16 * (n * 8))(*(v for frame in frames for v in frame))
        front = (C.c_int16 * (n * 2))()
        rear = (C.c_int16 * (n * 2))()
        self.lib.ha_mix(data, n, .707, .5, .125, rear_db, front, rear)
        return list(front), list(rear)

    def test_rear_does_not_switch_with_front_correlation(self):
        # One input is duplicated stereo; the other has unrelated front content.
        # Both must retain identical rear ambience.
        values = [int(400 * math.sin(i * .3)) for i in range(960)]
        duplicate = [[v, -v, 0, 0, 0, 0, v, -v] for v in values]
        unrelated = [[0, 0, 0, 0, 0, 0, v, -v] for v in values]
        self.assertEqual(self.mix(duplicate)[1], self.mix(unrelated)[1])

    def test_quiet_samples_survive_boost_before_rounding(self):
        _, rear = self.mix([[0, 0, 0, 0, 0, 0, 1, -1]] * 32, rear_db=38)
        self.assertTrue(all(v != 0 for v in rear))

    def test_silence_and_hot_input_are_bounded(self):
        self.assertEqual(self.mix([[0] * 8] * 32), ([0] * 64, [0] * 64))
        _, rear = self.mix([[32767] * 8, [-32768] * 8] * 16, rear_db=38)
        self.assertTrue(all(-32768 <= v <= 32767 for v in rear))
        self.assertTrue(0 < rear[0] < 32767)
        self.assertTrue(-32768 < rear[2] < 0)


if __name__ == '__main__':
    unittest.main()
