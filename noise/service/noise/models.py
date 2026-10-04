#!/usr/bin/env python3
"""Wire models shared by the server and client."""
from pydantic import BaseModel


class UserPublic(BaseModel):
    id: int
    name: str
    pubkey: str


class GroupPublic(BaseModel):
    """A group without its private key, as returned by /groups."""

    id: int
    name: str
    pubkey: str
    owner: int


class GroupSecret(BaseModel):
    """A group and its keypair, as returned by /group/create and /group/list."""

    id: int
    name: str
    pubkey: str
    privkey: str


class MessageOut(BaseModel):
    src_id: int
    src_name: str
    time: str
    message: str


class Challenge(BaseModel):
    """RSA-OAEP ciphertext (urlsafe-base64) of the subject's bearer token."""

    challenge: str


class Ok(BaseModel):
    ok: bool = True
