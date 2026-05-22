"use client";

import { apiClient } from "@/lib/api/browser";
import type {
  AuditLogListResponse,
  ContentHistoryFilters,
  FaqItem,
  FaqItemListFilters,
  FaqItemListResponse,
  FaqItemPayload,
  PromptTemplate,
  PromptTemplateListFilters,
  PromptTemplateListResponse,
  PromptTemplatePayload,
  WelcomeMessage,
  WelcomeMessageListFilters,
  WelcomeMessageListResponse,
  WelcomeMessagePayload,
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

// ---------------------------------------------------------------- prompt templates

export function getPromptTemplates(
  filters: PromptTemplateListFilters = {},
): Promise<PromptTemplateListResponse> {
  return apiClient().get<PromptTemplateListResponse>("/admin/content/prompt-templates", {
    query: listQuery(filters),
  });
}

export function postPromptTemplate(payload: PromptTemplatePayload): Promise<PromptTemplate> {
  return apiClient().post<PromptTemplate>("/admin/content/prompt-templates", payload);
}

export function putPromptTemplate(
  id: number,
  payload: PromptTemplatePayload,
): Promise<PromptTemplate> {
  return apiClient().request<PromptTemplate>(`/admin/content/prompt-templates/${id}`, {
    method: "PUT",
    body: payload,
  });
}

export function deletePromptTemplate(id: number): Promise<void> {
  return apiClient().delete<void>(`/admin/content/prompt-templates/${id}`);
}

// ----------------------------------------------------------------------- FAQ items

export function getFaqItems(filters: FaqItemListFilters = {}): Promise<FaqItemListResponse> {
  return apiClient().get<FaqItemListResponse>("/admin/content/faqs", {
    query: listQuery(filters),
  });
}

export function postFaqItem(payload: FaqItemPayload): Promise<FaqItem> {
  return apiClient().post<FaqItem>("/admin/content/faqs", payload);
}

export function putFaqItem(id: number, payload: FaqItemPayload): Promise<FaqItem> {
  return apiClient().request<FaqItem>(`/admin/content/faqs/${id}`, {
    method: "PUT",
    body: payload,
  });
}

export function deleteFaqItem(id: number): Promise<void> {
  return apiClient().delete<void>(`/admin/content/faqs/${id}`);
}

// ---------------------------------------------------------------- welcome messages

export function getWelcomeMessages(
  filters: WelcomeMessageListFilters = {},
): Promise<WelcomeMessageListResponse> {
  const query: Record<string, string | number | boolean> = {
    page: filters.page ?? 1,
    limit: filters.limit ?? 25,
  };
  if (filters.locale) query.locale = filters.locale;
  if (filters.is_active !== undefined) query.is_active = filters.is_active;
  return apiClient().get<WelcomeMessageListResponse>("/admin/content/welcomes", { query });
}

export function postWelcomeMessage(payload: WelcomeMessagePayload): Promise<WelcomeMessage> {
  return apiClient().post<WelcomeMessage>("/admin/content/welcomes", payload);
}

export function putWelcomeMessage(
  id: number,
  payload: WelcomeMessagePayload,
): Promise<WelcomeMessage> {
  return apiClient().request<WelcomeMessage>(`/admin/content/welcomes/${id}`, {
    method: "PUT",
    body: payload,
  });
}

export function deleteWelcomeMessage(id: number): Promise<void> {
  return apiClient().delete<void>(`/admin/content/welcomes/${id}`);
}

// ------------------------------------------------------------------------ history

export function getContentHistory(
  filters: ContentHistoryFilters = {},
): Promise<AuditLogListResponse> {
  const query: Record<string, string | number | boolean> = {
    page: filters.page ?? 1,
    limit: filters.limit ?? 25,
  };
  if (filters.entity) query.entity = filters.entity;
  if (filters.entity_id !== undefined) query.entity_id = filters.entity_id;
  return apiClient().get<AuditLogListResponse>("/admin/content/history", { query });
}
