import socket
import json
import random
import string
import time
from faker import Faker

HOST = "localhost"
PORT = 8492
TIMEOUT = 15


def _random_str(length=12):
    return "".join(random.choices(string.ascii_lowercase + string.digits, k=length))


def _connect(host):
    last_err = None
    for attempt in range(3):
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(TIMEOUT)
        try:
            s.connect((host, PORT))
            _read_until_prompt(s)
            return s
        except Exception as e:
            last_err = e
            try:
                s.close()
            except Exception:
                pass
            time.sleep(0.5 * (attempt + 1))
    raise last_err


def _read_until_prompt(s):
    data = b""
    while True:
        try:
            chunk = s.recv(4096)
            if not chunk:
                break
            data += chunk
            if b"> " in data:
                break
        except socket.timeout:
            break
    return data.decode(errors="replace")


def _send_cmd(s, cmd):
    s.sendall((cmd + "\n").encode())
    time.sleep(0.2)
    data = _read_until_prompt(s)
    for line in data.split("\r\n"):
        line = line.strip()
        if line and not line.startswith(">"):
            return line
    return data.strip()


def _close(s):
    try:
        s.close()
    except Exception:
        pass


def check(host):
    try:
        s = _connect(host)
        _close(s)
        return ("", "", True)
    except Exception as e:
        return (str(e), "", False)


def put(host, flag, flag_id):
    flag_id = Faker().user_name()
    password = _random_str(16)
    filename = "flag.txt"

    try:
        s = _connect(host)

        r = _send_cmd(s, f"register {flag_id} {password}")
        if "OK" not in r and "already exists" not in r:
            _close(s)
            return (f"register failed: {r}", "", False)

        r = _send_cmd(s, f"login {flag_id} {password}")
        if not r.startswith("OK"):
            _close(s)
            return (f"login failed: {r}", "", False)

        _ = _send_cmd(s, f"write {filename} {flag}")

        _close(s)

        private = json.dumps({"password": password, "filename": filename})
        return ("", private, True, flag_id)
    except Exception as e:
        return (str(e), "", False)


def get(host, flag, flag_id, private):
    try:
        data = json.loads(private)
        password = data["password"]
        filename = data["filename"]
    except (json.JSONDecodeError, KeyError):
        return ("invalid private data", "", False)

    try:
        time.sleep(random.uniform(0.5, 2.0))

        s = _connect(host)

        r = _send_cmd(s, f"login {flag_id} {password}")
        if not r.startswith("OK"):
            _close(s)
            return (f"login failed: {r}", "", False)

        time.sleep(random.uniform(0.3, 1.0))

        r = _send_cmd(s, f"read {filename}")

        _close(s)

        if r.startswith("ERROR") or r.startswith("usage"):
            return (f"read failed: {r}", "", False)

        if r != flag:
            return ("flag mismatch", "", False)

        return ("", "", True)
    except Exception as e:
        return (str(e), "", False)
