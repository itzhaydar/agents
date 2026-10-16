from __future__ import annotations
import fnmatch
import hashlib
import json
import os
import re
import shutil
import subprocess
import threading
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Callable
from .config import Project


class GitError(RuntimeError):
    pass


def sanitize(text: str) -> str:
    text = re.sub(r'(https?://)[^\s/@]+(?::[^\s/@]*)?@', r'\1[redacted]@', text)
    text = re.sub(r'(?i)\b(?:gh[pousr]_[\w]+|github_pat_[\w]+|sk-[\w-]{16,})', '[redacted]', text)
    return re.sub(r'(?i)((?:token|password|secret|authorization)\s*[:=]\s*)\S+', r'\1[redacted]', text)


@dataclass(frozen=True)
class Plan:
    project: str
    root: str
    branch: str
    upstream: str
    message: str
    files: tuple[str, ...]
    staged: tuple[str, ...]
    excluded: tuple[str, ...]
    ignored: tuple[str, ...]
    ahead: int
    fingerprint: str
    tree: str = ''

    @property
    def has_work(self) -> bool:
        return bool(self.files or self.ahead)


class GitManager:
    def __init__(self, output: Callable[[str], None] = lambda _: None,
                 phase: Callable[[str], None] = lambda _: None):
        self.output = output
        self.phase = phase
        self._lock = threading.Lock()

    def run(self, root: Path, *args: str, check: bool = True, timeout: int = 120, index: str | None = None) -> bytes:
        if not shutil.which('git'):
            raise GitError('Git is not installed. Please install Git first.')
        self.output('$ git ' + ' '.join(sanitize(a) for a in args))
        try:
            result = subprocess.run(['git', *args], cwd=root, stdout=subprocess.PIPE,
                                    stderr=subprocess.PIPE, shell=False, timeout=timeout,
                                    env={**os.environ, 'GIT_TERMINAL_PROMPT': '0', 'GCM_INTERACTIVE': 'Never',
                                         **({'GIT_INDEX_FILE': index} if index else {})},
                                    creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)
        except subprocess.TimeoutExpired as exc:
            raise GitError('Git timed out. Inspect repository status before retrying; a completed commit may remain local.') from exc
        if result.stderr:
            self.output(sanitize(result.stderr.decode('utf-8', 'replace')))
        if result.returncode and check:
            raise GitError(sanitize((result.stderr + result.stdout).decode('utf-8', 'replace')).strip() or f'Git exited {result.returncode}')
        return result.stdout

    def value(self, root: Path, *args: str) -> str:
        return self.run(root, *args).decode('utf-8', 'surrogateescape').strip()

    def validate(self, directory: str) -> tuple[Path, str, str]:
        path = Path(directory).resolve()
        if not path.is_dir():
            raise GitError("I couldn't find that project.")
        root = Path(self.value(path, 'rev-parse', '--show-toplevel')).resolve()
        if root != path:
            raise GitError(f'Selected folder is inside {root}. Register the repository root explicitly to approve its scope.')
        branch = self.value(root, 'symbolic-ref', '--quiet', '--short', 'HEAD')
        if not branch:
            raise GitError('Detached HEAD is unsupported. Check out a branch first.')
        self.value(root, 'rev-parse', '--verify', 'HEAD')
        upstream = self.value(root, 'rev-parse', '--abbrev-ref', '--symbolic-full-name', '@{upstream}')
        remote = self.value(root, 'config', '--get', f'branch.{branch}.remote')
        if remote == '.':
            raise GitError('A remote upstream is required; local upstream branches are unsupported.')
        fetch_urls = self.value(root, 'remote', 'get-url', '--all', remote).splitlines()
        push_urls = self.value(root, 'remote', 'get-url', '--push', '--all', remote).splitlines()
        if len(fetch_urls) != 1 or push_urls != fetch_urls:
            raise GitError('Different or multiple push URLs require manual review. Configure one matching fetch/push destination first.')
        if self.run(root, 'config', '--bool', '--get', f'remote.{remote}.mirror', check=False).strip() == b'true':
            raise GitError('Mirror remotes are unsupported.')
        for marker in ('MERGE_HEAD', 'CHERRY_PICK_HEAD', 'REVERT_HEAD', 'rebase-merge', 'rebase-apply', 'BISECT_LOG', 'sequencer', 'index.lock'):
            location = Path(self.value(root, 'rev-parse', '--git-path', marker))
            if not location.is_absolute():
                location = root / location
            if location.exists():
                raise GitError(f'Finish the interrupted Git operation first: {marker}')
        if self.run(root, 'ls-files', '-u', '-z'):
            raise GitError('Resolve merge conflicts first.')
        entries = self.run(root, 'ls-files', '--stage', '-z')
        if entries.startswith(b'160000 ') or b'\x00160000 ' in entries:
            raise GitError('Submodules require manual review and are unsupported in this version.')
        return root, branch, upstream

    def _paths(self, root: Path, *args: str) -> list[str]:
        return [os.fsdecode(p) for p in self.run(root, *args).split(b'\0') if p]

    def _snapshot(self, root: Path) -> str:
        digest = hashlib.sha256()
        # Hash content as well as status: status alone cannot bind confirmation to file contents.
        for args in [('status', '--porcelain=v1', '-z', '--untracked-files=all'),
                     ('diff', '--raw', '--abbrev=40', '-z', '--no-ext-diff', '--no-textconv'),
                     ('diff', '--cached', '--raw', '--abbrev=40', '-z', '--no-ext-diff', '--no-textconv'),
                     ('show-ref',), ('config', '--local', '--null', '--list')]:
            digest.update(self.run(root, *args))
        for name in self._paths(root, 'ls-files', '--cached', '--others', '--exclude-standard', '-z'):
            path = root / name
            digest.update(os.fsencode(name))
            if path.is_symlink():
                digest.update(os.fsencode(os.readlink(path)))
            elif path.is_file():
                with path.open('rb') as stream:
                    for chunk in iter(lambda: stream.read(65536), b''):
                        digest.update(chunk)
        digest.update(self.run(root, 'symbolic-ref', 'HEAD'))
        return digest.hexdigest()

    def suspicious(self, root: Path, name: str) -> bool:
        path = root / name
        if any(re.search(r'(?i)(^\.env(?:\.|$)|credentials|id_rsa|id_ed25519|\.pem$|\.key$|\.p12$|\.pfx$|\.npmrc$|\.netrc$)', part) for part in Path(name).parts):
            return True
        if path.is_symlink():
            return True
        if path.is_file():
            if path.stat().st_size > 10 * 1024 * 1024:
                return True
            content = path.read_bytes()
            if re.search(rb'-----BEGIN [A-Z ]*PRIVATE KEY-----|gh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,}|(?i:api[_-]?key|access[_-]?token|password|client_secret)\s*[:=]\s*[\x22\x27]?[^\s\x22\x27]{8,}', content):
                return True
        # Inspect staged content too; working-tree content can differ.
        size = self.run(root, 'cat-file', '-s', f':{name}', check=False).strip()
        if size.isdigit() and int(size) > 10 * 1024 * 1024:
            return True
        blob = self.run(root, 'show', f':{name}', check=False)
        return bool(re.search(rb'-----BEGIN [A-Z ]*PRIVATE KEY-----|gh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,}|(?i:api[_-]?key|access[_-]?token|password|client_secret)\s*[:=]\s*[\x22\x27]?[^\s\x22\x27]{8,}', blob))

    def prepare(self, project: Project, message: str) -> Plan:
        root, branch, upstream = self.validate(project.path)
        before = self._snapshot(root)
        staged = self._paths(root, 'diff', '--cached', '--name-only', '--no-renames', '-z')
        changed = set(staged + self._paths(root, 'diff', '--name-only', '--no-renames', '-z') +
                      self._paths(root, 'ls-files', '--others', '--exclude-standard', '-z'))
        excluded = sorted(p for p in changed if self.suspicious(root, p) or any(fnmatch.fnmatchcase(p, pattern) for pattern in project.exclusions))
        if set(staged) & set(excluded):
            raise GitError('Excluded or suspicious files are already staged. Review and unstage them manually before using the agent.')
        files = tuple(sorted(changed - set(excluded)))
        if files and not message.strip():
            raise GitError('Please describe the changes before committing.')
        counts = self.value(root, 'rev-list', '--left-right', '--count', f'HEAD...{upstream}').split()
        ahead, behind = map(int, counts)
        if behind:
            raise GitError('The local upstream indicates this branch is behind or diverged. Reconcile it manually; the agent will not pull or rebase.')
        ignored = tuple(self._paths(root, 'ls-files', '--others', '--ignored', '--exclude-standard', '-z'))
        tree = self.expected_tree(root, files)
        after = self._snapshot(root)
        if before != after:
            raise GitError('Repository changed during inspection. Please request a new preview.')
        return Plan(project.name, str(root), branch, upstream, message.strip(), files,
                    tuple(staged), tuple(excluded), ignored, ahead, after, tree)

    def stage(self, root: Path, files: tuple[str, ...], index: str | None = None) -> None:
        tracked = set(self._paths(root, 'ls-files', '--cached', '-z'))
        # A staged deletion/rename source may already be absent from both disk and index.
        paths = [name for name in files if (root / name).exists() or (root / name).is_symlink() or name in tracked]
        for offset in range(0, len(paths), 100):
            self.run(root, '--literal-pathspecs', 'add', '-A', '--', *paths[offset:offset + 100], index=index)

    def expected_tree(self, root: Path, files: tuple[str, ...]) -> str:
        # Build the approved tree in an isolated index; preview never changes the user's index.
        original = Path(self.value(root, 'rev-parse', '--git-path', 'index'))
        if not original.is_absolute():
            original = root / original
        with tempfile.TemporaryDirectory(prefix='gitpush-index-') as temporary:
            index = str(Path(temporary) / 'index')
            if original.exists():
                shutil.copyfile(original, index)
            else:
                self.run(root, 'read-tree', 'HEAD', index=index)
            self.stage(root, files, index=index)
            return self.run(root, 'write-tree', index=index).decode().strip()

    def execute(self, plan: Plan) -> str:
        if not self._lock.acquire(blocking=False):
            raise GitError('Another Git operation is already running.')
        try:
            root, branch, upstream = self.validate(plan.root)
            if (branch, upstream) != (plan.branch, plan.upstream) or self._snapshot(root) != plan.fingerprint:
                raise GitError('Repository changed after confirmation. Request a new preview and confirm again.')
            if not plan.has_work:
                return 'No changes to push.'
            self.output(f'Project: {plan.project}\nRepository: {root}\nBranch: {branch}')
            if plan.files:
                self.phase('STAGING')
                # Literal pathspecs protect names containing wildcards or leading dashes.
                self.stage(root, plan.files)
                if self.value(root, 'write-tree') != plan.tree:
                    raise GitError('File contents changed while staging. Nothing committed; review the index and confirm a fresh preview.')
                actual = set(self._paths(root, 'diff', '--cached', '--name-only', '--no-renames', '-z'))
                if actual != set(plan.files):
                    raise GitError('Staged selection changed or is empty. Review the index manually.')
                self.run(root, 'diff', '--cached', '--check')
                self.output(self.value(root, 'diff', '--cached', '--stat'))
                self.phase('COMMITTING')
                self.output(self.value(root, 'commit', '-m', plan.message))
                if self.value(root, 'rev-parse', 'HEAD^{tree}') != plan.tree:
                    raise GitError('A hook changed the approved tree. Local commit retained; push cancelled.')
            if self.value(root, 'symbolic-ref', '--short', 'HEAD') != branch:
                raise GitError('Branch changed during commit. Local commit retained; push cancelled.')
            self.phase('PUSHING')
            # Explicit destination avoids push.default, pushRemote, and matching-ref surprises.
            remote = self.value(root, 'config', '--get', f'branch.{branch}.remote')
            merge = self.value(root, 'config', '--get', f'branch.{branch}.merge')
            if not merge.startswith('refs/heads/'):
                raise GitError('Unsupported upstream destination.')
            self.output(self.value(root, 'push', '--porcelain', '--no-follow-tags', remote, f'HEAD:{merge}'))
            head = self.value(root, 'rev-parse', 'HEAD')
            advertised = self.value(root, 'ls-remote', '--exit-code', remote, merge).split()
            if not advertised or advertised[0] != head:
                raise GitError('Push returned but the remote branch could not be verified. Inspect the remote before retrying.')
            self.output(f'Verified remote commit: {head}')
            return 'Changes pushed successfully!'
        finally:
            self._lock.release()
