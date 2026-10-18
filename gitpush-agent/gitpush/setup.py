from __future__ import annotations
import os
import shutil
import ssl
import sys
import tempfile
import urllib.request
import zipfile
import time
from pathlib import Path
from .config import data_dir

MODEL_URL = 'https://alphacephei.com/vosk/models/vosk-model-small-en-us-0.15.zip'
MODEL_NAME = 'vosk-model-small-en-us-0.15'


def download_model(progress=lambda _: None, transfer=lambda received, total: None) -> Path:
    """Official HTTPS distribution, normal certificate verification, bounded extraction."""
    destination = data_dir() / 'models'
    destination.mkdir(exist_ok=True)
    final = destination / MODEL_NAME
    if (final / 'am' / 'final.mdl').is_file():
        return final
    with tempfile.TemporaryDirectory(dir=destination) as temporary:
        folder = Path(temporary)
        archive = folder / 'model.zip'
        progress('Downloading the small English model from alphacephei.com…')
        with urllib.request.urlopen(MODEL_URL, context=ssl.create_default_context(), timeout=60) as response, archive.open('wb') as output:
            size = response.headers.get('Content-Length')
            expected = int(size) if size and size.isdigit() else None
            total = 0
            last_update = 0.0
            while chunk := response.read(65536):
                total += len(chunk)
                if total > 100 * 1024 * 1024:
                    raise RuntimeError('Model download exceeds the expected size limit.')
                output.write(chunk)
                if time.monotonic() - last_update > .1:
                    transfer(total, expected)
                    last_update = time.monotonic()
            transfer(total, expected)
            if expected is not None and total != expected:
                raise RuntimeError('Model download was incomplete. Please retry.')
        progress('Download complete. Checking and extracting the offline voice model…')
        with zipfile.ZipFile(archive) as zipped:
            if sum(info.file_size for info in zipped.infolist()) > 250 * 1024 * 1024:
                raise RuntimeError('Model archive exceeds the extraction size limit.')
            for info in zipped.infolist():
                target = (folder / info.filename).resolve()
                if not target.is_relative_to(folder.resolve()) or info.external_attr >> 16 & 0o170000 == 0o120000:
                    raise RuntimeError('Unsafe model archive member.')
            zipped.extractall(folder)
        extracted = folder / MODEL_NAME
        if not (extracted / 'am' / 'final.mdl').is_file():
            raise RuntimeError('The downloaded archive is not the expected Vosk model.')
        if final.exists():
            raise RuntimeError('An incomplete model already exists. Select or remove it manually before downloading.')
        shutil.move(str(extracted), final)
    return final


def diagnostics(settings) -> list[str]:
    results = [f'Python {sys.version.split()[0]}: ' + ('OK' if sys.version_info >= (3, 11) else '3.11+ required'),
               'Git: ' + (shutil.which('git') or 'NOT FOUND — install Git for Windows'),
               'Windows offline SAPI: ' + ('available for testing' if os.name == 'nt' else 'requires Windows'),
               'Model: ' + ('found' if (Path(settings.model_path) / 'am' / 'final.mdl').is_file() else 'select or download model')]
    try:
        import sounddevice as sd
        from .windows import microphone_privacy_status
        results.append(microphone_privacy_status())
        device = sd.query_devices(settings.microphone, 'input')
        sd.check_input_settings(device=settings.microphone, channels=1, dtype='int16', samplerate=16000)
        with sd.RawInputStream(device=settings.microphone, channels=1, dtype='int16', samplerate=16000):
            results.append(f'Microphone: {device["name"]}; capture opened successfully (no audio saved)')
    except Exception as exc:
        results.append(f'Microphone check failed: {exc}. Check Windows microphone permission.')
    return results


def existing_model(configured: str = '') -> Path | None:
    candidates = [Path(configured)] if configured else []
    candidates.append(data_dir() / 'models' / MODEL_NAME)
    return next((path for path in candidates if (path / 'am' / 'final.mdl').is_file()), None)
