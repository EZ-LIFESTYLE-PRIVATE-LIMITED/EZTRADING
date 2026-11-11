# EZTrading

A multi-user web app for Zerodha Kite. It reads each user's holdings and takes the amount they want to deploy. It computes technical indicators, reads market and stock news, and asks an AI advisor (Gemini, Claude, or an offline rules engine) for a trading plan in one of three styles: **Intraday**, **Swing** or **Positional**.

Users can **Execute** a suggestion after confirming it, or **Ignore** it. EZTrading can also auto-analyze during market hours and send a notification (browser push and/or Telegram) when action is needed. An **IPO** tab lists open and upcoming NSE issues and can ask the AI for an apply/avoid verdict on each.

> Decision support only, not investment advice. Orders are placed only after the user confirms each one; auto-analysis never trades.

## Features
| | |
|---|---|
| Sign-in | Google SSO (plus a passwordless dev login, local development only). Each user's data is isolated. |
| Kite | Each user saves their own Kite API key and secret in **Settings** (encrypted at rest), then clicks **Connect Kite** once a day. |
| Advisor dropdown | Gemini 3.6/3.8 Flash, Claude Opus/Sonnet 5.5, or Rules. Uses the user's own API key if saved, otherwise the server's. |
| Trading styles | Intraday (MIS, 5-min data, VWAP/EMA/opening range, long and short, stop-loss required), Swing (CNC, days to weeks), Positional (CNC, weeks to months). |
| Execute / Ignore | Confirm dialog (quantity, LIMIT/MARKET, price). The server re-checks plan age, market hours, budget, holdings and duplicates before placing the order on Kite. |
| Notifications | Web Push (VAPID) and Telegram bot. Deduplicated, so the same suggested actions aren't notified twice. |
| Auto-analysis | Up to 10 schedules per user, each with its own style and interval (e.g. Intraday every 15 min plus Swing every 2 h), each switchable on/off. They run only during NSE hours, in a separate worker process. |
| Theme | Auto (follows the OS), Light or Dark, from the account menu. |
| IPO | NSE current and upcoming issues, with an AI verdict and suggested lots that fit the wallet. |

## Run locally

```bash
python -m venv .venv
.venv\Scripts\activate            # Windows  (source .venv/bin/activate on macOS/Linux)
pip install -r requirements.txt
copy .env.example .env            # DEV_LOGIN=true is already set
uvicorn app.main:app --port 8000
```

Open http://127.0.0.1:8000 and use **Dev sign-in**. The SQLite database and migrations are created automatically in development.

- **Demo data:** set `BROKER=fake` and `IPO_SOURCE=fake` to use sample holdings and IPOs, so no Kite account is needed. For an AI-free demo, pick **Rules** in the advisor dropdown.
- **Auto-analysis:** run the worker in a second terminal with `python -m app.worker`.
- **Tests:** run `pytest -q`.
- **Google sign-in locally:** create the OAuth client described under Deploy, but add `http://127.0.0.1:8000/auth/google/callback` as an authorized redirect URI. Put `GOOGLE_CLIENT_ID` and `GOOGLE_CLIENT_SECRET` in `.env` and restart. Signing in with Google using the same email as a dev-login account takes that account over, keeping its keys, wallet and plans.

## Where data is stored

Everything lives in one SQL database, set by `DATABASE_URL`:
- **Local development:** SQLite file `data/eztrading.db`.
- **Docker / production:** the Postgres `db` service, stored in the `pgdata` Docker volume.

| Table | Contents |
|---|---|
| `users` | Google account id, email, name, picture |
| `user_settings` | Advisor, default style, notification toggles, linked Telegram chat |
| `auto_schedules` | Auto-analysis schedules (style, interval, on/off, next run) |
| `credentials` | Kite and AI API keys, **Fernet-encrypted** with `APP_ENCRYPTION_KEY` |
| `kite_sessions` | Today's Kite access token, encrypted |
| `wallets` | The amount you want to deploy |
| `plans`, `suggestion_actions` | Generated plans and what you did with each suggestion |
| `orders` | Every order attempt and its Kite status |
| `push_subscriptions`, `notification_log`, `telegram_link_codes` | Notification plumbing and dedupe |

Losing `APP_ENCRYPTION_KEY` makes saved keys unreadable; users would have to re-enter them. Only the theme choice is kept in the browser (localStorage).

## Deploy (Docker on a VPS)

Use a VPS with a **static IP**, because Zerodha requires a whitelisted static IP for orders placed via the API. Any small Ubuntu VM with Docker works, e.g. DigitalOcean, Hetzner or Lightsail.

1. **DNS:** point an A record (e.g. `trade.example.com`) to the VPS IP. Caddy obtains the HTTPS certificate automatically.
2. **Google OAuth:** in Google Cloud Console → APIs & Services → Credentials, create an *OAuth client ID* (Web application). Set the authorized redirect URI to `https://trade.example.com/auth/google/callback`.
3. **Telegram (optional):** create a bot with @BotFather and note the token and username.
4. **Configure:**
   ```bash
   git clone <your repo> eztrading && cd eztrading
   cp .env.production.example .env
   python3 scripts/gen_keys.py      # paste the output into .env
   nano .env                        # DOMAIN, PUBLIC_BASE_URL, POSTGRES_PASSWORD, Google keys, AI keys, bot
   ```
5. **Start:**
   ```bash
   docker compose up -d --build
   docker compose logs -f web worker
   ```
   The `web` container runs `alembic upgrade head` on start. `worker` runs the auto-analysis loop. Run exactly one worker.
6. **Telegram webhook** (once):
   ```bash
   curl "https://api.telegram.org/bot$TELEGRAM_BOT_TOKEN/setWebhook" \
     -d "url=https://trade.example.com/telegram/webhook" \
     -d "secret_token=$TELEGRAM_WEBHOOK_SECRET"
   ```
7. **Each user then:**
   - creates a Kite Connect app at developers.kite.trade
   - sets its redirect URL to `https://trade.example.com/auth/kite/callback` (Settings shows it with a Copy button)
   - **registers the VPS static IP** in that app
   - pastes the API key and secret into Settings and clicks **Connect Kite**
8. **Backups:**
   ```bash
   docker compose exec db pg_dump -U eztrading eztrading > backup.sql
   ```

Set `NSE_HOLIDAYS` (comma-separated dates) so auto-analysis and order checks skip exchange holidays.

## Architecture

```
static/ (vanilla ES modules) ─► FastAPI routers (app/api) ─► per-user services (app/services) ─► ports (app/domain/ports.py)
                                        │                                                          ▲
                                 deps: session user, CSRF                     adapters (app/adapters) ─┘
                                                                              repositories (app/repositories) ─► SQLAlchemy (app/db)
```

- **Composition root (`app/container.py`):**
  - `AppContainer` holds the process singletons: DB, caches, news, the IPO source and the push/Telegram senders.
  - `for_user(db, user_id)` builds a `UserServices` bundle with that user's Kite session, advisor, wallet and so on.
- **Ports & adapters:** Kite, Yahoo Finance, RSS, NSE, Gemini, Claude, Web Push and Telegram are all adapters behind `Protocol`s, so services never import vendor SDKs.
- **Strategy + registry:**
  - Trading styles (`app/services/styles.py`), LLM providers (`app/adapters/llm/factory.py`) and the advisor catalog (`ADVISOR_CATALOG` in `app/config.py`).
  - Advisor *tasks* (`app/services/advice/`) are provider-neutral and work with any `LLMClientPort`.
- **Decorator / Chain of Responsibility:** `CachedPriceHistory(FallbackPriceHistory([Kite, Yahoo]))`, with a cache shared across users.
- **Null Objects:** `UnconfiguredBroker`, `NullPushSender` and `NullMessenger` replace scattered `if` checks.
- **Safety by construction:**
  - The worker receives an `AutoTarget` (analysis plus notifications) and no `OrderService`.
  - Every order is re-validated server-side.
  - Secrets are Fernet-encrypted and never returned by the API.

### Adding things
- **Another AI provider:** add `app/adapters/llm/<name>_client.py` with `complete_json(system, user, schema)`, register it in `factory.py`, and add rows to `ADVISOR_CATALOG`.
- **Another trading style:** add a `TradingStyle` to `STYLES`.
- **Another notification channel:** implement a sender and fan it out in `NotificationService.deliver`.

## API (all `/api/*` routes need a session; mutating requests need header `X-Requested-With: fetch`)
| Method | Path | |
|---|---|---|
| GET | `/api/config`, `/healthz` | public |
| GET | `/api/me`, `/api/status`, `/api/advisors`, `/api/styles` | |
| GET/PUT | `/api/settings` | advisor, default style, notification toggles |
| GET/POST | `/api/schedules` `{style, interval_min, enabled}` | auto-analysis schedules |
| PUT/DELETE | `/api/schedules/{id}` | |
| PUT/DELETE | `/api/credentials/{kite\|gemini\|claude}` | write-only secrets |
| GET | `/api/portfolio` | |
| GET/PUT | `/api/wallet` | |
| POST | `/api/analyze` `{style}` | |
| GET | `/api/plan` | |
| DELETE | `/api/plans/{id}` | |
| POST | `/api/plans/{id}/suggestions/{sid}/execute` `{quantity, order_type, price}` | |
| POST | `/api/plans/{id}/suggestions/{sid}/ignore` | |
| GET | `/api/orders` | |
| POST | `/api/orders/{id}/refresh` | |
| GET | `/api/ipos` | |
| POST | `/api/ipos/review` | |
| POST | `/api/push/subscribe`, `/api/push/unsubscribe`, `/api/telegram/link`, `/api/notifications/test` | |
| GET | `/auth/google/login`, `/auth/kite/login` (+ callbacks) | |
| POST | `/auth/logout`, `/telegram/webhook` | |

## Known limitations
- **Orders:** only the entry order is placed. Stop-loss and target are shown, but you set them in Kite yourself (a GTT/SL order is a natural next step).
- **NSE IPO data:** the endpoints are unofficial. NSE may block automated or cloud requests; the app then shows "IPO data unavailable".
- **Intraday staleness:** AI calls take 30–90 s, so intraday plans expire after 15 minutes and can't be executed after that.
- **Kite cost:** each user needs their own Kite Connect app. The historical-data add-on is optional, because Yahoo Finance is the fallback.
#   E Z T R A D I N G  
 