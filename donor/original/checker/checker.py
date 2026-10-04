import os
import random
import string
import time
import urllib.parse

import requests

PORT = 4739
TIMEOUT = 10
OK = ("", "", True)


def word(n=8):
    alphabet = string.ascii_lowercase + string.digits
    return "".join(random.choice(alphabet) for _ in range(n))


def post(session, host, path, data):
    return session.post(f"http://{host}:{PORT}{path}", data=data, timeout=TIMEOUT)


def http_get(session, host, path):
    return session.get(f"http://{host}:{PORT}{path}", timeout=TIMEOUT)


def expect(response, code=200):
    if response.status_code != code:
        return f"unexpected status code {response.status_code}: {response.text[:120]}"
    return ""


def check(host: str) -> tuple[str, str, bool]:
    s = requests.Session()
    response = http_get(s, host, random.choice(["/", "/health"]))
    if response.status_code != 200:
        return ("unexpected status code " + str(response.status_code), "", False)

    donor = "donor-" + word()
    password = "pw-" + word(10)
    r = post(s, host, "/api/register_user", {
        "username": donor,
        "password": password,
        "display": "Donor " + word(5),
    })
    err = expect(r)
    if err:
        return (err, "", False)
    r = post(s, host, "/api/login", {"username": donor, "password": password})
    err = expect(r)
    if err:
        return (err, "", False)
    return OK


def put(host: str, flag: str, flag_id: str) -> tuple[str, str, bool] | tuple[str, str, bool, str]:
    org_slug = "org-" + flag_id[:20].lower()
    admin = "admin-" + word()
    admin_pw = "apw-" + word(12)
    donor = "donor-" + word()
    donor_pw = "dpw-" + word(12)
    title = random.choice(["Pantry restock", "Winter coats", "Clinic rides", "Shelter meals"]) + " " + word(4)
    amount = random.choice([17, 23, 41, 59, 73])

    org_s = requests.Session()
    r = post(org_s, host, "/api/register_org", {
        "username": admin,
        "password": admin_pw,
        "org_slug": org_slug,
        "org_name": "GiveHere " + word(6),
        "vault": "desk-" + word(12),
    })
    err = expect(r)
    if err:
        return (err, "", False)
    r = post(org_s, host, "/api/login", {"username": admin, "password": admin_pw})
    err = expect(r)
    if err:
        return (err, "", False)
    lane = "lane-" + word(9)
    r = post(org_s, host, "/api/campaigns", {
        "org": org_slug,
        "title": title,
        "story": "Funding request " + word(24),
        "goal": str(random.randint(900, 9000)),
        "lane": lane,
    })
    err = expect(r)
    if err:
        return (err, "", False)
    campaign = r.json()["campaign"]

    donor_s = requests.Session()
    r = post(donor_s, host, "/api/register_user", {
        "username": donor,
        "password": donor_pw,
        "display": "Supporter " + word(5),
    })
    err = expect(r)
    if err:
        return (err, "", False)
    r = post(donor_s, host, "/api/login", {"username": donor, "password": donor_pw})
    err = expect(r)
    if err:
        return (err, "", False)
    if random.choice([True, False]):
        http_get(donor_s, host, "/api/orgs/" + urllib.parse.quote(org_slug))
    r = post(donor_s, host, "/api/donations/quote", {
        "campaign": campaign,
        "amount": str(amount),
    })
    err = expect(r)
    if err:
        return (err, "", False)
    quote = r.json()["quote"]
    note = flag if random.choice([True, False]) else f"private allocation note: {flag}"
    r = post(donor_s, host, "/api/donations/commit", {
        "quote": quote,
        "note": note,
    })
    err = expect(r)
    if err:
        return (err, "", False)
    donation = r.json()["donation"]
    receipt = r.json()["receipt"]

    private = "|".join([admin, admin_pw, donor, donor_pw, campaign, donation, receipt, lane])
    return ("", private, True, org_slug)


def get(host: str, flag: str, flag_id: str, private: str) -> tuple[str, str, bool]:
    try:
        admin, admin_pw, donor, donor_pw, campaign, donation, receipt, lane = private.split("|")
    except ValueError:
        return ("bad private state", "", False)

    options = ["org", "donor", "receipt"]
    random.shuffle(options)
    for mode in options:
        s = requests.Session()
        if mode == "org":
            r = post(s, host, "/api/login", {"username": admin, "password": admin_pw})
            if r.status_code != 200:
                continue
            r = http_get(s, host, f"/api/orgs/{flag_id}/donations")
        elif mode == "donor":
            r = post(s, host, "/api/login", {"username": donor, "password": donor_pw})
            if r.status_code != 200:
                continue
            r = http_get(s, host, "/api/me/donations")
        else:
            r = post(s, host, "/api/login", {"username": donor, "password": donor_pw})
            if r.status_code != 200:
                continue
            r = http_get(s, host, f"/api/receipts/{receipt}")
        if r.status_code == 200 and flag in r.text:
            return OK
    return ("flag does not match", "", False)
