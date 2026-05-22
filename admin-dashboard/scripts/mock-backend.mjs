#!/usr/bin/env node
// Tiny mock backend used to render the Users page for screenshots.
// Listens on http://localhost:8000 and returns deterministic fake data
// for the admin endpoints exercised by the dashboard.
import { createServer } from "node:http";

const USERS = [
  {
    id: 1, telegram_id: 1001, username: "alice", first_name: "Alice", last_name: "Andersen",
    language_code: "en", role: "user", is_premium: true, is_banned: false,
    ban_reason: null, banned_until: null,
    token_balance: 4250, total_tokens_purchased: 12000, total_tokens_spent: 7750,
    total_requests: 142, referral_code: "AU-1001", referred_by: null,
    created_at: "2026-04-02T10:14:00Z", last_active_at: "2026-05-16T07:11:00Z",
    last_login_at: "2026-05-16T07:10:00Z",
  },
  {
    id: 2, telegram_id: 1002, username: "bob_dev", first_name: "Bob", last_name: null,
    language_code: "en", role: "user", is_premium: false, is_banned: false,
    ban_reason: null, banned_until: null,
    token_balance: 980, total_tokens_purchased: 2000, total_tokens_spent: 1020,
    total_requests: 47, referral_code: "AU-1002", referred_by: 1,
    created_at: "2026-04-18T14:32:00Z", last_active_at: "2026-05-15T19:02:00Z",
    last_login_at: "2026-05-15T18:59:00Z",
  },
  {
    id: 3, telegram_id: 1003, username: "carol", first_name: "Carol", last_name: "C.",
    language_code: "pt", role: "user", is_premium: false, is_banned: true,
    ban_reason: "spam", banned_until: null,
    token_balance: 0, total_tokens_purchased: 500, total_tokens_spent: 500,
    total_requests: 21, referral_code: "AU-1003", referred_by: null,
    created_at: "2026-03-22T09:00:00Z", last_active_at: "2026-04-30T12:45:00Z",
    last_login_at: "2026-04-29T22:01:00Z",
  },
  {
    id: 4, telegram_id: 1004, username: "dmitry", first_name: "Dmitry", last_name: "V.",
    language_code: "ru", role: "support_admin", is_premium: true, is_banned: false,
    ban_reason: null, banned_until: null,
    token_balance: 8000, total_tokens_purchased: 8000, total_tokens_spent: 0,
    total_requests: 3, referral_code: "AU-1004", referred_by: null,
    created_at: "2026-02-11T08:00:00Z", last_active_at: "2026-05-16T06:55:00Z",
    last_login_at: "2026-05-16T06:50:00Z",
  },
  {
    id: 5, telegram_id: 1005, username: "elena", first_name: "Elena", last_name: "K.",
    language_code: "ru", role: "user", is_premium: false, is_banned: false,
    ban_reason: null, banned_until: null,
    token_balance: 320, total_tokens_purchased: 1000, total_tokens_spent: 680,
    total_requests: 28, referral_code: "AU-1005", referred_by: 2,
    created_at: "2026-05-01T11:20:00Z", last_active_at: "2026-05-14T17:10:00Z",
    last_login_at: "2026-05-14T17:08:00Z",
  },
];

const STATS = {
  user: USERS[0],
  transactions_total: 6,
  recent_transactions: [
    { id: 901, transaction_type: "purchase", tokens_amount: 4000, stars_amount: 5500,
      package_name: "Pro pack", payment_status: "completed",
      created_at: "2026-05-15T18:42:00Z", completed_at: "2026-05-15T18:42:00Z" },
    { id: 902, transaction_type: "spend", tokens_amount: -120, stars_amount: null,
      package_name: null, payment_status: null,
      created_at: "2026-05-15T18:31:00Z", completed_at: "2026-05-15T18:31:00Z" },
    { id: 903, transaction_type: "spend", tokens_amount: -240, stars_amount: null,
      package_name: null, payment_status: null,
      created_at: "2026-05-15T17:05:00Z", completed_at: "2026-05-15T17:05:00Z" },
    { id: 904, transaction_type: "bonus", tokens_amount: 50, stars_amount: null,
      package_name: null, payment_status: null,
      created_at: "2026-05-15T08:00:00Z", completed_at: "2026-05-15T08:00:00Z" },
    { id: 905, transaction_type: "spend", tokens_amount: -30, stars_amount: null,
      package_name: null, payment_status: null,
      created_at: "2026-05-14T22:14:00Z", completed_at: "2026-05-14T22:14:00Z" },
  ],
  services_usage: [
    { service_type: "image_generation", requests: 84, tokens_spent: 5040 },
    { service_type: "video_generation", requests: 12, tokens_spent: 2160 },
    { service_type: "text_generation", requests: 46, tokens_spent: 550 },
  ],
  referrals_count: 3,
  recent_referrals: [
    { user_id: 2, telegram_id: 1002, username: "bob_dev", first_name: "Bob",
      is_premium: false, created_at: "2026-04-18T14:32:00Z" },
    { user_id: 5, telegram_id: 1005, username: "elena", first_name: "Elena",
      is_premium: false, created_at: "2026-05-01T11:20:00Z" },
  ],
};

const CORS = {
  "Access-Control-Allow-Origin": "http://localhost:3097",
  "Access-Control-Allow-Credentials": "true",
  "Access-Control-Allow-Headers": "Authorization, Content-Type",
  "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
};

function json(res, status, body) {
  res.writeHead(status, { "Content-Type": "application/json", ...CORS });
  res.end(JSON.stringify(body));
}

createServer((req, res) => {
  if (req.method === "OPTIONS") {
    res.writeHead(204, CORS);
    return res.end();
  }
  const url = new URL(req.url, "http://localhost:8000");
  if (url.pathname === "/api/v1/admin/users") {
    return json(res, 200, {
      items: USERS, total: USERS.length, page: 1, limit: 25, has_more: false,
    });
  }
  if (url.pathname.match(/^\/api\/v1\/admin\/users\/\d+\/stats$/)) {
    return json(res, 200, STATS);
  }
  if (url.pathname === "/api/v1/admin/users/export.csv") {
    res.writeHead(200, { "Content-Type": "text/csv; charset=utf-8" });
    return res.end("id,telegram_id,username\n1,1001,alice\n");
  }
  return json(res, 404, { detail: `not mocked: ${url.pathname}` });
}).listen(8000, () => process.stdout.write("mock backend on :8000\n"));
