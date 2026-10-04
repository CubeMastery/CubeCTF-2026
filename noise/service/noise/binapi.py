#!/usr/bin/env python3
"""Binary-protocol client for the noise service."""
import socket
import threading

from . import crypto
from .binproto import (
    F_ERROR,
    F_REQUEST,
    BIN_PORT,
    Opcode,
    Reader,
    Writer,
    read_challenge,
    read_group,
    read_group_public,
    read_list,
    read_message,
    read_user,
    recv_frame,
    send_frame,
)


class ApiError(Exception):
    def __init__(self, status: int, message: str):
        super().__init__(f"{status}: {message}")
        self.status = status
        self.message = message


class BinaryNoiseClient:
    def __init__(self, host: str, port: int = BIN_PORT, timeout: float = 10.0):
        self.host = host
        self.port = port
        self.timeout = timeout
        self._sock: socket.socket | None = None
        self._lock = threading.Lock()

    # --- connection / call plumbing -------------------------------------

    def _connect(self):
        self._sock = socket.create_connection((self.host, self.port), timeout=self.timeout)

    def _close(self):
        if self._sock is not None:
            try:
                self._sock.close()
            finally:
                self._sock = None

    def _call(self, opcode: Opcode, payload: bytes) -> Reader:
        with self._lock:
            last = None
            for attempt in (1, 2):  # 1x transparent reconnect
                try:
                    if self._sock is None:
                        self._connect()
                    send_frame(self._sock, F_REQUEST, int(opcode), payload)
                    flags, _op, resp = recv_frame(self._sock)
                    break
                except (ConnectionError, OSError) as e:
                    last = e
                    self._close()
            else:
                raise last
        if flags == F_ERROR:
            rr = Reader(resp)
            raise ApiError(rr.u16(), rr.text())
        return Reader(resp)

    # --- users -----------------------------------------------------------

    def register(self, pubkey: str, name: str):
        r = self._call(Opcode.REGISTER, Writer().text(pubkey).text(name).data())
        return read_user(r)

    def get_users(self):
        return read_list(self._call(Opcode.LIST_USERS, b""), read_user)

    def get_groups(self):
        return read_list(self._call(Opcode.LIST_ALL_GROUPS, b""), read_group_public)

    def get_challenge(self, pubkey: str):
        return read_challenge(self._call(Opcode.CHALLENGE, Writer().text(pubkey).data()))

    def authenticate(self, pubkey: str, privkey: str) -> str:
        challenge = self.get_challenge(pubkey)
        return crypto.decrypt_with(privkey, challenge.challenge).decode()

    # --- direct messages -------------------------------------------------

    def send_dm(self, token: str, dst_id: int, message: str) -> dict:
        self._call(Opcode.SEND_DM, Writer().text(token).u32(dst_id).text(message).data())
        return {"ok": True}

    def get_messages(self, token: str):
        return read_list(self._call(Opcode.GET_MESSAGES, Writer().text(token).data()), read_message)

    # --- groups ----------------------------------------------------------

    def create_group(self, token: str, name: str):
        return read_group(self._call(Opcode.CREATE_GROUP, Writer().text(token).text(name).data()))

    def get_group_challenge(self, pubkey: str):
        return read_challenge(self._call(Opcode.GROUP_CHALLENGE, Writer().text(pubkey).data()))

    def group_token(self, group_pubkey: str, group_privkey: str) -> str:
        challenge = self.get_group_challenge(group_pubkey)
        return crypto.decrypt_with(group_privkey, challenge.challenge).decode()

    def invite(self, token: str, gid: int, uid: int) -> dict:
        self._call(Opcode.INVITE, Writer().text(token).u32(gid).u32(uid).data())
        return {"ok": True}

    def list_groups(self, token: str):
        return read_list(self._call(Opcode.LIST_GROUPS, Writer().text(token).data()), read_group)

    def send_group(self, token: str, gid: int, message: str) -> dict:
        self._call(Opcode.SEND_GROUP, Writer().text(token).u32(gid).text(message).data())
        return {"ok": True}

    def group_messages(self, group_token: str):
        return read_list(self._call(Opcode.GROUP_MESSAGES, Writer().text(group_token).data()), read_message)
