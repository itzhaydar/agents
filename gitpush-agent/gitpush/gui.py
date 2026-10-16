from __future__ import annotations
import logging
import os
import queue
import threading
import tkinter as tk
from pathlib import Path
from tkinter import ttk, filedialog, messagebox
from .config import Project, Settings
from .controller import Controller
from .git_manager import GitManager, Plan, sanitize
from .parser import normalize
from .setup import diagnostics, download_model
from .speech import SpeechOutput, VoiceListener
from .terminal import Terminal
from .windows import SingleInstance, set_startup, startup_enabled


class Application:
    def __init__(self, root: tk.Tk, settings: Settings, instance: SingleInstance, background: bool = False):
        self.root, self.settings, self.instance = root, settings, instance
        self.events: queue.Queue[tuple[str, object]] = queue.Queue()
        self.log = logging.getLogger('gitpush')
        self.terminal = Terminal()
        self.speech = SpeechOutput(settings, lambda value: self.emit('error', value),
                                   lambda voices: self.emit('voices', voices))
        self.listener = VoiceListener(settings, self.speech, self.emit)
        self.controller = Controller(settings, self.emit, self.say, self.mode, self.execute)
        root.title('GitPush Agent')
        root.geometry('960x740')
        root.minsize(740, 600)
        root.configure(bg='#101827')
        style = ttk.Style(root)
        style.theme_use('clam')
        style.configure('.', font=('Segoe UI', 10))
        style.configure('TFrame', background='#101827')
        style.configure('TLabel', background='#101827', foreground='#e2e8f0')
        style.configure('TButton', padding=(12, 7))
        style.configure('TCheckbutton', background='#101827', foreground='#e2e8f0')
        self.state = tk.StringVar(value='IDLE')
        self.mic = tk.StringVar(value='Microphone stopped')
        self.result = tk.StringVar(value='Register a project and complete Setup to begin.')
        header = ttk.Frame(root, padding=18)
        header.pack(fill='x')
        ttk.Label(header, text='GitPush Agent', font=('Segoe UI', 23, 'bold')).pack(side='left')
        ttk.Label(header, textvariable=self.state).pack(side='right')
        ttk.Label(root, textvariable=self.mic, padding=(18, 0)).pack(anchor='w')
        self.tabs = ttk.Notebook(root)
        self.tabs.pack(fill='both', expand=True, padx=18, pady=12)
        self.dashboard = ttk.Frame(self.tabs, padding=14)
        self.projects_tab = ttk.Frame(self.tabs, padding=14)
        self.settings_tab = ttk.Frame(self.tabs, padding=14)
        self.setup_tab = ttk.Frame(self.tabs, padding=14)
        for tab, title in [(self.dashboard, 'Activity'), (self.projects_tab, 'Projects'),
                           (self.settings_tab, 'Voice & startup'), (self.setup_tab, 'First-run setup')]:
            self.tabs.add(tab, text=title)
        self.build_dashboard()
        self.build_projects()
        self.build_settings()
        self.build_setup()
        root.protocol('WM_DELETE_WINDOW', self.close)
        root.after(100, self.drain)
        if not settings.projects or not settings.model_path:
            self.tabs.select(self.setup_tab)
        elif settings.model_path:
            self.listener.start()
        if background:
            root.iconify()  # Observable taskbar indicator; microphone never runs invisibly.

    def emit(self, kind: str, value: object) -> None:
        self.events.put((kind, value))

    def say(self, text: str) -> None:
        self.emit('output', text)
        self.speech.say(text)

    def mode(self, mode: str) -> None:
        if mode == 'stop':
            self.listener.stop()
        else:
            self.listener.set_mode(mode)

    def execute(self, plan: Plan) -> str:
        self.log.info('Project=%s branch=%s message=%s', sanitize(plan.project), sanitize(plan.branch), sanitize(plan.message))
        def output(text):
            clean = sanitize(text)
            self.terminal.write(clean)
            self.emit('output', clean)
            self.log.info('%s', clean)
        try:
            self.terminal.open()
            result = GitManager(output, lambda phase: self.emit('phase', phase)).execute(plan)
            output(result)
            return result
        except Exception as exc:
            output(f'FAILED: {exc}. Any completed local commit is retained.')
            raise
        finally:
            self.terminal.close()

    def build_dashboard(self) -> None:
        self.instruction = tk.StringVar()
        self.project_label = tk.StringVar(value='No project selected')
        self.message_label = tk.StringVar()
        for label, variable in [('Recognized instruction', self.instruction), ('Project', self.project_label), ('Commit message', self.message_label)]:
            ttk.Label(self.dashboard, text=label, font=('Segoe UI', 10, 'bold')).pack(anchor='w')
            ttk.Label(self.dashboard, textvariable=variable, wraplength=820).pack(anchor='w', pady=(0, 8))
        self.progress = ttk.Progressbar(self.dashboard, mode='indeterminate')
        self.progress.pack(fill='x', pady=4)
        self.output = tk.Text(self.dashboard, height=15, bg='#07111e', fg='#bce4d8',
                              insertbackground='white', wrap='word', state='disabled')
        self.output.pack(fill='both', expand=True)
        self.output.bind('<Control-a>', lambda event: self.output.tag_add('sel', '1.0', 'end'))
        ttk.Label(self.dashboard, textvariable=self.result, wraplength=820).pack(anchor='w', pady=8)
        controls = ttk.Frame(self.dashboard)
        controls.pack(fill='x')
        ttk.Button(controls, text='Wake / Resume listening', command=self.resume).pack(side='left')
        ttk.Button(controls, text='Confirm push', command=lambda: self.controller.handle('confirm push')).pack(side='left', padx=6)
        ttk.Button(controls, text='Cancel', command=self.controller.cancel).pack(side='left')
        self.manual = ttk.Entry(self.dashboard)
        self.manual.pack(fill='x', pady=(10, 4))
        self.manual.bind('<Return>', lambda event: self.submit())
        ttk.Button(self.dashboard, text='Submit manual instruction', command=self.submit).pack(anchor='w')

    def submit(self) -> None:
        text = self.manual.get().strip()
        if text:
            self.manual.delete(0, 'end')
            self.controller.handle(text)

    def resume(self) -> None:
        if self.controller.busy:
            return
        self.listener.start()
        if self.controller.state == 'STOPPED':
            self.controller.idle()
        if self.controller.state == 'IDLE':
            self.controller.wake()
        else:
            self.listener.set_mode('command')

    def build_projects(self) -> None:
        self.project_list = tk.Listbox(self.projects_tab, height=7, exportselection=False)
        self.project_list.pack(fill='x')
        self.project_list.bind('<<ListboxSelect>>', self.select_project)
        self.project_fields = {}
        for key, title in [('name', 'Display name'), ('path', 'Absolute repository root'),
                           ('aliases', 'Spoken aliases (comma separated)'), ('exclusions', 'Exclude file patterns (comma separated)')]:
            ttk.Label(self.projects_tab, text=title).pack(anchor='w', pady=(10, 2))
            variable = tk.StringVar()
            self.project_fields[key] = variable
            ttk.Entry(self.projects_tab, textvariable=variable).pack(fill='x')
        buttons = ttk.Frame(self.projects_tab)
        buttons.pack(fill='x', pady=12)
        ttk.Button(buttons, text='Choose folder', command=lambda: self.choose_folder(self.project_fields['path'])).pack(side='left')
        ttk.Button(buttons, text='Save / validate', command=self.save_project).pack(side='left', padx=6)
        ttk.Button(buttons, text='New', command=self.new_project).pack(side='left')
        ttk.Button(buttons, text='Remove selected', command=self.remove_project).pack(side='left', padx=6)
        self.refresh_projects()

    def choose_folder(self, variable: tk.StringVar) -> None:
        path = filedialog.askdirectory(parent=self.root)
        if path:
            variable.set(path)

    def refresh_projects(self) -> None:
        self.project_list.delete(0, 'end')
        for project in self.settings.projects:
            self.project_list.insert('end', f'{project.name} — {project.path} [{"validated at registration" if project.valid else "needs validation"}]')

    def select_project(self, event=None) -> None:
        selection = self.project_list.curselection()
        if selection:
            project = self.settings.projects[selection[0]]
            for key, variable in self.project_fields.items():
                value = getattr(project, key)
                variable.set(', '.join(value) if isinstance(value, list) else value)

    def new_project(self) -> None:
        self.project_list.selection_clear(0, 'end')
        for variable in self.project_fields.values():
            variable.set('')

    def editable(self) -> bool:
        if self.controller.busy:
            messagebox.showinfo('GitPush Agent', 'Wait for the current operation to finish.')
            return False
        if self.controller.state != 'IDLE':
            self.controller.cancel()
        return True

    def save_project(self) -> None:
        if not self.editable():
            return
        fields = {key: value.get().strip() for key, value in self.project_fields.items()}
        if not fields['name'] or not normalize(fields['name']) or not Path(fields['path']).is_absolute():
            messagebox.showerror('Project', 'Provide a spoken display name and an absolute repository path.')
            return
        selection = self.project_list.curselection()
        index = selection[0] if selection else None
        if any(normalize(p.name) == normalize(fields['name']) for i, p in enumerate(self.settings.projects) if i != index):
            messagebox.showerror('Project', 'Choose a unique display name. Shared aliases can be resolved by voice.')
            return
        project = Project(fields['name'], str(Path(fields['path']).resolve()),
                          [a.strip() for a in fields['aliases'].split(',') if a.strip()], False,
                          [p.strip() for p in fields['exclusions'].split(',') if p.strip()])
        self.result.set('Validating project…')
        def validate():
            try:
                GitManager().validate(project.path)
                project.valid = True
                self.emit('register', (index, project, ''))
            except Exception as exc:
                self.emit('register', (index, project, str(exc)))
        self.controller.busy = True
        threading.Thread(target=validate, daemon=True).start()

    def remove_project(self) -> None:
        if self.editable() and self.project_list.curselection():
            del self.settings.projects[self.project_list.curselection()[0]]
            self.settings.save()
            self.refresh_projects()
            self.new_project()

    def build_settings(self) -> None:
        self.voice_names = {'Automatic — prefer female English': ''}
        self.voice_choice = tk.StringVar(value='Automatic — prefer female English')
        ttk.Label(self.settings_tab, text='Offline Windows voice (save before testing)').pack(anchor='w')
        self.voice_picker = ttk.Combobox(self.settings_tab, textvariable=self.voice_choice,
                                        values=list(self.voice_names), state='readonly')
        self.voice_picker.pack(fill='x', pady=(2, 6))
        self.model = tk.StringVar(value=self.settings.model_path)
        self.wake = tk.StringVar(value=self.settings.wake_phrase)
        self.device = tk.StringVar(value='' if self.settings.microphone is None else str(self.settings.microphone))
        for title, variable in [('Extracted Vosk model directory', self.model), ('Wake phrase (lowercase words)', self.wake), ('Microphone device index (blank = default)', self.device)]:
            ttk.Label(self.settings_tab, text=title).pack(anchor='w', pady=(10, 2))
            ttk.Entry(self.settings_tab, textvariable=variable).pack(fill='x')
        ttk.Button(self.settings_tab, text='Choose model folder', command=lambda: self.choose_folder(self.model)).pack(anchor='w', pady=6)
        self.volume = tk.IntVar(value=self.settings.volume)
        self.rate = tk.IntVar(value=self.settings.rate)
        for title, var, low, high in [('Voice volume', self.volume, 0, 100), ('Voice speed', self.rate, -10, 10)]:
            ttk.Label(self.settings_tab, text=title).pack(anchor='w', pady=(12, 0))
            tk.Scale(self.settings_tab, variable=var, from_=low, to=high, orient='horizontal', bg='#101827', fg='white', highlightthickness=0).pack(fill='x')
        self.startup = tk.BooleanVar(value=startup_enabled())
        ttk.Checkbutton(self.settings_tab, text='Start GitPush Agent when Windows starts', variable=self.startup).pack(anchor='w', pady=12)
        ttk.Button(self.settings_tab, text='Save settings & restart listener', command=self.save_settings).pack(anchor='w')
        ttk.Button(self.settings_tab, text='Test offline Windows voice', command=lambda: self.say("I'm listening. This is the offline Windows voice test.")).pack(anchor='w', pady=8)

    def save_settings(self) -> None:
        if not self.editable():
            return
        try:
            phrase = normalize(self.wake.get())
            if len(phrase.split()) < 2:
                raise ValueError('Choose a wake phrase with at least two words.')
            microphone = int(self.device.get()) if self.device.get().strip() else None
            if os.name == 'nt':
                set_startup(self.startup.get())
            self.settings.model_path = self.model.get().strip()
            self.settings.wake_phrase = phrase
            self.settings.microphone = microphone
            self.settings.voice_id = self.voice_names.get(self.voice_choice.get(), self.settings.voice_id)
            self.settings.volume = self.volume.get()
            self.settings.rate = self.rate.get()
            self.settings.save()
            self.listener.stop()
            self.result.set('Settings saved. Restarting the microphone listener…')
            self.restart_listener_when_stopped()
        except Exception as exc:
            messagebox.showerror('Settings', str(exc))

    def restart_listener_when_stopped(self) -> None:
        if self.listener.thread and self.listener.thread.is_alive():
            self.root.after(100, self.restart_listener_when_stopped)
            return
        self.listener.set_mode('idle')
        self.listener.start()

    def build_setup(self) -> None:
        text = ('Welcome. Complete these steps once; routine use is hands-free.\n\n'
                '1. Run device checks. Install Git for Windows if missing.\n'
                '2. Download the small English model, or choose an extracted model in Voice & startup.\n'
                '3. Test the offline voice. Confirm that you hear it.\n'
                '4. Register your repositories in Projects. Configure Git identity and upstream outside the agent.\n'
                '5. Save voice settings, then say the wake phrase. Activity must show LISTENING and “I’m listening.”\n'
                '6. Speak a project instruction and verify the transcript in Activity. Say cancel for a safe test.\n'
                '7. Optionally enable sign-in startup in Voice & startup. The minimized window shows microphone status.\n\n'
                'Microphone permissions: Windows Settings → Privacy (or Privacy & security) → Microphone → '
                'allow desktop apps. No audio is recorded or sent over the network.\n'
                'Restricted-grammar wake recognition is not a dedicated wake-word engine; test in your room. '
                'Choose a different phrase if it activates accidentally.')
        ttk.Label(self.setup_tab, text=text, wraplength=810, justify='left').pack(anchor='w')
        ttk.Button(self.setup_tab, text='1. Run device checks', command=self.check_devices).pack(anchor='w', pady=(14, 6))
        self.download_button = ttk.Button(self.setup_tab, text='2. Download official small English model (~40 MB)', command=self.download)
        self.download_button.pack(anchor='w', pady=6)
        ttk.Button(self.setup_tab, text='3. Speak voice test', command=lambda: self.say('GitPush Agent is using your local Windows voice.')).pack(anchor='w', pady=6)
        ttk.Button(self.setup_tab, text='4. Register projects', command=lambda: self.tabs.select(self.projects_tab)).pack(anchor='w', pady=6)
        ttk.Button(self.setup_tab, text='5. Save voice settings / test wake phrase', command=lambda: self.tabs.select(self.settings_tab)).pack(anchor='w', pady=6)
        self.check_text = tk.StringVar()
        ttk.Label(self.setup_tab, textvariable=self.check_text, wraplength=810).pack(anchor='w', pady=12)

    def check_devices(self) -> None:
        threading.Thread(target=lambda: self.emit('diagnostics', '\n'.join(diagnostics(self.settings))), daemon=True).start()

    def download(self) -> None:
        self.download_button.configure(state='disabled')
        def run():
            try:
                path = download_model(lambda value: self.emit('diagnostics', value))
                self.emit('model', str(path))
            except Exception as exc:
                self.emit('download_error', str(exc))
        threading.Thread(target=run, daemon=True).start()

    def append(self, text: str) -> None:
        self.output.configure(state='normal')
        self.output.insert('end', sanitize(text) + '\n')
        if int(self.output.index('end-1c').split('.')[0]) > 1500:
            self.output.delete('1.0', '300.0')
        self.output.see('end')
        self.output.configure(state='disabled')

    def drain(self) -> None:
        for _ in range(200):
            try:
                kind, value = self.events.get_nowait()
            except queue.Empty:
                break
            if kind in ('prepared', 'prepare_failed', 'done', 'failed'):
                self.controller.receive(kind, value)
            elif kind == 'wake':
                self.root.deiconify()
                self.root.lift()
                self.root.attributes('-topmost', True)
                self.root.after(300, lambda: self.root.attributes('-topmost', False))
                self.controller.wake()
            elif kind == 'transcript':
                self.controller.handle(str(value))
            elif kind == 'unclear':
                self.controller.prompt(str(value))
            elif kind == 'timeout':
                self.controller.cancel()
            elif kind in ('microphone', 'microphone_error'):
                self.mic.set(str(value))
                if kind == 'microphone_error':
                    self.append(str(value))
                    self.result.set('Voice unavailable. Complete Setup or use the manual controls.')
            elif kind in ('output', 'error', 'result'):
                self.append(str(value))
                if kind != 'output':
                    self.result.set(str(value))
            elif kind == 'state':
                self.state.set(str(value))
                if self.controller.busy:
                    self.progress.start(15)
                else:
                    self.progress.stop()
            elif kind == 'phase':
                self.controller.transition(str(value))
            elif kind == 'instruction':
                self.instruction.set(str(value))
            elif kind == 'project':
                self.project_label.set(str(value))
            elif kind == 'preview':
                self.message_label.set(value.message or '(push existing commits only)')
                self.append(f'Preview: {value.project}\nRoot: {value.root}\nBranch: {value.branch}\nUpstream: {value.upstream}\nMessage: {value.message}\nAhead: {value.ahead}')
                for title, names in [('Selected', value.files), ('Previously staged', value.staged), ('EXCLUDED — review manually', value.excluded), ('Ignored (not staged)', value.ignored)]:
                    self.append(title + ':\n' + ('\n'.join(names) if names else '(none)'))
                self.result.set('Review the exact selection. Say “confirm push”, “change message to …”, or “cancel”.')
            elif kind == 'register':
                self.controller.busy = False
                index, project, error = value
                if error:
                    messagebox.showerror('Repository validation', error)
                else:
                    if index is None:
                        self.settings.projects.append(project)
                    else:
                        self.settings.projects[index] = project
                    self.settings.save()
                    self.refresh_projects()
                    self.result.set('Project registered and validated. It will be checked again before every push.')
            elif kind == 'voices':
                for voice in value:
                    label = f'{voice.name} ({"female" if voice.female else "other"}) [{voice.id}]'
                    self.voice_names[label] = voice.id
                self.voice_picker.configure(values=list(self.voice_names))
                if self.settings.voice_id:
                    label = next((name for name, voice_id in self.voice_names.items() if voice_id == self.settings.voice_id), None)
                    if label:
                        self.voice_choice.set(label)
                    else:
                        label = 'Saved voice unavailable — automatic fallback'
                        self.voice_names[label] = self.settings.voice_id
                        self.voice_picker.configure(values=list(self.voice_names))
                        self.voice_choice.set(label)
            elif kind == 'diagnostics':
                self.check_text.set(str(value))
            elif kind == 'model':
                self.model.set(str(value))
                self.check_text.set('Model downloaded. Save voice settings to start the listener.')
                self.download_button.configure(state='normal')
            elif kind == 'download_error':
                self.download_button.configure(state='normal')
                self.check_text.set('Model download failed: ' + str(value))
            elif kind == 'close':
                self.close()
                return
        self.controller.tick(self.speech.busy.is_set())
        if self.instance.activation_requested():
            self.root.deiconify()
            self.root.lift()
        self.root.after(100, self.drain)

    def close(self) -> None:
        if self.controller.busy:
            self.result.set('Wait for Git or validation to finish before closing. Running Git will not be interrupted.')
            return
        self.listener.stop()
        self.speech.close()
        self.root.destroy()
