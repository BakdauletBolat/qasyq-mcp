from urllib.parse import parse_qs, urlencode, urlparse, urlunparse

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse

from app.oauth import storage
from app.oauth.crypto import constant_time_eq, verify_pkce
from app.oauth.pages import error_page, login_page
from app.oauth.ratelimit import RateLimiter

router = APIRouter()
limiter = RateLimiter()

AUTHORIZE_PER_IP = (10, 60.0)
AUTHORIZE_GLOBAL = (30, 600.0)
TOKEN_PER_IP = (30, 60.0)

NO_STORE = {"Cache-Control": "no-store", "Pragma": "no-cache"}


def _db(request: Request) -> str:
    return request.app.state.settings.db_path


def _ip(request: Request) -> str:
    return request.client.host if request.client else "unknown"


def _oauth_error(error: str, description: str, status: int = 400) -> JSONResponse:
    return JSONResponse({"error": error, "error_description": description}, status_code=status, headers=NO_STORE)


# ---- metadata -------------------------------------------------------------

@router.get("/.well-known/oauth-protected-resource")
@router.get("/.well-known/oauth-protected-resource/mcp")
def protected_resource(request: Request):
    base = request.app.state.settings.base_url
    return {
        "resource": f"{base}/mcp",
        "authorization_servers": [base],
        "bearer_methods_supported": ["header"],
    }


@router.get("/.well-known/oauth-authorization-server")
def authorization_server(request: Request):
    base = request.app.state.settings.base_url
    return {
        "issuer": base,
        "authorization_endpoint": f"{base}/authorize",
        "token_endpoint": f"{base}/token",
        "registration_endpoint": f"{base}/register",
        "response_types_supported": ["code"],
        "grant_types_supported": ["authorization_code", "refresh_token"],
        "code_challenge_methods_supported": ["S256"],
        "token_endpoint_auth_methods_supported": ["none"],
    }


# ---- dynamic client registration (RFC 7591) -------------------------------

@router.post("/register")
async def register(request: Request):
    try:
        body = await request.json()
    except ValueError:
        body = None
    if not isinstance(body, dict):
        return _oauth_error("invalid_client_metadata", "body must be a JSON object")

    uris = body.get("redirect_uris")
    if not isinstance(uris, list) or not uris or not all(isinstance(u, str) for u in uris):
        return _oauth_error("invalid_redirect_uri", "redirect_uris must be a non-empty list of strings")
    if not all(storage.redirect_uri_allowed(u) for u in uris):
        return _oauth_error("invalid_redirect_uri", "redirect_uri is not allowed")
    if body.get("token_endpoint_auth_method", "none") != "none":
        return _oauth_error("invalid_client_metadata", "only token_endpoint_auth_method=none is supported")

    name = body.get("client_name")
    name = name if isinstance(name, str) else None
    created = storage.create_client(_db(request), uris, name)
    return JSONResponse(
        {
            **created,
            "redirect_uris": uris,
            "client_name": name,
            "token_endpoint_auth_method": "none",
            "grant_types": ["authorization_code", "refresh_token"],
            "response_types": ["code"],
        },
        status_code=201,
        headers=NO_STORE,
    )


# ---- authorization --------------------------------------------------------

_AUTH_FIELDS = ("response_type", "client_id", "redirect_uri", "code_challenge", "code_challenge_method", "state")


def _redirect(redirect_uri: str, **params: str) -> RedirectResponse:
    parts = urlparse(redirect_uri)
    query = parse_qs(parts.query, keep_blank_values=True)
    flat = [(k, v) for k, vs in query.items() for v in vs] + [(k, v) for k, v in params.items() if v]
    return RedirectResponse(urlunparse(parts._replace(query=urlencode(flat))), status_code=302)


def _validate_authorize(request: Request, p: dict[str, str]):
    """Returns (error_response, None) or (None, client)."""
    client = storage.get_client(_db(request), p.get("client_id", ""))
    if not client:
        return HTMLResponse(error_page("Unknown client_id"), status_code=400), None
    if p.get("redirect_uri") not in client["redirect_uris"]:
        return HTMLResponse(error_page("redirect_uri does not match registration"), status_code=400), None

    ru, state = p["redirect_uri"], p.get("state", "")
    if p.get("response_type") != "code":
        return _redirect(ru, error="unsupported_response_type", state=state), None
    if p.get("code_challenge_method") != "S256" or not p.get("code_challenge"):
        return _redirect(ru, error="invalid_request", error_description="PKCE S256 required", state=state), None
    return None, client


@router.get("/authorize")
def authorize_form(request: Request):
    params = {k: request.query_params.get(k, "") for k in _AUTH_FIELDS}
    err, _ = _validate_authorize(request, params)
    if err:
        return err
    return HTMLResponse(login_page(params), headers={"Cache-Control": "no-store"})


@router.post("/authorize")
async def authorize_submit(request: Request):
    ip = _ip(request)
    if not limiter.allow(f"authz:{ip}", *AUTHORIZE_PER_IP) or not limiter.allow("authz:*", *AUTHORIZE_GLOBAL):
        return HTMLResponse(error_page("Too many attempts, try again later."), status_code=429)

    form = await request.form()
    params = {k: str(form.get(k, "")) for k in _AUTH_FIELDS}
    err, _ = _validate_authorize(request, params)
    if err:
        return err

    password = str(form.get("password", ""))
    if not constant_time_eq(password, request.app.state.settings.owner_password):
        return HTMLResponse(login_page(params, "Wrong password"), status_code=401)

    code = storage.create_code(_db(request), params["client_id"], params["redirect_uri"], params["code_challenge"])
    return _redirect(params["redirect_uri"], code=code, state=params["state"])


# ---- token ----------------------------------------------------------------

@router.post("/token")
async def token(request: Request):
    if not limiter.allow(f"token:{_ip(request)}", *TOKEN_PER_IP):
        return _oauth_error("slow_down", "too many requests", 429)

    form = await request.form()
    grant = str(form.get("grant_type", ""))
    client_id = str(form.get("client_id", ""))
    db = _db(request)

    client = storage.get_client(db, client_id)
    if not client:
        return _oauth_error("invalid_client", "unknown client", 401)

    if grant == "authorization_code":
        code, verifier = str(form.get("code", "")), str(form.get("code_verifier", ""))
        row = storage.consume_code(db, code) if code else None
        if not row or row["client_id"] != client_id:
            return _oauth_error("invalid_grant", "invalid, expired or used code")
        if str(form.get("redirect_uri", "")) != row["redirect_uri"]:
            return _oauth_error("invalid_grant", "redirect_uri mismatch")
        if not verify_pkce(verifier, row["code_challenge"]):
            return _oauth_error("invalid_grant", "PKCE verification failed")
        return JSONResponse(storage.issue_tokens(db, client_id, row["code_hash"]), headers=NO_STORE)

    if grant == "refresh_token":
        tokens = storage.rotate_refresh(db, str(form.get("refresh_token", "")), client_id)
        if not tokens:
            return _oauth_error("invalid_grant", "invalid or expired refresh token")
        return JSONResponse(tokens, headers=NO_STORE)

    return _oauth_error("unsupported_grant_type", "grant_type must be authorization_code or refresh_token")
