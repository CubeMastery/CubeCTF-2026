#!/usr/bin/env python3
"""Binary socket server for noise."""
import logging
import os
import socket
import socketserver

from noise.binproto import (
    F_ERROR,
    F_OK,
    BIN_PORT,
    Opcode,
    ProtocolError,
    Reader,
    Writer,
    recv_frame,
    send_frame,
    write_challenge,
    write_group,
    write_group_public,
    write_list,
    write_message,
    write_user,
)
from noise.db import DB
from noise.service import (
    ConflictError,
    InvalidTokenError,
    NotAuthorizedError,
    NotFoundError,
    NoiseError,
    NoiseService,
)

HOST = os.environ.get("NOISE_BIND", "0.0.0.0")
PORT = int(os.environ.get("NOISE_BIN_PORT", BIN_PORT))
# Drop a connection that sends nothing for this long, so idle/kept-open clients
# do not pin a worker thread forever.
CONN_TIMEOUT = int(os.environ.get("NOISE_CONN_TIMEOUT", "60"))

_ERR_CODE = {
    NotFoundError: 404,
    ConflictError: 409,
    InvalidTokenError: 401,
    NotAuthorizedError: 403,
}


def _register(svc, r):
    pub, name = r.text(), r.text()
    w = Writer()
    write_user(w, svc.register(pub, name))
    return w.data()


def _list_users(svc, r):
    w = Writer()
    write_list(w, svc.list_users(), write_user)
    return w.data()


def _list_all_groups(svc, r):
    w = Writer()
    write_list(w, svc.list_groups_public(), write_group_public)
    return w.data()


def _challenge(svc, r):
    w = Writer()
    write_challenge(w, svc.challenge(r.text()))
    return w.data()


def _send_dm(svc, r):
    token, dst_id, message = r.text(), r.u32(), r.text()
    svc.send_dm(token, dst_id, message)
    return b""


def _get_messages(svc, r):
    w = Writer()
    write_list(w, svc.get_dms(r.text()), write_message)
    return w.data()


def _create_group(svc, r):
    token, name = r.text(), r.text()
    w = Writer()
    write_group(w, svc.create_group(token, name))
    return w.data()


def _group_challenge(svc, r):
    w = Writer()
    write_challenge(w, svc.group_challenge(r.text()))
    return w.data()


def _invite(svc, r):
    token, gid, uid = r.text(), r.u32(), r.u32()
    svc.invite(token, gid, uid)
    return b""


def _list_groups(svc, r):
    w = Writer()
    write_list(w, svc.list_groups(r.text()), write_group)
    return w.data()


def _send_group(svc, r):
    token, gid, message = r.text(), r.u32(), r.text()
    svc.send_group(token, gid, message)
    return b""


def _group_messages(svc, r):
    w = Writer()
    write_list(w, svc.get_group_messages(r.text()), write_message)
    return w.data()


_DISPATCH = {
    Opcode.REGISTER: _register,
    Opcode.LIST_USERS: _list_users,
    Opcode.CHALLENGE: _challenge,
    Opcode.SEND_DM: _send_dm,
    Opcode.GET_MESSAGES: _get_messages,
    Opcode.CREATE_GROUP: _create_group,
    Opcode.GROUP_CHALLENGE: _group_challenge,
    Opcode.INVITE: _invite,
    Opcode.LIST_GROUPS: _list_groups,
    Opcode.SEND_GROUP: _send_group,
    Opcode.GROUP_MESSAGES: _group_messages,
    Opcode.LIST_ALL_GROUPS: _list_all_groups,
}


def _error_payload(code: int, message: str) -> bytes:
    return Writer().u16(code).text(message).data()


class Handler(socketserver.BaseRequestHandler):
    def setup(self):
        # Idle timeout reaps stuck connections; keepalive detects dead peers.
        self.request.settimeout(CONN_TIMEOUT)
        try:
            self.request.setsockopt(socket.SOL_SOCKET, socket.SO_KEEPALIVE, 1)
        except OSError:
            pass

    def _send(self, flags, opcode, payload) -> bool:
        try:
            send_frame(self.request, flags, opcode, payload)
            return True
        except OSError:
            return False

    def handle(self):
        sock = self.request
        service = self.server.service
        with sock:  # guarantee the socket is closed on any exit
            while True:
                try:
                    flags, opcode, payload = recv_frame(sock)
                except (ConnectionError, OSError):  # closed, reset, or idle timeout
                    return
                except ProtocolError as e:
                    self._send(F_ERROR, 0, _error_payload(400, str(e)))
                    return

                handler = _DISPATCH.get(opcode)
                try:
                    if handler is None:
                        ok = self._send(F_ERROR, opcode, _error_payload(400, f"unknown opcode {opcode}"))
                    else:
                        resp = handler(service, Reader(payload))
                        ok = self._send(F_OK, opcode, resp)
                except NoiseError as e:
                    code = next((c for t, c in _ERR_CODE.items() if isinstance(e, t)), 400)
                    ok = self._send(F_ERROR, opcode, _error_payload(code, str(e) or e.__class__.__name__))
                except ProtocolError as e:
                    ok = self._send(F_ERROR, opcode, _error_payload(400, str(e)))
                except Exception as e:  # noqa: BLE001 - don't kill the connection on a bug
                    logging.exception("handler error")
                    ok = self._send(F_ERROR, opcode, _error_payload(500, f"internal error: {e}"))
                if not ok:  # client went away mid-response
                    return


class NoiseTCPServer(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True

    def __init__(self, addr):
        super().__init__(addr, Handler)
        self.db = DB()
        self.service = NoiseService(self.db)


def main():
    logging.basicConfig(level=logging.INFO)
    with NoiseTCPServer((HOST, PORT)) as server:
        logging.info("noise binary protocol listening on %s:%d", HOST, PORT)
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass
        finally:
            server.db.close()


if __name__ == "__main__":
    main()
