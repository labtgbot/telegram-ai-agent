// k6 scenario: production launch gate — 100 concurrent users for 10 min,
// covering the read + write mix the public bot will see in the first
// minutes after the announcement.
//
// Defends the same SLOs as the smaller dev scenarios (read p95 < 500 ms,
// write p95 < 2 s, error rate < 0.5 %), plus exercises the
// /payment/create-invoice path which the Stars launch depends on but
// which the dev mix avoids because it spends LLM credits.
//
// Run during a maintenance window with the on-call rotation watching the
// SLO Grafana dashboard. Archive the JSON summary so the launch entry in
// docs/CHANGELOG.md can cite the run.
//
//   BASE_URL=https://api.telegram-ai-agent.example.com \
//   AUTH_TOKEN="$BETA_INIT_DATA" \
//     k6 run loadtest/production_100u.js \
//       --summary-export "loadtest/results/$(date +%Y%m%d)-launch-100u.json"
//
// See docs/LAUNCH_CHECKLIST.md §5 for the exit gates and rollback steps.

import http from "k6/http";
import { check, sleep } from "k6";
import { Trend } from "k6/metrics";

const BASE_URL = __ENV.BASE_URL || "http://localhost:8000";
const INIT_DATA = __ENV.AUTH_TOKEN || "";

const readLatency = new Trend("read_latency_ms");
const writeLatency = new Trend("write_latency_ms");
const invoiceLatency = new Trend("invoice_latency_ms");

// 100 VUs for 10 min with a 30s ramp-up so we never thunder-herd the
// connection pool on startup. The ramp also gives Prometheus the
// observability window it needs to fire alerts before we declare
// success.
export const options = {
  scenarios: {
    launch_mix: {
      executor: "ramping-vus",
      startVUs: 0,
      stages: [
        { duration: "30s", target: 100 },
        { duration: "9m", target: 100 },
        { duration: "30s", target: 0 },
      ],
      gracefulRampDown: "30s",
      tags: { scenario: "launch_100u" },
    },
  },
  thresholds: {
    // Same SLOs as docs/PERFORMANCE.md, scoped per operation so a
    // regression in /balance does not hide behind a healthy invoice
    // path (or vice versa).
    "http_req_duration{op:read}": ["p(95)<500", "p(99)<1000"],
    "http_req_duration{op:write}": ["p(95)<2000"],
    "http_req_duration{op:invoice}": ["p(95)<2000"],
    http_req_failed: ["rate<0.005"],
    read_latency_ms: ["p(95)<500"],
    write_latency_ms: ["p(95)<2000"],
    invoice_latency_ms: ["p(95)<2000"],
  },
};

const headers = {
  "X-Telegram-Init-Data": INIT_DATA,
  Accept: "application/json",
  "Content-Type": "application/json",
};

// Traffic mix calibrated against the dev scenarios — 70 % reads
// (balance is the hottest endpoint), 20 % cheap writes (daily-bonus
// claim exercises the row-lock + Redis invalidation path), 10 %
// invoice creates (Stars launch surface).
export default function () {
  const roll = Math.random();
  if (roll < 0.7) {
    const res = http.get(`${BASE_URL}/api/v1/user/balance`, {
      headers,
      tags: { op: "read" },
    });
    readLatency.add(res.timings.duration);
    check(res, { "balance 200": (r) => r.status === 200 });
  } else if (roll < 0.9) {
    const res = http.post(`${BASE_URL}/api/v1/user/daily-bonus`, "{}", {
      headers,
      tags: { op: "write" },
    });
    writeLatency.add(res.timings.duration);
    // 200 (claimed) and 409 (already claimed today) are both healthy.
    check(res, {
      "daily-bonus status ok": (r) => r.status === 200 || r.status === 409,
    });
  } else {
    // Stars invoice creation — must succeed during the launch
    // window since this is the path the public announcement points
    // at. The endpoint is idempotent on pending state, so a retry on
    // failure does not leak phantom transactions.
    const res = http.post(
      `${BASE_URL}/api/v1/payment/create-invoice`,
      JSON.stringify({ package: "starter" }),
      { headers, tags: { op: "invoice" } },
    );
    invoiceLatency.add(res.timings.duration);
    check(res, {
      "invoice 200": (r) => r.status === 200,
      "invoice has link": (r) => {
        try {
          return typeof r.json("telegram_invoice_link") === "string";
        } catch {
          return false;
        }
      },
    });
  }
  // Random think-time keeps the request distribution out of lock-step
  // — without this every VU would fire at the top of each second and
  // the read SLO would look better than reality.
  sleep(0.5 + Math.random() * 1.5);
}
