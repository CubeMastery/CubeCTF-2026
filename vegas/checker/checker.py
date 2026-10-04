#!/usr/bin/env python3

import base64
import hashlib
import itertools
import json
import random
import shlex
import socket
import string
import sys

from faker import Faker

PORT = 7770
TIMEOUT = 10
PROMPT = "vegas>"
OK = ("", "", True)

GROUP_P = 21474836291
GROUP_Q = 2147483629
GROUP_G = 1024
RSA_E = 65537

fake = Faker()


def rand_text(prefix: str, n: int = 8) -> str:
    alphabet = string.ascii_lowercase + string.digits
    return prefix + "".join(random.choice(alphabet) for _ in range(n))


def mod_pow(base, exp, mod):
    return pow(base, exp, mod)


def xor_bytes(a: bytes, b: bytes) -> bytes:
    return bytes(x ^ y for x, y in zip(a, itertools.cycle(b)))


def auth_challenge(message: str, commitment: int) -> int:
    digest = hashlib.sha1((message + str(commitment)).encode()).digest()
    return int.from_bytes(digest[:8], "big") % GROUP_Q


def verify_signature_event(
    slip_id: str,
    secret: str,
    message: str,
    commitment: int,
    challenge: int,
    response: int,
    public_key: int,
) -> bool:
    if message != f"prove:{slip_id[:8]}:{len(secret.encode())}":
        return False
    if challenge != auth_challenge(message, commitment):
        return False
    left = mod_pow(GROUP_G, response, GROUP_P)
    right = (mod_pow(public_key, challenge, GROUP_P) * commitment) % GROUP_P
    return left == right


def verify_rsa_event(
    secret: str, modulus: int, exponent: int, code_hex: str
) -> bool:
    if exponent != RSA_E:
        return False
    codes = code_hex.split(":")
    if len(codes) != len(secret.encode()):
        return False
    for index, byte in enumerate(secret.encode()):
        try:
            actual = int(codes[index], 16)
        except ValueError:
            return False
        if mod_pow(byte, exponent, modulus) != actual:
            return False
    return True


def fake_userpass():
    username = fake.user_name() + str(random.randint(100, 999))
    password = fake.password(length=random.randint(10, 20))
    return username, password


class Client:
    def __init__(self, host: str, port: int = PORT, timeout: int = TIMEOUT):
        if ":" in host:
            host, _, port_text = host.partition(":")
            port = int(port_text)
        self.sock = socket.create_connection((host, port), timeout=timeout)
        self.sock.settimeout(timeout)
        self.stream = self.sock.makefile("rwb")
        self._read_block()

    def close(self):
        try:
            self.stream.close()
            self.sock.close()
        except OSError:
            pass

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()

    def _read_block(self):
        lines = []
        while True:
            raw = self.stream.readline()
            if not raw:
                raise ConnectionError("service closed the connection")
            line = raw.decode("utf-8", "replace").rstrip("\r\n")
            if line.startswith(PROMPT):
                return lines
            if line:
                lines.append(line)

    def send(self, *parts) -> list:
        self.stream.write((" ".join(parts) + "\n").encode())
        self.stream.flush()
        return self._read_block()

    def cmd(self, name: str, *args) -> list:
        return self.send(name, *(shlex.quote(str(arg)) for arg in args))


def parse(line: str) -> dict:
    out = {}
    for token in shlex.split(line):
        key, _, value = token.partition("=")
        out[key] = value
    return out


def rows(lines, kind: str) -> list:
    return [parse(line) for line in lines if line.startswith(kind + " ")]


def assert_true(cond, msg):
    if not cond:
        raise AssertionError(msg)


def check(host: str):
    client = None
    try:
        client = Client(host)

        health = parse(client.cmd("health")[0])
        assert_true(health.get("status") == "ok", "health command returned bad status")

        username, password = fake_userpass()
        title = rand_text("Lobby Note ")
        teaser = rand_text("teaser_")
        secret = rand_text("secret_", 24)

        register = parse(client.cmd("register", username, password)[0])
        assert_true(register.get("status") == "registered", "register failed")

        dupe = client.cmd("register", username, password)[0]
        assert_true("already taken" in dupe, "duplicate registration accepted")

        client.cmd("logout")
        slip_fail = client.cmd("new", title, teaser, secret)[0]
        assert_true("login required" in slip_fail, "created slip while logged out")

        bad_login = client.cmd("login", username, password + "!x")[0]
        assert_true("login failed" in bad_login, "logged in with wrong password!")

        login = parse(client.cmd("login", username, password)[0])
        assert_true(login.get("status") == "logged in", f"could not login as {username}")

        created = parse(client.cmd("new", title, teaser, secret)[0])
        assert_true(created.get("status") == "created", "slip creation failed when logged in")
        slip_id = created.get("slip_id")
        assert_true(bool(slip_id), "missing slip id after creation")

        shown = client.cmd("show", slip_id)
        head = parse(shown[0])
        sig = rows(shown, "sig")
        rsa = rows(shown, "rsa")
        assert_true(head.get("title") == title, "slip does not contain expected title")
        assert_true(head.get("teaser") == teaser, "slip does not contain expected teaser")
        assert_true(len(sig) == 1 and len(rsa) == 1, "missing fairness proof on slip")

        assert_true(
            verify_signature_event(
                slip_id,
                secret,
                sig[0]["message"],
                int(sig[0]["commitment"]),
                int(sig[0]["challenge"]),
                int(sig[0]["response"]),
                int(sig[0]["public_key"]),
            ),
            "Signature event verification failed - message, commitment, challenge, or response incorrect",
        )
        assert_true(
            verify_rsa_event(
                secret, int(rsa[0]["modulus"]), int(rsa[0]["exponent"]), rsa[0]["code_hex"]
            ),
            "RSA event verification failed - modulus, exponent, or code incorrect",
        )

        verified = parse(
            client.cmd(
                "verify-sig",
                sig[0]["message"],
                sig[0]["commitment"],
                sig[0]["challenge"],
                sig[0]["response"],
                sig[0]["public_key"],
            )[0]
        )
        assert_true(verified.get("valid") == "true", "service rejected a valid signature")

        verified = parse(
            client.cmd(
                "verify-rsa",
                secret,
                rsa[0]["modulus"],
                rsa[0]["exponent"],
                rsa[0]["code_hex"],
            )[0]
        )
        assert_true(verified.get("valid") == "true", "service rejected a valid rsa bond")

        panels = [("sigs", "prove"), ("rsa", "Jackpot")]
        for panel, marker in panels:
            body = client.cmd(panel)
            assert_true(marker in " ".join(body), f"panel {panel} missing expected content")

        flag = secret[::-1]
        flag_id = rand_text("flagid_")
        put = parse(client.cmd("put", flag_id, flag)[0])
        assert_true(put.get("status") == "stored", "put command failed")
        priv = {
            "owner": put["owner"],
            "password": put["password"],
            "slip_id": put["slip_id"],
        }
        got = parse(
            client.cmd("get", priv["slip_id"], priv["owner"], priv["password"])[0]
        )
        assert_true(got.get("secret") == flag, "Retrieved secret does not match flag")
        bad = client.cmd(
            "get", priv["slip_id"], priv["owner"], priv["password"] + "'*"
        )[0]
        assert_true("bad credentials" in bad, "wrong credentials were not rejected")

        return OK
    except AssertionError as exc:
        return (str(exc), "", False)
    except Exception as exc:
        return (f"connection error: {exc}", "", False)
    finally:
        if client is not None:
            client.close()


def put(host: str, flag: str, flag_id: str):
    client = None
    try:
        client = Client(host)
        username, password = fake_userpass()
        registered = parse(client.cmd("register", username, password)[0])
        if registered.get("status") != "registered":
            return (f"register failed: {registered}", "", False)
        login = parse(client.cmd("login", username, password)[0])
        if login.get("status") != "logged in":
            return (f"login failed: {login}", "", False)
        created = parse(client.cmd("new", rand_text("Lobby Note ", 10), rand_text("teaser_", 10), flag)[0])
        if created.get("status") != "created":
            return (f"slip creation failed: {created}", "", False)
        slip_id = created["slip_id"]
        private = json.dumps(
            {"username": username, "password": password, "slip_id": slip_id}
        )
        return ("", private, True, slip_id)
    except Exception as exc:
        return (f"connection error: {exc}", "", False)
    finally:
        if client is not None:
            client.close()


def get(host: str, flag: str, flag_id: str, private: str):
    client = None
    try:
        data = json.loads(private)
        client = Client(host)
        login = parse(client.cmd("login", data["username"], data["password"])[0])
        if login.get("status") != "logged in":
            return (f"login failed: {login}", "", False)
        shown = client.cmd("show", data["slip_id"])
        if not shown:
            return ("slip page not found", "", False)
        head = parse(shown[0])
        vault = head.get("vault")
        if not vault:
            return ("could not extract vault data", "", False)
        hasher = hashlib.sha256()
        hasher.update(b"vegas-vault")
        hasher.update(data["username"].encode())
        hasher.update(data["slip_id"].encode())
        cipher = base64.urlsafe_b64decode(vault + "=" * (-len(vault) % 4))
        plain = xor_bytes(cipher, hasher.digest()).decode(errors="replace")
        if flag != plain:
            return ("flag does not match", "", False)
        return OK
    except Exception as exc:
        return (f"connection error: {exc}", "", False)
    finally:
        if client is not None:
            client.close()


def main():
    host = sys.argv[1] if len(sys.argv) > 1 else "host.docker.internal"

    public, _, success = check(host)
    if not success:
        print(f"CHECK failed: {public}")
        sys.exit(1)
    print("CHECK passed")

    flag = "flag{" + rand_text("", 32) + "}"
    flag_id = rand_text("flagid_", 8)

    public, private, success, flag_id = put(host, flag, flag_id)
    if not success:
        print(f"PUT failed: {public}")
        sys.exit(1)

    print(f"flag:{flag},flag_id:{flag_id}")

    public, _, success = get(host, flag, flag_id, private)
    if not success:
        print(f"GET failed: {public}")
        sys.exit(1)

    print("All checks passed")


if __name__ == "__main__":
    main()
