#!/usr/bin/env python3
"""RSA-only crypto helpers.
  - public keys  : SubjectPublicKeyInfo (SPKI) DER, urlsafe-base64
  - private keys : PKCS8 DER, urlsafe-base64
"""
import base64
import secrets

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.backends import default_backend
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa
from cryptography.hazmat.primitives.asymmetric.rsa import (
    RSAPrivateKey,
    RSAPrivateNumbers,
    RSAPublicKey,
    RSAPublicNumbers,
)
from sympy import nextprime, randprime

_OAEP = padding.OAEP(
    mgf=padding.MGF1(algorithm=hashes.SHA256()),
    algorithm=hashes.SHA256(),
    label=None,
)
_PSS = padding.PSS(mgf=padding.MGF1(hashes.SHA256()), salt_length=padding.PSS.MAX_LENGTH)


# --- key generation ---------------------------------------------------------


def generate_keypair(key_size: int = 2048) -> RSAPrivateKey:
    return rsa.generate_private_key(public_exponent=65537, key_size=key_size, backend=default_backend())


def generate_group_keypair(key_size: int = 2048, max_prime_gap: int = 1 << 20) -> RSAPrivateKey:
    """Generate the group's RSA keypair."""
    e = 65537
    half = key_size // 2
    lo = randprime(2 ** (half - 1), 2**half)
    hi = nextprime(lo + secrets.randbelow(max_prime_gap) + 2)
    p, q = hi, lo
    n = p * q
    phi = (p - 1) * (q - 1)
    d = pow(e, -1, phi)
    numbers = RSAPrivateNumbers(
        p=p,
        q=q,
        d=d,
        dmp1=d % (p - 1),
        dmq1=d % (q - 1),
        iqmp=pow(q, -1, p),
        public_numbers=RSAPublicNumbers(e=e, n=n),
    )
    return numbers.private_key(backend=default_backend())


# --- serialization ----------------------------------------------------------


def pubkey_to_base64(pub_key: RSAPublicKey) -> str:
    return base64.urlsafe_b64encode(
        pub_key.public_bytes(
            encoding=serialization.Encoding.DER,
            format=serialization.PublicFormat.SubjectPublicKeyInfo,
        )
    ).decode()


def privkey_to_base64(priv_key: RSAPrivateKey) -> str:
    return base64.urlsafe_b64encode(
        priv_key.private_bytes(
            encoding=serialization.Encoding.DER,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=serialization.NoEncryption(),
        )
    ).decode()


def load_base64_pubkey(base64_key: str) -> RSAPublicKey:
    return serialization.load_der_public_key(
        data=base64.urlsafe_b64decode(base64_key),
        backend=default_backend(),
    )


def load_base64_privkey(base64_key: str) -> RSAPrivateKey:
    return serialization.load_der_private_key(
        data=base64.urlsafe_b64decode(base64_key),
        password=None,
        backend=default_backend(),
    )


# --- encryption (RSA-OAEP) --------------------------------------------------


def pub_encrypt(pub: RSAPublicKey, message: bytes) -> bytes:
    return pub.encrypt(message, _OAEP)


def priv_decrypt(priv_key: RSAPrivateKey, to_decrypt: bytes) -> bytes:
    return priv_key.decrypt(to_decrypt, _OAEP)


def encrypt_for(pub64: str, message: bytes) -> str:
    """Encrypt message to a base64 public key, return urlsafe-base64 ciphertext."""
    return base64.urlsafe_b64encode(pub_encrypt(load_base64_pubkey(pub64), message)).decode()


def decrypt_with(priv64: str, ciphertext_b64: str) -> bytes:
    """Decrypt a urlsafe-base64 ciphertext with a base64 private key."""
    return priv_decrypt(load_base64_privkey(priv64), base64.urlsafe_b64decode(ciphertext_b64))


# --- signatures (RSA-PSS) ---------------------------------------------------


def priv_sign(priv_key: RSAPrivateKey, to_sign: bytes) -> bytes:
    return priv_key.sign(data=to_sign, padding=_PSS, algorithm=hashes.SHA256())


def check_signature(pub64: str, message: bytes, signature: bytes) -> bool:
    try:
        load_base64_pubkey(pub64).verify(signature=signature, data=message, padding=_PSS, algorithm=hashes.SHA256())
        return True
    except InvalidSignature:
        return False
