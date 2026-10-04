import random
import shlex
import string
import uuid
from datetime import datetime, timezone

RNG = random.SystemRandom()


def now():
    return datetime.now(timezone.utc)


def stamp(value):
    return value.strftime("%Y-%m-%d %H:%M:%S UTC")


def short_id():
    return uuid.uuid4().hex[:10]


def random_password():
    return "".join(RNG.choice(string.ascii_letters + string.digits) for _ in range(18))


def normalize(value):
    return value.strip().lower()


def clamp(value, max_len):
    return value.strip()[:max_len]


def quote(value):
    return shlex.quote(str(value))


def fields(*pairs):
    return " ".join(f"{key}={quote(value)}" for key, value in pairs)
