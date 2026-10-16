from __future__ import annotations
import argparse
import logging
from logging.handlers import RotatingFileHandler
import multiprocessing
import sys


def main() -> int:
    if sys.version_info < (3, 11):
        raise SystemExit('GitPush Agent requires Python 3.11 or newer.')
    parser = argparse.ArgumentParser(description='GitPush Agent — offline Windows voice Git assistant')
    parser.add_argument('--background', action='store_true', help='Start minimized, with observable microphone indicator')
    parser.add_argument('--terminal', metavar='LOG', help=argparse.SUPPRESS)
    parser.add_argument('--diagnose', action='store_true', help='Check local prerequisites without launching the GUI')
    args = parser.parse_args()
    if args.terminal:
        from gitpush.terminal import view
        view(args.terminal)
        return 0
    from gitpush.config import Settings, data_dir
    try:
        settings = Settings.load()
    except (ValueError, TypeError, OSError) as exc:
        if args.diagnose:
            print(f'Cannot load configuration: {exc}', file=sys.stderr)
            return 1
        import tkinter as tk
        from tkinter import messagebox
        root = tk.Tk()
        root.withdraw()
        messagebox.showerror('Configuration error', f'Cannot load config.json: {exc}. Back up and correct the configuration in {data_dir()}.')
        root.destroy()
        return 1
    if args.diagnose:
        from gitpush.setup import diagnostics
        print('\n'.join(diagnostics(settings)))
        return 0
    handler = RotatingFileHandler(data_dir() / 'agent.log', maxBytes=1_000_000, backupCount=3, encoding='utf-8')
    handler.setFormatter(logging.Formatter('%(asctime)s %(levelname)s %(message)s'))
    logger = logging.getLogger('gitpush')
    logger.setLevel(logging.INFO)
    logger.addHandler(handler)
    from gitpush.windows import SingleInstance
    instance = SingleInstance()
    if not instance.acquire():
        instance.close()
        return 0
    try:
        import tkinter as tk
        from gitpush.gui import Application
        root = tk.Tk()
        Application(root, settings, instance, args.background)
        root.mainloop()
    finally:
        instance.close()
        handler.close()
    return 0


if __name__ == '__main__':
    multiprocessing.freeze_support()
    raise SystemExit(main())
