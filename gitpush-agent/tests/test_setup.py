import io
import os
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch
from gitpush.setup import download_model, existing_model, MODEL_NAME


class Response(io.BytesIO):
    def __init__(self, body, expected=None):
        super().__init__(body)
        self.headers = {'Content-Length': str(len(body) if expected is None else expected)}


class SetupTests(unittest.TestCase):
    def archive(self, name=None):
        output = io.BytesIO()
        with zipfile.ZipFile(output, 'w') as zipped:
            zipped.writestr(name or MODEL_NAME + '/am/final.mdl', b'test model fixture, not a production model')
        return output.getvalue()

    def test_actual_bytes_progress_and_reuse(self):
        with tempfile.TemporaryDirectory() as folder, patch.dict(os.environ, {'GITPUSH_DATA_DIR': folder}):
            payload = self.archive()
            progress, transfers = [], []
            with patch('gitpush.setup.urllib.request.urlopen', return_value=Response(payload)) as request:
                path = download_model(progress.append, lambda count, total: transfers.append((count, total)))
                self.assertEqual(transfers[-1], (len(payload), len(payload)))
                self.assertTrue(any('extracting' in item for item in progress))
                self.assertEqual(existing_model(), path)
                self.assertEqual(download_model(), path)
                request.assert_called_once()
                self.assertIsNotNone(request.call_args.kwargs['context'])

    def test_truncated_response_rejected(self):
        with tempfile.TemporaryDirectory() as folder, patch.dict(os.environ, {'GITPUSH_DATA_DIR': folder}), patch('gitpush.setup.urllib.request.urlopen', return_value=Response(self.archive(), expected=99999)):
            with self.assertRaisesRegex(RuntimeError, 'incomplete'):
                download_model()
            self.assertIsNone(existing_model())

    def test_archive_traversal_rejected(self):
        with tempfile.TemporaryDirectory() as folder, patch.dict(os.environ, {'GITPUSH_DATA_DIR': folder}), patch('gitpush.setup.urllib.request.urlopen', return_value=Response(self.archive('../escape'))):
            with self.assertRaisesRegex(RuntimeError, 'Unsafe'):
                download_model()
            self.assertFalse((Path(folder) / 'escape').exists())

    def test_configured_model_is_reused(self):
        with tempfile.TemporaryDirectory() as folder, patch.dict(os.environ, {'GITPUSH_DATA_DIR': folder}):
            model = Path(folder) / 'external'
            (model / 'am').mkdir(parents=True)
            (model / 'am' / 'final.mdl').write_bytes(b'fixture')
            self.assertEqual(existing_model(str(model)), model)

    def test_device_diagnostics_open_capture(self):
        import sys
        from unittest.mock import Mock
        from gitpush.config import Settings
        from gitpush.setup import diagnostics
        sd = Mock()
        sd.query_devices.return_value = {'name': 'Test microphone'}
        sd.RawInputStream.return_value.__enter__ = Mock()
        sd.RawInputStream.return_value.__exit__ = Mock()
        with patch.dict(sys.modules, {'sounddevice': sd}), patch('gitpush.windows.microphone_privacy_status', return_value='Privacy check fixture'):
            result = diagnostics(Settings())
        sd.RawInputStream.assert_called_once()
        self.assertTrue(any('capture opened successfully' in line for line in result))
