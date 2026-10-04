import os
import re
import time

import requests


PORT = 4729
TIMEOUT = 10


def clean_ident(value: str) -> str:
    value = re.sub(r"[^A-Za-z0-9_-]", "", value.upper())[:32]
    return value or os.urandom(8).hex().upper()


def api(host: str) -> str:
    return f"http://{host}:{PORT}"


def check(host: str):
    try:
        response = requests.get(f"{api(host)}/", timeout=TIMEOUT)
        if response.status_code != 200 or "Flight Plan" not in response.text:
            return ("portal unavailable", "", False)
        airac = requests.get(f"{api(host)}/airac.json", timeout=TIMEOUT)
        if airac.status_code != 200 or "station_beacon" not in airac.json():
            return ("airac feed unavailable", "", False)

        username = "ck" + os.urandom(5).hex()
        password = os.urandom(12).hex()
        session = requests.Session()
        reg = session.post(
            f"{api(host)}/api/register",
            json={"username": username, "password": password, "full_name": "Check Pilot", "home_base": "KMSP"},
            timeout=TIMEOUT,
        )
        if reg.status_code != 200:
            return ("operator registration failed", "", False)
        login = session.post(f"{api(host)}/api/login", json={"username": username, "password": password}, timeout=TIMEOUT)
        if login.status_code != 200:
            return ("operator login failed", "", False)
        ident = "CK-" + os.urandom(5).hex().upper()
        check_note = "routine check " + str(int(time.time()))
        created = session.post(
            f"{api(host)}/api/plans",
            json={
                "ident": ident,
                "callsign": "CFX901",
                "departure": "KMSP",
                "arrival": "KORD",
                "alternate": "KMKE",
                "route": "DCT ODI V100 DLL",
                "cruise": "FL290",
                "fuel": 8200,
                "passengers": 38,
                "private_notes": check_note,
            },
            timeout=TIMEOUT,
        )
        if created.status_code != 200:
            return ("plan filing failed", "", False)
        briefing = requests.get(f"{api(host)}/api/briefing/{ident}", timeout=TIMEOUT)
        if briefing.status_code != 200 or briefing.json().get("ident") != ident:
            return ("station briefing failed", "", False)
        public = briefing.json()
        if len(str(public.get("navlog_seal", ""))) < 24:
            return ("navlog seal missing", "", False)
        navlog = session.get(f"{api(host)}/api/plans/{ident}/navlog", timeout=TIMEOUT)
        if navlog.status_code != 200:
            return ("navlog unseal failed", "", False)
        navlog_data = navlog.json()
        if navlog_data.get("navlog_seal") != public.get("navlog_seal") or navlog_data.get("remarks") != check_note:
            return ("navlog seal mismatch", "", False)
        return ("", "", True)
    except Exception:
        return ("connection error", "", False)


def put(host: str, flag: str, flag_id: str):
    try:
        username = "op" + os.urandom(6).hex()
        password = os.urandom(16).hex()
        ident = "FP-" + clean_ident(flag_id)[:28]
        session = requests.Session()
        reg = session.post(
            f"{api(host)}/api/register",
            json={"username": username, "password": password, "full_name": "Release Desk", "home_base": "KMSP"},
            timeout=TIMEOUT,
        )
        if reg.status_code != 200:
            return ("operator registration failed", "", False)
        login = session.post(f"{api(host)}/api/login", json={"username": username, "password": password}, timeout=TIMEOUT)
        if login.status_code != 200:
            return ("operator login failed", "", False)
        created = session.post(
            f"{api(host)}/api/plans",
            json={
                "ident": ident,
                "callsign": "CFX" + str(100 + int.from_bytes(os.urandom(2), "big") % 899),
                "departure": "KMSP",
                "arrival": "KBOS",
                "alternate": "KBDL",
                "route": "DCT DLL J34 ALB DCT",
                "cruise": "FL370",
                "fuel": 17400,
                "passengers": 82,
                "private_notes": flag,
            },
            timeout=TIMEOUT,
        )
        if created.status_code != 200:
            return ("plan filing failed", "", False)
        return ("", {"username": username, "password": password, "ident": ident}, True, ident)
    except Exception:
        return ("connection error", "", False)


def get(host: str, flag: str, flag_id: str, private):
    try:
        session = requests.Session()
        login = session.post(
            f"{api(host)}/api/login",
            json={"username": private["username"], "password": private["password"]},
            timeout=TIMEOUT,
        )
        if login.status_code != 200:
            return ("operator login failed", "", False)
        briefing = requests.get(f"{api(host)}/api/briefing/{private['ident']}", timeout=TIMEOUT)
        if briefing.status_code != 200 or len(str(briefing.json().get("navlog_seal", ""))) < 24:
            return ("navlog seal missing", "", False)
        response = session.get(f"{api(host)}/api/plans/{private['ident']}/navlog", timeout=TIMEOUT)
        if response.status_code != 200:
            return ("navlog unavailable", "", False)
        if response.json().get("navlog_seal") != briefing.json().get("navlog_seal"):
            return ("navlog seal mismatch", "", False)
        if response.json().get("remarks") != flag:
            return ("flag does not match", "", False)
        return ("", private, True)
    except Exception:
        return ("connection error", "", False)
