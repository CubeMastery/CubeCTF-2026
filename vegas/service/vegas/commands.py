from . import crypto, views
from .config import (
    HELP,
    MAX_TEASER,
    MAX_TITLE,
    MIN_PASSWORD,
    PITBOSS_CHIPS,
    STARTING_CHIPS,
)
from .util import clamp, fields, normalize, random_password, short_id


def username_of(session, database):
    with database.lock:
        return database.username_for(session.token)


def cmd_help(session, database, args):
    return "\n".join(HELP)


def cmd_health(session, database, args):
    with database.lock:
        slips = len(database.slips)
    return fields(("service", "vegas"), ("status", "ok"), ("slips", slips))


def cmd_register(session, database, args):
    if len(args) < 2:
        return "error=usage: register <username> <password>"
    username = normalize(args[0])
    password = args[1]
    if not username or len(password) < MIN_PASSWORD:
        return "error=invalid registration"
    with database.lock:
        if username in database.users:
            return "error=username already taken"
        database.add_user(username, password, STARTING_CHIPS)
        session.token = database.create_session(username)
    return "ok " + fields(
        ("status", "registered"),
        ("username", username),
        ("chips", STARTING_CHIPS),
        ("session", session.token),
    )


def cmd_login(session, database, args):
    if len(args) < 2:
        return "error=usage: login <username> <password>"
    username = normalize(args[0])
    with database.lock:
        if not database.auth_ok(username, args[1]):
            return "error=login failed"
        session.token = database.create_session(username)
        chips = database.users[username]["chips"]
    return "ok " + fields(
        ("status", "logged in"),
        ("username", username),
        ("chips", chips),
        ("session", session.token),
    )


def cmd_logout(session, database, args):
    session.token = None
    return "ok " + fields(("status", "logged out"))


def cmd_session(session, database, args):
    if not args:
        return "error=usage: session <token>"
    with database.lock:
        username = database.username_for(args[0])
    if not username:
        return "error=unknown session"
    session.token = args[0]
    return "ok " + fields(("status", "session restored"), ("username", username))


def cmd_whoami(session, database, args):
    username = username_of(session, database)
    if not username:
        return "error=login required"
    with database.lock:
        chips = database.users[username]["chips"]
    return "ok " + fields(("username", username), ("chips", chips))


def cmd_new(session, database, args):
    if len(args) < 3:
        return "error=usage: new <title> <teaser> <secret>"
    username = username_of(session, database)
    if not username:
        return "error=login required"
    title = clamp(args[0], MAX_TITLE)
    teaser = clamp(args[1], MAX_TEASER)
    secret = " ".join(args[2:]).strip()
    if not title or not teaser or not secret:
        return "error=all fields are required"
    with database.lock:
        slip = database.build_slip(username, title, teaser, secret)
    return "ok " + fields(("status", "created"), ("slip_id", slip["slip_id"]))


def cmd_show(session, database, args):
    if not args:
        return "error=usage: show <slip_id>"
    with database.lock:
        slip = database.slips.get(args[0])
        if slip is None:
            return "error=slip not found"
        own = username_of(session, database) == slip["owner"]
    return "\n".join(
        [
            views.slip_view(slip, own),
            views.signature_view(slip["slip_id"], slip["signature_event"]),
            views.rsa_view(slip["slip_id"], slip["rsa_event"]),
        ]
    )


def cmd_put(session, database, args):
    if len(args) < 2:
        return "error=usage: put <slip_id> <secret>"
    slip_id, secret = args[0], " ".join(args[1:])
    with database.lock:
        owner = f"pitboss_{short_id()}"
        password = random_password()
        database.add_user(owner, password, PITBOSS_CHIPS)
        token = database.create_session(owner)
        slip = database.build_slip(
            owner,
            f"Slip vault {slip_id}",
            f"High-roller cache for {slip_id}",
            secret,
        )
    return "ok " + fields(
        ("status", "stored"),
        ("slip_id", slip["slip_id"]),
        ("owner", owner),
        ("password", password),
        ("session", token),
    )


def cmd_get(session, database, args):
    if len(args) < 3:
        return "error=usage: get <slip_id> <owner> <password>"
    slip_id, owner, password = args[0], args[1], args[2]
    with database.lock:
        if owner not in database.users:
            return "error=user not found"
        if not database.auth_ok(owner, password):
            return "error=bad credentials"
        slip = database.slips.get(slip_id)
        if slip is None:
            return "error=slip not found"
        if slip["owner"] != owner:
            return "error=wrong owner"
        try:
            secret = crypto.decrypt_vault(slip["vault_data_b64"], slip["owner"], slip["slip_id"])
        except ValueError as exc:
            return f"error={exc}"
    return "ok " + fields(("status", "retrieved"), ("title", slip["title"]), ("secret", secret))


def cmd_sigs(session, database, args):
    with database.lock:
        slips = database.select_slips(args[0] if args else None)
    if not args:
        slips = sorted(slips, key=lambda s: s["created_at"], reverse=True)[:30]
    rows = [views.signature_view(slip["slip_id"], slip["signature_event"]) for slip in slips]
    return "\n".join([f"count={len(rows)}"] + rows)


def cmd_rsa(session, database, args):
    with database.lock:
        slips = database.select_slips(args[0] if args else None)
    if not args:
        slips = sorted(slips, key=lambda s: s["created_at"], reverse=True)[:30]
    rows = [views.rsa_view(slip["slip_id"], slip["rsa_event"]) for slip in slips]
    return "\n".join([f"count={len(rows)}"] + rows)


def cmd_verify_sig(session, database, args):
    if len(args) < 5:
        return "error=usage: verify-sig <message> <commitment> <challenge> <response> <public_key>"
    message = args[0]
    try:
        commitment, challenge, response, public_key = (int(value) for value in args[1:5])
    except ValueError:
        return "ok " + fields(("valid", "false"))
    valid = crypto.verify_signature(message, commitment, challenge, response, public_key)
    return "ok " + fields(("valid", str(valid).lower()))


def cmd_verify_rsa(session, database, args):
    if len(args) < 4:
        return "error=usage: verify-rsa <secret> <modulus> <exponent> <code_hex>"
    secret = args[0]
    try:
        modulus = int(args[1])
        exponent = int(args[2])
    except ValueError:
        return "ok " + fields(("valid", "false"))
    valid = crypto.verify_rsa_secret(secret, modulus, exponent, args[3])
    return "ok " + fields(("valid", str(valid).lower()))
