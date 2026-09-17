"""Identity-scoped durable encrypted room history and delivery outbox."""

from __future__ import annotations

import os
from pathlib import Path

import aiosqlite
from nostr_sdk import Keys, Nip44Version, nip44_decrypt, nip44_encrypt

from toad.extensions.dega_panel.rooms.protocol import Envelope, RoomError, decode


class Journal:
    """Serialize durable room changes using one SQLite connection per identity."""

    def __init__(self, path: Path, keys: Keys) -> None:
        self.path = path
        self.keys = keys
        self._db: aiosqlite.Connection | None = None

    @property
    def db(self) -> aiosqlite.Connection:
        assert self._db is not None
        return self._db

    async def open(self) -> None:
        if self._db is not None:
            return
        self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        descriptor = os.open(self.path, os.O_CREAT | os.O_RDWR, 0o600)
        os.close(descriptor)
        os.chmod(self.path, 0o600)
        self._db = await aiosqlite.connect(self.path)
        try:
            await self.db.executescript("""
                PRAGMA journal_mode=DELETE;
                CREATE TABLE IF NOT EXISTS rooms (
                    id TEXT PRIMARY KEY, proof TEXT NOT NULL, status TEXT NOT NULL,
                    conflict INTEGER NOT NULL DEFAULT 0);
                CREATE TABLE IF NOT EXISTS events (
                    id TEXT PRIMARY KEY, room TEXT NOT NULL, author TEXT NOT NULL,
                    kind TEXT NOT NULL, timestamp INTEGER NOT NULL, cipher TEXT NOT NULL,
                    status TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS outbox (
                    event TEXT NOT NULL REFERENCES events(id), peer TEXT NOT NULL,
                    status TEXT NOT NULL, error TEXT NOT NULL DEFAULT '',
                    PRIMARY KEY(event, peer));
                CREATE TABLE IF NOT EXISTS proofs (
                    room TEXT NOT NULL, revision INTEGER NOT NULL, id TEXT NOT NULL,
                    proof TEXT NOT NULL,
                    PRIMARY KEY(room, id));
                CREATE TABLE IF NOT EXISTS deferred (
                    id TEXT PRIMARY KEY, room TEXT NOT NULL, cipher TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS dm_history (
                    id TEXT PRIMARY KEY, peer TEXT NOT NULL, mine INTEGER NOT NULL,
                    timestamp INTEGER NOT NULL, cipher TEXT NOT NULL);
            """)
            await self.db.commit()
        except BaseException:
            await self.close()
            raise

    def encrypt(self, content: str) -> str:
        return nip44_encrypt(
            self.keys.secret_key(), self.keys.public_key(), content, Nip44Version.V2
        )

    def decrypt(self, cipher: str) -> str:
        return nip44_decrypt(self.keys.secret_key(), self.keys.public_key(), cipher)

    async def rows(self, sql: str, params: tuple = ()) -> list:
        assert self.db is not None
        async with self.db.execute(sql, params) as cursor:
            return list(await cursor.fetchall())

    async def write(
        self,
        event: Envelope,
        *,
        recipients: list[str] | None = None,
        room: tuple[str, str, str] | None = None,
        status: str = "accepted",
        proof: Envelope | None = None,
    ) -> bool:
        """Atomically save an encrypted event, its outbox, and optional room projection."""
        assert self.db is not None
        existing = await self.rows("SELECT cipher FROM events WHERE id=?", (event.key,))
        if existing:
            if decode(self.decrypt(existing[0][0])).event_id != event.event_id:
                raise RoomError(
                    "state_conflict",
                    "Logical operation ID reused with different content",
                )
            return False
        try:
            if proof is not None:
                await self.db.execute(
                    "INSERT OR IGNORE INTO proofs VALUES (?,?,?,?)",
                    (
                        proof.room_id,
                        proof.payload["revision"],
                        proof.event_id,
                        proof.signed,
                    ),
                )
            await self.db.execute(
                "INSERT INTO events VALUES (?,?,?,?,?,?,?)",
                (
                    event.key,
                    event.room_id,
                    event.author,
                    event.kind,
                    event.created_at,
                    self.encrypt(event.signed),
                    status,
                ),
            )
            for peer in set(recipients or []):
                await self.db.execute(
                    "INSERT INTO outbox(event,peer,status) VALUES (?,?,'pending')",
                    (event.key, peer),
                )
            if room is not None:
                await self.db.execute(
                    "INSERT INTO rooms(id,proof,status) VALUES (?,?,?) "
                    "ON CONFLICT(id) DO UPDATE SET proof=excluded.proof,status=excluded.status",
                    room,
                )
            await self.db.commit()
        except Exception:
            await self.db.rollback()
            raise
        return True

    async def close(self) -> None:
        if self._db is not None:
            await self._db.close()
            self._db = None
