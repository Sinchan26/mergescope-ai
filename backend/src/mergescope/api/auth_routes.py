from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.responses import RedirectResponse

from mergescope.services.auth import OAUTH_COOKIE, SESSION_COOKIE, Session, require_session

router = APIRouter(prefix="/auth", tags=["authentication"])
SessionDep = Annotated[Session, Depends(require_session)]


@router.get("/status")
async def auth_status(request: Request):
    settings = request.app.state.auth.settings
    return {
        "configured": settings.github_login_ready,
        "install_url": f"https://github.com/apps/{settings.github_app_slug}/installations/new"
        if settings.github_app_slug
        else None,
    }


@router.get("/login")
async def login(request: Request):
    auth = request.app.state.auth
    url, browser = await auth.start()
    response = RedirectResponse(url, status_code=302)
    response.set_cookie(
        OAUTH_COOKIE,
        browser,
        httponly=True,
        secure=auth.settings.auth_cookie_secure,
        samesite="lax",
        max_age=600,
        path=f"{auth.settings.api_prefix}/auth",
    )
    return response


@router.get("/callback")
async def callback(request: Request, state: str = "", code: str = "", error: str = ""):
    auth = request.app.state.auth
    if error or not code or not state:
        response = RedirectResponse(
            f"{auth.settings.app_origin.rstrip('/')}?auth_error=cancelled", status_code=302
        )
    else:
        try:
            key = await auth.finish(state, request.cookies.get(OAUTH_COOKIE, ""), code)
        except HTTPException as exc:
            reason = "not_allowed" if exc.status_code == 403 else "failed"
            response = RedirectResponse(
                f"{auth.settings.app_origin.rstrip('/')}?auth_error={reason}", status_code=302
            )
        else:
            previous = request.cookies.get(SESSION_COOKIE)
            if previous:
                await auth.delete(previous)
            response = RedirectResponse(auth.settings.app_origin, status_code=302)
            response.set_cookie(
                SESSION_COOKIE,
                key,
                httponly=True,
                secure=auth.settings.auth_cookie_secure,
                samesite="lax",
                max_age=auth.settings.session_ttl_seconds,
                path="/",
            )
    response.delete_cookie(OAUTH_COOKIE, path=f"{auth.settings.api_prefix}/auth")
    return response


@router.get("/me")
async def me(session: SessionDep):
    return {"user": {"id": session.user_id, "login": session.login}, "csrf_token": session.csrf}


@router.get("/repositories")
async def repositories(request: Request, session: SessionDep):
    return {"items": await request.app.state.auth.repositories(session)}


@router.post("/logout", status_code=204)
async def logout(request: Request, session: SessionDep):
    await request.app.state.auth.delete(session.key)
    response = Response(status_code=204)
    response.delete_cookie(SESSION_COOKIE, path="/")
    return response
