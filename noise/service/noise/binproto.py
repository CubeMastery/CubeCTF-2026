#!/usr/bin/env python3
"""Binary wire protocol for noise.

Frame:
    struct !4sBBBI = magic, version, flags, opcode, payload_len
    payload        = packed fields (see the per-op layouts in binapi/server)

Field packing (big-endian):
    u8/u16/u32     = struct !B / !H / !I
    bytes          = u32 length prefix + raw bytes
    str            = bytes of UTF-8
"""
import socket
import struct
from enum import IntEnum

from .models import Challenge, GroupPublic, GroupSecret, MessageOut, UserPublic

MAGIC = b"NOIZ"
VERSION = 1
BIN_PORT = 31416
MAX_FRAME = 1 << 20  # 1 MiB guard

# frame flags
F_REQUEST = 0
F_OK = 1
F_ERROR = 2

_HEADER = struct.Struct("!4sBBBI")


class Opcode(IntEnum):
    REGISTER = 1
    LIST_USERS = 2
    CHALLENGE = 3
    SEND_DM = 4
    GET_MESSAGES = 5
    CREATE_GROUP = 6
    GROUP_CHALLENGE = 7
    INVITE = 8
    LIST_GROUPS = 9
    SEND_GROUP = 10
    GROUP_MESSAGES = 11
    LIST_ALL_GROUPS = 12


class ProtocolError(Exception):
    """Malformed frame or payload."""


# --- field codec ------------------------------------------------------------


class Writer:
    def __init__(self):
        self.buf = bytearray()

    def u8(self, v: int) -> "Writer":
        self.buf += struct.pack("!B", v)
        return self

    def u16(self, v: int) -> "Writer":
        self.buf += struct.pack("!H", v)
        return self

    def u32(self, v: int) -> "Writer":
        self.buf += struct.pack("!I", v)
        return self

    def raw(self, b: bytes) -> "Writer":
        self.u32(len(b))
        self.buf += b
        return self

    def text(self, s: str) -> "Writer":
        return self.raw(s.encode("utf-8"))

    def data(self) -> bytes:
        return bytes(self.buf)


class Reader:
    def __init__(self, data: bytes):
        self.data = data
        self.i = 0

    def _take(self, n: int) -> bytes:
        if self.i + n > len(self.data):
            raise ProtocolError("payload truncated")
        chunk = self.data[self.i : self.i + n]
        self.i += n
        return chunk

    def u8(self) -> int:
        return struct.unpack("!B", self._take(1))[0]

    def u16(self) -> int:
        return struct.unpack("!H", self._take(2))[0]

    def u32(self) -> int:
        return struct.unpack("!I", self._take(4))[0]

    def raw(self) -> bytes:
        return self._take(self.u32())

    def text(self) -> str:
        return self.raw().decode("utf-8")


# --- entity (de)serialization ----------------------------------------------


def write_user(w: Writer, u: UserPublic):
    w.u32(u.id).text(u.name).text(u.pubkey)


def read_user(r: Reader) -> UserPublic:
    return UserPublic(id=r.u32(), name=r.text(), pubkey=r.text())


def write_group(w: Writer, g: GroupSecret):
    w.u32(g.id).text(g.name).text(g.pubkey).text(g.privkey)


def read_group(r: Reader) -> GroupSecret:
    return GroupSecret(id=r.u32(), name=r.text(), pubkey=r.text(), privkey=r.text())


def write_group_public(w: Writer, g: GroupPublic):
    w.u32(g.id).text(g.name).text(g.pubkey).u32(g.owner)


def read_group_public(r: Reader) -> GroupPublic:
    return GroupPublic(id=r.u32(), name=r.text(), pubkey=r.text(), owner=r.u32())


def write_message(w: Writer, m: MessageOut):
    w.u32(m.src_id).text(m.src_name).text(m.time).text(m.message)


def read_message(r: Reader) -> MessageOut:
    return MessageOut(src_id=r.u32(), src_name=r.text(), time=r.text(), message=r.text())


def write_challenge(w: Writer, c: Challenge):
    w.text(c.challenge)


def read_challenge(r: Reader) -> Challenge:
    return Challenge(challenge=r.text())


def write_list(w: Writer, items, write_item):
    w.u32(len(items))
    for it in items:
        write_item(w, it)


def read_list(r: Reader, read_item) -> list:
    return [read_item(r) for _ in range(r.u32())]


# --- framing over a socket --------------------------------------------------


def _recv_exact(sock: socket.socket, n: int) -> bytes:
    chunks = []
    got = 0
    while got < n:
        chunk = sock.recv(n - got)
        if not chunk:
            raise ConnectionError("peer closed connection")
        chunks.append(chunk)
        got += len(chunk)
    return b"".join(chunks)


def send_frame(sock: socket.socket, flags: int, opcode: int, payload: bytes):
    if len(payload) > MAX_FRAME:
        raise ProtocolError("payload too large")
    sock.sendall(_HEADER.pack(MAGIC, VERSION, flags, opcode, len(payload)) + payload)


def recv_frame(sock: socket.socket) -> tuple[int, int, bytes]:
    magic, version, flags, opcode, length = _HEADER.unpack(_recv_exact(sock, _HEADER.size))
    if magic != MAGIC:
        raise ProtocolError("bad magic")
    if version != VERSION:
        raise ProtocolError(f"unsupported version {version}")
    if length > MAX_FRAME:
        raise ProtocolError("frame too large")
    payload = _recv_exact(sock, length) if length else b""
    return flags, opcode, payload
