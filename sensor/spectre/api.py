"""FastAPI surface: REST endpoints + the live WebSocket feed.

All data routes require a session cookie. First-run setup (creating the admin
password) is the only mutating route allowed before a user exists.

Author: gurvinny
Project: SPECTRE
"""
from __future__ import annotations

import asyncio
import logging
import os
import time
from collections import deque

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
MIN_PASSWORD = 12

# Failed password attempts allowed per client address inside the window before
# further attempts are refused with 429. Counted for login and password change.
LOGIN_MAX_FAILURES = 5
LOGIN_WINDOW_SECONDS = 15 * 60

DEFAULT_WEB_ORIGINS = "http://localhost:4100,http://127.0.0.1:4100"


def web_origins() -> list[str]:
    """Browser origins allowed to call the API with the session cookie.

    Comma-separated in ``SPECTRE_WEB_ORIGINS``; the compose file derives it
    from ``HOST_IP`` and ``WEB_PORT``. Never a wildcard: a credentialed
    wildcard makes the browser hand the session to any origin that asks.
    """
    raw = os.environ.get("SPECTRE_WEB_ORIGINS") or DEFAULT_WEB_ORIGINS
    return [o.strip().rstrip("/") for o in raw.split(",") if o.strip() and o.strip() != "*"]


def _clamp(value: int, upper: int) -> int:
    """Bound a client-supplied row limit. SQLite reads LIMIT -1 as unlimited."""
    return max(1, min(value, upper))


class FailureLimiter:
    """In-memory sliding window of failed password attempts per client."""

    def __init__(self, max_failures: int = LOGIN_MAX_FAILURES,
                 window: float = LOGIN_WINDOW_SECONDS) -> None:
        self.max_failures = max_failures
        self.window = window
        self._fails: dict[str, deque[float]] = {}

    def _recent(self, key: str, now: float) -> deque[float]:
        q = self._fails.setdefault(key, deque())
        while q and q[0] <= now - self.window:
            q.popleft()
        return q

    def retry_after(self, key: str, now: float | None = None) -> int:
        """Seconds until *key* may try again, or 0 if it is not blocked."""
        now = time.time() if now is None else now
        q = self._recent(key, now)
        if len(q) < self.max_failures:
            return 0
        return max(1, int(q[0] + self.window - now) + 1)

    def fail(self, key: str, now: float | None = None) -> None:
        now = time.time() if now is None else now
        self._recent(key, now).append(now)

    def reset(self, key: str) -> None:
        self._fails.pop(key, None)


def create_app(store: Store, config: Config, pipeline: Pipeline,
               origins: list[str] | None = None) -> FastAPI:
    app = FastAPI(title="SPECTRE", version=__version__)
    allowed = set(origins if origins is not None else web_origins())
    limiter = FailureLimiter()
    app.state.limiter = limiter

    # The browser talks to the API cross-origin (different port), with the
    # session cookie, so only the console's own origin(s) may do so.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=sorted(allowed),
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "DELETE"],
        allow_headers=["content-type"],
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

    def client_key(request: Request) -> str:
        return request.client.host if request.client else "unknown"

    def check_password(request: Request, password: str, row: dict | None) -> bool:
        """Verify under the failure limiter; raises 429 while a client is blocked."""
        key = client_key(request)
        wait = limiter.retry_after(key)
        if wait:
            raise HTTPException(status_code=429, detail="too many attempts",
                                headers={"Retry-After": str(wait)})
        if row and verify_password(password, row["pwd_hash"], row["salt"]):
            limiter.reset(key)
            return True
        limiter.fail(key)
        return False

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
        if len(password) < MIN_PASSWORD:
            raise HTTPException(
                status_code=400,
                detail=f"password must be at least {MIN_PASSWORD} characters")
        pwd_hash, salt = hash_password(password)
        store.upsert_user(ADMIN, pwd_hash, salt)
        # Optional initial config from the wizard.
        for key in ("wazuh_host", "wazuh_port", "wazuh_proto", "wazuh_enabled"):
            if key in (body or {}):
                config.set(key, body[key])
        issue_session(response, ADMIN)
        return {"ok": True}

    @app.post("/api/login")
    def login(body: dict, request: Request, response: Response) -> dict:
        user = store.get_user(ADMIN)
        password = (body or {}).get("password") or ""
        if not check_password(request, password, user):
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
    def change_password(body: dict, request: Request,
                        user: str = Depends(current_user)) -> dict:
        row = store.get_user(user)
        old = (body or {}).get("current") or ""
        new = (body or {}).get("new") or ""
        if not check_password(request, old, row):
            raise HTTPException(status_code=401, detail="current password wrong")
        if len(new) < MIN_PASSWORD:
            raise HTTPException(
                status_code=400,
                detail=f"new password must be at least {MIN_PASSWORD} characters")
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
        return {"frames": store.recent_frames(_clamp(limit, 1000), band, type)}

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
        return {"devices": store.list_devices(_clamp(limit, 2000), since, until)}

    @app.get("/api/access-points")
    def access_points(limit: int = 500, scope: str = "active",
                      user: str = Depends(current_user)) -> dict:
        since, until = _inv_window("ap", scope)
        return {"access_points": store.list_aps(_clamp(limit, 2000), since, until)}

    @app.get("/api/search")
    def search(q: str = "", limit: int = 20,
               user: str = Depends(current_user)) -> dict:
        return {"results": store.search(q, _clamp(limit, 50))}

    @app.get("/api/threats")
    def threats(limit: int = 200, user: str = Depends(current_user)) -> dict:
        return {"threats": store.list_threats(_clamp(limit, 1000))}

    @app.get("/api/channels")
    def channels(user: str = Depends(current_user)) -> dict:
        ov = pipeline.overview()
        return {"channels": ov["channels"], "band_breakdown": ov["band_breakdown"]}

    @app.get("/api/summaries")
    def summaries(limit: int = 120, user: str = Depends(current_user)) -> dict:
        return {"summaries": store.recent_summaries(_clamp(limit, 500))}

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
        # Browsers always send Origin on a WebSocket handshake and CORS does
        # not apply to it, so the allowlist has to be enforced here.
        origin = (ws.headers.get("origin") or "").rstrip("/")
        token = ws.cookies.get(SESSION_COOKIE)
        if (origin and origin not in allowed) or not token \
                or not store.get_session(token):
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
