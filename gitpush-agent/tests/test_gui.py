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
            settings = Settings(search_roots=[str(base)])
            # Discover this unregistered repository by its spoken folder name.
            root_path.rename(base / 'sample')
            root_path = base / 'sample'
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
                    wait_for(lambda: bool(app.controller.discovered_projects))
                    self.assertFalse(app.settings.projects)
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

    def test_setup_feedback_visible_on_small_windows(self):
        import tkinter as tk
        from gitpush.gui import Application
        with tempfile.TemporaryDirectory() as folder, patch.dict(os.environ, {'GITPUSH_DATA_DIR': folder}), patch('gitpush.gui.SpeechOutput') as speech, patch('gitpush.gui.VoiceListener'), patch('gitpush.gui.diagnostics', return_value=['Python: OK', 'Microphone: missing']), patch('gitpush.gui.download_model', side_effect=RuntimeError('Network unavailable')):
            speech.return_value.busy.is_set.return_value = False
            instance = Mock()
            instance.activation_requested.return_value = False
            root = tk.Tk()
            app = Application(root, Settings(search_roots=[folder]), instance)
            try:
                def wait_for(predicate):
                    deadline = time.monotonic() + 5
                    while not predicate() and time.monotonic() < deadline:
                        root.update()
                        threading.Event().wait(.01)
                    self.assertTrue(predicate())
                for size in ['1280x680', '740x600']:
                    root.geometry(size)
                    root.update()
                    self.assertGreater(app.setup_output.winfo_height(), 80)
                    self.assertGreater(app.setup_output.winfo_width(), 100)
                    page_bottom = app.setup_tab.winfo_rooty() + app.setup_tab.winfo_height()
                    self.assertLess(app.setup_output.winfo_rooty() + app.setup_output.winfo_height(), page_bottom)
                    for button in app.check_button.master.winfo_children():
                        self.assertLessEqual(button.winfo_rooty() + button.winfo_height(), page_bottom)
                app.check_devices()
                self.assertIn('Checking', app.check_text.get())
                self.assertEqual(str(app.check_button['state']), 'disabled')
                wait_for(lambda: app.setup_task is None)
                self.assertIn('Microphone: missing', app.setup_output.get('1.0', 'end'))
                self.assertEqual(str(app.check_button['state']), 'normal')
                app.download()
                self.assertIn('Downloading', app.check_text.get())
                wait_for(lambda: app.setup_task is None)
                self.assertIn('Network unavailable', app.setup_output.get('1.0', 'end'))
                app.test_voice()
                speech.return_value.say.assert_called_with('GitPush Agent is using your local Windows voice.')
                self.assertIn('Voice test requested', app.check_text.get())
                app.emit('error', 'Speech unavailable')
                wait_for(lambda: app.check_text.get() == 'Speech unavailable')
                app.open_projects()
                self.assertEqual(app.tabs.select(), str(app.projects_tab))
                app.open_voice_settings()
                self.assertEqual(app.tabs.select(), str(app.settings_tab))
                self.assertIn('Save settings', app.result.get())
            finally:
                app.close()
