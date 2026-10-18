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
from .setup import diagnostics, download_model, existing_model
from .discovery import default_roots, discover
from .speech import SpeechOutput, VoiceListener
from .terminal import Terminal
from .windows import SingleInstance, set_startup, startup_enabled, open_microphone_settings


class Application:
    def __init__(self, root: tk.Tk, settings: Settings, instance: SingleInstance, background: bool = False):
        self.root, self.settings, self.instance = root, settings, instance
        self.events: queue.Queue[tuple[str, object]] = queue.Queue()
        self.log = logging.getLogger('gitpush')
        self.terminal = Terminal()
        self.speech = SpeechOutput(settings, lambda value: self.emit('error', value),
                                   lambda voices: self.emit('voices', voices), lambda text: self.emit('spoken', text))
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
        style.configure('TNotebook', background='#101827', borderwidth=0)
        style.configure('TNotebook.Tab', background='#1c2a40', foreground='#aabbd1', padding=(18, 10))
        style.map('TNotebook.Tab', background=[('selected', '#183f49')], foreground=[('selected', '#73edcf')])
        style.configure('TButton', padding=(12, 8), background='#22344b', foreground='#e2e8f0', borderwidth=0)
        style.map('TButton', background=[('active', '#304b68'), ('disabled', '#192538')], foreground=[('disabled', '#708198')])
        style.configure('Accent.TButton', background='#20a88a', foreground='#071b17')
        style.map('Accent.TButton', background=[('active', '#54d8b7'), ('disabled', '#23483f')])
        style.configure('TEntry', fieldbackground='#18273d', foreground='#edf4fc', insertcolor='#edf4fc')
        style.configure('Treeview', background='#142238', fieldbackground='#142238', foreground='#e2e8f0', rowheight=25)
        style.configure('Treeview.Heading', background='#22344b', foreground='#aabbd1')
        style.map('Treeview', background=[('selected', '#225649')])
        style.configure('TProgressbar', background='#39cfaa', troughcolor='#1c2a40')
        style.configure('TCheckbutton', background='#101827', foreground='#e2e8f0')
        self.state = tk.StringVar(value='IDLE')
        self.mic = tk.StringVar(value='Microphone stopped')
        self.result = tk.StringVar(value='Welcome. Prepare offline voice once; discover your Git folders automatically.')
        header = ttk.Frame(root, padding=18)
        header.pack(fill='x')
        brand = ttk.Frame(header)
        brand.pack(side='left')
        ttk.Label(brand, text='GitPush Agent', font=('Segoe UI', 23, 'bold')).pack(anchor='w')
        ttk.Label(brand, text='SPEAK. REVIEW. SHIP.', foreground='#64d6b8', font=('Segoe UI', 9)).pack(anchor='w')
        ttk.Label(header, textvariable=self.state).pack(side='right')
        ttk.Label(root, textvariable=self.mic, padding=(18, 0)).pack(anchor='w')
        self.notice_text = tk.StringVar(value=self.result.get())
        self.result.trace_add('write', lambda *args: self.notice_text.set(self.result.get().split('\n')[0][:200]))
        self.notice = ttk.Label(root, textvariable=self.notice_text, padding=(18, 6), wraplength=860)
        self.notice.pack(fill='x')
        root.bind('<Configure>', lambda event: self.notice.configure(wraplength=max(300, root.winfo_width() - 40)) if event.widget == root else None)
        self.tabs = ttk.Notebook(root)
        self.tabs.pack(fill='both', expand=True, padx=18, pady=12)
        self.dashboard = ttk.Frame(self.tabs, padding=14)
        self.projects_tab = ttk.Frame(self.tabs, padding=14)
        self.settings_tab = ttk.Frame(self.tabs, padding=14)
        self.setup_tab = ttk.Frame(self.tabs, padding=14)
        for tab, title in [(self.dashboard, 'Activity'), (self.projects_tab, 'Workspaces'),
                           (self.settings_tab, 'Voice & startup'), (self.setup_tab, 'Get started')]:
            self.tabs.add(tab, text=title)
        self.build_dashboard()
        self.build_projects()
        self.build_settings()
        self.build_setup()
        root.protocol('WM_DELETE_WINDOW', self.close)
        self._drain_after = root.after(100, self.drain)
        self.scanning = False
        if not settings.model_path:
            self.tabs.select(self.setup_tab)
        elif settings.model_path:
            self.listener.start()
        self._scan_after = root.after(500, self.scan_workspaces)
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
        canvas = tk.Canvas(self.projects_tab, bg='#101827', highlightthickness=0)
        scroll = ttk.Scrollbar(self.projects_tab, command=canvas.yview)
        scroll.pack(side='right', fill='y')
        canvas.pack(side='left', fill='both', expand=True)
        canvas.configure(yscrollcommand=scroll.set)
        content = ttk.Frame(canvas)
        window = canvas.create_window((0, 0), window=content, anchor='nw')
        content.bind('<Configure>', lambda event: canvas.configure(scrollregion=canvas.bbox('all')))
        canvas.bind('<Configure>', lambda event: canvas.itemconfigure(window, width=event.width))
        ttk.Label(content, text='Find your repositories — no individual registration needed', font=('Segoe UI', 12, 'bold')).pack(anchor='w')
        self.workspace_label = tk.StringVar()
        ttk.Label(content, textvariable=self.workspace_label, wraplength=680).pack(anchor='w', pady=6)
        workspace_buttons = ttk.Frame(self.projects_tab)
        workspace_buttons.pack(fill='x', pady=(0, 8))
        ttk.Button(workspace_buttons, text='Add workspace folder', command=self.add_workspace).pack(side='left')
        ttk.Button(workspace_buttons, text='Refresh folders', command=self.scan_workspaces).pack(side='left', padx=6)
        ttk.Button(workspace_buttons, text='Use common folders', command=self.reset_workspaces).pack(side='left')
        self.discovered_list = tk.Listbox(content, height=3, bg='#142238', fg='#bce4d8', highlightthickness=0)
        self.discovered_list.pack(fill='x', pady=(0, 8))
        ttk.Label(content, text='Optional saved aliases and exclusions', foreground='#8ca3bf').pack(anchor='w')
        self.project_list = tk.Listbox(content, height=7, exportselection=False)
        self.project_list.pack(fill='x')
        self.project_list.bind('<<ListboxSelect>>', self.select_project)
        self.project_fields = {}
        for key, title in [('name', 'Display name'), ('path', 'Absolute repository root'),
                           ('aliases', 'Spoken aliases (comma separated)'), ('exclusions', 'Exclude file patterns (comma separated)')]:
            ttk.Label(content, text=title).pack(anchor='w', pady=(10, 2))
            variable = tk.StringVar()
            self.project_fields[key] = variable
            ttk.Entry(content, textvariable=variable).pack(fill='x')
        buttons = ttk.Frame(self.projects_tab)
        buttons.pack(fill='x', pady=12)
        ttk.Button(buttons, text='Choose folder', command=lambda: self.choose_folder(self.project_fields['path'])).pack(side='left')
        ttk.Button(buttons, text='Save / validate', command=self.save_project).pack(side='left', padx=6)
        ttk.Button(buttons, text='New', command=self.new_project).pack(side='left')
        ttk.Button(buttons, text='Remove selected', command=self.remove_project).pack(side='left', padx=6)
        self.refresh_projects()

    def add_workspace(self) -> None:
        if not self.editable() or self.scanning:
            return
        path = filedialog.askdirectory(parent=self.root, title='Choose a folder containing your Git projects')
        if path:
            roots = self.settings.search_roots or default_roots()
            self.settings.search_roots = list(dict.fromkeys([*roots, str(Path(path).resolve())]))
            self.settings.save()
            self.scan_workspaces()

    def reset_workspaces(self) -> None:
        if self.editable() and not self.scanning:
            self.settings.search_roots = []
            self.settings.save()
            self.scan_workspaces()

    def scan_workspaces(self) -> None:
        if self.scanning:
            return
        self.scanning = True
        roots = self.settings.search_roots or default_roots()
        self.workspace_label.set('Searching: ' + (', '.join(roots) or 'No common work folders exist. Add a workspace folder.'))
        self.set_step(4, 'Searching folders…')
        def run():
            try:
                self.emit('discovered', discover(roots, lambda text: self.emit('scan_progress', text)))
            except Exception as exc:
                self.emit('scan_error', str(exc))
        threading.Thread(target=run, daemon=True).start()

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
        canvas = tk.Canvas(self.settings_tab, bg='#101827', highlightthickness=0)
        scrollbar = ttk.Scrollbar(self.settings_tab, orient='vertical', command=canvas.yview)
        scrollbar.pack(side='right', fill='y')
        canvas.pack(side='left', fill='both', expand=True)
        canvas.configure(yscrollcommand=scrollbar.set)
        content = ttk.Frame(canvas, padding=(0, 0, 12, 12))
        window = canvas.create_window((0, 0), window=content, anchor='nw')
        content.bind('<Configure>', lambda event: canvas.configure(scrollregion=canvas.bbox('all')))
        canvas.bind('<Configure>', lambda event: canvas.itemconfigure(window, width=event.width))
        self.voice_names = {'Automatic — prefer female English': ''}
        self.voice_choice = tk.StringVar(value='Automatic — prefer female English')
        ttk.Label(content, text='Offline Windows voice (save before testing)').pack(anchor='w')
        self.voice_picker = ttk.Combobox(content, textvariable=self.voice_choice,
                                        values=list(self.voice_names), state='readonly')
        self.voice_picker.pack(fill='x', pady=(2, 6))
        self.model = tk.StringVar(value=self.settings.model_path)
        self.wake = tk.StringVar(value=self.settings.wake_phrase)
        self.device = tk.StringVar(value='' if self.settings.microphone is None else str(self.settings.microphone))
        for title, variable in [('Extracted Vosk model directory', self.model), ('Wake phrase (lowercase words)', self.wake), ('Microphone device index (blank = default)', self.device)]:
            ttk.Label(content, text=title).pack(anchor='w', pady=(10, 2))
            ttk.Entry(content, textvariable=variable).pack(fill='x')
        ttk.Button(content, text='Choose model folder', command=lambda: self.choose_folder(self.model)).pack(anchor='w', pady=6)
        self.volume = tk.IntVar(value=self.settings.volume)
        self.rate = tk.IntVar(value=self.settings.rate)
        for title, var, low, high in [('Voice volume', self.volume, 0, 100), ('Voice speed', self.rate, -10, 10)]:
            ttk.Label(content, text=title).pack(anchor='w', pady=(12, 0))
            tk.Scale(content, variable=var, from_=low, to=high, orient='horizontal', bg='#101827', fg='white', highlightthickness=0).pack(fill='x')
        self.startup = tk.BooleanVar(value=startup_enabled())
        ttk.Checkbutton(content, text='Start GitPush Agent when Windows starts', variable=self.startup).pack(anchor='w', pady=12)
        ttk.Button(content, text='Save settings & restart listener', command=self.save_settings).pack(anchor='w')
        ttk.Button(content, text='Test offline Windows voice', command=lambda: self.say("I'm listening. This is the offline Windows voice test.")).pack(anchor='w', pady=8)

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
        self.setup_task = None
        self.setup_tab.columnconfigure(1, weight=1)
        self.setup_tab.rowconfigure(1, weight=1)
        ttk.Label(self.setup_tab, text='Get ready in minutes. Offline speech stays on your PC. Your Git folders are found automatically.',
                  wraplength=650).grid(row=0, column=0, columnspan=2, sticky='w', pady=(0, 12))
        buttons = ttk.Frame(self.setup_tab)
        buttons.grid(row=1, column=0, sticky='nw', padx=(0, 16))
        self.check_button = ttk.Button(buttons, text='1. Run device checks', command=self.check_devices)
        self.check_button.pack(fill='x', pady=(0, 8))
        self.download_button = ttk.Button(buttons, text='2. Prepare offline voice', command=self.download)
        self.download_button.pack(fill='x', pady=8)
        ttk.Button(buttons, text='3. Speak voice test', command=self.test_voice).pack(fill='x', pady=8)
        ttk.Button(buttons, text='4. Find my Git folders', command=self.find_folders).pack(fill='x', pady=8)
        ttk.Button(buttons, text='5. Start wake listening', command=self.start_wake).pack(fill='x', pady=8)
        results = ttk.Frame(self.setup_tab)
        results.grid(row=1, column=1, sticky='nsew')
        ttk.Label(results, text='Setup results', font=('Segoe UI', 11, 'bold')).pack(anchor='w')
        self.steps = ttk.Treeview(results, columns=('status',), show='tree headings', height=5)
        self.steps.heading('#0', text='Step')
        self.steps.heading('status', text='Progress')
        self.steps.column('#0', width=115, minwidth=90, stretch=False)
        self.steps.column('status', width=170, minwidth=80)
        for number, title in enumerate(['Device check', 'Offline voice', 'Voice playback', 'Git folders', 'Wake listening'], 1):
            self.steps.insert('', 'end', iid=str(number), text=title, values=('Not started',))
        self.steps.pack(fill='x', pady=(6, 0))
        self.setup_progress = ttk.Progressbar(results, mode='determinate', value=0)
        self.setup_progress.pack(fill='x', pady=8)
        output_frame = ttk.Frame(results)
        output_frame.pack(fill='both', expand=True)
        self.setup_output = tk.Text(output_frame, height=10, width=28, wrap='word', state='disabled',
                                    bg='#07111e', fg='#bce4d8', padx=10, pady=10)
        scroll = ttk.Scrollbar(output_frame, command=self.setup_output.yview)
        scroll.pack(side='right', fill='y')
        self.setup_output.configure(yscrollcommand=scroll.set)
        self.setup_output.pack(fill='both', expand=True)
        self.check_text = tk.StringVar()
        self.check_text.trace_add('write', self.show_setup_results)
        self.check_text.set('Start with step 1. Device-check results and any errors will appear here. No files are changed by device checks.')
        footer = ttk.Frame(self.setup_tab)
        footer.grid(row=2, column=0, columnspan=2, sticky='ew', pady=(8, 0))
        ttk.Button(footer, text='Windows microphone settings', command=self.microphone_settings).pack(side='left')
        ttk.Label(footer, text='No admin access needed. Audio stays local.', foreground='#8ca3bf').pack(side='left', padx=12)

    def set_step(self, number: int, status: str) -> None:
        self.steps.item(str(number), values=(status,))

    def microphone_settings(self) -> None:
        try:
            open_microphone_settings()
            self.check_text.set('In Windows Settings, enable Microphone access and Allow desktop apps to access your microphone. '
                                'Windows may not show a separate permission popup for this desktop app. Return here and run Device checks.')
        except Exception as exc:
            self.check_text.set(str(exc))

    def find_folders(self) -> None:
        self.tabs.select(self.projects_tab)
        self.result.set('Discovering Git folders. Add a workspace if your projects are elsewhere; no per-project registration is required.')
        self.scan_workspaces()

    def start_wake(self) -> None:
        if self.controller.busy:
            return
        model = existing_model(self.model.get().strip() or self.settings.model_path)
        if model is None:
            self.set_step(5, 'Needs offline voice')
            self.check_text.set('Prepare offline voice in step 2 first. A local speech model is required to hear your wake phrase.')
            return
        self.model.set(str(model))
        self.set_step(5, 'Opening microphone…')
        self.settings.model_path = str(model)
        self.save_settings()
        self.check_text.set('Starting offline listening. Wait for Microphone active, then say your wake phrase: ' + self.settings.wake_phrase)


    def show_setup_results(self, *args) -> None:
        self.setup_output.configure(state='normal')
        self.setup_output.delete('1.0', 'end')
        self.setup_output.insert('1.0', self.check_text.get())
        self.setup_output.configure(state='disabled')

    def start_setup_task(self, task: str, message: str) -> bool:
        if self.setup_task:
            self.result.set(f'{self.setup_task} is still running. Please wait for its result.')
            return False
        self.setup_task = task
        self.check_text.set(message)
        self.result.set(message)
        self.check_button.configure(state='disabled')
        self.download_button.configure(state='disabled')
        self.setup_progress.configure(mode='indeterminate')
        self.setup_progress.start(15)
        return True

    def finish_setup_task(self) -> None:
        self.setup_task = None
        self.setup_progress.stop()
        self.setup_progress.configure(mode='determinate', value=0)
        self.check_button.configure(state='normal')
        self.download_button.configure(state='normal')

    def check_devices(self) -> None:
        if not self.start_setup_task('Device check', 'Checking Python, Git, model and microphone…'):
            return
        self.set_step(1, 'Checking…')
        def run():
            try:
                self.emit('diagnostics', '\n'.join(diagnostics(self.settings)))
            except Exception as exc:
                self.emit('diagnostics', f'Device checks failed: {exc}')
        threading.Thread(target=run, daemon=True).start()

    def test_voice(self) -> None:
        self.set_step(3, 'Playing…')
        self.check_text.set('Voice test requested. You should hear a spoken sentence. If you hear it, continue to step 4. '
                            'If not, check speaker volume and Voice & startup. Any speech error will appear here.')
        self.result.set('Playing the offline voice test. Check your speakers or headphones.')
        self.say('GitPush Agent is using your local Windows voice.')

    def open_projects(self) -> None:
        self.result.set('Projects: enter a name, choose the repository root, then click Save / validate.')
        self.tabs.select(self.projects_tab)

    def open_voice_settings(self) -> None:
        self.result.set('Voice settings: check the model path and voice, then click Save settings & restart listener. Scroll down if needed.')
        self.tabs.select(self.settings_tab)

    def download(self) -> None:
        model = existing_model(self.model.get().strip() or self.settings.model_path)
        if model is not None:
            self.emit('model', str(model))
            return
        if not self.start_setup_task('Model download', 'Downloading the English model (~40 MB). Keep the app open; this can take a few minutes…'):
            return
        self.set_step(2, 'Downloading…')
        def run():
            try:
                path = download_model(lambda value: self.emit('download_progress', value),
                                      lambda count, total: self.emit('download_bytes', (count, total)))
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
                self.set_step(5, 'Wake phrase detected')
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
                if kind == 'microphone' and str(value).startswith('Microphone active'):
                    self.set_step(5, 'Listening — say wake phrase')
                    self.check_text.set('Microphone active. Say ' + self.settings.wake_phrase + ', then name your folder and describe the changes.')
                if kind == 'microphone' and str(value) == 'Microphone stopped':
                    if 'error' not in str(self.steps.item('5', 'values')).lower():
                        self.set_step(5, 'Stopped')
                if kind == 'microphone_error':
                    self.set_step(5, 'Microphone/model error')
                    self.append(str(value))
                    self.result.set('Voice unavailable. Complete Setup or use the manual controls.')
                    self.check_text.set(str(value))
            elif kind in ('output', 'error', 'result'):
                self.append(str(value))
                if kind != 'output':
                    self.result.set(str(value))
                if kind == 'error':
                    self.check_text.set(str(value))
                    if 'Speech' in str(value) or 'SAPI' in str(value):
                        self.set_step(3, 'Voice needs attention')
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
            elif kind == 'spoken':
                if str(value) == 'GitPush Agent is using your local Windows voice.':
                    self.set_step(3, 'Played — did you hear it?')
                    self.check_text.set('Windows finished playing the voice test. If you heard it, continue. If not, check speaker volume and the selected output device.')
            elif kind == 'scan_progress':
                self.workspace_label.set(str(value))
                self.set_step(4, str(value))
            elif kind == 'discovered':
                self.scanning = False
                self.controller.discovered_projects = value.projects
                self.discovered_list.delete(0, 'end')
                for project in value.projects:
                    self.discovered_list.insert('end', f'{project.name} — {project.path}')
                summary = f'{len(value.projects)} Git folders found; {value.visited} folders checked.'
                self.workspace_label.set(summary + (' Some folders could not be searched; see Activity.' if value.warnings else ''))
                self.set_step(4, f'{len(value.projects)} found' + ('; review scan warnings' if value.warnings else ''))
                self.append(summary + '\n' + '\n'.join(value.warnings))
            elif kind == 'scan_error':
                self.scanning = False
                self.set_step(4, 'Search failed')
                self.workspace_label.set(str(value))
                self.append(str(value))
            elif kind == 'download_bytes':
                count, total = value
                detail = f'{count / 1048576:.1f} MB received'
                if total:
                    percent = min(100, count * 100 / total)
                    self.setup_progress.stop()
                    self.setup_progress.configure(mode='determinate', value=percent)
                    detail = f'{percent:.0f}% — {count / 1048576:.1f} / {total / 1048576:.1f} MB'
                self.set_step(2, detail)
                self.check_text.set('Downloading offline voice: ' + detail + '. After download, the archive will be checked and extracted.')
            elif kind == 'diagnostics':
                self.finish_setup_task()
                needs_attention = any(word in str(value).lower() for word in ('not found', 'failed', 'blocked', 'requires windows'))
                self.set_step(1, 'Review results' if needs_attention else 'Checks complete')
                self.check_text.set(str(value))
                self.result.set('Device checks finished. Review Setup results for any missing requirements.')
            elif kind == 'download_progress':
                self.check_text.set(str(value))
            elif kind == 'model':
                self.model.set(str(value))
                self.settings.model_path = str(value)
                self.settings.save()
                self.set_step(2, 'Ready — saved locally')
                self.finish_setup_task()
                message = f'Offline voice ready: {value}\nNext: test the voice, find your Git folders, then click Start wake listening. No individual project registration is required.'
                self.check_text.set(message)
                self.result.set('Offline voice is saved and ready. Continue with steps 3–5.')
            elif kind == 'download_error':
                self.finish_setup_task()
                self.set_step(2, 'Download failed — retry')
                self.check_text.set('Model download failed: ' + str(value) + '\nCheck internet access, or select an extracted official model in Voice & startup.')
                self.result.set('Model download failed. See Setup results for the error.')
            elif kind == 'close':
                self.close()
                return
        self.controller.tick(self.speech.busy.is_set())
        if self.instance.activation_requested():
            self.root.deiconify()
            self.root.lift()
        self._drain_after = self.root.after(100, self.drain)

    def close(self) -> None:
        if self.controller.busy:
            self.result.set('Wait for Git or validation to finish before closing. Running Git will not be interrupted.')
            return
        self.listener.stop()
        self.speech.close()
        self.root.after_cancel(self._drain_after)
        self.root.after_cancel(self._scan_after)
        self.root.destroy()
