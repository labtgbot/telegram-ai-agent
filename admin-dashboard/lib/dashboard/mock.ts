import type {
  ActivityPoint,
  DashboardCharts,
  DashboardKpis,
  DashboardSnapshot,
  KpiTotal,
  NewUserRow,
  PeriodKey,
  RevenuePoint,
  ServiceUsageSlice,
  TransactionRow,
  TransactionType,
} from "@/lib/dashboard/types";

/**
 * Deterministic pseudo-data for the admin dashboard.
 *
 * The real backend endpoint (`GET /api/v1/admin/dashboard`) lands with the
 * Analytics service (separate ticket).  Until then this module powers the UI
 * so KPIs/charts render and reviewers can verify behavior end-to-end.  The
 * shape matches `DashboardSnapshot`, so swapping the source is a one-liner
 * inside `app/api/admin/dashboard/route.ts`.
 *
 * The generator is deterministic per `(period, day-of-year)` so two requests
 * within the same day return identical data — this lets E2E tests assert
 * specific values without flake while still showing variation across days.
 */

const PERIOD_DAYS: Record<PeriodKey, number> = {
  "1d": 1,
  "7d": 7,
  "30d": 30,
  "90d": 90,
};

const SERVICE_NAMES = ["image", "video", "text"] as const;

const FIRST_NAMES = [
  "Alex",
  "Maria",
  "Ivan",
  "Olga",
  "Dmitry",
  "Anna",
  "Sergey",
  "Tanya",
  "Pavel",
  "Lena",
  "Igor",
  "Polina",
];

const USERNAMES = [
  "neo_42",
  "starlight",
  "max_pwr",
  "octocat",
  "vibes",
  "kira",
  "skywalker",
  "echo",
  "miko",
  "ren",
  "aurora",
  "vlad",
];

const LANG_CODES = ["en", "ru", "es", "de", "tr"] as const;

/** Cheap deterministic 32-bit hash. */
function hash(...parts: Array<string | number>): number {
  let h = 2166136261;
  const input = parts.join("|");
  for (let i = 0; i < input.length; i += 1) {
    h ^= input.charCodeAt(i);
    h = Math.imul(h, 16777619);
  }
  return h >>> 0;
}

function mulberry32(seed: number): () => number {
  let t = seed >>> 0;
  return () => {
    t = (t + 0x6d2b79f5) >>> 0;
    let r = t;
    r = Math.imul(r ^ (r >>> 15), r | 1);
    r ^= r + Math.imul(r ^ (r >>> 7), r | 61);
    return ((r ^ (r >>> 14)) >>> 0) / 4294967296;
  };
}

function dayOfYear(d: Date): number {
  const start = Date.UTC(d.getUTCFullYear(), 0, 0);
  const diff = d.getTime() - start;
  return Math.floor(diff / 86_400_000);
}

function isoDateOnly(d: Date): string {
  const out = d.toISOString();
  return out.slice(0, 10);
}

function startOfUtcDay(d: Date): Date {
  const copy = new Date(d.getTime());
  copy.setUTCHours(0, 0, 0, 0);
  return copy;
}

function pickDelta(rng: () => number, max = 25): number {
  // Centered around zero so half the cards trend up, half trend down.
  const sign = rng() > 0.45 ? 1 : -1;
  const magnitude = Math.round(rng() * max * 10) / 10;
  return sign * magnitude;
}

function kpi(value: number, deltaPct: number): KpiTotal {
  const previous = deltaPct === -100 ? 0 : Math.round(value / (1 + deltaPct / 100));
  return { value, delta_pct: deltaPct, previous };
}

function buildKpis(period: PeriodKey, rng: () => number, totalUsersBase: number): DashboardKpis {
  const days = PERIOD_DAYS[period];
  const totalUsers = totalUsersBase + Math.round(rng() * 200);
  const newUsers = Math.round((50 + rng() * 90) * Math.sqrt(days));
  const activeUsers = Math.round(totalUsers * (0.18 + rng() * 0.07));

  const purchasersPerDay = 18 + rng() * 12;
  const avgPurchaseUsd = 9 + rng() * 4;
  const periodRevenue = Math.round(purchasersPerDay * avgPurchaseUsd * days);
  const mrr = Math.round((purchasersPerDay * avgPurchaseUsd * 30 + 1500) / 100) * 100;
  const stars = Math.round(periodRevenue * (1000 / 13)); // ~13 USD per 1k Stars

  const tokensSold = Math.round(periodRevenue * (1000 / 5)); // ~5 USD per 1k tokens
  const conversion = Math.round(((purchasersPerDay * days) / Math.max(activeUsers, 1)) * 1000) / 10;

  return {
    users: {
      total: kpi(totalUsers, pickDelta(rng, 12)),
      new: kpi(newUsers, pickDelta(rng, 35)),
      active: kpi(activeUsers, pickDelta(rng, 18)),
    },
    revenue: {
      mrr_usd: kpi(mrr, pickDelta(rng, 22)),
      period_usd: kpi(periodRevenue, pickDelta(rng, 28)),
      stars: kpi(stars, pickDelta(rng, 28)),
    },
    tokens: {
      sold: kpi(tokensSold, pickDelta(rng, 30)),
      conversion_pct: kpi(conversion, pickDelta(rng, 15)),
    },
  };
}

function buildRevenue(rng: () => number, anchor: Date): RevenuePoint[] {
  const points: RevenuePoint[] = [];
  const today = startOfUtcDay(anchor);
  for (let i = 29; i >= 0; i -= 1) {
    const day = new Date(today.getTime() - i * 86_400_000);
    const weekday = day.getUTCDay();
    const isWeekend = weekday === 0 || weekday === 6;
    const base = 180 + (isWeekend ? -40 : 0);
    const noise = rng() * 60;
    const trend = (29 - i) * 4;
    points.push({ date: isoDateOnly(day), usd: Math.round(base + trend + noise) });
  }
  return points;
}

function buildActivity(rng: () => number, anchor: Date): ActivityPoint[] {
  const points: ActivityPoint[] = [];
  const today = startOfUtcDay(anchor);
  for (let i = 6; i >= 0; i -= 1) {
    const day = new Date(today.getTime() - i * 86_400_000);
    const active = Math.round(420 + rng() * 220);
    const newCount = Math.round(45 + rng() * 60);
    points.push({ date: isoDateOnly(day), active_users: active, new_users: newCount });
  }
  return points;
}

function buildUsage(rng: () => number, period: PeriodKey): ServiceUsageSlice[] {
  const days = PERIOD_DAYS[period];
  const totals: Record<(typeof SERVICE_NAMES)[number], number> = {
    image: Math.round(2200 * days * (0.85 + rng() * 0.4)),
    video: Math.round(800 * days * (0.85 + rng() * 0.4)),
    text: Math.round(5400 * days * (0.85 + rng() * 0.4)),
  };
  return SERVICE_NAMES.map((service) => ({
    service,
    tokens: totals[service],
    requests: Math.round(totals[service] / (service === "video" ? 90 : service === "image" ? 30 : 8)),
  }));
}

const TX_TYPES: TransactionType[] = ["purchase", "purchase", "purchase", "bonus", "manual_bonus", "refund"];
const PACKAGE_PRICES: Array<{ usd: number; tokens: number; stars: number }> = [
  { usd: 5, tokens: 500, stars: 250 },
  { usd: 10, tokens: 1200, stars: 500 },
  { usd: 15, tokens: 2000, stars: 750 },
];

function buildTransactions(rng: () => number, anchor: Date, count: number): TransactionRow[] {
  const rows: TransactionRow[] = [];
  for (let i = 0; i < count; i += 1) {
    const offsetMinutes = Math.round(rng() * 240) + i * 7;
    const created = new Date(anchor.getTime() - offsetMinutes * 60_000);
    const type = TX_TYPES[Math.floor(rng() * TX_TYPES.length)] as TransactionType;
    const userIndex = Math.floor(rng() * USERNAMES.length);
    const isPurchase = type === "purchase" || type === "refund";
    const pkg = PACKAGE_PRICES[Math.floor(rng() * PACKAGE_PRICES.length)] as (typeof PACKAGE_PRICES)[number];
    const sign = type === "refund" || type === "manual_bonus" ? -1 : 1;
    const tokens = type === "bonus" ? 50 : pkg.tokens * (type === "manual_bonus" ? -1 : 1);
    rows.push({
      id: 100_000 + Math.floor(rng() * 900_000),
      user_id: 1000 + userIndex,
      username: USERNAMES[userIndex] ?? null,
      transaction_type: type,
      tokens_amount: tokens,
      stars_amount: isPurchase ? pkg.stars * sign : null,
      usd_amount: isPurchase ? pkg.usd * sign : null,
      created_at: created.toISOString(),
      payment_status: type === "refund" ? "refunded" : "completed",
    });
  }
  return rows.sort((a, b) => b.created_at.localeCompare(a.created_at));
}

function buildNewUsers(rng: () => number, anchor: Date, count: number): NewUserRow[] {
  const rows: NewUserRow[] = [];
  for (let i = 0; i < count; i += 1) {
    const offsetMinutes = Math.round(rng() * 600) + i * 25;
    const created = new Date(anchor.getTime() - offsetMinutes * 60_000);
    const fnIdx = Math.floor(rng() * FIRST_NAMES.length);
    const unIdx = Math.floor(rng() * USERNAMES.length);
    const langIdx = Math.floor(rng() * LANG_CODES.length);
    rows.push({
      id: 5000 + Math.floor(rng() * 5000),
      telegram_id: 100_000_000 + Math.floor(rng() * 800_000_000),
      username: rng() > 0.2 ? (USERNAMES[unIdx] ?? null) : null,
      first_name: FIRST_NAMES[fnIdx] ?? null,
      language_code: LANG_CODES[langIdx] ?? null,
      created_at: created.toISOString(),
      is_premium: rng() > 0.85,
    });
  }
  return rows.sort((a, b) => b.created_at.localeCompare(a.created_at));
}

export interface BuildOptions {
  /** Override the wall-clock anchor — used by tests for determinism. */
  now?: Date;
  /** Stable seed component, e.g. tenant id. Defaults to a fixed string. */
  seedSalt?: string;
  /** How many rows in each list. */
  transactionCount?: number;
  newUserCount?: number;
}

export function buildDashboardSnapshot(
  period: PeriodKey,
  options: BuildOptions = {},
): DashboardSnapshot {
  const now = options.now ?? new Date();
  const seedSalt = options.seedSalt ?? "telegram-ai-agent";
  const seed = hash(seedSalt, period, dayOfYear(now));
  const rng = mulberry32(seed);

  const charts: DashboardCharts = {
    revenue_30d: buildRevenue(rng, now),
    activity_7d: buildActivity(rng, now),
    usage_by_service: buildUsage(rng, period),
  };

  const kpis = buildKpis(period, rng, 12_400);

  return {
    period,
    generated_at: now.toISOString(),
    kpis,
    charts,
    latest_transactions: buildTransactions(rng, now, options.transactionCount ?? 8),
    new_users: buildNewUsers(rng, now, options.newUserCount ?? 8),
  };
}
