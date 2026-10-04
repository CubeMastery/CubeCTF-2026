import threading
import uuid

from . import crypto
from .config import (
    GROUP_G,
    GROUP_P,
    GROUP_Q,
    HOUSE_SIGNING_KEY,
    RSA_E,
    RSA_Q_POOL,
    RSA_SHARED_P,
)
from .util import now, short_id


class Database:
    def __init__(self):
        self.lock = threading.RLock()
        self.users = {}
        self.sessions = {}
        self.slips = {}
        self.nonces = [38_771, 38_771, 90_113, 90_113, 500_009, 500_009]
        self.rsa_index = 0
        self.house_signing_key = HOUSE_SIGNING_KEY

    def create_session(self, username):
        token = short_id() + short_id()
        self.sessions[token] = username
        return token

    def username_for(self, token):
        if not token:
            return None
        return self.sessions.get(token)

    def add_user(self, username, password, chips):
        self.users[username] = {
            "username": username,
            "password": password,
            "chips": chips,
            "created_at": now(),
        }

    def auth_ok(self, username, password):
        user = self.users.get(username)
        return bool(user) and user["password"] == password

    def build_slip(self, owner, title, teaser, secret):
        slip_id = str(uuid.uuid4())
        slip = {
            "slip_id": slip_id,
            "owner": owner,
            "title": title,
            "teaser": teaser,
            "vault_data_b64": crypto.encode_vault(secret, owner, slip_id),
            "signature_event": self.build_signature_event(slip_id, secret),
            "rsa_event": self.build_rsa_event(slip_id, secret),
            "created_at": now(),
        }
        self.slips[slip_id] = slip
        return slip

    def build_signature_event(self, slip_id, secret):
        secret_key = self.house_signing_key
        public_key = crypto.mod_pow(GROUP_G, secret_key, GROUP_P)
        nonce = self.nonces.pop(0) % GROUP_Q
        self.nonces.append(nonce)
        commitment = crypto.mod_pow(GROUP_G, nonce, GROUP_P)
        message = f"prove:{slip_id[:8]}:{len(secret.encode())}"
        challenge = crypto.auth_challenge(message, commitment)
        response = (nonce + (challenge * secret_key) % GROUP_Q) % GROUP_Q
        mask = crypto.signature_mask(secret_key, len(secret.encode()))
        code_hex = crypto.xor_bytes(secret.encode(), mask).hex()
        return {
            "message": message,
            "commitment": commitment,
            "challenge": challenge,
            "response": response,
            "public_key": public_key,
            "code_hex": code_hex,
            "note": "Weekly provably fair proof",
        }

    def build_rsa_event(self, slip_id, secret):
        q = RSA_Q_POOL[self.rsa_index % len(RSA_Q_POOL)]
        self.rsa_index += 1
        modulus = RSA_SHARED_P * q
        return {
            "modulus": modulus,
            "exponent": RSA_E,
            "code_hex": crypto.encrypt_rsa_secret(secret, modulus),
            "jackpot_name": f"{slip_id[:8]} Grand Jackpot",
        }

    def select_slips(self, slip_id=None):
        slips = list(self.slips.values())
        if slip_id:
            slips = [slip for slip in slips if slip["slip_id"] == slip_id]
        return slips
