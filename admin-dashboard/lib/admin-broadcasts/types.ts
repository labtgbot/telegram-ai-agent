/**
 * Type contracts for the admin Broadcast section (issue #28).
 *
 * Mirrors the FastAPI response models in
 * `backend/app/api/v1/admin_broadcasts.py` so the server fetcher, the
 * browser fetcher, and the composer share a single source of truth.
 * Keep field names snake_case to match the wire format.
 */

export const BROADCAST_AUDIENCES = ["all", "premium", "free", "inactive_7d", "custom"] as const;

export type BroadcastAudience = (typeof BROADCAST_AUDIENCES)[number];

export const BROADCAST_STATUSES = [
  "draft",
  "scheduled",
  "in_progress",
  "completed",
  "cancelled",
  "failed",
] as const;

export type BroadcastStatus = (typeof BROADCAST_STATUSES)[number];

/** Statuses the API will accept for /broadcasts/{id}/cancel. */
export const CANCELLABLE_STATUSES: ReadonlySet<BroadcastStatus> = new Set([
  "draft",
  "scheduled",
  "in_progress",
]);

export interface BroadcastButtonPayload {
  text: string;
  url?: string | null;
  callback_data?: string | null;
}

export interface BroadcastCreateRequest {
  text: string;
  title?: string | null;
  parse_mode?: string | null;
  media_type?: string | null;
  media_url?: string | null;
  buttons?: BroadcastButtonPayload[];
  audience: BroadcastAudience;
  audience_filter?: Record<string, unknown> | null;
  scheduled_at?: string | null;
}

export interface PreviewAudienceRequest {
  audience: BroadcastAudience;
  audience_filter?: Record<string, unknown> | null;
}

export interface PreviewAudienceResponse {
  audience: BroadcastAudience;
  total: number;
}

export interface BroadcastResponse {
  id: number;
  created_by: number;
  title: string | null;
  text: string;
  parse_mode: string | null;
  media_type: string | null;
  media_url: string | null;
  buttons: BroadcastButtonPayload[] | null;
  audience: BroadcastAudience;
  audience_filter: Record<string, unknown> | null;
  status: BroadcastStatus;
  scheduled_at: string | null;
  started_at: string | null;
  finished_at: string | null;
  cancelled_at: string | null;
  total_recipients: number;
  sent_count: number;
  delivered_count: number;
  failed_count: number;
  skipped_count: number;
  clicks_count: number;
  last_error: string | null;
  created_at: string;
  updated_at: string;
}

export interface BroadcastListResponse {
  items: BroadcastResponse[];
  total: number;
  page: number;
  limit: number;
  has_more: boolean;
}

export interface BroadcastStatsResponse {
  broadcast: BroadcastResponse;
  total_recipients: number;
  pending: number;
  sent: number;
  delivered: number;
  failed: number;
  skipped: number;
  clicks: number;
}
