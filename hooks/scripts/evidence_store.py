"""Transactional session-local coverage and checkpoint receipts."""
import json
import os
from pathlib import Path
import re
import sqlite3

from evidence_source import digest, encoded


class EvidenceStore:
    def __init__(self, data):
        session = data.get('session_id')
        if not isinstance(session, str) or not session:
            raise ValueError('claim evidence requires a session identity')
        agent = data.get('agent_id') or 'root'
        if not isinstance(agent, str):
            raise ValueError('invalid evidence agent identity')
        self.agent = encoded([str(Path(data['cwd']).resolve()), agent])
        root = Path.home().resolve() / '.cache' / 'ioncache-ai-tools' / 'claim-evidence'
        root.mkdir(mode=0o700, parents=True, exist_ok=True)
        info = root.lstat()
        if root.is_symlink() or info.st_uid != os.getuid() or info.st_mode & 0o077:
            raise ValueError('evidence directory must be owned by this user and private')
        identity = digest(session)
        path = root / f'{identity}.sqlite3'
        self.requests = root / f'{identity}-requests'
        descriptor = os.open(path, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
        try:
            info = os.fstat(descriptor)
            if info.st_uid != os.getuid() or info.st_mode & 0o077:
                raise ValueError('evidence database must be owned by this user and private')
        finally:
            os.close(descriptor)
        self.connection = sqlite3.connect(path, timeout=1)
        self.connection.execute(
            'CREATE TABLE IF NOT EXISTS records (agent TEXT, category TEXT, key TEXT, value TEXT, '
            'PRIMARY KEY (agent, category, key))'
        )

    def __enter__(self):
        try:
            self.connection.execute('BEGIN IMMEDIATE')
        except sqlite3.Error:
            self.connection.close()
            raise
        return self

    def __exit__(self, kind, value, traceback):
        try:
            if kind is None:
                self.connection.commit()
            else:
                self.connection.rollback()
        finally:
            self.connection.close()

    def get(self, category, key):
        row = self.connection.execute(
            'SELECT value FROM records WHERE agent = ? AND category = ? AND key = ?',
            (self.agent, category, key),
        ).fetchone()
        return json.loads(row[0]) if row else None

    def put(self, category, item):
        key, value = item
        self.connection.execute(
            'INSERT OR REPLACE INTO records VALUES (?, ?, ?, ?)',
            (self.agent, category, key, encoded(value)),
        )

    def remove(self, category, key):
        self.connection.execute(
            'DELETE FROM records WHERE agent = ? AND category = ? AND key = ?',
            (self.agent, category, key),
        )

    def reset(self):
        self.connection.execute('DELETE FROM records')
        if self.requests.exists():
            self.validate_requests()
            for path in self.requests.iterdir():
                if re.fullmatch(r'[a-f0-9]{64}(?:\.review)?\.json', path.name):
                    path.unlink()

    def request_path(self, fingerprint):
        self.requests.mkdir(mode=0o700, exist_ok=True)
        self.validate_requests()
        return self.requests / f'{fingerprint}.json'

    def validate_requests(self):
        info = self.requests.lstat()
        if self.requests.is_symlink() or info.st_uid != os.getuid() or info.st_mode & 0o077:
            raise ValueError('evidence request directory must be owned by this user and private')


def reference_key(reference):
    return encoded({key: reference[key] for key in ('path', 'sha256', 'unit')})


def record_page(store, page):
    key = reference_key(page)
    seen = set(store.get('pages', key) or [])
    seen.add(page['page'])
    store.put('pages', (key, sorted(seen)))
    complete = len(seen) == page['pages']
    if complete:
        store.put('coverage', (key, True))
    return complete
