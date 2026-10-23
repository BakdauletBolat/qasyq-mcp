import json

from app.oauth import storage
from app.oauth.deps import bearer_from_header, www_authenticate


class BearerAuthASGI:
    """Rejects requests without a valid access token before they reach the MCP app."""

    def __init__(self, app, settings):
        self.app = app
        self.settings = settings

    async def __call__(self, scope, receive, send):
        if scope["type"] == "http":
            headers = {k.decode().lower(): v.decode() for k, v in scope["headers"]}
            token = bearer_from_header(headers.get("authorization"))
            if not token or not storage.verify_access_token(self.settings.db_path, token):
                body = json.dumps({"error": "invalid_token"}).encode()
                await send(
                    {
                        "type": "http.response.start",
                        "status": 401,
                        "headers": [
                            (b"content-type", b"application/json"),
                            (b"content-length", str(len(body)).encode()),
                            (b"www-authenticate", www_authenticate(self.settings.base_url).encode()),
                        ],
                    }
                )
                await send({"type": "http.response.body", "body": body})
                return
        await self.app(scope, receive, send)
