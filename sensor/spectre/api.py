"""FastAPI surface: REST endpoints + the live WebSocket feed.

All data routes require a session cookie. First-run setup (creating the admin
password) is the only mutating route allowed before a user exists.

Author: gurvinny
Project: SPECTRE
"""
from __future__ import annotations

import asyncio
import logging
import time

from fastapi import (Depends, FastAPI, HTTPException, Request, Response,
                     WebSocket, WebSocketDisconnect)
from fastapi.middleware.cors import CORSMiddleware

from . import __version__
from .auth import hash_password, new_session_token, verify_password
from .config import Config
from .pipeline import Pipeline
from .store import Store

log = logging.getLogger("spectre.api")

ADMIN = "admin"
SESSION_COOKIE = "spectre_session"
SESSION_TTL = 7 * 24 * 3600


def create_app(store: Store, config: Config, pipeline: Pipeline) -> FastAPI:
    app = FastAPI(title="SPECTRE", version=__version__)

    # The browser talks to the API cross-origin (different port); allow it and
    # send credentials so the session cookie flows.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # ── auth helpers ───────────────────────────────────────────────────
    def current_user(request: Request) -> str:
        token = request.cookies.get(SESSION_COOKIE)
        if token:
            sess = store.get_session(token)
            if sess:
                return sess["username"]
        raise HTTPException(status_code=401, detail="not authenticated")

    def issue_session(response: Response, username: str) -> None:
        token = new_session_token()
        store.create_session(token, username, SESSION_TTL)
        response.set_cookie(SESSION_COOKIE, token, max_age=SESSION_TTL,
                            httponly=True, samesite="lax")

    # ── public / gate ──────────────────────────────────────────────────
    @app.get("/health")
    def health() -> dict:
        return {"status": "ok", "version": __version__}

    @app.get("/api/status")
    def status() -> dict:
        return {"setup_complete": store.has_users(), "version": __version__}

    @app.post("/api/setup")
    def setup(body: dict, response: Response) -> dict:
        if store.has_users():
            raise HTTPException(status_code=409, detail="already set up")
        password = (body or {}).get("password") or ""
        if len(password) < 6:
            raise HTTPException(status_code=400,
                                detail="password must be at least 6 characters")
        pwd_hash, salt = hash_password(password)
        store.upsert_user(ADMIN, pwd_hash, salt)
        # Optional initial config from the wizard.
        for key in ("wazuh_host", "wazuh_port", "wazuh_proto", "wazuh_enabled"):
            if key in (body or {}):
                config.set(key, body[key])
        issue_session(response, ADMIN)
        return {"ok": True}

    @app.post("/api/login")
    def login(body: dict, response: Response) -> dict:
        user = store.get_user(ADMIN)
        password = (body or {}).get("password") or ""
        if not user or not verify_password(password, user["pwd_hash"], user["salt"]):
            raise HTTPException(status_code=401, detail="invalid password")
        issue_session(response, ADMIN)
        return {"ok": True}

    @app.post("/api/logout")
    def logout(request: Request, response: Response) -> dict:
        token = request.cookies.get(SESSION_COOKIE)
        if token:
            store.delete_session(token)
        response.delete_cookie(SESSION_COOKIE)
        return {"ok": True}

    @app.post("/api/password")
    def change_password(body: dict, user: str = Depends(current_user)) -> dict:
        row = store.get_user(user)
        old = (body or {}).get("current") or ""
        new = (body or {}).get("new") or ""
        if not row or not verify_password(old, row["pwd_hash"], row["salt"]):
            raise HTTPException(status_code=401, detail="current password wrong")
        if len(new) < 6:
            raise HTTPException(status_code=400, detail="new password too short")
        pwd_hash, salt = hash_password(new)
        store.upsert_user(user, pwd_hash, salt)
        return {"ok": True}

    # ── data (auth required) ───────────────────────────────────────────
    @app.get("/api/overview")
    def overview(user: str = Depends(current_user)) -> dict:
        return pipeline.overview()

    @app.get("/api/frames")
    def frames(limit: int = 200, band: str | None = None,
               type: str | None = None, user: str = Depends(current_user)) -> dict:
        return {"frames": store.recent_frames(min(limit, 1000), band, type)}

    def _inv_window(kind: str, scope: str) -> tuple[float | None, float | None]:
        """Translate a scope into (since, until) last_seen bounds.
        active = seen within the active window; archived = older than that (but
        not yet purged); all = no bounds."""
        active = float(config(f"{kind}_active_seconds",
                              600 if kind == "device" else 1800))
        cut = time.time() - active
        if scope == "archived":
            return (None, cut)
        if scope == "all":
            return (None, None)
        return (cut, None)  # active (default)

    @app.get("/api/devices")
    def devices(limit: int = 500, scope: str = "active",
                user: str = Depends(current_user)) -> dict:
        since, until = _inv_window("device", scope)
        return {"devices": store.list_devices(min(limit, 2000), since, until)}

    @app.get("/api/access-points")
    def access_points(limit: int = 500, scope: str = "active",
                      user: str = Depends(current_user)) -> dict:
        since, until = _inv_window("ap", scope)
        return {"access_points": store.list_aps(min(limit, 2000), since, until)}

    @app.get("/api/search")
    def search(q: str = "", limit: int = 20,
               user: str = Depends(current_user)) -> dict:
        return {"results": store.search(q, min(max(limit, 1), 50))}

    @app.get("/api/threats")
    def threats(limit: int = 200, user: str = Depends(current_user)) -> dict:
        return {"threats": store.list_threats(min(limit, 1000))}

    @app.get("/api/channels")
    def channels(user: str = Depends(current_user)) -> dict:
        ov = pipeline.overview()
        return {"channels": ov["channels"], "band_breakdown": ov["band_breakdown"]}

    @app.get("/api/summaries")
    def summaries(limit: int = 120, user: str = Depends(current_user)) -> dict:
        return {"summaries": store.recent_summaries(min(limit, 500))}

    # ── settings ───────────────────────────────────────────────────────
    @app.get("/api/settings")
    def get_settings(user: str = Depends(current_user)) -> dict:
        return {"settings": config.snapshot(), "wazuh": pipeline.wazuh.status()}

    @app.put("/api/settings")
    def put_settings(body: dict, user: str = Depends(current_user)) -> dict:
        for key, value in (body or {}).items():
            config.set(key, value)
        return {"settings": config.snapshot()}

    # ── known networks (evil-twin allowlist) ──────────────────────────
    @app.get("/api/known-networks")
    def get_known(user: str = Depends(current_user)) -> dict:
        return {"known_networks": store.list_known_networks()}

    @app.post("/api/known-networks")
    def add_known(body: dict, user: str = Depends(current_user)) -> dict:
        ssid = (body or {}).get("ssid")
        if not ssid:
            raise HTTPException(status_code=400, detail="ssid required")
        row_id = store.add_known_network(ssid, body.get("bssid"),
                                         body.get("band"), body.get("note", ""))
        pipeline.refresh_known_networks()
        return {"ok": True, "id": row_id}

    @app.delete("/api/known-networks/{row_id}")
    def del_known(row_id: int, user: str = Depends(current_user)) -> dict:
        store.delete_known_network(row_id)
        pipeline.refresh_known_networks()
        return {"ok": True}

    @app.delete("/api/known-networks/by-bssid/{bssid}")
    def del_known_by_bssid(bssid: str, user: str = Depends(current_user)) -> dict:
        removed = store.delete_known_by_bssid(bssid)
        pipeline.refresh_known_networks()
        return {"ok": True, "removed": removed}

    # ── muted devices (trusted clients — silence anomaly alerts) ──────
    @app.get("/api/muted-devices")
    def get_muted(user: str = Depends(current_user)) -> dict:
        return {"muted_devices": config.get("muted_devices", []) or []}

    @app.post("/api/muted-devices")
    def add_muted(body: dict, user: str = Depends(current_user)) -> dict:
        mac = ((body or {}).get("mac") or "").upper()
        if not mac:
            raise HTTPException(status_code=400, detail="mac required")
        muted = list(config.get("muted_devices", []) or [])
        if mac not in muted:
            muted.append(mac)
            config.set("muted_devices", muted)
            pipeline.refresh_muted_devices()
        return {"ok": True, "muted_devices": muted}

    @app.delete("/api/muted-devices/{mac}")
    def del_muted(mac: str, user: str = Depends(current_user)) -> dict:
        mac = mac.upper()
        muted = [m for m in (config.get("muted_devices", []) or []) if m.upper() != mac]
        config.set("muted_devices", muted)
        pipeline.refresh_muted_devices()
        return {"ok": True, "muted_devices": muted}

    # ── live feed ──────────────────────────────────────────────────────
    @app.websocket("/ws")
    async def ws_feed(ws: WebSocket) -> None:
        token = ws.cookies.get(SESSION_COOKIE)
        if not token or not store.get_session(token):
            await ws.close(code=1008)  # policy violation
            return
        await ws.accept()
        queue = pipeline.subscribe()
        # Prime the client with a snapshot so the UI isn't blank until traffic.
        await ws.send_json({"type": "snapshot", "overview": pipeline.overview()})
        try:
            while True:
                msg = await queue.get()
                await ws.send_json(msg)
        except (WebSocketDisconnect, asyncio.CancelledError):
            pass
        finally:
            pipeline.unsubscribe(queue)

    return app
