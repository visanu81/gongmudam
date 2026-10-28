import importlib.util
from pathlib import Path
import socket
import unittest

spec = importlib.util.spec_from_file_location('local_run', Path(__file__).resolve().parents[1] / 'tools/run_local_app.py')
local = importlib.util.module_from_spec(spec)
spec.loader.exec_module(local)


class LocalRunTest(unittest.TestCase):
    def test_browser_readiness_requires_expected_private_app(self):
        value = dict(status='ok', service_version='v72', desktop_connected=True, public_demo=False)
        self.assertTrue(local.ready(value, 'v72'))
        self.assertFalse(local.ready(value, 'other'))
        self.assertFalse(local.ready(value | {'public_demo': True}, 'v72'))
        self.assertFalse(local.ready(value | {'desktop_connected': False}, 'v72'))

    def test_existing_port_is_not_silently_reused(self):
        with socket.socket() as server:
            server.bind(('127.0.0.1', 0))
            server.listen()
            with self.assertRaisesRegex(RuntimeError, 'in use'):
                local.free_port(server.getsockname()[1])


if __name__ == '__main__':
    unittest.main()
