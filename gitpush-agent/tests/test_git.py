import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from gitpush.config import Project
from gitpush.git_manager import GitManager, GitError, sanitize


class GitTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.remote = self.base / 'remote.git'
        self.root = self.base / 'project with spaces'
        self.root.mkdir()
        self.git(self.base, 'init', '--bare', str(self.remote))
        self.git(self.root, 'init', '-b', 'topic')
        self.git(self.root, 'config', 'user.email', 'test@example.invalid')
        self.git(self.root, 'config', 'user.name', 'Test User')
        self.write('readme.txt', 'original\n')
        self.git(self.root, 'add', '.')
        self.git(self.root, 'commit', '-m', 'Initial')
        self.git(self.root, 'remote', 'add', 'origin', str(self.remote))
        self.git(self.root, 'push', '-u', 'origin', 'topic')
        self.project = Project('Portfolio', str(self.root), ['my portfolio'])
        self.manager = GitManager()

    @staticmethod
    def git(root, *args):
        result = subprocess.run(['git', *args], cwd=root, capture_output=True, check=True)
        return result.stdout.decode().strip()

    def write(self, name, content):
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)

    def prepare(self):
        return self.manager.prepare(self.project, 'Fix layout')

    def test_push_success(self):
        self.write('mobile CV.txt', 'fixed\n')
        plan = self.prepare()
        self.assertEqual(plan.files, ('mobile CV.txt',))
        self.assertEqual(self.manager.execute(plan), 'Changes pushed successfully!')
        self.assertEqual(self.git(self.root, 'rev-parse', 'HEAD'), self.git(self.remote, 'rev-parse', 'topic'))
        self.assertFalse(self.git(self.root, 'status', '--porcelain'))

    def test_no_changes(self):
        plan = self.manager.prepare(self.project, '')
        self.assertFalse(plan.has_work)
        self.assertEqual(self.manager.execute(plan), 'No changes to push.')

    def test_push_only(self):
        self.write('readme.txt', 'new\n')
        self.git(self.root, 'commit', '-am', 'Local commit')
        plan = self.manager.prepare(self.project, '')
        self.assertEqual(plan.ahead, 1)
        self.assertFalse(plan.files)
        self.assertEqual(self.manager.execute(plan), 'Changes pushed successfully!')

    def test_sensitive_and_ignored_excluded(self):
        self.write('.env', 'TOP_SECRET=yes')
        self.write('.gitignore', '*.log\n')
        self.write('debug.log', 'ignored')
        self.write('safe.txt', 'safe')
        plan = self.prepare()
        self.assertIn('.env', plan.excluded)
        self.assertIn('debug.log', plan.ignored)
        self.manager.execute(plan)
        self.assertTrue((self.root / '.env').exists())
        self.assertNotIn('.env', self.git(self.root, 'ls-tree', '-r', '--name-only', 'HEAD').splitlines())

    def test_content_secret_excluded(self):
        self.write('settings.txt', 'api_key="abcdefghijklmnopqrstuvwxyz"')
        self.assertIn('settings.txt', self.prepare().excluded)

    def test_staged_secret_blocks(self):
        self.write('.env', 'SECRET=yes')
        self.git(self.root, 'add', '.env')
        with self.assertRaisesRegex(GitError, 'already staged'):
            self.prepare()

    def test_exclusions(self):
        self.project.exclusions = ['generated/*']
        self.write('generated/output.txt', 'ignore me')
        self.write('safe.txt', 'keep me')
        self.assertEqual(self.prepare().files, ('safe.txt',))

    def test_previously_staged_included(self):
        self.write('already.txt', 'staged')
        self.git(self.root, 'add', 'already.txt')
        self.write('other.txt', 'new')
        plan = self.prepare()
        self.assertEqual(plan.staged, ('already.txt',))
        self.manager.execute(plan)
        self.assertFalse(self.git(self.root, 'status', '--porcelain'))

    def test_renamed_deleted_unusual_paths(self):
        self.git(self.root, 'mv', 'readme.txt', 'renamed file.txt')
        self.write('colon [file].txt', 'unusual')
        self.write('--flag.txt', 'literal')
        if os.name != 'nt':
            self.write('line\nbreak.txt', 'newline')
        plan = self.prepare()
        self.manager.execute(plan)
        self.assertFalse(self.git(self.root, 'status', '--porcelain'))
        (self.root / 'renamed file.txt').unlink()
        self.manager.execute(self.prepare())
        self.assertFalse(self.git(self.root, 'status', '--porcelain'))

    def test_changed_content_invalidates_confirmation(self):
        self.write('readme.txt', 'one')
        plan = self.prepare()
        self.write('readme.txt', 'two')
        with self.assertRaisesRegex(GitError, 'changed after confirmation'):
            self.manager.execute(plan)

    def test_new_file_invalidates_confirmation(self):
        self.write('one.txt', 'one')
        plan = self.prepare()
        self.write('two.txt', 'two')
        with self.assertRaisesRegex(GitError, 'changed after confirmation'):
            self.manager.execute(plan)

    def test_config_change_invalidates_confirmation(self):
        self.write('one.txt', 'one')
        plan = self.prepare()
        self.git(self.root, 'config', 'branch.topic.merge', 'refs/heads/elsewhere')
        with self.assertRaises(GitError):
            self.manager.execute(plan)

    @unittest.skipIf(os.name == 'nt', 'Unix hook fixture')
    def test_commit_failure_no_push(self):
        self.write('readme.txt', 'changed')
        old = self.git(self.root, 'rev-parse', 'HEAD')
        hook = self.root / '.git' / 'hooks' / 'pre-commit'
        hook.write_text('#!/bin/sh\necho blocked >&2\nexit 1\n')
        hook.chmod(0o755)
        with self.assertRaisesRegex(GitError, 'blocked'):
            self.manager.execute(self.prepare())
        self.assertEqual(old, self.git(self.remote, 'rev-parse', 'topic'))
        self.assertEqual(old, self.git(self.root, 'rev-parse', 'HEAD'))

    @unittest.skipIf(os.name == 'nt', 'Unix hook fixture')
    def test_push_failure_preserves_local_commit(self):
        self.write('readme.txt', 'changed')
        old = self.git(self.root, 'rev-parse', 'HEAD')
        hook = self.remote / 'hooks' / 'pre-receive'
        hook.write_text('#!/bin/sh\necho denied >&2\nexit 1\n')
        hook.chmod(0o755)
        with self.assertRaisesRegex(GitError, 'rejected|denied'):
            self.manager.execute(self.prepare())
        self.assertNotEqual(old, self.git(self.root, 'rev-parse', 'HEAD'))
        self.assertEqual(old, self.git(self.remote, 'rev-parse', 'topic'))

    def test_missing_upstream(self):
        self.git(self.root, 'branch', '--unset-upstream')
        with self.assertRaises(GitError):
            self.prepare()

    def test_detached_head(self):
        self.git(self.root, 'checkout', '--detach')
        with self.assertRaises(GitError):
            self.prepare()

    def test_missing_project(self):
        self.project.path = str(self.base / 'missing')
        with self.assertRaises(GitError):
            self.prepare()

    def test_nested_project_requires_root_registration(self):
        nested = self.root / 'nested'
        nested.mkdir()
        self.project.path = str(nested)
        with self.assertRaisesRegex(GitError, 'Register the repository root'):
            self.prepare()

    def test_interrupted_operation(self):
        (self.root / '.git' / 'MERGE_HEAD').write_text(self.git(self.root, 'rev-parse', 'HEAD'))
        with self.assertRaisesRegex(GitError, 'interrupted'):
            self.prepare()

    def test_duplicate_operation_blocked(self):
        self.manager._lock.acquire()
        self.addCleanup(self.manager._lock.release)
        with self.assertRaisesRegex(GitError, 'already running'):
            self.manager.execute(self.prepare())

    def test_missing_description(self):
        self.write('readme.txt', 'changed')
        with self.assertRaisesRegex(GitError, 'describe'):
            self.manager.prepare(self.project, '')

    def test_large_file_excluded(self):
        with (self.root / 'large.bin').open('wb') as stream:
            stream.truncate(10 * 1024 * 1024 + 1)
        self.assertIn('large.bin', self.prepare().excluded)

    def test_sanitize(self):
        value = sanitize('https://user:password@example.com/repo ghp_' + 'a' * 30 + ' password=hello')
        self.assertNotIn('password@', value)
        self.assertNotIn('a' * 30, value)
        self.assertNotIn('hello', value)

    def test_preview_preserves_real_index(self):
        self.write('staged.txt', 'staged')
        self.git(self.root, 'add', 'staged.txt')
        before = (self.root / '.git' / 'index').read_bytes()
        self.write('unstaged.txt', 'unstaged')
        self.prepare()
        self.assertEqual(before, (self.root / '.git' / 'index').read_bytes())

    def test_mutation_during_staging_does_not_commit(self):
        self.write('readme.txt', 'approved')
        plan = self.prepare()
        old = self.git(self.root, 'rev-parse', 'HEAD')
        def output(line):
            if line.startswith('$ git --literal-pathspecs add'):
                self.write('readme.txt', 'changed concurrently')
        self.manager.output = output
        with self.assertRaisesRegex(GitError, 'contents changed'):
            self.manager.execute(plan)
        self.assertEqual(old, self.git(self.root, 'rev-parse', 'HEAD'))

    @unittest.skipIf(os.name == 'nt', 'Unix hook fixture')
    def test_hook_tree_change_prevents_push(self):
        self.write('readme.txt', 'approved')
        hook = self.root / '.git' / 'hooks' / 'pre-commit'
        hook.write_text('#!/bin/sh\nprintf changed > readme.txt\ngit add readme.txt\n')
        hook.chmod(0o755)
        before = self.git(self.remote, 'rev-parse', 'topic')
        with self.assertRaisesRegex(GitError, 'hook changed'):
            self.manager.execute(self.prepare())
        self.assertEqual(before, self.git(self.remote, 'rev-parse', 'topic'))

    def test_separate_push_url_rejected(self):
        self.git(self.root, 'config', 'remote.origin.pushurl', str(self.base / 'another.git'))
        with self.assertRaisesRegex(GitError, 'push URLs'):
            self.prepare()

    def test_secret_only_in_staged_version_rejected(self):
        self.write('settings.txt', 'api_key="abcdefghijklmnopqrstuvwxyz"')
        self.git(self.root, 'add', 'settings.txt')
        self.write('settings.txt', 'safe')
        with self.assertRaisesRegex(GitError, 'already staged'):
            self.prepare()

    def test_remote_rejection_after_other_clone_pushes(self):
        self.write('local.txt', 'local')
        plan = self.prepare()
        other = self.base / 'other'
        self.git(self.base, 'clone', '-b', 'topic', str(self.remote), str(other))
        self.git(other, 'config', 'user.email', 'other@example.invalid')
        self.git(other, 'config', 'user.name', 'Other')
        (other / 'remote.txt').write_text('remote')
        self.git(other, 'add', '.')
        self.git(other, 'commit', '-m', 'Remote change')
        self.git(other, 'push')
        with self.assertRaisesRegex(GitError, 'rejected'):
            self.manager.execute(plan)
        self.assertEqual(self.git(self.root, 'log', '-1', '--format=%s'), 'Fix layout')

    def test_git_not_installed(self):
        from unittest.mock import patch
        with patch('gitpush.git_manager.shutil.which', return_value=None):
            with self.assertRaisesRegex(GitError, 'Git is not installed'):
                self.prepare()

    def test_git_timeout(self):
        from unittest.mock import patch
        with patch('gitpush.git_manager.subprocess.run', side_effect=subprocess.TimeoutExpired('git', 1)):
            with self.assertRaisesRegex(GitError, 'timed out'):
                self.manager.run(self.root, 'status')

    def test_merge_conflict_blocked(self):
        self.git(self.root, 'checkout', '-b', 'other')
        self.write('readme.txt', 'other')
        self.git(self.root, 'commit', '-am', 'Other')
        self.git(self.root, 'checkout', 'topic')
        self.write('readme.txt', 'topic')
        self.git(self.root, 'commit', '-am', 'Topic')
        result = subprocess.run(['git', 'merge', 'other'], cwd=self.root, capture_output=True)
        self.assertNotEqual(result.returncode, 0)
        with self.assertRaises(GitError):
            self.prepare()

    def test_behind_upstream_blocked(self):
        other = self.base / 'other'
        self.git(self.base, 'clone', '-b', 'topic', str(self.remote), str(other))
        self.git(other, 'config', 'user.email', 'other@example.invalid')
        self.git(other, 'config', 'user.name', 'Other')
        (other / 'remote.txt').write_text('remote')
        self.git(other, 'add', '.')
        self.git(other, 'commit', '-m', 'Remote change')
        self.git(other, 'push')
        self.git(self.root, 'fetch')
        with self.assertRaisesRegex(GitError, 'behind or diverged'):
            self.prepare()
