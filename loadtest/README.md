# Load testing

[`k6`](https://k6.io) scenarios for the Telegram AI Agent backend.
See [`docs/PERFORMANCE.md`](../docs/PERFORMANCE.md) for SLOs, capacity
numbers and how to run these against staging.

## Layout

```
loadtest/
├── README.md              # this file
├── balance_read.js        # GET /api/v1/user/balance — read SLO check
├── mixed_rw.js            # read + spend mix matching production traffic
└── results/               # archived JSON summaries (gitignored)
```

## Running

```sh
# Pure read smoke; should sit well under the p95 < 500 ms read SLO.
k6 run loadtest/balance_read.js --vus 100 --duration 5m

# Mixed read/write — exercises TokenService.spend and the row-lock path.
BASE_URL=https://staging.api.example.com \
  AUTH_TOKEN=$STAGING_TOKEN \
  k6 run loadtest/mixed_rw.js --vus 200 --duration 10m
```

Both scripts honour `BASE_URL` (default `http://localhost:8000`) and
`AUTH_TOKEN` (a Telegram WebApp `initData` string or a JWT admin token,
depending on the scenario).

## Archiving runs

The CI workflow uploads the JSON summary as an artifact; for ad-hoc
runs persist the result under `loadtest/results/` so quarterly capacity
planning can replot the trend:

```sh
k6 run loadtest/balance_read.js \
  --summary-export "loadtest/results/$(date +%Y%m%d)-balance-read.json"
```
