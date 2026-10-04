import base64
import json
import os
import random
import socket
import string
import time

PORT = 4783
TIMEOUT = 8
PROMPT = b"C:\\Doors> "


def rnd(n=12, alphabet=string.ascii_lowercase + string.digits):
    return "".join(random.choice(alphabet) for _ in range(n))


def b64(data: str) -> str:
    return base64.b64encode(data.encode()).decode()


def unb64(data: str) -> str:
    return base64.b64decode(data.encode()).decode(errors="replace")


class DoorsClient:
    def __init__(self, host: str):
        self.sock = socket.create_connection((host, PORT), timeout=TIMEOUT)
        self.sock.settimeout(TIMEOUT)
        self._read_prompt()

    def close(self):
        try:
            self.sock.close()
        except OSError:
            pass

    def _read_prompt(self) -> str:
        data = b""
        while not data.endswith(PROMPT):
            chunk = self.sock.recv(4096)
            if not chunk:
                raise ConnectionError("closed")
            data += chunk
            if len(data) > 262144:
                raise ConnectionError("oversized response")
        return data[: -len(PROMPT)].decode(errors="replace").replace("\r\n", "\n").strip()

    def cmd(self, command: str) -> str:
        self.sock.sendall(command.encode() + b"\n")
        return self._read_prompt()

    def expect_ok(self, command: str) -> str:
        response = self.cmd(command)
        if not response.startswith("OK"):
            raise RuntimeError(f"{command!r}: {response!r}")
        return response[2:].strip()


def check(host: str):
    c = None
    try:
        c = DoorsClient(host)
        if c.expect_ok("PING") != "PONG":
            return ("bad ping", "", False)

        username = "chk" + rnd(10)
        password = rnd(18, string.ascii_letters + string.digits)
        folder = random.choice(["Documents", "Desktop", "Vault"])
        note_name = rnd(6) + ".txt"
        body = f"note-{rnd(10)}-{int(time.time())}"

        c.expect_ok(f"REGISTER {username} {password}")
        c.expect_ok(f"LOGIN {username} {password}")
        c.expect_ok(f"MKDIR {folder}\\{rnd(5)}")
        c.expect_ok(f"PUT {folder}\\{note_name} {b64(body)}")
        got = c.expect_ok(f"GET {folder}\\{note_name}")
        if unb64(got) != body:
            return ("file mismatch", "", False)

        script_name = f"Documents\\{rnd(7)}.door"
        copied_name = f"Public\\{rnd(7)}.txt"
        script = f"COPY {folder}\\{note_name} {copied_name}\nECHO %USER%\n"
        c.expect_ok(f"PUT {script_name} {b64(script)}")
        c.expect_ok(f"RUN {script_name}")
        copied = c.expect_ok(f"GET {copied_name}")
        if unb64(copied) != body:
            return ("script copy mismatch", "", False)

        c.close()
        c = DoorsClient(host)

        output = c.expect_ok(f"RECOVER {username}")
        if len(output) < 1:
            return ("recovery failed", "", False)
        # TODO: actually test recovery


        return ("", "", True)
    except Exception as exc:
        return (str(exc)[:80], "", False)
    finally:
        if c:
            c.close()


def put(host: str, flag: str, flag_id: str):
    c = None
    try:
        username = "u" + os.urandom(8).hex()
        password = rnd(22, string.ascii_letters + string.digits)
        decoy_count = random.randint(2, 5)
        c = DoorsClient(host)
        c.expect_ok(f"REGISTER {username} {password}")
        c.expect_ok(f"LOGIN {username} {password}")

        for _ in range(decoy_count):
            folder = random.choice(["Documents", "Desktop", "Vault"])
            name = rnd(random.randint(5, 10)) + random.choice([".txt", ".cfg", ".log"])
            content = f"{rnd(16)}:{flag_id}:{rnd(8)}"
            c.expect_ok(f"PUT {folder}\\{name} {b64(content)}")

        path = "Vault\\flag.txt"
        c.expect_ok(f"PUT {path} {b64(flag)}")

        marker = rnd(9)
        script = f"ECHO saved-{marker}\nTYPE {path}\n"
        c.expect_ok(f"PUT Documents\\{marker}.door {b64(script)}")

        private = json.dumps({"username": username, "password": password, "path": path})
        return ("", private, True, username)
    except Exception as exc:
        return (str(exc)[:80], "", False)
    finally:
        if c:
            c.close()


def get(host: str, flag: str, flag_id: str, private: str):
    c = None
    try:
        data = json.loads(private)
        c = DoorsClient(host)
        c.expect_ok(f"LOGIN {data['username']} {data['password']}")

        if random.choice([True, False]):
            c.expect_ok("DIR Vault")
        got = c.expect_ok(f"GET {data['path']}")
        if unb64(got) != flag:
            return ("flag does not match", "", False)

        scratch = f"Public\\{rnd(6)}.txt"
        c.expect_ok(f"COPY {data['path']} {scratch}")
        copied = c.expect_ok(f"GET {scratch}")
        if unb64(copied) != flag:
            return ("copy mismatch", "", False)
        return ("", private, True)
    except Exception as exc:
        return (str(exc)[:80], private, False)
    finally:
        if c:
            c.close()
