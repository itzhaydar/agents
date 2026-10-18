from __future__ import annotations
import ctypes
import os
import subprocess
import sys
from pathlib import Path


class SingleInstance:
    def __init__(self):
        self.handle = None
        self.event = None

    def acquire(self) -> bool:
        if os.name != 'nt':
            # Used for development on Unix; Windows uses a per-session named mutex.
            import fcntl
            from .config import data_dir
            self.handle = (data_dir() / 'instance.lock').open('w')
            try:
                fcntl.flock(self.handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
                return True
            except BlockingIOError:
                return False
        kernel = ctypes.WinDLL('kernel32', use_last_error=True)
        kernel.CreateMutexW.restype = ctypes.c_void_p
        kernel.CreateEventW.restype = ctypes.c_void_p
        kernel.SetEvent.argtypes = [ctypes.c_void_p]
        self.handle = kernel.CreateMutexW(None, False, 'Local\\GitPushAgent.Instance')
        if not self.handle:
            raise OSError('Cannot create application mutex')
        exists = ctypes.get_last_error() == 183
        self.event = kernel.CreateEventW(None, False, False, 'Local\\GitPushAgent.Activate')
        if exists:
            kernel.SetEvent(self.event)
        return not exists

    def activation_requested(self) -> bool:
        if os.name != 'nt' or not self.event:
            return False
        kernel = ctypes.WinDLL('kernel32', use_last_error=True)
        kernel.WaitForSingleObject.argtypes = [ctypes.c_void_p, ctypes.c_uint]
        return kernel.WaitForSingleObject(self.event, 0) == 0

    def close(self) -> None:
        if os.name == 'nt':
            kernel = ctypes.WinDLL('kernel32', use_last_error=True)
            kernel.CloseHandle.argtypes = [ctypes.c_void_p]
            for handle in (self.event, self.handle):
                if handle:
                    kernel.CloseHandle(handle)
        elif self.handle:
            self.handle.close()


def startup_enabled() -> bool:
    if os.name != 'nt':
        return False
    import winreg
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r'Software\Microsoft\Windows\CurrentVersion\Run') as key:
            winreg.QueryValueEx(key, 'GitPushAgent')
        return True
    except FileNotFoundError:
        return False


def set_startup(enabled: bool) -> None:
    if os.name != 'nt':
        raise RuntimeError('Sign-in startup is available only on Windows.')
    import winreg
    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, r'Software\Microsoft\Windows\CurrentVersion\Run') as key:
        if enabled:
            if getattr(sys, 'frozen', False):
                arguments = [sys.executable, '--background']
            else:
                pythonw = Path(sys.executable).with_name('pythonw.exe')
                arguments = [str(pythonw if pythonw.exists() else Path(sys.executable)),
                             str(Path(__file__).resolve().parent.parent / 'main.py'), '--background']
            winreg.SetValueEx(key, 'GitPushAgent', 0, winreg.REG_SZ, subprocess.list2cmdline(arguments))
        else:
            try:
                winreg.DeleteValue(key, 'GitPushAgent')
            except FileNotFoundError:
                pass


def open_microphone_settings() -> None:
    if os.name != 'nt':
        raise RuntimeError('Windows microphone settings are available on Windows only.')
    os.startfile('ms-settings:privacy-microphone')


def microphone_privacy_status() -> str:
    if os.name != 'nt':
        return 'Microphone privacy: managed by the operating system'
    import winreg
    try:
        base = r'Software\Microsoft\Windows\CurrentVersion\CapabilityAccessManager\ConsentStore\microphone'
        for suffix in ('', r'\NonPackaged'):
            try:
                with winreg.OpenKey(winreg.HKEY_CURRENT_USER, base + suffix) as key:
                    value, _ = winreg.QueryValueEx(key, 'Value')
                    if str(value).lower() == 'deny':
                        return 'Windows microphone privacy: blocked. Enable microphone and desktop-app access in Windows Settings.'
            except FileNotFoundError:
                pass
        return 'Windows microphone privacy: capture must be tested; desktop apps do not always show an individual permission prompt.'
    except OSError:
        return 'Windows microphone privacy: setting unavailable or managed by policy; test capture and check Windows Settings.'
