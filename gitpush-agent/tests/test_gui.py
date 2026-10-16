"""Optional real-Tk smoke test; requires a display, uses only local Git remotes."""
import os
import subprocess
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import Mock, patch
from gitpush.config import Project, Settings


@unittest.skipUnless(os.name == 'nt' or os.environ.get('DISPLAY'), 'GUI test needs a display')
class GuiTests(unittest.TestCase):
    def test_manual_preview_confirm_and_real_push(self):
        import tkinter as tk
        from gitpush.gui import Application
        with tempfile.TemporaryDirectory() as folder:
            base = Path(folder)
            root_path = base / 'project'
            root_path.mkdir()
            remote = base / 'remote.git'
            def git(path, *args):
                return subprocess.run(['git', *args], cwd=path, check=True, capture_output=True).stdout.decode().strip()
            git(base, 'init', '--bare', str(remote))
            git(root_path, 'init', '-b', 'feature')
            git(root_path, 'config', 'user.name', 'GUI test')
            git(root_path, 'config', 'user.email', 'gui@example.invalid')
            file = root_path / 'layout.txt'
            file.write_text('original')
            git(root_path, 'add', '.')
            git(root_path, 'commit', '-m', 'Initial')
            git(root_path, 'remote', 'add', 'origin', str(remote))
            git(root_path, 'push', '-u', 'origin', 'feature')
            file.write_text('fixed')
            settings = Settings(projects=[Project('sample', str(root_path))])
            instance = Mock()
            instance.activation_requested.return_value = False
            with patch.dict(os.environ, {'GITPUSH_DATA_DIR': str(base / 'data')}), patch('gitpush.gui.SpeechOutput') as speech, patch('gitpush.gui.VoiceListener'), patch('gitpush.gui.Terminal'):
                speech.return_value.busy.is_set.return_value = False
                root = tk.Tk()
                app = Application(root, settings, instance)
                try:
                    def wait_for(predicate):
                        deadline = time.monotonic() + 10
                        while not predicate() and time.monotonic() < deadline:
                            root.update()
                            threading.Event().wait(.01)
                        self.assertTrue(predicate(), app.result.get())
                    root.update()
                    self.assertEqual(app.tabs.index('end'), 4)
                    app.manual.insert(0, 'Push sample. Fixed layout.')
                    app.submit()
                    wait_for(lambda: app.controller.state == 'AWAITING_CONFIRMATION')
                    self.assertEqual(app.message_label.get(), 'Fix layout')
                    self.assertIn('layout.txt', app.output.get('1.0', 'end'))
                    app.controller.handle('confirm push')
                    wait_for(lambda: app.result.get() == 'Changes pushed successfully!')
                    self.assertEqual(git(root_path, 'rev-parse', 'HEAD'), git(remote, 'rev-parse', 'feature'))
                    self.assertEqual(app.controller.state, 'IDLE')
                    speech.return_value.say.assert_any_call('Changes pushed successfully!')
                finally:
                    app.close()
