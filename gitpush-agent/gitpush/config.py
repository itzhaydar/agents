from __future__ import annotations
import json
import os
from dataclasses import asdict, dataclass, field
from pathlib import Path


def data_dir() -> Path:
    override = os.environ.get('GITPUSH_DATA_DIR')
    path = Path(override) if override else Path(os.environ.get('LOCALAPPDATA', Path.home() / '.local' / 'share')) / 'GitPushAgent'
    path.mkdir(parents=True, exist_ok=True)
    return path


@dataclass
class Project:
    name: str
    path: str
    aliases: list[str] = field(default_factory=list)
    valid: bool = False
    exclusions: list[str] = field(default_factory=list)


@dataclass
class Settings:
    projects: list[Project] = field(default_factory=list)
    model_path: str = ''
    wake_phrase: str = 'hey git push'
    volume: int = 90
    rate: int = 0
    microphone: int | None = None
    command_timeout: int = 30
    confirmation_timeout: int = 30

    @classmethod
    def load(cls, path: Path | None = None) -> Settings:
        path = path or data_dir() / 'config.json'
        if not path.exists():
            return cls()
        raw = json.loads(path.read_text(encoding='utf-8'))
        projects = [Project(**p) for p in raw.pop('projects', [])]
        return cls(projects=projects, **raw)

    def save(self, path: Path | None = None) -> None:
        path = path or data_dir() / 'config.json'
        temporary = path.with_suffix('.tmp')
        temporary.write_text(json.dumps(asdict(self), indent=2), encoding='utf-8')
        os.replace(temporary, path)
