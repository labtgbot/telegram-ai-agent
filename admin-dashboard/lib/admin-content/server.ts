import "server-only";

import { createServerApiClient } from "@/lib/api/server";
import type {
  AuditLogListResponse,
  ContentHistoryFilters,
  FaqItem,
  FaqItemListFilters,
  FaqItemListResponse,
  PromptTemplate,
  PromptTemplateListFilters,
  PromptTemplateListResponse,
  WelcomeMessage,
  WelcomeMessageListFilters,
  WelcomeMessageListResponse,
} from "@/lib/admin-content/types";

function listQuery(filters: PromptTemplateListFilters | FaqItemListFilters): Record<string, string | number | boolean> {
  const query: Record<string, string | number | boolean> = {
    page: filters.page ?? 1,
    limit: filters.limit ?? 25,
  };
  if (filters.search) query.search = filters.search;
  if (filters.category) query.category = filters.category;
  if (filters.locale) query.locale = filters.locale;
  if (filters.is_active !== undefined) query.is_active = filters.is_active;
  return query;
}

export async function fetchPromptTemplates(
  filters: PromptTemplateListFilters = {},
): Promise<PromptTemplateListResponse> {
  const api = createServerApiClient();
  return api.get<PromptTemplateListResponse>("/admin/content/prompt-templates", {
    query: listQuery(filters),
  });
}

export async function fetchPromptTemplate(id: number): Promise<PromptTemplate> {
  const api = createServerApiClient();
  return api.get<PromptTemplate>(`/admin/content/prompt-templates/${id}`);
}

export async function fetchFaqItems(
  filters: FaqItemListFilters = {},
): Promise<FaqItemListResponse> {
  const api = createServerApiClient();
  return api.get<FaqItemListResponse>("/admin/content/faqs", { query: listQuery(filters) });
}

export async function fetchFaqItem(id: number): Promise<FaqItem> {
  const api = createServerApiClient();
  return api.get<FaqItem>(`/admin/content/faqs/${id}`);
}

export async function fetchWelcomeMessages(
  filters: WelcomeMessageListFilters = {},
): Promise<WelcomeMessageListResponse> {
  const api = createServerApiClient();
  const query: Record<string, string | number | boolean> = {
    page: filters.page ?? 1,
    limit: filters.limit ?? 25,
  };
  if (filters.locale) query.locale = filters.locale;
  if (filters.is_active !== undefined) query.is_active = filters.is_active;
  return api.get<WelcomeMessageListResponse>("/admin/content/welcomes", { query });
}

export async function fetchWelcomeMessage(id: number): Promise<WelcomeMessage> {
  const api = createServerApiClient();
  return api.get<WelcomeMessage>(`/admin/content/welcomes/${id}`);
}

export async function fetchContentHistory(
  filters: ContentHistoryFilters = {},
): Promise<AuditLogListResponse> {
  const api = createServerApiClient();
  const query: Record<string, string | number | boolean> = {
    page: filters.page ?? 1,
    limit: filters.limit ?? 25,
  };
  if (filters.entity) query.entity = filters.entity;
  if (filters.entity_id !== undefined) query.entity_id = filters.entity_id;
  return api.get<AuditLogListResponse>("/admin/content/history", { query });
}
