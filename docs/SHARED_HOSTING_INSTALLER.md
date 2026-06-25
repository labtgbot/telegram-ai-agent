# Shared Hosting PHP/MySQL Installer

Issue #134 asks for an automatic installer that can be uploaded to a regular
hosting account with PHP 8.1+ and MySQL, then guide the operator through all
deployment settings.

The installer lives at [`deploy/shared-hosting/install.php`](../deploy/shared-hosting/install.php).
It is intentionally a single PHP file so it can be uploaded through a hosting
panel without Composer or Node.js.

## What It Does

- Checks PHP version and required extensions: `json`, `curl`, `mbstring`,
  `openssl`, `pdo`, `pdo_mysql`, and `session`.
- Checks that the installer directory is writable.
- Collects public domains, Mini App URL, API URLs, and ACME email.
- Collects MySQL credentials and can write redacted installer metadata.
- Collects the real application runtime settings: PostgreSQL `DATABASE_URL`,
  Redis `REDIS_URL`, and Docker image references.
- Collects Telegram bot token, username, webhook secret, and BotFather values.
- Collects admin secrets, initial super-admin Telegram IDs, AI provider keys,
  payment settings, and Sentry settings.
- Generates production-ready configuration files and a webhook script.
- Optionally calls Telegram `setWebhook` from the hosting account.

## Runtime Boundary

The current application is not a PHP/MySQL application. The backend uses:

- FastAPI / Python 3.11+
- PostgreSQL with JSONB, partial indexes, and partitioned tables
- Redis for rate limits, cache, and short-lived state
- React/Vite Mini App
- Next.js admin dashboard

Therefore the installer does not claim that shared PHP hosting alone can run
the whole product. It helps an operator configure either:

- the existing single-host Docker Compose deployment,
- a managed container platform with PostgreSQL and Redis,
- or a static Mini App hosted on the PHP hosting account while backend/admin
  run elsewhere.

MySQL is used only for installer metadata so a hosting operator can keep a
redacted audit record of completed installs.

## Generated Files

After the final step the installer writes files into
`deploy/shared-hosting/generated/` on the hosting account:

| File | Purpose |
|------|---------|
| `.env.prod` | Production env file for `docker/compose.prod.yml` or equivalent runtime mapping. |
| `mini-app.env` | Build-time variables for `mini-app/.env`. |
| `admin-dashboard.env` | Variables for `admin-dashboard/.env`. |
| `telegram-webhook.sh` | Repeatable `setWebhook` and `getWebhookInfo` commands. |
| `botfather-checklist.md` | Manual BotFather steps for domain and menu button. |
| `install-summary.md` | Redacted installation summary for operators. |

Secret-bearing files are written with restrictive permissions where the host
allows it.

## Operator Flow

1. Upload `deploy/shared-hosting/install.php` to the hosting account.
2. Open it over HTTPS.
3. Confirm the requirements page.
4. Fill in public domains and API URLs.
5. Enter MySQL credentials if metadata storage is needed.
6. Enter PostgreSQL and Redis runtime URLs.
7. Enter Telegram bot and Mini App settings.
8. Enter admin, AI provider, payment, and Sentry settings.
9. Generate the files.
10. Move `.env.prod` to the Docker/managed runtime host, or map the values into
    the provider UI.
11. Run migrations and deploy using [`docs/DEPLOYMENT.md`](DEPLOYMENT.md).
12. Configure BotFather with `botfather-checklist.md`.
13. Register the webhook with `telegram-webhook.sh` or the installer checkbox.
14. Delete `install.php` or protect the installer directory.

## Security Notes

- Do not commit generated files.
- Delete the installer after use.
- Use HTTPS for the wizard, especially when entering tokens or secrets.
- Treat `.env.prod`, `mini-app.env`, and `admin-dashboard.env` as secrets.
- MySQL metadata is redacted, but it still contains operational topology and
  should not be public.

## Test Coverage

The installer has a dependency-free smoke test:

```bash
php -l deploy/shared-hosting/install.php
php deploy/shared-hosting/tests/installer_smoke.php
```

The deploy workflow also runs the PHP syntax check and smoke test for pull
requests that touch `deploy/**`.
