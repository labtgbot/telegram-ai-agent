"""Tiny mock backend used only for taking PR screenshots.

Serves the four /api/v1/* endpoints the BalancePage hits, with deterministic
data so the rendered screenshot is reproducible.  Run with:

    python experiments/mock_backend.py 8788

Then proxy via vite.config.ts so the mini-app dev server forwards /api/v1.
"""
from __future__ import annotations

import json
import sys
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import parse_qs, urlparse

TRANSACTIONS = [
    {"id": 5, "transaction_type": "manual_bonus", "tokens_amount": 200, "stars_amount": None, "package_name": None, "payment_status": None, "payment_method": None, "created_at": "2026-05-05T12:00:00Z", "completed_at": "2026-05-05T12:00:01Z"},
    {"id": 4, "transaction_type": "refund", "tokens_amount": 250, "stars_amount": 125, "package_name": "starter", "payment_status": "refunded", "payment_method": "telegram_stars", "created_at": "2026-05-04T12:00:00Z", "completed_at": "2026-05-04T12:05:00Z"},
    {"id": 3, "transaction_type": "bonus", "tokens_amount": 30, "stars_amount": None, "package_name": "daily_bonus", "payment_status": None, "payment_method": None, "created_at": "2026-05-03T12:00:00Z", "completed_at": "2026-05-03T12:00:01Z"},
    {"id": 2, "transaction_type": "spend", "tokens_amount": 12, "stars_amount": None, "package_name": None, "payment_status": None, "payment_method": None, "created_at": "2026-05-02T12:00:00Z", "completed_at": None},
    {"id": 1, "transaction_type": "purchase", "tokens_amount": 500, "stars_amount": 250, "package_name": "starter", "payment_status": "completed", "payment_method": "telegram_stars", "created_at": "2026-05-01T12:00:00Z", "completed_at": "2026-05-01T12:01:00Z"},
]

BALANCE = {
    "token_balance": 1850,
    "is_premium": True,
    "premium_expires_at": "2026-12-31T23:59:59Z",
    "daily_bonus_available": True,
}

REFERRAL = {
    "referral_code": "REF-DEMO",
    "referral_link": "https://t.me/test_ai_bot?start=ref_REF-DEMO",
    "bot_username": "test_ai_bot",
    "start_param": "ref_REF-DEMO",
}

PACKAGES = {
    "items": [
        {"code": "starter", "title": "Starter", "description": "500 tokens", "tokens": 500, "stars": 250, "is_subscription": False, "subscription_days": 0},
        {"code": "basic", "title": "Basic", "description": "1,200 tokens", "tokens": 1200, "stars": 500, "is_subscription": False, "subscription_days": 0},
        {"code": "premium", "title": "Premium", "description": "2,000 tokens", "tokens": 2000, "stars": 750, "is_subscription": False, "subscription_days": 0},
        {"code": "pro_monthly", "title": "Pro Monthly", "description": "2,000 tokens every 30 days", "tokens": 2000, "stars": 500, "is_subscription": True, "subscription_days": 30},
    ]
}


class Handler(BaseHTTPRequestHandler):
    def _send(self, body: dict, status: int = 200) -> None:
        payload = json.dumps(body).encode("utf-8")
        self.send_response(status)
        self.send_header("content-type", "application/json")
        self.send_header("content-length", str(len(payload)))
        self.send_header("access-control-allow-origin", "*")
        self.end_headers()
        self.wfile.write(payload)

    def do_GET(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        if parsed.path == "/api/v1/user/balance":
            self._send(BALANCE)
            return
        if parsed.path == "/api/v1/user/referral":
            self._send(REFERRAL)
            return
        if parsed.path == "/api/v1/payment/packages":
            self._send(PACKAGES)
            return
        if parsed.path.startswith("/api/v1/payment/status/"):
            invoice_id = parsed.path.rsplit("/", 1)[-1]
            self._send({
                "invoice_id": invoice_id,
                "status": "completed",
                "package": "starter",
                "tokens_credited": 500,
                "stars_amount": 250,
                "transaction_id": 99,
                "created_at": "2026-05-22T06:00:00Z",
                "completed_at": "2026-05-22T06:00:05Z",
                "telegram_payment_charge_id": "ch_demo",
            })
            return
        if parsed.path == "/api/v1/user/transactions":
            q = parse_qs(parsed.query)
            tx_type = (q.get("type") or [None])[0]
            items = TRANSACTIONS
            if tx_type:
                items = [t for t in items if t["transaction_type"] == tx_type]
            self._send({"items": items, "total": len(items), "page": 1, "limit": 10, "has_more": False})
            return
        self._send({"detail": "not found"}, status=404)

    def do_POST(self) -> None:  # noqa: N802
        length = int(self.headers.get("content-length") or 0)
        _body = self.rfile.read(length)
        parsed = urlparse(self.path)
        if parsed.path == "/api/v1/payment/create-invoice":
            self._send({
                "invoice_id": "inv_demo",
                "stars_amount": 250,
                "tokens_amount": 500,
                "telegram_invoice_link": "https://t.me/$demo_invoice",
                "transaction_id": 99,
                "is_subscription": False,
            })
            return
        self._send({"detail": "not found"}, status=404)

    def log_message(self, fmt: str, *args) -> None:  # silence
        return


if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8788
    print(f"mock backend on :{port}")
    HTTPServer(("127.0.0.1", port), Handler).serve_forever()
