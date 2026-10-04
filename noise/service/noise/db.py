#!/usr/bin/env python3
"""SQLite access layer"""
import os
import sqlite3
import threading

from .models import GroupPublic, GroupSecret, MessageOut, UserPublic

SCHEMA_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "schema.sql")


class DB:
    def __init__(self, path: str | None = None):
        path = path or os.environ.get("NOISE_DB", "noise.sqlite3")
        self._conn = sqlite3.connect(path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA foreign_keys = ON;")
        self._conn.execute("PRAGMA journal_mode = WAL;")  # tolerate two transports sharing the file
        self._lock = threading.Lock()
        self._create_tables()

    def _create_tables(self):
        with open(SCHEMA_PATH) as f, self._lock:
            self._conn.executescript(f.read())
            self._conn.commit()

    def close(self):
        with self._lock:
            self._conn.close()

    # --- users ---------------------------------------------------------------

    def create_user(self, pubkey: str, name: str) -> UserPublic:
        with self._lock:
            row = self._conn.execute(
                "INSERT INTO users (pub, name) VALUES (?, ?) RETURNING id, name, pub;", (pubkey, name)
            ).fetchone()
            self._conn.commit()
        return UserPublic(id=row["id"], name=row["name"], pubkey=row["pub"])

    def get_user_by_key(self, pubkey: str) -> UserPublic | None:
        with self._lock:
            row = self._conn.execute("SELECT id, name, pub FROM users WHERE pub = ?;", (pubkey,)).fetchone()
        return UserPublic(id=row["id"], name=row["name"], pubkey=row["pub"]) if row else None

    def get_user_by_id(self, uid: int) -> UserPublic | None:
        with self._lock:
            row = self._conn.execute("SELECT id, name, pub FROM users WHERE id = ?;", (uid,)).fetchone()
        return UserPublic(id=row["id"], name=row["name"], pubkey=row["pub"]) if row else None

    def get_users(self) -> list[UserPublic]:
        with self._lock:
            rows = self._conn.execute("SELECT id, name, pub FROM users ORDER BY id;").fetchall()
        return [UserPublic(id=r["id"], name=r["name"], pubkey=r["pub"]) for r in rows]

    # --- groups --------------------------------------------------------------

    def create_group(self, pubkey: str, privkey: str, name: str, owner_id: int) -> GroupSecret:
        with self._lock:
            row = self._conn.execute(
                "INSERT INTO groups (pub, priv, name, owner) VALUES (?, ?, ?, ?) " "RETURNING id, name, pub, priv;",
                (pubkey, privkey, name, owner_id),
            ).fetchone()
            self._conn.commit()
        return GroupSecret(id=row["id"], name=row["name"], pubkey=row["pub"], privkey=row["priv"])

    def get_group_by_key(self, pubkey: str) -> GroupSecret | None:
        with self._lock:
            row = self._conn.execute("SELECT id, name, pub, priv FROM groups WHERE pub = ?;", (pubkey,)).fetchone()
        return GroupSecret(id=row["id"], name=row["name"], pubkey=row["pub"], privkey=row["priv"]) if row else None

    def get_group_by_id(self, gid: int) -> GroupSecret | None:
        with self._lock:
            row = self._conn.execute("SELECT id, name, pub, priv FROM groups WHERE id = ?;", (gid,)).fetchone()
        return GroupSecret(id=row["id"], name=row["name"], pubkey=row["pub"], privkey=row["priv"]) if row else None

    def get_groups_public(self) -> list[GroupPublic]:
        with self._lock:
            rows = self._conn.execute("SELECT id, name, pub, owner FROM groups ORDER BY id;").fetchall()
        return [GroupPublic(id=r["id"], name=r["name"], pubkey=r["pub"], owner=r["owner"]) for r in rows]

    # --- direct messages -----------------------------------------------------

    def create_dm(self, src_id: int, dst_id: int, message: str):
        with self._lock:
            self._conn.execute(
                "INSERT INTO dm (src_uid, dst_uid, message) VALUES (?, ?, ?);", (src_id, dst_id, message)
            )
            self._conn.commit()

    def get_dms(self, dst_id: int) -> list[MessageOut]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT d.src_uid, u.name AS src_name, d.time, d.message "
                "FROM dm d JOIN users u ON u.id = d.src_uid "
                "WHERE d.dst_uid = ? ORDER BY d.id;",
                (dst_id,),
            ).fetchall()
        return [
            MessageOut(src_id=r["src_uid"], src_name=r["src_name"], time=str(r["time"]), message=r["message"])
            for r in rows
        ]

    # --- group messages ------------------------------------------------------

    def create_gmsg(self, src_id: int, gid: int, message: str):
        with self._lock:
            self._conn.execute("INSERT INTO gmsg (src_uid, gid, message) VALUES (?, ?, ?);", (src_id, gid, message))
            self._conn.commit()

    def get_gmsg(self, gid: int) -> list[MessageOut]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT g.src_uid, u.name AS src_name, g.time, g.message "
                "FROM gmsg g JOIN users u ON u.id = g.src_uid "
                "WHERE g.gid = ? ORDER BY g.id;",
                (gid,),
            ).fetchall()
        return [
            MessageOut(src_id=r["src_uid"], src_name=r["src_name"], time=str(r["time"]), message=r["message"])
            for r in rows
        ]

    # --- membership ----------------------------------------------------------

    def create_group_member(self, gid: int, uid: int):
        with self._lock:
            self._conn.execute("INSERT INTO group_members (gid, uid) VALUES (?, ?);", (gid, uid))
            self._conn.commit()

    def get_group_member_ids(self, gid: int) -> list[int]:
        with self._lock:
            rows = self._conn.execute("SELECT uid FROM group_members WHERE gid = ?;", (gid,)).fetchall()
        return [r["uid"] for r in rows]

    def is_member(self, gid: int, uid: int) -> bool:
        with self._lock:
            row = self._conn.execute(
                "SELECT 1 FROM group_members WHERE gid = ? AND uid = ? LIMIT 1;", (gid, uid)
            ).fetchone()
        return row is not None

    def get_user_groups(self, uid: int) -> list[GroupSecret]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT g.id, g.name, g.pub, g.priv FROM groups g "
                "JOIN group_members m ON m.gid = g.id WHERE m.uid = ? ORDER BY g.id;",
                (uid,),
            ).fetchall()
        return [GroupSecret(id=r["id"], name=r["name"], pubkey=r["pub"], privkey=r["priv"]) for r in rows]
