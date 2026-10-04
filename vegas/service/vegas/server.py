import shlex
import socket
import socketserver
from datetime import datetime, timezone

from . import commands
from .config import BANNER, IDLE_TIMEOUT, PROMPT
from .database import Database
from .session import Session

QUIT_COMMANDS = ("quit", "exit")


def resolve(name):
    return getattr(commands, "cmd_" + name.replace("-", "_"), None)


class CasinoHandler(socketserver.StreamRequestHandler):
    def setup(self):
        super().setup()
        self.session = Session()
        self.connection.settimeout(IDLE_TIMEOUT)

    def handle(self):
        try:
            self.reply(BANNER)
            self.reply(PROMPT)
            while True:
                line = self.rfile.readline()
                if not line:
                    break
                command = line.decode("utf-8", "replace").strip()
                if command:
                    response = self.run(command)
                    self.log_command(command, response)
                    self.reply(response)
                self.reply(PROMPT)
        except (socket.timeout, OSError, ValueError):
            pass

    def log_command(self, command, response):
        ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
        addr = f"{self.client_address[0]}:{self.client_address[1]}"
        username = self.session.token or "(anonymous)"
        print(f"[{ts}] {addr} user={username} cmd={command}", flush=True)
        for line in response.split("\n"):
            print(f"  → {line}", flush=True)

    def reply(self, text):
        self.wfile.write((text + "\n").encode())
        self.wfile.flush()

    def run(self, command):
        try:
            argv = shlex.split(command)
        except ValueError:
            return "error=unbalanced quotes in command"
        if not argv:
            return ""
        name = argv[0].lower()
        if name in QUIT_COMMANDS:
            raise ConnectionResetError("quit")
        handler = resolve(name)
        if handler is None:
            return "\n".join([f"error=unknown command '{argv[0]}'", "hint=type help"])
        try:
            return handler(self.session, self.database, argv[1:])
        except Exception as exc:
            return f"error={exc}"

    @property
    def database(self):
        return self.server.database


class CasinoServer(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True

    def __init__(self, address, handler):
        self.database = Database()
        super().__init__(address, handler)


def serve(address, handler=CasinoHandler):
    server = CasinoServer(address, handler)
    try:
        server.serve_forever()
    finally:
        server.server_close()
    return server
