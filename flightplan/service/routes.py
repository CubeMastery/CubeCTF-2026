import base64
import json
import secrets
import sqlite3
import time
from typing import Optional

from fastapi import APIRouter, Cookie, Depends, Header, HTTPException
from fastapi.responses import JSONResponse

from auth import hash_password, require_user, sessions, verify_password
from config import PORTAL_NAME
from database import db
from flightplans import (
    compatibility_tag,
    create_plan,
    load_plan,
    plan_public,
    plan_summary,
    seal_payload,
    station_beacon,
    unseal_payload,
)


router = APIRouter()


@router.get("/")
def index():
    return {
        "service": PORTAL_NAME,
        "description": "AIRAC coordination, route filing, dispatch release, and station briefing workspace.",
        "endpoints": {
            "airac": "/airac.json",
            "register": "/api/register",
            "login": "/api/login",
            "logout": "/api/logout",
            "plans": "/api/plans",
            "plan": "/api/plans/{ident}",
            "plan_private": "/api/plans/{ident}/private",
            "plan_navlog": "/api/plans/{ident}/navlog",
            "briefing": "/api/briefing/{ident}",
            "briefing_loadsheet": "/api/briefing/{ident}/loadsheet",
        },
    }


@router.get("/airac.json")
def airac():
    return {
        "cycle": "2606",
        "published": "2026-06-01",
        "valid_until": "2026-06-30",
        "station_beacon": station_beacon(),
        "briefing_formats": ["json", "telex", "loadsheet"],
    }


@router.post("/api/register")
def api_register(payload: dict):
    username = str(payload.get("username", "")).strip().lower()[:40]
    password = str(payload.get("password", ""))
    full_name = str(payload.get("full_name", username))[:80]
    home_base = str(payload.get("home_base", "KMSP")).upper()[:8]
    if not username or len(password) < 8:
        raise HTTPException(status_code=400, detail="invalid operator")
    try:
        with db() as conn:
            conn.execute(
                "insert into users(username,password_hash,full_name,home_base,created_at) values(?,?,?,?,?)",
                (username, hash_password(password), full_name, home_base, int(time.time())),
            )
    except sqlite3.IntegrityError:
        raise HTTPException(status_code=409, detail="operator exists")
    return {"ok": True, "username": username, "full_name": full_name, "home_base": home_base}


@router.post("/api/login")
def api_login(payload: dict):
    username = str(payload.get("username", "")).strip().lower()
    password = str(payload.get("password", ""))
    with db() as conn:
        user = conn.execute("select * from users where username = ?", (username,)).fetchone()
    if not user or not verify_password(password, user["password_hash"]):
        raise HTTPException(status_code=403, detail="invalid credentials")
    session_id = secrets.token_urlsafe(32)
    sessions[session_id] = user["id"]
    response = JSONResponse(
        {"ok": True, "username": username, "full_name": user["full_name"], "home_base": user["home_base"]}
    )
    response.set_cookie("session", session_id, httponly=True, samesite="lax")
    return response


@router.post("/api/logout")
def api_logout(session: Optional[str] = Cookie(default=None)):
    if session:
        sessions.pop(session, None)
    response = JSONResponse({"ok": True})
    response.delete_cookie("session")
    return response


@router.get("/api/plans")
def api_list_plans(user=Depends(require_user)):
    with db() as conn:
        plans = conn.execute(
            "select * from plans where owner_id = ? order by updated_at desc", (user["id"],)
        ).fetchall()
    return {"plans": [plan_summary(plan) for plan in plans]}


@router.post("/api/plans")
def api_create_plan(payload: dict, user=Depends(require_user)):
    plan_id = create_plan(user["id"], payload)
    return {"ident": plan_id, "briefing": f"/api/briefing/{plan_id}"}


@router.get("/api/plans/{ident}/private")
def api_private_plan(ident: str, user=Depends(require_user)):
    plan = load_plan(ident)
    if not plan or plan["owner_id"] != user["id"]:
        raise HTTPException(status_code=404, detail="plan not found")
    return {"ident": plan["ident"], "private_notes": plan["private_notes"]}


@router.get("/api/plans/{ident}/navlog")
def api_navlog(ident: str, user=Depends(require_user)):
    plan = load_plan(ident)
    if not plan or plan["owner_id"] != user["id"]:
        raise HTTPException(status_code=404, detail="plan not found")
    try:
        payload = unseal_payload(plan)
    except Exception:
        raise HTTPException(status_code=500, detail="navlog seal unavailable")
    return {
        "ident": plan["ident"],
        "navlog_seal": seal_payload(plan),
        "remarks": payload.get("remarks", ""),
        "release": payload.get("release"),
    }


@router.get("/api/briefing/{ident}")
def api_briefing(ident: str):
    plan = load_plan(ident)
    if not plan:
        raise HTTPException(status_code=404, detail="briefing not found")
    return plan_public(plan)


@router.get("/api/briefing/{ident}/loadsheet")
def loadsheet(ident: str, x_dispatch_client: str = Header(default="web")):
    plan = load_plan(ident)
    if not plan:
        raise HTTPException(status_code=404, detail="briefing not found")
    packet = plan_public(plan)
    packet["weights"] = {
        "fuel": plan["fuel"],
        "passengers": plan["passengers"],
        "bags": max(plan["passengers"] * 18, 0),
    }
    try:
        client = json.loads(base64.urlsafe_b64decode(x_dispatch_client + "==="))
    except Exception:
        client = {}
    profile = client.get("profile", {})
    accepts = client.get("accept", [])
    try:
        schema = int(profile.get("schema", 0))
    except Exception:
        schema = 0
    if (
        client.get("station") == plan["departure"]
        and schema < 4
        and "ops" in accepts
        and profile.get("cap") == compatibility_tag(plan)
    ):
        packet["ops"] = {
            "release_text": f'{plan["callsign"]} {plan["departure"]}-{plan["arrival"]} {plan["route"]}',
            "crew_channel": plan["private_notes"],
        }
    return packet
