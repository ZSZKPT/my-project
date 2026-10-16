import contextlib
import io
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import windows_bootstrap as boot


class WindowsStartupTests(unittest.TestCase):
    def run_in_folder(self,folder):
        # main changes cwd, so restore it before TemporaryDirectory cleanup.
        import os
        before=Path.cwd()
        try:
            with patch.object(boot,'ROOT',Path(folder)),contextlib.redirect_stdout(io.StringIO()):
                return boot.main()
        finally:os.chdir(before)

    def test_old_python_logs_actionable_error_without_launching(self):
        with tempfile.TemporaryDirectory() as d,patch.object(boot.sys,'version_info',(3,11)),patch.object(boot.subprocess,'Popen') as spawn:
            self.assertEqual(self.run_in_folder(d),1)
            self.assertIn('Python 3.12 or newer',Path(d,'startup.log').read_text())
            spawn.assert_not_called()

    def test_install_failure_keeps_error_and_does_not_open_browser(self):
        with tempfile.TemporaryDirectory() as d,patch.object(boot.sys,'version_info',(3,12)),patch.object(boot.webbrowser,'open') as browser:
            python=Path(d,'.venv','Scripts','python.exe');python.parent.mkdir(parents=True);python.touch()
            failed=SimpleNamespace(stdout=iter(['Package download failed\n']),wait=lambda:1)
            with patch.object(boot.subprocess,'Popen',return_value=failed):
                self.assertEqual(self.run_in_folder(d),1)
            text=Path(d,'startup.log').read_text()
            self.assertIn('Package download failed',text);self.assertIn('STARTUP FAILED',text)
            browser.assert_not_called()

    def test_existing_healthy_server_opens_browser_without_duplicate_server(self):
        with tempfile.TemporaryDirectory() as d,patch.object(boot.sys,'version_info',(3,12)),patch.object(boot.webbrowser,'open') as browser:
            python=Path(d,'.venv','Scripts','python.exe');python.parent.mkdir(parents=True);python.touch()
            def process(*args,**kwargs):return SimpleNamespace(stdout=iter(['Dependencies OK\n']),wait=lambda:0)
            with patch.object(boot.subprocess,'Popen',side_effect=process) as spawn,patch.object(boot,'urlopen',side_effect=lambda *a,**k:io.BytesIO(b'{"ok":true,"app":"nesting"}')):
                self.assertEqual(self.run_in_folder(d),0)
                self.assertEqual(spawn.call_count,2)  # pip install + pip check, no duplicate server
            browser.assert_called_once_with('http://127.0.0.1:8765')


if __name__=='__main__':unittest.main()
