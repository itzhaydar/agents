"""Bounded, read-only Git discovery; never initialize or modify repositories."""
from __future__ import annotations
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable
from .config import Project

SKIP = {'.git', '.venv', 'venv', 'node_modules', '__pycache__', 'AppData', '$RECYCLE.BIN', 'Windows', 'Program Files', 'build', 'dist'}


def default_roots() -> list[str]:
    home = Path.home()
    candidates = [home / name for name in ('Documents', 'Desktop', 'Projects', 'source', 'repos', 'Developer')]
    if os.environ.get('OneDrive'):
        candidates.extend(Path(os.environ['OneDrive']) / name for name in ('Documents', 'Desktop'))
    return list(dict.fromkeys(str(path) for path in candidates if path.is_dir()))


def spoken_name(name: str) -> str:
    name = re.sub(r'(?<=[a-z0-9])(?=[A-Z])', ' ', name)
    return ' '.join(re.findall(r'\w+', name.replace('_', ' '))).lower()


@dataclass
class Discovery:
    projects: list[Project] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    visited: int = 0


def discover(roots: list[str], progress: Callable[[str], None] = lambda _: None,
             limit: int = 20000, depth: int = 6) -> Discovery:
    result = Discovery()
    seen: set[Path] = set()
    stack = [(Path(root), 0) for root in reversed(roots)]
    while stack:
        path, level = stack.pop()
        if result.visited >= limit:
            result.warnings.append(f'Scan stopped at {limit} folders. Choose a narrower workspace to find more repositories.')
            break
        try:
            if path.is_symlink() or (hasattr(path, 'is_junction') and path.is_junction()):
                continue
            resolved = path.resolve(strict=True)
            if resolved in seen:
                continue
            seen.add(resolved)
            result.visited += 1
            if result.visited % 100 == 0:
                progress(f'Checked {result.visited} folders; found {len(result.projects)} Git repositories…')
            marker = path / '.git'
            if marker.is_dir() or marker.is_file():
                name = spoken_name(path.name)
                if name:
                    result.projects.append(Project(name, str(resolved), aliases=[path.name]))
                # Stop at roots to avoid declaring submodules as independent projects.
                continue
            with os.scandir(path) as entries:
                children = sorted((entry for entry in entries if entry.name not in SKIP and not entry.name.startswith('.')
                                   and entry.is_dir(follow_symlinks=False)), key=lambda entry: entry.name.casefold())
            if level < depth:
                stack.extend((Path(entry.path), level + 1) for entry in reversed(children))
            elif children:
                result.warnings.append(f'Depth limit reached under {path}. Add a deeper workspace to search it.')
        except OSError as exc:
            result.warnings.append(f'Could not inspect {path}: {exc.strerror or type(exc).__name__}')
    return result


def merge_projects(registered: list[Project], discovered: list[Project]) -> list[Project]:
    projects = {}
    for project in [*registered, *discovered]:
        projects.setdefault(os.path.normcase(str(Path(project.path).resolve())), project)
    return list(projects.values())
