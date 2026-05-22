/**
 * Type contracts for the admin Content section (issue #29).
 *
 * Mirrors the FastAPI response models in
 * `backend/app/api/v1/admin_content.py` so the server fetcher, the
 * browser fetcher, and the editors share a single source of truth.
 * Field names stay snake_case to match the wire format.
 */

export const CONTENT_ENTITIES = ["prompt_template", "faq_item", "welcome_message"] as const;
export type ContentEntity = (typeof CONTENT_ENTITIES)[number];

export interface AuditLogEntry {
  id: number;
  admin_id: number;
  target_user_id: number | null;
  action: string;
  payload: Record<string, unknown> | null;
  ip_address: string | null;
  user_agent: string | null;
  created_at: string;
}

export interface AuditLogListResponse {
  items: AuditLogEntry[];
  total: number;
  page: number;
  limit: number;
  has_more: boolean;
}

// -------------------------------------------------------------- prompt templates

export interface PromptTemplate {
  id: number;
  code: string;
  title: string;
  body: string;
  category: string | null;
  locale: string;
  sort_order: number;
  is_active: boolean;
  created_by: number | null;
  updated_by: number | null;
  created_at: string;
  updated_at: string;
}

export interface PromptTemplatePayload {
  code: string;
  title: string;
  body: string;
  category?: string | null;
  locale?: string;
  sort_order?: number;
  is_active?: boolean;
}

export interface PromptTemplateListResponse {
  items: PromptTemplate[];
  total: number;
  page: number;
  limit: number;
  has_more: boolean;
}

export interface PromptTemplateListFilters {
  search?: string;
  category?: string;
  locale?: string;
  is_active?: boolean;
  page?: number;
  limit?: number;
}

// ------------------------------------------------------------------- FAQ items

export interface FaqItem {
  id: number;
  question: string;
  answer: string;
  category: string | null;
  locale: string;
  sort_order: number;
  is_active: boolean;
  created_by: number | null;
  updated_by: number | null;
  created_at: string;
  updated_at: string;
}

export interface FaqItemPayload {
  question: string;
  answer: string;
  category?: string | null;
  locale?: string;
  sort_order?: number;
  is_active?: boolean;
}

export interface FaqItemListResponse {
  items: FaqItem[];
  total: number;
  page: number;
  limit: number;
  has_more: boolean;
}

export interface FaqItemListFilters {
  search?: string;
  category?: string;
  locale?: string;
  is_active?: boolean;
  page?: number;
  limit?: number;
}

// ----------------------------------------------------------- welcome messages

export interface WelcomeMessage {
  id: number;
  name: string;
  body: string;
  locale: string;
  is_active: boolean;
  created_by: number | null;
  updated_by: number | null;
  created_at: string;
  updated_at: string;
}

export interface WelcomeMessagePayload {
  name: string;
  body: string;
  locale?: string;
  is_active?: boolean;
}

export interface WelcomeMessageListResponse {
  items: WelcomeMessage[];
  total: number;
  page: number;
  limit: number;
  has_more: boolean;
}

export interface WelcomeMessageListFilters {
  locale?: string;
  is_active?: boolean;
  page?: number;
  limit?: number;
}

export interface ContentHistoryFilters {
  entity?: ContentEntity;
  entity_id?: number;
  page?: number;
  limit?: number;
}
