"""Self-contained binary-protocol client + RSA helpers for the noise service."""
import base64
import hashlib
import math
import socket
import struct

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa
from cryptography.hazmat.primitives.asymmetric.rsa import RSAPrivateNumbers, RSAPublicNumbers

PORT = 6426
MAGIC, VER = b"NOIZ", 1
HDR = struct.Struct("!4sBBBI")
OAEP = padding.OAEP(mgf=padding.MGF1(hashes.SHA256()), algorithm=hashes.SHA256(), label=None)
OP = {"register": 1, "users": 2, "challenge": 3, "send_dm": 4, "messages": 5, "create_group": 6,
      "group_challenge": 7, "invite": 8, "list_groups": 9, "send_group": 10, "group_messages": 11, "groups": 12}


class ApiError(Exception):
    def __init__(self, code, msg):
        super().__init__(f"{code}: {msg}")
        self.code, self.msg = code, msg


def b64e(b):
    return base64.urlsafe_b64encode(b).decode()


def b64d(s):
    return base64.urlsafe_b64decode(s)


def keypair():
    k = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    pub = k.public_key().public_bytes(serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo)
    priv = k.private_bytes(serialization.Encoding.DER, serialization.PrivateFormat.PKCS8, serialization.NoEncryption())
    return b64e(pub), b64e(priv)


def encrypt_for(pub_b64, msg):
    key = serialization.load_der_public_key(b64d(pub_b64))
    return b64e(key.encrypt(msg, OAEP))


def decrypt_with(priv_b64, ct_b64):
    key = serialization.load_der_private_key(b64d(priv_b64), password=None)
    return key.decrypt(b64d(ct_b64), OAEP)


def modulus(pub_b64):
    return serialization.load_der_public_key(b64d(pub_b64)).public_numbers().n


def fermat(n):
    a = math.isqrt(n) + 1
    while True:
        r = math.isqrt(a * a - n)
        if r * r == a * a - n:
            return a + r, a - r
        a += 1


def priv_from_primes(p, q, e=65537):
    n = p * q
    d = pow(e, -1, (p - 1) * (q - 1))
    nums = RSAPrivateNumbers(p, q, d, d % (p - 1), d % (q - 1), pow(q, -1, p), RSAPublicNumbers(e, n))
    return b64e(nums.private_key().private_bytes(
        serialization.Encoding.DER, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()))


def forge_token(kind, sid):
    return f"{kind}:{sid}:" + hashlib.sha256(f"noise-token-{kind}-{sid}".encode()).hexdigest()[:16]


class _R:
    def __init__(self, b):
        self.b, self.i = b, 0

    def take(self, n):
        v = self.b[self.i:self.i + n]
        self.i += n
        return v

    def u16(self):
        return struct.unpack("!H", self.take(2))[0]

    def u32(self):
        return struct.unpack("!I", self.take(4))[0]

    def text(self):
        return self.take(self.u32()).decode()


def _enc(f):
    if isinstance(f, int):
        return struct.pack("!I", f)
    b = f.encode() if isinstance(f, str) else f
    return struct.pack("!I", len(b)) + b


class Client:
    def __init__(self, host, port=PORT):
        self.sock = socket.create_connection((host, port), 10)

    def _recv(self, n):
        buf = b""
        while len(buf) < n:
            chunk = self.sock.recv(n - len(buf))
            if not chunk:
                raise ConnectionError("peer closed")
            buf += chunk
        return buf

    def _call(self, op, *fields):
        payload = b"".join(_enc(f) for f in fields)
        self.sock.sendall(HDR.pack(MAGIC, VER, 0, OP[op], len(payload)) + payload)
        _, _, flags, _, ln = HDR.unpack(self._recv(HDR.size))
        r = _R(self._recv(ln) if ln else b"")
        if flags == 2:
            raise ApiError(r.u16(), r.text())
        return r

    def _user(self, r):
        return {"id": r.u32(), "name": r.text(), "pubkey": r.text()}

    def _group(self, r):
        return {"id": r.u32(), "name": r.text(), "pubkey": r.text(), "privkey": r.text()}

    def _gpub(self, r):
        return {"id": r.u32(), "name": r.text(), "pubkey": r.text(), "owner": r.u32()}

    def _msg(self, r):
        return {"src_id": r.u32(), "src_name": r.text(), "time": r.text(), "message": r.text()}

    def _list(self, r, f):
        return [f(r) for _ in range(r.u32())]

    def register(self, pub, name):
        return self._user(self._call("register", pub, name))

    def users(self):
        return self._list(self._call("users"), self._user)

    def groups(self):
        return self._list(self._call("groups"), self._gpub)

    def challenge(self, pub):
        return self._call("challenge", pub).text()

    def auth(self, pub, priv):
        return decrypt_with(priv, self.challenge(pub)).decode()

    def send_dm(self, token, dst, msg):
        self._call("send_dm", token, dst, msg)

    def messages(self, token):
        return self._list(self._call("messages", token), self._msg)

    def create_group(self, token, name):
        return self._group(self._call("create_group", token, name))

    def group_challenge(self, pub):
        return self._call("group_challenge", pub).text()

    def group_token(self, pub, priv):
        return decrypt_with(priv, self.group_challenge(pub)).decode()

    def invite(self, token, gid, uid):
        self._call("invite", token, gid, uid)

    def list_groups(self, token):
        return self._list(self._call("list_groups", token), self._group)

    def send_group(self, token, gid, msg):
        self._call("send_group", token, gid, msg)

    def group_messages(self, token):
        return self._list(self._call("group_messages", token), self._msg)
