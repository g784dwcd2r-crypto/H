"""Service-key and operator-session protected control plane; tenant identities are never accepted."""

from __future__ import annotations

import hmac
from typing import Any

from fastapi import APIRouter, Body, Depends, HTTPException, Query, Request
from fastapi.responses import JSONResponse

from filings_hub.admin_operations import Operations
from filings_hub.platform_admin import LOOPBACK, AdminStore, csrf_for
from filings_hub.tenancy import SecurityError


def attach_admin(app, store: AdminStore, database):
    settings = store.settings
    ops = Operations(store, database)
    app.state.platform_admin = store
    app.state.admin_operations = ops

    @app.middleware("http")
    async def admin_response_headers(request: Request, call_next):
        response = await call_next(request)
        if request.url.path.startswith("/platform-admin"):
            response.headers["Cache-Control"] = "private, no-store"
            response.headers["Pragma"] = "no-cache"
            response.headers["X-Content-Type-Options"] = "nosniff"
            response.headers["X-Frame-Options"] = "DENY"
        return response

    @app.exception_handler(SecurityError)
    async def security_error(_request, error):
        return JSONResponse({"detail": error.detail}, status_code=error.status, headers={"Cache-Control": "no-store"})

    def gate(request: Request):
        if not settings.platform_admin_enabled:
            raise HTTPException(503, "Platform administration is not enabled on this deployment.")
        key = request.headers.get("x-api-key", "")
        if settings.api_key and not hmac.compare_digest(key, settings.api_key):
            raise HTTPException(401, "A trusted service gateway is required.")
        if settings.platform_admin_environment == "development" and (
            not request.client or request.client.host not in LOOPBACK
        ):
            raise HTTPException(403, "Development administration accepts loopback connections only.")
        if request.method != "GET":
            if request.headers.get("origin") != settings.platform_admin_origin:
                raise HTTPException(403, "The request origin does not match the configured administrator origin.")
            if not request.headers.get("content-type", "").startswith("application/json"):
                raise HTTPException(415, "Administrator mutations require JSON.")

    def session(request: Request, _=Depends(gate)):
        token = request.headers.get("x-admin-session", "")
        if request.method != "GET" and not hmac.compare_digest(
            request.headers.get("x-admin-csrf", ""), csrf_for(token)
        ):
            raise HTTPException(403, "Administrator CSRF token is missing or invalid.")
        return token

    router = APIRouter(prefix="/platform-admin", dependencies=[Depends(gate)])

    @router.post("/login")
    def login(request: Request, payload: dict[str, Any] = Body(...)):
        return store.login(payload.get("username"), payload.get("password"), peer=request.client.host)

    @router.get("/session")
    def me(token=Depends(session)):
        return store.me(token)

    @router.post("/password")
    def password(payload: dict[str, Any] = Body(...), token=Depends(session)):
        return store.password(token, payload.get("current_password"), payload.get("new_password", ""))

    @router.post("/reauthenticate")
    def reauthenticate(payload: dict[str, Any] = Body(...), token=Depends(session)):
        return store.password(token, payload.get("password"))

    @router.post("/logout")
    def logout(token=Depends(session)):
        return store.logout(token)

    @router.get("/overview")
    def overview(token=Depends(session)):
        return ops.overview(token)

    @router.get("/users")
    def users(
        q: str = Query("", max_length=150),
        limit: int = Query(25, ge=1, le=100),
        offset: int = Query(0, ge=0),
        token=Depends(session),
    ):
        return ops.users(token, q, limit, offset)

    @router.get("/users/{uid}")
    def user(uid: str, token=Depends(session)):
        return ops.user(token, uid)

    @router.post("/users/{uid}/status")
    def account_status(uid: str, payload: dict[str, Any] = Body(...), token=Depends(session)):
        return store.user_action(token, uid, payload)

    @router.post("/users/{uid}/revoke-sessions")
    def revoke(uid: str, payload: dict[str, Any] = Body(...), token=Depends(session)):
        return store.user_action(token, uid, payload, revoke=True)

    @router.get("/organizations")
    def organizations(
        q: str = Query("", max_length=150),
        limit: int = Query(25, ge=1, le=100),
        offset: int = Query(0, ge=0),
        token=Depends(session),
    ):
        return ops.organizations(token, q, limit, offset)

    @router.get("/organizations/{org}")
    def organization(org: str, token=Depends(session)):
        return ops.organization(token, org)

    @router.post("/organizations/{org}/members/{uid}")
    def member(org: str, uid: str, payload: dict[str, Any] = Body(...), token=Depends(session)):
        return store.member_action(token, org, uid, payload)

    @router.get("/audit")
    def audit(
        q: str = Query("", max_length=150),
        limit: int = Query(25, ge=1, le=100),
        offset: int = Query(0, ge=0),
        token=Depends(session),
    ):
        return ops.audit(token, q, limit, offset)

    @router.get("/research")
    def research(
        q: str = Query("", max_length=150),
        limit: int = Query(25, ge=1, le=100),
        offset: int = Query(0, ge=0),
        token=Depends(session),
    ):
        return ops.research(token, q=q, limit=limit, offset=offset)

    @router.get("/jobs")
    def jobs(
        q: str = Query("", max_length=150),
        limit: int = Query(25, ge=1, le=100),
        offset: int = Query(0, ge=0),
        token=Depends(session),
    ):
        return ops.jobs(token, q=q, limit=limit, offset=offset)

    @router.get("/sources")
    def sources(token=Depends(session)):
        return ops.sources(token)

    @router.post("/jobs/{job_id}/{action}")
    def job_action(job_id: str, action: str, payload: dict[str, Any] = Body(...), token=Depends(session)):
        return ops.job_action(token, job_id, action, payload)

    @router.get("/configuration")
    def configuration(token=Depends(session)):
        with store.transaction() as tx:
            store.authorize(tx, token)
            return {
                "configuration": store.configuration(tx),
                "deployment": {
                    "environment": settings.platform_admin_environment,
                    "admin_session_minutes": settings.platform_admin_session_minutes,
                    "mail_configured": bool(settings.smtp_host),
                    "google_configured": bool(settings.google_client_id and settings.google_client_secret),
                    "mfa": "not_configured",
                    "secrets_editable": False,
                },
            }

    @router.post("/configuration")
    def update_configuration(payload: dict[str, Any] = Body(...), token=Depends(session)):
        return {"configuration": store.configure(token, payload)}

    app.include_router(router)
