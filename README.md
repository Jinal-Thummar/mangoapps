# TaskFlow

A simple, database-driven to-do list web application built with **Flask** and
**PostgreSQL**, prepared to run under **Gunicorn** behind an **Nginx** reverse proxy.

## Features

- Add, view, edit and delete tasks
- Mark tasks as completed / pending
- Priority: Low, Medium, High
- Filter: All, Pending, Completed
- Total / pending / completed counters
- Server-side input validation
- All data persisted in PostgreSQL
- `/health` endpoint that checks the app **and** database connectivity
- Structured logging to stdout, friendly error pages

## Project structure

```
app/
  __init__.py          Application factory (config, logging, DB, ProxyFix, error handlers)
  models.py            Task model (SQLAlchemy)
  routes.py            UI routes + /health
  templates/           base.html, index.html, error.html
  static/css/style.css
tests/test_app.py      pytest suite (in-memory SQLite, no PostgreSQL required)
config.py              Settings, all secrets read from environment variables
run.py                 Entry point (python run.py / gunicorn run:app)
requirements.txt
.env.example           Template for your local .env file
pytest.ini
```

## Database schema

Table `tasks` (created automatically on startup):

| Column        | Type                      | Notes                                 |
|---------------|---------------------------|---------------------------------------|
| `id`          | integer, primary key      |                                       |
| `title`       | varchar(200), not null    |                                       |
| `description` | text, nullable            | max 1000 chars (validated)            |
| `priority`    | varchar(10), not null     | `Low` / `Medium` / `High` (CHECK)     |
| `completed`   | boolean, not null         | default `false`                       |
| `created_at`  | timestamptz, not null     | set automatically (UTC)               |

---

## Run locally (macOS)

### 1. Install and start PostgreSQL

```bash
brew install postgresql@16
brew services start postgresql@16          # starts now and on every login
echo 'export PATH="/opt/homebrew/opt/postgresql@16/bin:$PATH"' >> ~/.zshrc
source ~/.zshrc
```

### 2. Create the database and user

```bash
psql postgres -c "CREATE USER taskflow WITH PASSWORD 'choose-a-strong-password';"
psql postgres -c "CREATE DATABASE taskflow OWNER taskflow;"
```

### 3. Set up Python

```bash
cd /path/to/project
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### 4. Configure environment variables

```bash
cp .env.example .env
python3 -c "import secrets; print(secrets.token_hex(32))"   # paste into SECRET_KEY
# edit .env: set SECRET_KEY and DB_PASSWORD
```

`.env` is git-ignored. In production, set the same variables through the
process manager (e.g. a systemd `EnvironmentFile`) instead of a `.env` file.

### 5. Run

Development server (auto-reload, debug):

```bash
python run.py
# open http://127.0.0.1:5000
```

With Gunicorn (how it runs in production):

```bash
gunicorn --bind 127.0.0.1:8000 --workers 3 --access-logfile - --error-logfile - run:app
# open http://127.0.0.1:8000
```

Tables are created automatically on startup. If PostgreSQL was down when the
app started, create them later with:

```bash
flask --app run init-db
```

---

## Testing

### Automated tests

```bash
source .venv/bin/activate
pytest -v
```

Tests use an in-memory SQLite database, so they run without PostgreSQL. They
cover CRUD, validation, filters, counters, 404/405 handling and the health
check (including a simulated database outage returning 503).

### Health check

```bash
curl -i http://127.0.0.1:5000/health
# HTTP/1.1 200 OK
# {"application":"up","database":"up","status":"healthy"}
```

Simulate a database outage:

```bash
brew services stop postgresql@16
curl -i http://127.0.0.1:5000/health     # HTTP/1.1 503 SERVICE UNAVAILABLE
brew services start postgresql@16
curl -i http://127.0.0.1:5000/health     # back to 200 (connections are re-checked automatically)
```

### Data persistence

1. Add a few tasks in the browser.
2. Stop the app (`Ctrl+C`) and start it again.
3. Reload the page: the tasks are still there, because they are stored in PostgreSQL.

You can also inspect the data directly:

```bash
psql -U taskflow -h localhost taskflow -c "SELECT id, title, priority, completed, created_at FROM tasks;"
```

---

## Environment variables

| Variable                | Required | Default      | Description                                  |
|-------------------------|----------|--------------|----------------------------------------------|
| `APP_ENV`               | no       | `production` | `development` or `production`                |
| `SECRET_KEY`            | yes*     | —            | Flask session signing key (*random in dev)   |
| `DATABASE_URL`          | no       | —            | Full Postgres URL; overrides the `DB_*` vars |
| `DB_HOST`               | no       | `localhost`  |                                              |
| `DB_PORT`               | no       | `5432`       |                                              |
| `DB_NAME`               | no       | `taskflow`   |                                              |
| `DB_USER`               | no       | `taskflow`   |                                              |
| `DB_PASSWORD`           | yes      | —            |                                              |
| `DB_CONNECT_TIMEOUT`    | no       | `5`          | Seconds before a DB connection attempt fails |
| `LOG_LEVEL`             | no       | `INFO`       |                                              |
| `SESSION_COOKIE_SECURE` | no       | `false`      | Set `true` when served over HTTPS            |

---

## Nginx reverse proxy (reference)

Gunicorn should listen only on `127.0.0.1`; Nginx is the public entry point.
The app uses Werkzeug's `ProxyFix`, so it trusts these forwarded headers from
one proxy hop:

```nginx
server {
    listen 80;
    server_name _;

    location / {
        proxy_pass         http://127.0.0.1:8000;
        proxy_set_header   Host              $host;
        proxy_set_header   X-Real-IP         $remote_addr;
        proxy_set_header   X-Forwarded-For   $proxy_add_x_forwarded_for;
        proxy_set_header   X-Forwarded-Proto $scheme;
    }

    location = /health {
        proxy_pass http://127.0.0.1:8000/health;
        access_log off;
    }
}
```

## Logging

Application logs go to **stdout** in the format
`timestamp [LEVEL] app: message`. Under Gunicorn, add `--access-logfile -`
and `--error-logfile -` so everything lands in one stream, which systemd and
journald collect automatically.

## Notes

- Normal database operations use the SQLAlchemy ORM. The only raw SQL is
  `SELECT 1` in the health check.
- No credentials are stored in the source code.
- The app has no authentication or CSRF protection (out of scope for this
  assessment). Add Flask-WTF/CSRF before exposing it publicly.
