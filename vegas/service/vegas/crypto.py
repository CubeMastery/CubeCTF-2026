import base64
import hashlib
import itertools

from .config import GROUP_G, GROUP_P, GROUP_Q, RSA_E


def mod_pow(base, exp, modulus):
    if modulus <= 1:
        return 0
    return pow(base, exp, modulus)


def xor_bytes(a: bytes, b: bytes) -> bytes:
    return bytes(x ^ y for x, y in zip(a, itertools.cycle(b)))


def derive_secret_key(owner, slip_id):
    hasher = hashlib.sha256()
    hasher.update(b"vegas-vault")
    hasher.update(owner.encode())
    hasher.update(slip_id.encode())
    return hasher.digest()


def encode_vault(secret, owner, slip_id):
    key = derive_secret_key(owner, slip_id)
    cipher = xor_bytes(secret.encode(), key)
    return base64.urlsafe_b64encode(cipher).decode().rstrip("=")


def decrypt_vault(vault_data_b64, owner, slip_id):
    try:
        body = base64.urlsafe_b64decode(vault_data_b64 + "=" * (-len(vault_data_b64) % 4))
    except Exception:
        raise ValueError("vault decode failed")
    try:
        return xor_bytes(body, derive_secret_key(owner, slip_id)).decode()
    except UnicodeDecodeError:
        raise ValueError("utf8 decode failed")


def auth_challenge(message, commitment):
    digest = hashlib.sha1((message + str(commitment)).encode()).digest()
    return int.from_bytes(digest[:8], "big") % GROUP_Q


def signature_mask(secret_key, length):
    seed = str(secret_key).encode()
    out = bytearray()
    while len(out) < length:
        digest = hashlib.sha256(seed).digest()
        out.extend(digest)
        seed = digest
    return bytes(out[:length])


def verify_signature(message, commitment, challenge, response, public_key):
    if challenge != auth_challenge(message, commitment):
        return False
    left = mod_pow(GROUP_G, response, GROUP_P)
    right = (mod_pow(public_key, challenge, GROUP_P) * commitment) % GROUP_P
    return left == right


def encrypt_rsa_secret(secret, modulus):
    return ":".join(format(mod_pow(byte, RSA_E, modulus), "x") for byte in secret.encode())


def verify_rsa_secret(secret, modulus, exponent, code_hex):
    codes = code_hex.split(":")
    if len(secret) != len(codes):
        return False
    for index, char in enumerate(secret):
        try:
            actual = int(codes[index], 16)
        except ValueError:
            return False
        if mod_pow(ord(char), exponent, modulus) != actual:
            return False
    return True
