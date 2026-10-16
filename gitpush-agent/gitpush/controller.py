from __future__ import annotations
import threading
import time
from typing import Callable
from .config import Settings, Project
from .git_manager import GitManager, GitError, Plan
from .parser import parse, commit_message, phrase_in


class Controller:
    """UI thread owns this state; background workers only publish events."""
    def __init__(self, settings: Settings, emit: Callable[[str, object], None],
                 say: Callable[[str], None], mode: Callable[[str], None],
                 execute: Callable[[Plan], str]):
        self.settings, self.emit, self.say, self.mode, self.execute = settings, emit, say, mode, execute
        self.state = 'IDLE'
        self.plan: Plan | None = None
        self.project: Project | None = None
        self.pending_text = ''
        self.candidates: list[Project] = []
        self.expires = 0.0
        self.busy = False
        self.need_description = False

    def transition(self, state: str) -> None:
        self.state = state
        self.emit('state', state)

    def prompt(self, text: str) -> None:
        self.say(text)
        self.mode('command')
        self.expires = time.monotonic() + self.settings.confirmation_timeout

    def idle(self) -> None:
        self.plan = None
        self.project = None
        self.candidates = []
        self.need_description = False
        self.expires = 0
        self.transition('IDLE')
        self.mode('idle')

    def wake(self) -> None:
        if self.busy or self.state != 'IDLE':
            return
        self.transition('LISTENING')
        self.prompt("I'm listening.")

    def cancel(self) -> None:
        if self.busy:
            self.say('An operation is running. I will let Git finish safely.')
            return
        self.transition('CANCELLED')
        self.say('Push cancelled.')
        self.idle()

    def tick(self, speaking: bool = False) -> None:
        if speaking and self.expires:
            self.expires = time.monotonic() + self.settings.confirmation_timeout
        if self.expires and time.monotonic() > self.expires and not self.busy:
            self.cancel()

    def handle(self, text: str) -> None:
        self.emit('instruction', text)
        command = parse(text, self.settings.projects)
        if self.busy:
            return
        if command.action == 'cancel':
            self.cancel()
            return
        if command.action == 'close':
            self.emit('close', '')
            return
        if command.action == 'stop':
            self.plan = None
            self.expires = 0
            self.transition('STOPPED')
            self.mode('stop')
            self.say('Listening stopped. Use Resume listening to turn the microphone on again.')
            return
        if command.action == 'status':
            self.prompt(f'Current status: {self.state.lower().replace("_", " ")}.')
            return
        if command.action == 'confirm':
            if self.state != 'AWAITING_CONFIRMATION' or self.plan is None:
                self.prompt('There is no push awaiting confirmation.')
                return
            if time.monotonic() > self.expires:
                self.cancel()
                return
            plan = self.plan
            self.plan = None
            self.busy = True
            self.expires = 0
            self.mode('paused')
            self.transition('STAGING' if plan.files else 'PUSHING')
            def run():
                try:
                    self.emit('done', self.execute(plan))
                except Exception as exc:
                    self.emit('failed', str(exc))
            threading.Thread(target=run, daemon=True).start()
            return
        if command.action == 'correct' and self.plan and self.project:
            if not command.message:
                self.prompt('Please repeat your commit message.')
                return
            self.prepare(self.project, command.message)
            return
        if self.candidates:
            matches = [p for p in self.candidates if phrase_in(p.name, text)]
            if len(matches) != 1:
                self.prompt('Choose one project: ' + ', '.join(p.name for p in self.candidates))
                return
            self.project = matches[0]
            self.candidates = []
            message = commit_message(self.pending_text, [self.project])
            self.with_description(self.project, message)
            return
        if self.need_description and self.project:
            self.with_description(self.project, commit_message(text, [self.project]))
            return
        if command.action != 'push':
            self.prompt('Please repeat your instruction.')
            return
        self.plan = None
        self.transition('PARSING')
        if len(command.projects) > 1:
            self.plan = None
            self.candidates = command.projects
            self.pending_text = text
            self.transition('LISTENING')
            self.prompt('Choose one project: ' + ', '.join(p.name for p in command.projects))
        elif not command.projects:
            self.prompt("I couldn't find that project.")
        else:
            self.with_description(command.projects[0], command.message)

    def with_description(self, project: Project, message: str) -> None:
        # Prepare even without a message: a clean repository can have push-only work.
        self.project = project
        self.prepare(project, message)

    def prepare(self, project: Project, message: str) -> None:
        self.plan = None
        self.busy = True
        self.expires = 0
        self.mode('paused')
        self.transition('VALIDATING')
        self.emit('project', project.name)
        def run():
            try:
                self.emit('prepared', GitManager().prepare(project, message))
            except Exception as exc:
                self.emit('prepare_failed', str(exc))
        threading.Thread(target=run, daemon=True).start()

    def receive(self, kind: str, value: object) -> None:
        if kind == 'prepared':
            self.busy = False
            self.plan = value
            self.need_description = False
            self.emit('preview', value)
            if not value.has_work:
                self.say('No changes to push.')
                self.idle()
                return
            self.transition('AWAITING_CONFIRMATION')
            summary = f'{len(value.files)} files selected, {len(value.staged)} previously staged, {len(value.excluded)} excluded. '
            self.prompt(summary + f'Ready to push changes to {value.project}. Commit message: {value.message or "push existing commits only"}. Say confirm push or cancel.')
        elif kind == 'prepare_failed':
            self.busy = False
            if str(value) == 'Please describe the changes before committing.':
                self.need_description = True
                self.transition('LISTENING')
                self.prompt(str(value))
            else:
                self.emit('error', value)
                self.say(str(value))
                self.idle()
        elif kind in ('done', 'failed'):
            self.busy = False
            self.transition('SUCCESS' if kind == 'done' else 'FAILED')
            self.emit('result', value)
            self.say(str(value) if kind == 'done' else 'Changes not pushed. Check the files.')
            self.idle()
