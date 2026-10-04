#!/usr/bin/env python3
"""Transport-agnostic business logic"""
import hashlib

from . import crypto
from .models import (
    Challenge,
    GroupPublic,
    GroupSecret,
    MessageOut,
    Ok,
    UserPublic,
)

GROUP_KEY_BITS = 2048


# --- domain exceptions ------------------------------------------------------


class NoiseError(Exception):
    """Base for errors the transport maps to a client-visible status."""


class NotFoundError(NoiseError):
    pass


class ConflictError(NoiseError):
    pass


class InvalidTokenError(NoiseError):
    pass


class NotAuthorizedError(NoiseError):
    pass


# --- tokens -----------------------------------------------------------------

auth_cache: dict[str, UserPublic | GroupSecret] = {}


def make_token(kind: str, subject_id: int) -> str:
    digest = hashlib.sha256(f"noise-token-{kind}-{subject_id}".encode()).hexdigest()[:16]
    return f"{kind}:{subject_id}:{digest}"


def get_token_subject(token: str, assert_type: type[UserPublic] | type[GroupSecret]) -> UserPublic | GroupSecret:
    if token not in auth_cache:
        raise InvalidTokenError
    return auth_cache[token]


class NoiseService:
    def __init__(self, db):
        self.db = db

    # --- auth helpers ----------------------------------------------------

    def _user_from_token(self, token: str) -> UserPublic:
        return get_token_subject(token, UserPublic)

    def _group_from_token(self, token: str) -> GroupSecret:
        return get_token_subject(token, GroupSecret)

    # --- users -----------------------------------------------------------

    def register(self, pubkey: str, name: str) -> UserPublic:
        # Reject unusable keys up front so /challenge can't 500 later.
        try:
            crypto.load_base64_pubkey(pubkey)
        except Exception:
            raise ConflictError("invalid public key")
        if self.db.get_user_by_key(pubkey) is not None:
            raise ConflictError("public key already registered")
        return self.db.create_user(pubkey, name)

    def list_users(self) -> list[UserPublic]:
        return self.db.get_users()

    def list_groups_public(self) -> list[GroupPublic]:
        return self.db.get_groups_public()

    def challenge(self, pubkey: str) -> Challenge:
        user = self.db.get_user_by_key(pubkey)
        if user is None:
            raise NotFoundError("no such user")
        token = make_token("user", user.id)
        auth_cache[token] = user
        return Challenge(challenge=crypto.encrypt_for(user.pubkey, token.encode()))

    # --- direct messages -------------------------------------------------

    def send_dm(self, token: str, dst_id: int, message: str) -> Ok:
        sender = self._user_from_token(token)
        if self.db.get_user_by_id(dst_id) is None:
            raise NotFoundError("no such recipient")
        self.db.create_dm(sender.id, dst_id, message)
        return Ok()

    def get_dms(self, token: str) -> list[MessageOut]:
        user = self._user_from_token(token)
        return self.db.get_dms(user.id)

    # --- groups ----------------------------------------------------------

    def create_group(self, token: str, name: str) -> GroupSecret:
        owner = self._user_from_token(token)
        key = crypto.generate_group_keypair(GROUP_KEY_BITS)
        pub = crypto.pubkey_to_base64(key.public_key())
        priv = crypto.privkey_to_base64(key)
        group = self.db.create_group(pub, priv, name, owner.id)
        self.db.create_group_member(group.id, owner.id)
        return group

    def group_challenge(self, pubkey: str) -> Challenge:
        group = self.db.get_group_by_key(pubkey)
        if group is None:
            raise NotFoundError("no such group")
        token = make_token("group", group.id)
        auth_cache[token] = group
        return Challenge(challenge=crypto.encrypt_for(group.pubkey, token.encode()))

    def invite(self, token: str, gid: int, uid: int) -> Ok:
        caller = self._user_from_token(token)
        group = self.db.get_group_by_id(gid)
        if group is None:
            raise NotFoundError("no such group")
        invitee = self.db.get_user_by_id(uid)
        if invitee is None:
            raise NotFoundError("no such user")
        if self.db.is_member(gid, invitee.id):
            raise NotAuthorizedError("already a member")
        self.db.create_group_member(gid, invitee.id)
        return Ok()

    def list_groups(self, token: str) -> list[GroupSecret]:
        user = self._user_from_token(token)
        return self.db.get_user_groups(user.id)

    def send_group(self, token: str, gid: int, message: str) -> Ok:
        sender = self._user_from_token(token)
        if self.db.get_group_by_id(gid) is None:
            raise NotFoundError("no such group")
        if not self.db.is_member(gid, sender.id):
            raise NotAuthorizedError("not a group member")
        self.db.create_gmsg(sender.id, gid, message)
        return Ok()

    def get_group_messages(self, group_token: str) -> list[MessageOut]:
        group = self._group_from_token(group_token)
        return self.db.get_gmsg(group.id)
