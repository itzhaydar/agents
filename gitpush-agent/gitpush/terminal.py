from __future__ import annotations
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path
from .config import data_dir


class Terminal:
    """Read-only console viewer. Git runs once, in the application worker."""
    def __init__(self):
        self.path: Path | None = None
        self.stream = None

    def open(self) -> None:
        path = data_dir() / f'terminal-{time.time_ns()}.log'
        self.path = path
        self.stream = path.open('w', encoding='utf-8', buffering=1)
        if os.name == 'nt':
            if getattr(sys, 'frozen', False):
                args = [sys.executable, '--terminal', str(path)]
            else:
                interpreter = Path(sys.executable)
                if os.name == 'nt' and interpreter.name.lower() == 'pythonw.exe':
                    interpreter = interpreter.with_name('python.exe')
                args = [str(interpreter), str(Path(__file__).resolve().parent.parent / 'main.py'), '--terminal', str(path)]
            windows_terminal = shutil.which('wt.exe')
            if windows_terminal:
                try:
                    launcher = subprocess.Popen([windows_terminal, '-w', 'new', 'new-tab', '--title', 'GitPush Agent', '--', *args])
                    try:
                        if launcher.wait(timeout=.5) == 0:
                            return
                    except subprocess.TimeoutExpired:
                        return
                except OSError:
                    pass
            # Native console fallback, without command-shell interpolation.
            subprocess.Popen(args, creationflags=subprocess.CREATE_NEW_CONSOLE)

    def write(self, text: str) -> None:
        if self.stream:
            self.stream.write(text + '\n')

    def close(self) -> None:
        if self.stream:
            self.stream.write('\n[GITPUSH FINISHED]\n')
            self.stream.close()
            self.stream = None
        # Retain only ten sanitized terminal transcripts.
        for path in sorted(data_dir().glob('terminal-*.log'), reverse=True)[10:]:
            try:
                path.unlink()
            except OSError:
                pass


def view(path: str) -> None:
    if os.name == 'nt' and (sys.stdout is None or sys.stdin is None):
        # Windowed PyInstaller builds have no standard handles. Attach a real console.
        import ctypes
        ctypes.windll.kernel32.AllocConsole()
        sys.stdout = open('CONOUT$', 'w', encoding='utf-8', buffering=1)
        sys.stderr = sys.stdout
        sys.stdin = open('CONIN$', 'r', encoding='utf-8')
    print('GitPush Agent — live Git output\n')
    with Path(path).open(encoding='utf-8') as stream:
        while True:
            line = stream.readline()
            if line:
                print(line, end='', flush=True)
                if line.strip() == '[GITPUSH FINISHED]':
                    break
            else:
                time.sleep(.1)
    input('\nPress Enter to close this terminal (GitPush remains hands-free).')
