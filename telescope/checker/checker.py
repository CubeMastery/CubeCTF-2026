import os
import random
import socket
import string
import sys
import time

PORT = 7419
TIMEOUT = 8
OK = ("", "", True)

SCOPES = ["VegaArray", "HalleyPier", "KeplerFork", "Borealis", "Asteria", "MizarRig"]
MOUNTS = ["equatorial", "dobsonian", "altaz", "harmonic-drive", "fork"]
TITLES = ["polar-log", "mirror-log", "focus-log", "tracking-log", "finder-log"]


def is_ok(resp: str) -> bool:
    return resp == "OK" or resp.startswith("OK ") or resp.startswith("OK|")


class TelescopeClient:
    def __init__(self, host: str):
        self.sock = socket.create_connection((host, PORT), timeout=TIMEOUT)
        self.sock.settimeout(TIMEOUT)
        self.file = self.sock.makefile("rwb", buffering=0)
        banner = self.recv()
        if not banner.startswith("OK "):
            raise RuntimeError("bad banner")

    def close(self):
        try:
            self.file.close()
            self.sock.close()
        except OSError:
            pass

    def recv(self) -> str:
        line = self.file.readline(65536)
        if not line:
            raise RuntimeError("connection closed")
        return line.decode("utf-8", "replace").rstrip("\r\n")

    def cmd(self, line: str) -> str:
        self.file.write((line + "\n").encode())
        return self.recv()


def rand_text(n: int = 12) -> str:
    alphabet = string.ascii_letters + string.digits
    return "".join(random.choice(alphabet) for _ in range(n))


def password() -> str:
    return "pw-" + os.urandom(10).hex()


def safe_user(flag_id: str) -> str:
    cleaned = "".join(c if c.isalnum() or c in "_.-" else "_" for c in flag_id)
    return cleaned[:36] or ("u" + os.urandom(4).hex())


def exercise_public_features(c: TelescopeClient, scope: str):
    month = random.randint(1, 12)
    hour = random.randint(0, 23)
    probes = [
        f"CONSTELLATIONS {scope} {hour:02d}:00 {month}",
        f"EPHEMERIS {scope} M{random.randint(1, 110)}",
        "LIST_SCOPES",
        "BANNER",
    ]
    random.shuffle(probes)
    for probe in probes[: random.randint(2, len(probes))]:
        resp = c.cmd(probe)
        if not is_ok(resp):
            raise RuntimeError(f"probe failed: {probe}: {resp}")


def check(host: str) -> tuple[str, str, bool]:
    try:
        c = TelescopeClient(host)
        try:
            resp = c.cmd("PING")
            if resp != "OK ORION":
                return ("bad ping " + resp, "", False)
            user = "chk_" + os.urandom(5).hex()
            pw = password()
            if not is_ok(c.cmd(f"REGISTER {user} {pw}")):
                return ("register failed", "", False)
            if not is_ok(c.cmd(f"LOGIN {user} {pw}")):
                return ("login failed", "", False)
            scope = random.choice(SCOPES) + rand_text(4)
            add = c.cmd(
                f"ADD_SCOPE {scope} {random.uniform(-55, 55):.3f} "
                f"{random.uniform(-150, 150):.3f} {random.randint(70, 450)} "
                f"{random.choice(MOUNTS)}"
            )
            if not is_ok(add):
                return ("scope add failed " + add, "", False)
            exercise_public_features(c, scope)
            return OK
        finally:
            c.close()
    except Exception as exc:
        return (str(exc), "", False)


def put(host: str, flag: str, flag_id: str) -> tuple[str, str, bool] | tuple[str, str, bool, str]:
    user = safe_user(flag_id)
    pw = password()
    scope = random.choice(SCOPES) + rand_text(5)
    title = random.choice(TITLES) + "-" + rand_text(5)
    body = f"{flag} seeing={random.randint(1, 5)} target=N{random.randint(1000, 9999)}"
    private = "|".join([user, pw, title])
    try:
        c = TelescopeClient(host)
        try:
            resp = c.cmd(f"REGISTER {user} {pw}")
            if not is_ok(resp):
                return ("register failed " + resp, private, False, user)
            if not is_ok(c.cmd(f"LOGIN {user} {pw}")):
                return ("login failed", private, False, user)
            resp = c.cmd(
                f"ADD_SCOPE {scope} {random.uniform(-60, 60):.4f} "
                f"{random.uniform(-170, 170):.4f} {random.randint(90, 600)} "
                f"{random.choice(MOUNTS)}"
            )
            if not is_ok(resp):
                return ("scope failed " + resp, private, False, user)
            resp = c.cmd(f"STORE_NOTE {scope} {title} {body}")
            if not is_ok(resp):
                return ("note failed " + resp, private, False, user)
            exercise_public_features(c, scope)
            return ("", private, True, user)
        finally:
            c.close()
    except Exception as exc:
        return (str(exc), private, False, user)


def get(host: str, flag: str, flag_id: str, private: str) -> tuple[str, str, bool]:
    try:
        user, pw, title = private.split("|", 2)
    except ValueError:
        return ("bad private state", "", False)
    try:
        c = TelescopeClient(host)
        try:
            if not is_ok(c.cmd(f"LOGIN {user} {pw}")):
                return ("login failed", "", False)
            resp = c.cmd(f"GET_NOTE {title}")
            if not is_ok(resp):
                return ("note fetch failed " + resp, "", False)
            if flag not in resp:
                return ("flag does not match", "", False)
            if random.choice([True, False]):
                exercise_public_features(c, random.choice(SCOPES))
            return OK
        finally:
            c.close()
    except Exception as exc:
        return (str(exc), "", False)


def _forcad_exit(resp):
    public, private, success = resp[:3]
    print(private)
    print(public)
    sys.exit(101 if success else 102)


if __name__ == "__main__":
    random.seed(time.time_ns() ^ os.getpid())
    if len(sys.argv) < 3:
        print("usage: checker.py check|get|put HOST ...", file=sys.stderr)
        sys.exit(102)
    action = sys.argv[1]
    host = sys.argv[2]
    if action == "check":
        _forcad_exit(check(host))
    if action == "put" and len(sys.argv) >= 5:
        _forcad_exit(put(host, sys.argv[4], sys.argv[3])[:3])
    if action == "get" and len(sys.argv) >= 5:
        _forcad_exit(get(host, sys.argv[4], sys.argv[3], sys.argv[3]))
    print("bad arguments", file=sys.stderr)
    sys.exit(102)
