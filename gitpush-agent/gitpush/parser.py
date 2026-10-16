from __future__ import annotations
import re
from dataclasses import dataclass, field
from .config import Project


def normalize(text: str) -> str:
    return ' '.join(re.findall(r"[\w]+", text.lower()))


def phrase_in(phrase: str, text: str) -> bool:
    return f' {normalize(phrase)} ' in f' {normalize(text)} '


def wake_matches(text: str, phrase: str) -> bool:
    # Restricted grammar is phrase recognition, not a dedicated wake-word engine.
    return normalize(text).replace('gitpush', 'git push') == normalize(phrase).replace('gitpush', 'git push')


def commit_message(text: str, projects: list[Project]) -> str:
    value = text.lower()
    value = re.sub(r'\b(?:commit and push|push)(?:\s+(?:the|my))?(?:\s+changes)?\b', ' ', value)
    for project in sorted(projects, key=lambda p: len(p.name), reverse=True):
        for alias in sorted([project.name, *project.aliases], key=len, reverse=True):
            value = re.sub(r'(?<!\w)' + re.escape(alias.lower()) + r'(?!\w)', ' ', value)
    value = re.sub(r'\b(?:we|i|have|has|in|to|my|project|folder|changes|the)\b', ' ', value)
    value = re.sub(r'\b(?:updated|update)\s+and\b', '', value)
    value = re.sub(r'^[\W_]*(?:and\s+)?', '', value)
    value = ' '.join(value.strip(' .,!?:;').split())
    # A change description must have a recognized change verb and an object.
    match = re.search(r'\b(fixed|fix|added|add|updated|update|improved|improve|removed|remove|changed|change|refactored|refactor|documented|document|resolved|resolve)\s+(.+)', value)
    if not match:
        return ''
    verbs = {'fixed': 'Fix', 'added': 'Add', 'updated': 'Update', 'improved': 'Improve',
             'removed': 'Remove', 'changed': 'Change', 'refactored': 'Refactor',
             'documented': 'Document', 'resolved': 'Resolve'}
    result = verbs.get(match[1], match[1].capitalize()) + ' ' + match[2].strip(' .')
    return re.sub(r'\bcv\b', 'CV', result)[:200]


@dataclass
class Command:
    action: str
    projects: list[Project] = field(default_factory=list)
    message: str = ''


def parse(text: str, projects: list[Project]) -> Command:
    normalized = normalize(text)
    controls = {'confirm push': 'confirm', 'cancel': 'cancel', 'cancel push': 'cancel',
                'close gitpush': 'close', 'close git push': 'close',
                'stop listening': 'stop', 'what s the status': 'status',
                'whats the status': 'status', 'status': 'status'}
    if normalized in controls:
        return Command(controls[normalized])
    if normalized.startswith('change message to ') or normalized.startswith('commit message '):
        prefix = 'change message to ' if normalized.startswith('change message to ') else 'commit message '
        message = normalized[len(prefix):].strip()
        return Command('correct', message=message[:200].capitalize())
    matches = [p for p in projects if any(phrase_in(a, text) for a in [p.name, *p.aliases])]
    action = 'push' if re.search(r'\bpush\b', normalized) else 'describe'
    return Command(action, matches, commit_message(text, matches))
