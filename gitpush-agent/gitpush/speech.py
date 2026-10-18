from __future__ import annotations
import json
import os
import queue
import threading
import time
from typing import Callable
from dataclasses import dataclass
from .config import Settings
from .parser import wake_matches, normalize


def wake_grammar(model, phrase: str) -> list[str]:
    words = normalize(phrase).replace('gitpush', 'git push').split()
    # Some small English models omit the word "git". Use its close pronunciation
    # only in the wake grammar, never to guess registered project names.
    grammar_words = [word if model.vosk_model_find_word(word) >= 0 else
                     'get' if word == 'git' and model.vosk_model_find_word('get') >= 0 else word
                     for word in words]
    missing = [word for word in grammar_words if model.vosk_model_find_word(word) < 0]
    if missing:
        raise RuntimeError('Wake words missing from this model: ' + ', '.join(missing) + '. Choose a supported phrase such as hey push in Voice & startup.')
    return [' '.join(grammar_words), '[unk]']


@dataclass(frozen=True)
class VoiceInfo:
    id: str
    name: str
    female: bool
    english: bool


def voice_catalog(engine) -> list[tuple[VoiceInfo, object]]:
    result = []
    tokens = engine.GetVoices()
    for index in range(tokens.Count):
        token = tokens.Item(index)
        def attribute(name):
            try:
                return str(token.GetAttribute(name))
            except Exception:
                return ''
        english = False
        for language in attribute('Language').split(';'):
            try:
                english = english or (int(language, 16) & 0x3ff) == 9
            except ValueError:
                pass
        result.append((VoiceInfo(str(token.Id), str(token.GetDescription()),
                                 attribute('Gender').lower() == 'female', english), token))
    return result


def select_voice(voices: list[VoiceInfo], requested: str = '') -> VoiceInfo | None:
    if requested:
        selected = next((voice for voice in voices if voice.id == requested), None)
        if selected:
            return selected
    female = [voice for voice in voices if voice.female]
    return next((voice for voice in female if voice.english), female[0] if female else None)


class SpeechOutput:
    def __init__(self, settings: Settings, error: Callable[[str], None],
                 catalog: Callable[[list[VoiceInfo]], None] = lambda _: None,
                 spoken: Callable[[str], None] = lambda _: None):
        self.settings, self.error, self.catalog, self.spoken = settings, error, catalog, spoken
        self.busy = threading.Event()
        self.items: queue.Queue[str | None] = queue.Queue()
        self._queue_lock = threading.Lock()
        self.thread = threading.Thread(target=self._run, daemon=True)
        self.thread.start()

    def say(self, text: str) -> None:
        with self._queue_lock:
            self.busy.set()
            self.items.put(text)

    def _run(self) -> None:
        voice = None
        com = None
        voices = []
        default_token = None
        last_selection = None
        try:
            if os.name == 'nt':
                import pythoncom
                import win32com.client
                pythoncom.CoInitialize()
                com = pythoncom
                voice = win32com.client.Dispatch('SAPI.SpVoice')
                default_token = voice.Voice
                voices = voice_catalog(voice)
                self.catalog([info for info, _ in voices])
            else:
                self.error('Windows SAPI speech output is unavailable on this operating system.')
        except Exception as exc:
            self.error(f'Speech synthesis unavailable: {type(exc).__name__}. Check installed Windows voices.')
        try:
            while True:
                text = self.items.get()
                if text is None:
                    break
                try:
                    if voice is not None:
                        if last_selection != self.settings.voice_id:
                            infos = [info for info, _ in voices]
                            selected = select_voice(infos, self.settings.voice_id)
                            if self.settings.voice_id and not any(info.id == self.settings.voice_id for info in infos):
                                self.error('The saved voice is no longer installed. Using the automatic female preference when available.')
                            if selected:
                                voice.Voice = next(token for info, token in voices if info.id == selected.id)
                            else:
                                voice.Voice = default_token
                                self.error('No female SAPI voice is installed. Using the Windows default. Install an offline female voice exposed to SAPI, then restart GitPush.')
                            last_selection = self.settings.voice_id
                        voice.Volume = self.settings.volume
                        voice.Rate = self.settings.rate
                        voice.Speak(text, 16)  # SVSFIsNotXML: literal text, with native voice prosody.
                        self.spoken(text)
                    else:
                        self.error('Speech output unavailable. Check offline Windows voices and pywin32; use manual controls meanwhile.')
                except Exception as exc:
                    self.error(f'Speech output failed: {type(exc).__name__}. Use manual controls and check your voice settings.')
                finally:
                    with self._queue_lock:
                        if self.items.empty():
                            self.busy.clear()
        finally:
            self.busy.clear()
            if com is not None:
                com.CoUninitialize()

    def close(self) -> None:
        self.items.put(None)


class VoiceListener:
    def __init__(self, settings: Settings, speech: SpeechOutput,
                 event: Callable[[str, str], None]):
        self.settings, self.speech, self.event = settings, speech, event
        self.mode = 'idle'
        self.generation = 0
        self._mode_lock = threading.Lock()
        self.stop_event = threading.Event()
        self.audio: queue.Queue[bytes] = queue.Queue(maxsize=20)
        self.thread: threading.Thread | None = None

    def set_mode(self, mode: str) -> None:
        with self._mode_lock:
            self.mode = mode
            self.generation += 1

    def start(self) -> None:
        if self.thread and self.thread.is_alive():
            return
        self.stop_event.clear()
        self.thread = threading.Thread(target=self._run, daemon=True)
        self.thread.start()

    def stop(self) -> None:
        self.stop_event.set()

    def _capture(self, data, frames, timing, status) -> None:
        if self.speech.busy.is_set() or self.mode == 'paused':
            return
        try:
            self.audio.put_nowait(bytes(data))
        except queue.Full:
            pass  # Bound memory; drop audio rather than block the microphone callback.

    def _run(self) -> None:
        try:
            import sounddevice as sd
            from vosk import Model, KaldiRecognizer
            if not self.settings.model_path:
                raise RuntimeError('Choose an extracted small Vosk English model in Setup.')
            model = Model(self.settings.model_path)  # Exactly one model instance per listener.
            grammar_phrases = wake_grammar(model, self.settings.wake_phrase)
            current_generation = -1
            recognizer = None
            deadline = time.monotonic()
            was_speaking = False
            with sd.RawInputStream(samplerate=16000, blocksize=4000, device=self.settings.microphone,
                                   dtype='int16', channels=1, callback=self._capture):
                self.event('microphone', 'Microphone active — offline wake listening')
                while not self.stop_event.is_set():
                    speaking = self.speech.busy.is_set()
                    if speaking or self.mode == 'paused':
                        was_speaking = True
                        while not self.audio.empty():
                            try:
                                self.audio.get_nowait()
                            except queue.Empty:
                                break
                        self.stop_event.wait(.05)
                        continue
                    if was_speaking:
                        current_generation = -1
                        was_speaking = False
                        # Discard queued speaker echo before restarting the recognizer.
                        while not self.audio.empty():
                            try:
                                self.audio.get_nowait()
                            except queue.Empty:
                                break
                    if current_generation != self.generation:
                        mode = self.mode
                        current_generation = self.generation
                        if mode == 'idle':
                            grammar = json.dumps(grammar_phrases)
                            recognizer = KaldiRecognizer(model, 16000, grammar)
                        else:
                            recognizer = KaldiRecognizer(model, 16000)
                        deadline = time.monotonic() + self.settings.command_timeout
                    try:
                        data = self.audio.get(timeout=.2)
                    except queue.Empty:
                        data = None
                    if data and recognizer.AcceptWaveform(data):
                        text = json.loads(recognizer.Result()).get('text', '').strip()
                        if mode == 'idle':
                            if wake_matches(text, grammar_phrases[0]):
                                self.set_mode('paused')
                                self.event('wake', text)
                        elif text:
                            self.set_mode('paused')
                            self.event('transcript', text)
                        else:
                            self.event('unclear', "I didn't catch that. Please repeat.")
                        deadline = time.monotonic() + self.settings.command_timeout
                    if mode != 'idle' and time.monotonic() > deadline:
                        self.set_mode('paused')
                        self.event('timeout', '')
                        deadline = float('inf')
        except Exception as exc:
            self.event('microphone_error', f'Microphone unavailable or model failed: {exc}. Check Windows Settings > Privacy > Microphone and the selected model.')
        finally:
            self.event('microphone', 'Microphone stopped')
