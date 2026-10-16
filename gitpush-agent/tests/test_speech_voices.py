import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock
from gitpush.config import Settings
from gitpush.speech import VoiceInfo, select_voice, voice_catalog


class VoiceTests(unittest.TestCase):
    def test_prefers_english_female_over_default_male(self):
        david = VoiceInfo('david', 'Microsoft David', False, True)
        other = VoiceInfo('other', 'French female', True, False)
        zira = VoiceInfo('zira', 'Microsoft Zira', True, True)
        self.assertEqual(select_voice([david, other, zira]), zira)

    def test_explicit_user_selection_is_preserved(self):
        first = VoiceInfo('one', 'First female', True, True)
        second = VoiceInfo('two', 'Second female', True, True)
        self.assertEqual(select_voice([first, second], 'two'), second)

    def test_missing_saved_voice_falls_back_to_female(self):
        female = VoiceInfo('zira', 'Microsoft Zira', True, True)
        self.assertEqual(select_voice([female], 'removed'), female)

    def test_no_female_leaves_windows_default(self):
        self.assertIsNone(select_voice([VoiceInfo('male', 'Male', False, True)]))
        self.assertIsNone(select_voice([]))

    def test_catalog_uses_gender_and_language_metadata(self):
        token = Mock()
        token.Id = 'zira'
        token.GetDescription.return_value = 'Microsoft Zira Desktop'
        token.GetAttribute.side_effect = lambda key: {'Gender': 'Female', 'Language': '809;409'}[key]
        engine = Mock()
        engine.GetVoices.return_value.Count = 1
        engine.GetVoices.return_value.Item.return_value = token
        catalog = voice_catalog(engine)
        self.assertEqual(catalog, [(VoiceInfo('zira', 'Microsoft Zira Desktop', True, True), token)])

    def test_missing_metadata_does_not_crash(self):
        token = Mock()
        token.Id = 'unknown'
        token.GetDescription.return_value = 'Unknown'
        token.GetAttribute.side_effect = RuntimeError('missing attribute')
        engine = Mock()
        engine.GetVoices.return_value.Count = 1
        engine.GetVoices.return_value.Item.return_value = token
        self.assertEqual(voice_catalog(engine)[0][0], VoiceInfo('unknown', 'Unknown', False, False))

    def test_voice_and_pace_persist_without_overriding_existing_rate(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'config.json'
            settings = Settings(voice_id='zira', rate=0)
            settings.save(path)
            loaded = Settings.load(path)
            self.assertEqual(loaded.voice_id, 'zira')
            self.assertEqual(loaded.rate, 0)
            self.assertEqual(Settings().rate, -1)

    def test_old_config_automatically_prefers_female(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'config.json'
            path.write_text('{"rate": 0, "volume": 90}')
            self.assertEqual(Settings.load(path).voice_id, '')

    def test_speech_worker_selects_female_and_uses_plain_text(self):
        import sys
        import types
        import threading
        from unittest.mock import patch
        from gitpush.speech import SpeechOutput
        male = Mock()
        male.Id = 'david'
        male.GetDescription.return_value = 'David'
        male.GetAttribute.side_effect = lambda key: {'Gender': 'Male', 'Language': '409'}[key]
        female = Mock()
        female.Id = 'zira'
        female.GetDescription.return_value = 'Zira'
        female.GetAttribute.side_effect = lambda key: {'Gender': 'Female', 'Language': '409'}[key]
        engine = Mock()
        engine.Voice = male
        engine.GetVoices.return_value.Count = 2
        engine.GetVoices.return_value.Item.side_effect = [male, female]
        spoken = threading.Event()
        engine.Speak.side_effect = lambda *args: spoken.set()
        client = types.ModuleType('win32com.client')
        client.Dispatch = Mock(return_value=engine)
        package = types.ModuleType('win32com')
        package.client = client
        com = types.SimpleNamespace(CoInitialize=Mock(), CoUninitialize=Mock())
        errors, catalogs = [], []
        with patch.dict(sys.modules, {'pythoncom': com, 'win32com': package, 'win32com.client': client}), patch('gitpush.speech.os.name', 'nt'):
            speech = SpeechOutput(Settings(), errors.append, catalogs.append)
            try:
                speech.say('Ready to push <project>.')
                self.assertTrue(spoken.wait(timeout=2))
            finally:
                speech.close()
                speech.thread.join(timeout=2)
        self.assertEqual(engine.Voice, female)
        self.assertEqual(engine.Rate, -1)
        engine.Speak.assert_called_once_with('Ready to push <project>.', 16)
        self.assertFalse(errors)
        self.assertEqual(len(catalogs[0]), 2)
        com.CoUninitialize.assert_called_once()
