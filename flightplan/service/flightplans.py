import base64
import hashlib
import json
import secrets
import time
import zlib

from config import AIRAC_SECRET
from database import db


def normalize_ident(value: str) -> str:
    value = "".join(ch for ch in value.upper() if ch.isalnum() or ch in "-_")
    return value[:46] or secrets.token_hex(8).upper()


def station_beacon() -> str:
    return hashlib.blake2s(AIRAC_SECRET, digest_size=32, person=b"AIRAC260").hexdigest()


def route_fingerprint(plan) -> str:
    material = "|".join(
        [
            plan["ident"],
            plan["callsign"].upper(),
            plan["departure"].upper(),
            plan["arrival"].upper(),
            " ".join(plan["route"].upper().split()),
            plan["cruise"].upper(),
        ]
    )
    return hashlib.sha256(material.encode()).hexdigest()[:24]


def stream_bytes(ident: str, fingerprint: str, size: int) -> bytes:
    seed = f"{station_beacon()}:{ident[:6]}:{fingerprint[-8:]}".encode()
    key = hashlib.blake2s(seed, digest_size=16, person=b"RTEKEY").digest()
    output = bytearray()
    counter = 0
    while len(output) < size:
        counter += 1
        block = hashlib.blake2s(
            f"{ident}:{fingerprint}:{counter}".encode(), key=key, digest_size=32, person=b"NAVSEAL"
        ).digest()
        output.extend(block)
    return bytes(output[:size])


def seal_payload(plan) -> str:
    payload = json.dumps(
        {
            "ident": plan["ident"],
            "pilot": plan["callsign"],
            "remarks": plan["private_notes"],
            "release": plan["updated_at"],
        },
        separators=(",", ":"),
    ).encode()
    compressed = zlib.compress(payload)
    fingerprint = route_fingerprint(plan)
    mask = stream_bytes(plan["ident"], fingerprint, len(compressed))
    sealed = bytes(a ^ b for a, b in zip(compressed, mask))
    return base64.urlsafe_b64encode(sealed).decode().rstrip("=")


def unseal_payload(plan) -> dict:
    sealed = seal_payload(plan)
    ciphertext = base64.urlsafe_b64decode(sealed + "=" * (-len(sealed) % 4))
    fingerprint = route_fingerprint(plan)
    mask = stream_bytes(plan["ident"], fingerprint, len(ciphertext))
    compressed = bytes(a ^ b for a, b in zip(ciphertext, mask))
    payload = json.loads(zlib.decompress(compressed))
    if payload.get("ident") != plan["ident"] or payload.get("release") != plan["updated_at"]:
        raise ValueError("navlog seal mismatch")
    return payload


def plan_public(plan) -> dict:
    fingerprint = route_fingerprint(plan)
    return {
        "ident": plan["ident"],
        "callsign": plan["callsign"],
        "departure": plan["departure"],
        "arrival": plan["arrival"],
        "alternate": plan["alternate"],
        "route": plan["route"],
        "cruise": plan["cruise"],
        "fuel": plan["fuel"],
        "passengers": plan["passengers"],
        "created_at": plan["created_at"],
        "updated_at": plan["updated_at"],
        "fingerprint": fingerprint,
        "navlog_seal": seal_payload(plan),
    }


def plan_summary(plan) -> dict:
    return {
        "ident": plan["ident"],
        "callsign": plan["callsign"],
        "departure": plan["departure"],
        "arrival": plan["arrival"],
        "alternate": plan["alternate"],
        "route": plan["route"],
        "cruise": plan["cruise"],
        "fuel": plan["fuel"],
        "passengers": plan["passengers"],
        "created_at": plan["created_at"],
        "updated_at": plan["updated_at"],
    }


def compatibility_tag(plan) -> str:
    slot = int(plan["updated_at"]) // 300
    material = f'{plan["ident"]}:{route_fingerprint(plan)}:{plan["departure"]}:{slot}'
    return hashlib.blake2s(material.encode(), digest_size=12, person=b"LDREV3").hexdigest()


def load_plan(ident: str):
    with db() as conn:
        return conn.execute(
            "select plans.*, users.username, users.full_name, users.home_base from plans join users on users.id = plans.owner_id where ident = ?",
            (ident,),
        ).fetchone()


def create_plan(owner_id: int, payload: dict) -> str:
    plan_id = normalize_ident(str(payload.get("ident") or f"FP-{secrets.token_hex(5)}"))
    now = int(time.time())
    with db() as conn:
        conn.execute(
            """insert into plans(ident,owner_id,callsign,departure,arrival,alternate,route,cruise,fuel,passengers,private_notes,created_at,updated_at)
               values(?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                plan_id,
                owner_id,
                str(payload.get("callsign", "CFX100")).upper()[:16],
                str(payload.get("departure", "KMSP")).upper()[:8],
                str(payload.get("arrival", "KBOS")).upper()[:8],
                str(payload.get("alternate", "KBDL")).upper()[:8],
                str(payload.get("route", "DCT DLL J34 ALB DCT"))[:240],
                str(payload.get("cruise", "FL370")).upper()[:12],
                int(payload.get("fuel", 17400)),
                int(payload.get("passengers", 82)),
                str(payload.get("private_notes", "")),
                now,
                now,
            ),
        )
    return plan_id
