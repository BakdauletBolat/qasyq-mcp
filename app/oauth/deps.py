from fastapi import HTTPException, Request

from app.oauth import storage


def www_authenticate(base_url: str) -> str:
    return f'Bearer resource_metadata="{base_url}/.well-known/oauth-protected-resource"'


def bearer_from_header(value: str | None) -> str | None:
    if not value:
        return None
    scheme, _, token = value.partition(" ")
    return token.strip() if scheme.lower() == "bearer" and token.strip() else None


def require_bearer(request: Request) -> None:
    settings = request.app.state.settings
    token = bearer_from_header(request.headers.get("authorization"))
    if not token or not storage.verify_access_token(settings.db_path, token):
        raise HTTPException(
            status_code=401,
            detail="invalid_token",
            headers={"WWW-Authenticate": www_authenticate(settings.base_url)},
        )
