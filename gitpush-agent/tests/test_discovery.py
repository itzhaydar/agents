import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from gitpush.config import Project
from gitpush.discovery import discover, merge_projects, spoken_name


class DiscoveryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def repo(self, relative):
        folder = self.root / relative
        (folder / '.git').mkdir(parents=True)
        return folder

    def test_find_multiple_without_registration(self):
        self.repo('Portfolio')
        self.repo('client/flight-app')
        result = discover([str(self.root)])
        self.assertEqual({p.name for p in result.projects}, {'portfolio', 'flight app'})
        self.assertFalse(result.warnings)

    def test_duplicate_names_preserved_for_disambiguation(self):
        self.repo('client/portfolio')
        self.repo('personal/portfolio')
        self.assertEqual(len(discover([str(self.root)]).projects), 2)

    def test_stops_at_root_and_skips_dependency_cache(self):
        self.repo('repo')
        self.repo('repo/submodule')
        self.repo('node_modules/dependency')
        self.assertEqual(len(discover([str(self.root)]).projects), 1)

    def test_linked_worktree_git_file(self):
        folder = self.root / 'linked'
        folder.mkdir()
        (folder / '.git').write_text('gitdir: /metadata/worktrees/linked')
        self.assertEqual(discover([str(self.root)]).projects[0].path, str(folder.resolve()))

    def test_limit_and_inaccessible_folder_reported(self):
        self.repo('one')
        self.assertTrue(discover([str(self.root)], limit=1).warnings)
        self.assertTrue(discover([str(self.root / 'missing')]).warnings)

    def test_symlink_does_not_escape_search_root(self):
        with tempfile.TemporaryDirectory() as outside:
            (Path(outside) / '.git').mkdir()
            try:
                (self.root / 'outside').symlink_to(outside, target_is_directory=True)
            except OSError:
                self.skipTest('Symlink creation not permitted')
            self.assertFalse(discover([str(self.root)]).projects)

    def test_registered_alias_and_exclusions_win_by_path(self):
        path = str(self.repo('repo'))
        saved = Project('special', path, ['alias'], exclusions=['private/*'])
        merged = merge_projects([saved], discover([str(self.root)]).projects)
        self.assertEqual(merged, [saved])

    def test_names_support_camel_case_and_hyphens(self):
        self.assertEqual(spoken_name('myPortfolio-app'), 'my portfolio app')
