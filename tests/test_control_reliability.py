# SPDX-License-Identifier: GPL-2.0-or-later
"""Control-plane stalls must not mute audio or discard unconfirmed intent.

No network connections, playback controls or PCM devices are opened.
"""
import asyncio
import importlib.util
import json
from pathlib import Path
import os
import sys
import tempfile
import time
import unittest
from unittest.mock import AsyncMock, patch

APP = Path(__file__).resolve().parents[1] / 'app'
sys.path.insert(0, str(APP))
from coupled_trial import render_gain


def load_controller():
    with tempfile.TemporaryDirectory() as tmp:
        settings = Path(tmp) / 'site.json'
        settings.write_text(json.dumps({'native_homepod_ids': ['alpha', 'beta']}))
        with patch.dict(os.environ, {'PI_SURROUND_SETTINGS': str(settings)}):
            spec = importlib.util.spec_from_file_location('control_under_test', APP / 'native_master.py')
            result = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(result)
            return result


controller = load_controller()


class ControlReliabilityTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.enterContext(patch.object(controller, 'ROOT', self.root))
        self.enterContext(patch.object(controller, 'RT', self.root))
        self.enterContext(patch.object(controller, 'enabled', return_value=True))
        (self.root / 'settings.json').write_text(json.dumps({'front_level': 100}))

    def make_controller(self):
        c = controller.NativeController.__new__(controller.NativeController)
        c.command_path = self.root / 'command'
        c.command_path.write_text('-12')
        c.owned = True
        c.observed = time.monotonic()
        c.current_gain = .2
        c.gain_task = None
        return c

    async def test_control_wait_does_not_expire_gain_but_mute_and_route_loss_win(self):
        c = self.make_controller()
        c.set_gain(.2)
        task = asyncio.create_task(c.refresh_gain())
        try:
            # Longer than the two-second IPC expiry; route observation continues
            # while a native operation awaits its transport response.
            for _ in range(12):
                c.observed = time.monotonic()
                await asyncio.sleep(.2)
            path = self.root / 'coupled-rear-gain.json'
            self.assertEqual(render_gain(path), .2)
            c.command_path.write_text('-144')
            await asyncio.sleep(.15)
            self.assertEqual(render_gain(path), 0.)
            c.command_path.write_text('-12')
            c.set_gain(.2)
            c.owned = False
            await asyncio.sleep(.15)
            self.assertEqual(render_gain(path), 0.)
            c.owned = True
            c.observed = time.monotonic() - 4
            c.set_gain(.2)
            await asyncio.sleep(.15)
            self.assertEqual(render_gain(path), 0.)
        finally:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)

    async def test_failed_volume_request_retries_without_another_key(self):
        c = self.make_controller()
        c.command_path.write_text('-15')
        c.policy = controller.Policy(.6, -12, grace=0)
        c.failures = 0
        c.last_reconnect = c.last_stream_check = c.last_ok = time.monotonic()
        c.last_event = c.hold_reason = c.error = None
        c.trace = lambda *args, **kwargs: None
        c.close = AsyncMock()
        c.sync_streams = AsyncMock()
        c.read_native = AsyncMock(return_value=.6)
        retried = asyncio.Event()
        attempts = []

        async def write(target):
            attempts.append(target)
            if len(attempts) == 1:
                raise TimeoutError('Injected volume transport failure')
            retried.set()
            return target

        c.write_native = write
        task = asyncio.create_task(c.run())
        try:
            await asyncio.wait_for(retried.wait(), 1)
            self.assertEqual(attempts, [.5, .5])
        finally:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)

    async def test_unrefreshed_instruction_still_expires(self):
        path = self.root / 'gain'
        path.write_text(json.dumps({'timestamp': time.time() - 2.1, 'gain': .2}))
        self.assertEqual(render_gain(path), 0.)

    async def test_stop_cancels_publisher_and_leaves_zero_gain(self):
        c = self.make_controller()

        async def run():
            try:
                await asyncio.sleep(100)
            finally:
                c.gain_task.cancel()
                await asyncio.gather(c.gain_task, return_exceptions=True)

        c.run = run
        c.start()
        await asyncio.sleep(.05)
        c.stop()
        await asyncio.gather(c.task, c.gain_task, return_exceptions=True)
        self.assertTrue(c.gain_task.done())
        self.assertEqual(c.current_gain, 0.)
