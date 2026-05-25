# Shared Hosting Installer

This directory contains a single-file PHP installer for operators who start
from a regular hosting account with PHP 8.1+ and MySQL.

The installer is a configuration wizard. It checks the hosting account,
collects all public URLs, Telegram Mini App settings, admin secrets, AI
provider keys, payment settings, and runtime URLs, then generates:

- `.env.prod` for `docker/compose.prod.yml` or an equivalent managed runtime.
- `mini-app.env` for `mini-app/.env`.
- `admin-dashboard.env` for `admin-dashboard/.env`.
- `telegram-webhook.sh` for repeatable webhook registration.
- `botfather-checklist.md` with manual BotFather actions.
- `install-summary.md` with a redacted configuration summary.

Important: this does not turn the current backend into a PHP/MySQL
application. The product backend is FastAPI/Python and still requires
PostgreSQL and Redis. MySQL is used by the installer only to store redacted
installation metadata when the operator enables that option.

## Usage

1. Upload `install.php` to the hosting account.
2. Open it over HTTPS.
3. Complete the wizard steps.
4. Download or move files from the generated directory.
5. Delete `install.php` or protect the installer directory.

For the full runbook, see
[`docs/SHARED_HOSTING_INSTALLER.md`](../../docs/SHARED_HOSTING_INSTALLER.md).

## Local checks

```bash
php -l deploy/shared-hosting/install.php
php deploy/shared-hosting/tests/installer_smoke.php
```
