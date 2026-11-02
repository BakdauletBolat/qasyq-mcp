# qasyq-mcp

Личный учёт еды как remote MCP-коннектор для Claude (claude.ai и мобильное приложение).
FastAPI + SQLite, авторизация OAuth 2.1 (Authorization Code + PKCE S256, DCR, refresh с ротацией).
Сервис только хранит записи (`date, name, grams, kcal, protein, fat, carbs`), вся логика на стороне Claude.

## Запуск

```bash
uv sync
cp .env.example .env      # заполните BASE_URL и OWNER_PASSWORD
set -a; source .env; set +a
uv run uvicorn app.main:app_factory --factory --host 127.0.0.1 --port 8000 \
    --proxy-headers --forwarded-allow-ips="127.0.0.1"
```

| Переменная       | Описание                                               |
|------------------|--------------------------------------------------------|
| `BASE_URL`       | публичный https URL без завершающего `/`               |
| `OWNER_PASSWORD` | единственный пароль на странице `/authorize`           |
| `DB_PATH`        | путь к SQLite (по умолчанию `./data/food.db`)          |

`--proxy-headers` нужен, чтобы rate limit видел реальный IP клиента, а не IP прокси.
`.env` и `*.db` в `.gitignore`, секреты не коммитятся.

## Деплой за HTTPS

Claude подключается только к публичному https-адресу.

**Cloudflare Tunnel** (без открытых портов):
```bash
cloudflared tunnel --url http://127.0.0.1:8000        # быстрый тест, выдаст *.trycloudflare.com
# постоянный домен: cloudflared tunnel create / route dns / run
```

**Caddy** (свой сервер и домен, сертификат выдаётся автоматически):
```
food.example.com {
    reverse_proxy 127.0.0.1:8000
}
```

Затем укажите этот адрес в `BASE_URL` (например `https://food.example.com`) и перезапустите сервис.

## Подключение к Claude

Settings → Connectors → Add custom connector → URL `https://<домен>/mcp`.
Claude сам зарегистрируется через `/register`, откроет страницу входа: введите `OWNER_PASSWORD`.

Инструменты: `log_entry`, `get_day`, `delete_entry`, `log_weight`, `get_weights`, `get_range`.
`get_weights` отдаёт ещё и MCP App (`ui://weights/chart.html`): график веса прямо в чате, если клиент поддерживает MCP Apps.

## Эндпоинты

- `GET /.well-known/oauth-protected-resource` (RFC 9728), `GET /.well-known/oauth-authorization-server` (RFC 8414)
- `POST /register` (RFC 7591): принимает `https://claude.ai/api/mcp/auth_callback` и `http://localhost|127.0.0.1:*`
- `GET/POST /authorize`: вход по паролю, PKCE S256 обязателен
- `POST /token`: `authorization_code` и `refresh_token` (ротация)
- `GET /entries/range?start=&end=` (итоги по дням и средние за период)
- `POST /weights` (`kg`, опционально `recorded_at`), `GET /weights/recent` (записи веса за 3 месяца)
- `/mcp` (Streamable HTTP) и REST `/entries` требуют `Authorization: Bearer`; иначе 401 с `WWW-Authenticate: Bearer resource_metadata=...`

Сроки жизни: code 60 с (одноразовый), access 1 ч, refresh 30 дней. В БД хранятся только sha256-хеши.
Повторное использование code отзывает токены, выданные по нему.

Rate limit (в памяти процесса): `POST /authorize` 10/мин на IP и 30 за 10 мин суммарно; `POST /token` 30/мин на IP.
Рассчитан на один процесс uvicorn, не запускайте несколько воркеров.

## Тесты

```bash
uv run pytest
```
