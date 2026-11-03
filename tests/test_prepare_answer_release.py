"""The release candidate carries a wheel for every pinned package, so it installs offline."""
from pathlib import Path
import tempfile
import unittest

from tools import prepare_answer_release as release


class CopyDependenciesTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        root=Path(self.temp.name);self.source=root/'service';self.dest=root/'candidate'
        (self.source/'wheels').mkdir(parents=True);self.dest.mkdir()
        for name in ('python_hwpx-6.11.0-py3-none-any.whl','pycryptodome-4.2.0-cp39-abi3-win_amd64.whl',
                     'typing_extensions-4.16.0-py3-none-any.whl','unused-1.0-py3-none-any.whl'):
            (self.source/'wheels'/name).write_bytes(name.encode())
        (self.source/'requirements.txt').write_text('python-hwpx==6.11.0\n',encoding='utf-8')
        (self.dest/'requirements-travel.lock.txt').write_text('typing_extensions==4.16.0\n',encoding='utf-8')

    def lock(self,text):(self.source/'requirements-travel.lock.txt').write_text(text,encoding='utf-8')

    def test_wheels_added_after_the_first_release_are_shipped(self):
        self.lock('python-hwpx==6.11.0\npycryptodome==4.2.0\ntyping_extensions==4.16.0\n')
        release.copy_dependencies(self.source,self.dest)
        self.assertEqual(sorted(p.name for p in (self.dest/'wheels').iterdir()),
                         ['pycryptodome-4.2.0-cp39-abi3-win_amd64.whl','python_hwpx-6.11.0-py3-none-any.whl',
                          'typing_extensions-4.16.0-py3-none-any.whl'])
        self.assertIn('python-hwpx',(self.dest/'requirements-travel.lock.txt').read_text(encoding='utf-8'))
        self.assertIn('python-hwpx',(self.dest/'requirements.txt').read_text(encoding='utf-8'))

    def test_a_pinned_package_without_its_wheel_stops_the_release(self):
        for text in ('skdconv==1.0.5\n','python-hwpx==6.12.0\n'):
            with self.subTest(text=text):
                self.lock(text)
                with self.assertRaises(ValueError):release.copy_dependencies(self.source,self.dest)


if __name__=='__main__':
    unittest.main()
