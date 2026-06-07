# Database Schema

PostgreSQL 15+. Все идентификаторы — `BIGSERIAL`. Используется `timestamptz`.

## Tables

### users
```sql
CREATE TABLE users (
    id                      BIGSERIAL PRIMARY KEY,
    telegram_id             BIGINT UNIQUE NOT NULL,
    username                VARCHAR(255),
    first_name              VARCHAR(255),
    last_name               VARCHAR(255),
    language_code           VARCHAR(10) DEFAULT 'ru',

    token_balance           INTEGER NOT NULL DEFAULT 0,
    total_tokens_purchased  INTEGER NOT NULL DEFAULT 0,
    total_tokens_spent      INTEGER NOT NULL DEFAULT 0,

    is_premium              BOOLEAN NOT NULL DEFAULT FALSE,
    premium_expires_at      TIMESTAMPTZ,

    created_at              TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    last_active_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    total_requests          INTEGER NOT NULL DEFAULT 0,

    referred_by             BIGINT REFERENCES users(id),
    referral_code           VARCHAR(50) UNIQUE NOT NULL,

    is_banned               BOOLEAN NOT NULL DEFAULT FALSE,
    ban_reason              TEXT,
    banned_until            TIMESTAMPTZ
);

CREATE INDEX idx_users_telegram_id ON users(telegram_id);
CREATE INDEX idx_users_premium     ON users(is_premium) WHERE is_premium = TRUE;
CREATE INDEX idx_users_referral    ON users(referral_code);
```

### transactions
```sql
CREATE TABLE transactions (
    id                  BIGSERIAL PRIMARY KEY,
    user_id             BIGINT NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
    transaction_type    VARCHAR(50) NOT NULL CHECK (transaction_type IN ('purchase','spend','bonus','refund','manual_bonus')),

    tokens_amount       INTEGER NOT NULL,
    stars_amount        INTEGER,
    usd_amount          DECIMAL(10,2),

    package_name        VARCHAR(100),
    discount_percent    INTEGER DEFAULT 0,

    payment_id          VARCHAR(255),
    payment_status      VARCHAR(50) DEFAULT 'pending',
    payment_method      VARCHAR(50),

    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    completed_at        TIMESTAMPTZ
);

CREATE INDEX idx_tx_user_id ON transactions(user_id);
CREATE INDEX idx_tx_type    ON transactions(transaction_type);
CREATE INDEX idx_tx_created ON transactions(created_at DESC);
```

### token_usage_logs
```sql
CREATE TABLE token_usage_logs (
    id                  BIGSERIAL PRIMARY KEY,
    user_id             BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    service_type        VARCHAR(100) NOT NULL,
    tokens_consumed     INTEGER NOT NULL,

    request_params      JSONB,
    response_status     VARCHAR(50),
    processing_time_ms  INTEGER,

    composio_tool       VARCHAR(255),
    mcp_server          VARCHAR(255),

    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
) PARTITION BY RANGE (created_at);

CREATE INDEX idx_usage_user_id ON token_usage_logs(user_id);
CREATE INDEX idx_usage_service ON token_usage_logs(service_type);
CREATE INDEX idx_usage_created ON token_usage_logs(created_at DESC);
```

### admin_settings
```sql
CREATE TABLE admin_settings (
    id              SERIAL PRIMARY KEY,
    setting_key     VARCHAR(100) UNIQUE NOT NULL,
    setting_value   JSONB NOT NULL,
    updated_by      BIGINT,
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
```

### daily_analytics
```sql
CREATE TABLE daily_analytics (
    date                    DATE PRIMARY KEY,
    total_users             INTEGER NOT NULL DEFAULT 0,
    new_users               INTEGER NOT NULL DEFAULT 0,
    active_users            INTEGER NOT NULL DEFAULT 0,
    premium_users           INTEGER NOT NULL DEFAULT 0,

    total_tokens_sold       INTEGER NOT NULL DEFAULT 0,
    total_stars_revenue     INTEGER NOT NULL DEFAULT 0,
    total_usd_revenue       DECIMAL(12,2) NOT NULL DEFAULT 0,

    total_requests          INTEGER NOT NULL DEFAULT 0,
    image_generations       INTEGER NOT NULL DEFAULT 0,
    video_generations       INTEGER NOT NULL DEFAULT 0,
    text_queries            INTEGER NOT NULL DEFAULT 0,

    avg_tokens_per_user     DECIMAL(10,2),
    conversion_rate         DECIMAL(5,2),

    created_at              TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
```

### daily_bonus_claims
```sql
CREATE TABLE daily_bonus_claims (
    id              BIGSERIAL PRIMARY KEY,
    user_id         BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    claim_date      DATE NOT NULL,                       -- UTC calendar day
    streak_day      INTEGER NOT NULL,                    -- 1-indexed position in ladder
    amount          INTEGER NOT NULL,                    -- tokens credited
    transaction_id  BIGINT REFERENCES transactions(id),  -- credit row (NULL-able for back-fills)
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    CONSTRAINT uq_daily_bonus_user_date UNIQUE (user_id, claim_date)
);

CREATE INDEX ix_daily_bonus_user_id        ON daily_bonus_claims(user_id);
CREATE INDEX ix_daily_bonus_user_date_desc ON daily_bonus_claims(user_id, claim_date);
```

One row per successful claim. The `UNIQUE(user_id, claim_date)` constraint is the second layer of the daily-bonus idempotency stack (see `docs/TOKEN_ECONOMY.md > Daily Bonus & Streak`) — racing requests that pass the service-level guard collide here as an `IntegrityError`, which the service converts into `AlreadyClaimedError`. Reading the user's most recent row is enough to recover the active streak, so the service never re-scans the ledger to derive the next reward.

### account_deletion_requests
```sql
CREATE TABLE account_deletion_requests (
    id              BIGSERIAL PRIMARY KEY,
    user_id         BIGINT NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
    status          VARCHAR(32) NOT NULL DEFAULT 'pending'
                    CHECK (status IN ('pending','cancelled','completed','failed')),

    requested_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    scheduled_for   TIMESTAMPTZ NOT NULL,
    cancelled_at    TIMESTAMPTZ,
    completed_at    TIMESTAMPTZ,
    failed_at       TIMESTAMPTZ,

    requested_via   VARCHAR(32),
    reason          TEXT,
    failure_reason  TEXT
);

CREATE INDEX ix_account_deletion_pending
    ON account_deletion_requests(scheduled_for)
    WHERE status = 'pending';

CREATE UNIQUE INDEX uq_account_deletion_active
    ON account_deletion_requests(user_id)
    WHERE status = 'pending';
```

The worker processes only `pending` rows. Failed worker attempts are marked
with `status = 'failed'`, `failed_at`, and `failure_reason`, while the original
user-supplied `reason` is preserved for audit context.

### subscriptions
```sql
CREATE TABLE subscriptions (
    id                  BIGSERIAL PRIMARY KEY,
    user_id             BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    plan_code           VARCHAR(50) NOT NULL,
    starts_at           TIMESTAMPTZ NOT NULL,
    expires_at          TIMESTAMPTZ NOT NULL,
    auto_renew          BOOLEAN NOT NULL DEFAULT TRUE,
    last_transaction_id BIGINT REFERENCES transactions(id),
    status              VARCHAR(50) NOT NULL DEFAULT 'active'
);
CREATE INDEX idx_sub_user ON subscriptions(user_id);
```

## Migrations

Используем Alembic. Каждое изменение схемы — отдельная миграция в `backend/alembic/versions/`.

## Invariants

- `users.token_balance >= 0` (constraint в коде, не в БД, чтобы возвращать понятную ошибку).
- Каждая запись в `token_usage_logs` сопровождается транзакцией типа `spend`.
- Покупка: одна транзакция `purchase` ↔ одно `successful_payment` от Telegram.
- Daily bonus: одна строка `daily_bonus_claims(user_id, claim_date)` ↔ одна транзакция `bonus` с `payment_id = "daily_bonus:user:<id>:date:<YYYY-MM-DD>"`.
