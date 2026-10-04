from .util import fields, stamp


def slip_view(slip, own):
    return "slip " + fields(
        ("slip_id", slip["slip_id"]),
        ("owner", slip["owner"]),
        ("title", slip["title"]),
        ("teaser", slip["teaser"]),
        ("created", stamp(slip["created_at"])),
        ("own", str(own).lower()),
        ("vault", slip["vault_data_b64"] if own else "hidden"),
    )


def signature_view(slip_id, event):
    return "sig " + fields(
        ("slip_id", slip_id),
        ("message", event["message"]),
        ("commitment", event["commitment"]),
        ("challenge", event["challenge"]),
        ("response", event["response"]),
        ("public_key", event["public_key"]),
        ("code_hex", event["code_hex"]),
        ("note", event["note"]),
    )


def rsa_view(slip_id, event):
    return "rsa " + fields(
        ("slip_id", slip_id),
        ("modulus", event["modulus"]),
        ("exponent", event["exponent"]),
        ("code_hex", event["code_hex"]),
        ("jackpot_name", event["jackpot_name"]),
    )
