// k6 scenario: 80/20 read/write mix matching production traffic shape.
// Validates the write SLO (p95 < 2 s) under realistic contention on
// the user-row lock used by TokenService.spend.

import http from "k6/http";
import { check, sleep } from "k6";
import { Trend } from "k6/metrics";

const BASE_URL = __ENV.BASE_URL || "http://localhost:8000";
const INIT_DATA = __ENV.AUTH_TOKEN || "";

const readLatency = new Trend("read_latency_ms");
const writeLatency = new Trend("write_latency_ms");

export const options = {
  vus: Number(__ENV.K6_VUS || 200),
  duration: __ENV.K6_DURATION || "10m",
  thresholds: {
    "http_req_duration{op:read}": ["p(95)<500"],
    "http_req_duration{op:write}": ["p(95)<2000"],
    http_req_failed: ["rate<0.005"],
  },
};

const headers = {
  "X-Telegram-Init-Data": INIT_DATA,
  Accept: "application/json",
  "Content-Type": "application/json",
};

export default function () {
  const roll = Math.random();
  if (roll < 0.8) {
    const res = http.get(`${BASE_URL}/api/v1/user/balance`, {
      headers,
      tags: { op: "read" },
    });
    readLatency.add(res.timings.duration);
    check(res, { "read 200": (r) => r.status === 200 });
  } else {
    // Daily-bonus claim is the most realistic cheap "write" we can
    // drive from a load generator without touching paid APIs. It
    // exercises the same row-lock + Redis invalidation path as a
    // spend without spending real LLM credits.
    const res = http.post(
      `${BASE_URL}/api/v1/user/daily-bonus`,
      "{}",
      { headers, tags: { op: "write" } },
    );
    writeLatency.add(res.timings.duration);
    // 200 (claimed) and 409 (already claimed today) are both healthy.
    check(res, {
      "write status ok": (r) => r.status === 200 || r.status === 409,
    });
  }
  sleep(Math.random() * 2);
}
