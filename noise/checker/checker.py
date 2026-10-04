"""Glitch checker for the noise service (binary protocol): check(host), put, get."""
import json
import os

import noiselib as nl


def rand(prefix):
    return f"{prefix}-{os.urandom(4).hex()}"


def check(host):
    try:
        c = nl.Client(host)
        pa, sa = nl.keypair()
        pb, sb = nl.keypair()
        c.register(pa, rand("alice"))
        ub = c.register(pb, rand("bob"))
        ta, tb = c.auth(pa, sa), c.auth(pb, sb)

        secret = os.urandom(8).hex().encode()
        c.send_dm(ta, ub["id"], nl.encrypt_for(pb, secret))
        if not any(nl.decrypt_with(sb, m["message"]) == secret for m in c.messages(tb)):
            return ("dm round-trip failed", "", False)

        g = c.create_group(ta, rand("grp"))
        c.invite(ta, g["id"], ub["id"])
        gsecret = os.urandom(8).hex().encode()
        c.send_group(ta, g["id"], nl.encrypt_for(g["pubkey"], gsecret))
        gt = c.group_token(g["pubkey"], g["privkey"])
        if not any(nl.decrypt_with(g["privkey"], m["message"]) == gsecret for m in c.group_messages(gt)):
            return ("group round-trip failed", "", False)
        if not any(x["id"] == g["id"] for x in c.list_groups(tb)):
            return ("invited member cannot see group", "", False)
        return ("", "", True)
    except (OSError, ConnectionError):
        return ("connection error", "", False)
    except Exception as e:
        return (f"unexpected: {e}", "", False)


def put(host, flag, flag_id):
    try:
        c = nl.Client(host)
        pub, priv = nl.keypair()
        c.register(pub, rand("user"))
        token = c.auth(pub, priv)
        g = c.create_group(token, rand("grp"))
        c.send_group(token, g["id"], nl.encrypt_for(g["pubkey"], flag.encode()))
        private = json.dumps({"group_pub": g["pubkey"], "group_priv": g["privkey"]})
        return ("", private, True, str(g["id"]))
    except (OSError, ConnectionError):
        return ("connection error", "", False)
    except Exception as e:
        return (f"unexpected: {e}", "", False)


def get(host, flag, flag_id, private):
    try:
        c = nl.Client(host)
        p = json.loads(private)
        gt = c.group_token(p["group_pub"], p["group_priv"])
        for m in c.group_messages(gt):
            try:
                if nl.decrypt_with(p["group_priv"], m["message"]).decode() == flag:
                    return ("", "", True)
            except Exception:
                continue
        return ("flag not found", "", False)
    except (OSError, ConnectionError):
        return ("connection error", "", False)
    except Exception as e:
        return (f"unexpected: {e}", "", False)
