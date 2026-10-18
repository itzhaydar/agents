import queue
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch, Mock
from gitpush.config import Project, Settings
from gitpush.parser import parse, wake_matches, commit_message
from gitpush.controller import Controller
from gitpush.git_manager import Plan
from gitpush.speech import VoiceListener


class CommandTests(unittest.TestCase):
    def setUp(self):
        self.portfolio = Project('portfolio', '/portfolio', ['my portfolio', 'portfolio project'])
        self.marshout = Project('Marshout', '/marshout')
        self.projects = [self.portfolio, self.marshout]

    def test_examples(self):
        examples = [
            ('We updated the portfolio folder and fixed the mobile CV layout. Push the changes.', 'Fix mobile CV layout'),
            ('We updated portfolio and fixed the mobile CV layout. Push the changes.', 'Fix mobile CV layout'),
            ('Push Marshout. Added new flight controls.', 'Add new flight controls'),
            ('Push changes in portfolio. Added a contact section.', 'Add a contact section'),
            ('Commit and push portfolio. Fixed responsive navigation.', 'Fix responsive navigation'),
            ('Push my portfolio project. Updated the CV.', 'Update CV'),
            ('We updated Marshout and improved the flight animation. Push the changes.', 'Improve flight animation'),
        ]
        for text, expected in examples:
            with self.subTest(text=text):
                command = parse(text, self.projects)
                self.assertEqual(command.action, 'push')
                self.assertEqual(len(command.projects), 1)
                self.assertEqual(command.message, expected)

    def test_no_invented_message(self):
        self.assertEqual(parse('Push portfolio', self.projects).message, '')
        self.assertEqual(commit_message('hello world', self.projects), '')

    def test_alias_boundary(self):
        self.assertEqual(parse('Push my portfolio project. Fixed layout', self.projects).projects, [self.portfolio])
        self.assertFalse(parse('Push portfolios', self.projects).projects)

    def test_ambiguous_project(self):
        self.marshout.aliases = ['portfolio']
        self.assertEqual(len(parse('Push portfolio', self.projects).projects), 2)

    def test_controls(self):
        for text, action in [('Confirm push.', 'confirm'), ('Cancel!', 'cancel'), ('Stop listening', 'stop'), ('Close GitPush', 'close'), ("What's the status?", 'status')]:
            self.assertEqual(parse(text, self.projects).action, action)
        self.assertNotEqual(parse('maybe confirm push later', self.projects).action, 'confirm')

    def test_wake(self):
        for text in ['Hey GitPush!', 'hey git push']:
            self.assertTrue(wake_matches(text, 'hey git push'))
        for text in ['', 'git push', 'they git push', 'hey git push my changes']:
            self.assertFalse(wake_matches(text, 'hey git push'))

    def test_config_roundtrip(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'config.json'
            settings = Settings(projects=self.projects)
            settings.save(path)
            self.assertEqual(Settings.load(path), settings)
            settings.save(path)
            self.assertEqual(Settings.load(path), settings)


class ControllerTests(unittest.TestCase):
    def setUp(self):
        self.events = queue.Queue()
        self.responses = []
        self.executed = []
        self.settings = Settings(projects=[Project('portfolio', '/portfolio')])
        self.controller = Controller(self.settings, lambda k, v: self.events.put((k, v)), self.responses.append, lambda _: None, self.executed.append)
        self.plan = Plan('portfolio', '/portfolio', 'topic', 'origin/topic', 'Fix layout', ('file.txt',), (), (), (), 0, 'hash')

    def await_event(self, kind):
        while True:
            event, value = self.events.get(timeout=2)
            if event == kind:
                return value

    def test_cancel_does_not_execute(self):
        self.controller.receive('prepared', self.plan)
        self.controller.handle('cancel')
        self.assertEqual(self.controller.state, 'IDLE')
        self.assertFalse(self.executed)
        self.assertIn('Push cancelled.', self.responses)

    def test_silence_cancels(self):
        self.controller.receive('prepared', self.plan)
        self.controller.expires = time.monotonic() - 1
        self.controller.tick()
        self.assertIsNone(self.controller.plan)
        self.assertFalse(self.executed)

    def test_exact_confirmation_executes_once(self):
        self.controller.receive('prepared', self.plan)
        self.controller.handle('confirm push')
        self.controller.handle('confirm push')
        self.await_event('done')
        self.assertEqual(self.executed, [self.plan])

    def test_uncertain_confirmation_does_not_execute(self):
        self.controller.receive('prepared', self.plan)
        self.controller.handle('maybe confirm push later')
        self.assertFalse(self.executed)

    def test_confirmation_without_plan(self):
        self.controller.handle('confirm push')
        self.assertFalse(self.executed)

    def test_no_change_voice(self):
        plan = Plan('portfolio', '/portfolio', 'topic', 'origin/topic', '', (), (), (), (), 0, 'hash')
        self.controller.receive('prepared', plan)
        self.assertIn('No changes to push.', self.responses)
        self.assertEqual(self.controller.state, 'IDLE')

    def test_push_failure_voice(self):
        self.controller.receive('failed', 'rejected')
        self.assertIn('Changes not pushed. Check the files.', self.responses)

    def test_push_success_voice(self):
        self.controller.receive('done', 'Changes pushed successfully!')
        self.assertIn('Changes pushed successfully!', self.responses)

    def test_unknown_project(self):
        self.controller.handle('Push unknown. Fixed layout')
        self.assertIn("I couldn't find that project.", self.responses)

    def test_stop(self):
        modes = []
        self.controller.mode = modes.append
        self.controller.handle('stop listening')
        self.assertEqual(modes[-1], 'stop')
        self.assertEqual(self.controller.state, 'STOPPED')

    def test_speaking_extends_confirmation_timeout(self):
        self.controller.receive('prepared', self.plan)
        self.controller.expires = time.monotonic() - 1
        self.controller.tick(speaking=True)
        self.assertIsNotNone(self.controller.plan)

    def test_transcription_audio_bounded_and_paused(self):
        speech = Mock()
        speech.busy.is_set.return_value = True
        listener = VoiceListener(self.settings, speech, lambda *_: None)
        listener._capture(b'voice', 1, None, None)
        self.assertTrue(listener.audio.empty())
        speech.busy.is_set.return_value = False
        for _ in range(50):
            listener._capture(b'voice', 1, None, None)
        self.assertEqual(listener.audio.qsize(), 20)

    def test_new_unknown_request_invalidates_old_confirmation(self):
        self.controller.receive('prepared', self.plan)
        self.controller.handle('Push unknown. Fixed layout')
        self.controller.handle('confirm push')
        self.assertFalse(self.executed)

    def test_ambiguous_project_spoken_selection(self):
        projects = [Project('Portfolio', '/one', ['site']), Project('Marshout', '/two', ['site'])]
        self.settings.projects = projects
        self.controller.handle('Push site. Fixed layout')
        self.assertEqual(self.controller.candidates, projects)
        with patch('gitpush.controller.GitManager') as manager:
            manager.return_value.prepare.return_value = self.plan
            self.controller.handle('Portfolio')
            self.await_event('prepared')
            manager.return_value.prepare.assert_called_once_with(projects[0], 'Fix layout')

    def test_wake_grammar_handles_missing_git_vocabulary(self):
        from gitpush.speech import wake_grammar
        model = Mock()
        model.vosk_model_find_word.side_effect = lambda word: -1 if word == 'git' else 1
        self.assertEqual(wake_grammar(model, 'hey git push'), ['hey get push', '[unk]'])
        model.vosk_model_find_word.return_value = -1
        model.vosk_model_find_word.side_effect = None
        with self.assertRaisesRegex(RuntimeError, 'Wake words missing'):
            wake_grammar(model, 'hey git push')

    def test_recognition_pipeline_uses_one_model(self):
        import sys
        import types
        self.settings.model_path = '/model'
        events = []
        speech = Mock()
        speech.busy.is_set.return_value = False
        listener = VoiceListener(self.settings, speech, lambda k, v: events.append((k, v)))
        model = Mock()
        model.vosk_model_find_word.return_value = 1
        model_factory = Mock(return_value=model)
        recognizer = Mock()
        recognizer.AcceptWaveform.return_value = True
        recognizer.Result.return_value = '{"text": "hey git push"}'
        def publish(kind, value):
            events.append((kind, value))
            if kind == 'wake':
                listener.set_mode('command')
                recognizer.Result.return_value = '{"text": "push portfolio fixed layout"}'
                listener.audio.put(b'audio')
            elif kind == 'transcript':
                listener.stop()
        listener.event = publish
        class Stream:
            def __init__(self, **kwargs):
                self.callback = kwargs['callback']
            def __enter__(self):
                self.callback(b'audio', 1, None, None)
                return self
            def __exit__(self, *args):
                pass
        factory = Mock(return_value=recognizer)
        with patch.dict(sys.modules, {'vosk': types.SimpleNamespace(Model=model_factory, KaldiRecognizer=factory), 'sounddevice': types.SimpleNamespace(RawInputStream=Stream)}):
            listener._run()
        model_factory.assert_called_once_with('/model')
        self.assertEqual(len(factory.call_args_list), 2)
        self.assertEqual(len(factory.call_args_list[0].args), 3)
        self.assertEqual(len(factory.call_args_list[1].args), 2)
        self.assertIn(('transcript', 'push portfolio fixed layout'), events)

    def test_unavailable_speech_does_not_leave_recognition_paused(self):
        import os
        import threading
        from gitpush.speech import SpeechOutput
        if os.name == 'nt':
            self.skipTest('This fixture tests the explicit non-Windows fallback')
        errors = []
        speech = SpeechOutput(self.settings, errors.append)
        try:
            speech.say('First')
            speech.say('Second')
            end = time.monotonic() + 2
            while speech.busy.is_set() and time.monotonic() < end:
                threading.Event().wait(.01)
            self.assertFalse(speech.busy.is_set())
            self.assertTrue(errors)
            self.assertTrue(speech.thread.is_alive())
        finally:
            speech.close()
            speech.thread.join(timeout=2)

    def test_discovered_project_is_used_without_registration(self):
        discovered = Project('flight app', '/workspace/flight-app')
        self.settings.projects = []
        self.controller.discovered_projects = [discovered]
        with patch('gitpush.controller.GitManager') as manager:
            manager.return_value.prepare.return_value = self.plan
            self.controller.handle('Push flight app. Added flight controls.')
            self.await_event('prepared')
            manager.return_value.prepare.assert_called_once_with(discovered, 'Add flight controls')

    def test_duplicate_discovered_names_resolved_by_spoken_number(self):
        first, second = Project('portfolio', '/client/portfolio'), Project('portfolio', '/personal/portfolio')
        self.settings.projects = []
        self.controller.discovered_projects = [first, second]
        self.controller.handle('Push portfolio. Fixed mobile layout.')
        self.assertIn('/client/portfolio', self.responses[-1])
        self.assertFalse(self.executed)
        with patch('gitpush.controller.GitManager') as manager:
            manager.return_value.prepare.return_value = self.plan
            self.controller.handle('option two')
            self.await_event('prepared')
            manager.return_value.prepare.assert_called_once_with(second, 'Fix mobile layout')
