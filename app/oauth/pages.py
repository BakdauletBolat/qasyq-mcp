from html import escape

_STYLE = (
    "body{font-family:system-ui,sans-serif;max-width:360px;margin:15vh auto;padding:0 16px}"
    "input,button{width:100%;padding:10px;margin-top:10px;font-size:16px;box-sizing:border-box}"
    ".err{color:#b00020}"
)


def login_page(params: dict[str, str], error: str | None = None) -> str:
    hidden = "".join(
        f'<input type="hidden" name="{escape(k)}" value="{escape(v, quote=True)}">' for k, v in params.items()
    )
    err = f'<p class="err">{escape(error)}</p>' if error else ""
    return (
        f"<!doctype html><meta charset=utf-8><meta name=viewport content='width=device-width,initial-scale=1'>"
        f"<title>Sign in</title><style>{_STYLE}</style>"
        f"<h2>Authorize access</h2><p>Enter the owner password to connect Claude.</p>{err}"
        f'<form method="post">{hidden}'
        f'<input type="password" name="password" placeholder="Password" autofocus required>'
        f"<button type=submit>Sign in</button></form>"
    )


def error_page(message: str) -> str:
    return (
        f"<!doctype html><meta charset=utf-8><title>Error</title><style>{_STYLE}</style>"
        f'<h2>Request error</h2><p class="err">{escape(message)}</p>'
    )
