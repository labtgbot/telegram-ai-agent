// k6 scenario: hammer GET /api/v1/user/balance to validate the
// read-side SLO (p95 < 500 ms) from issue #36. Defaults match the
// numbers tabled in docs/PERFORMANCE.md so a CI run alerts on
// regression without needing extra flags.

import http from "k6/http";
import { check, sleep } from "k6";
import { Trend } from "k6/metrics";

const BASE_URL = __ENV.BASE_URL || "http://localhost:8000";
const INIT_DATA = __ENV.AUTH_TOKEN || "";

const balanceLatency = new Trend("balance_latency_ms");

export const options = {
  vus: Number(__ENV.K6_VUS || 100),
  duration: __ENV.K6_DURATION || "5m",
  thresholds: {
    // p95 < 500 ms — the read SLO. p99 < 1 s leaves headroom for the
    // tail without paging on every garbage-collection blip.
    http_req_duration: ["p(95)<500", "p(99)<1000"],
    http_req_failed: ["rate<0.001"],
    balance_latency_ms: ["p(95)<500"],
  },
};

export default function () {
  const res = http.get(`${BASE_URL}/api/v1/user/balance`, {
    headers: {
      "X-Telegram-Init-Data": INIT_DATA,
      Accept: "application/json",
    },
    tags: { endpoint: "balance" },
  });
  balanceLatency.add(res.timings.duration);
  check(res, {
    "status is 200": (r) => r.status === 200,
    "body has token_balance": (r) => {
      try {
        return typeof r.json("token_balance") === "number";
      } catch {
        return false;
      }
    },
  });
  sleep(1);
}
