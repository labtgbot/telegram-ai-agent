/**
 * Chat domain types for the Main Chat Interface (issue #18).
 *
 * Mirrors the relevant backend contracts:
 *
 *   - `POST /api/v1/generate/text` / `text/stream` — text modes
 *     (basic / advanced / autonomous_agent) — see
 *     `backend/app/api/v1/generate.py`.
 *   - `POST /api/v1/generate/image`  — image attachment / result.
 *   - `POST /api/v1/generate/video`  — async video job.
 *   - `POST /api/v1/generate/search` — web search results.
 *   - `POST /api/v1/generate/document` — document upload + Q&A.
 *
 * Mode costs come from `MODE_COST` in the backend and act as the upper
 * bound for the pre-send cost indicator.
 */

/** Text-generation modes supported by the backend `generate/text` endpoint. */
export type AgentMode = "basic" | "advanced" | "autonomous_agent";

/** Token cost per request for each mode (must match backend MODE_COST). */
export const MODE_COST: Record<AgentMode, number> = {
  basic: 1,
  advanced: 5,
  autonomous_agent: 10,
};

export const MODE_LABEL: Record<AgentMode, string> = {
  basic: "Basic",
  advanced: "Advanced",
  autonomous_agent: "Autonomous agent",
};

export const MODE_DESCRIPTION: Record<AgentMode, string> = {
  basic: "Gemini · fastest · 1 token",
  advanced: "Claude · deeper · 5 tokens",
  autonomous_agent: "GPT · tools / planning · 10 tokens",
};

/** Side action buttons available next to the input. */
export type ChatAction = "image" | "video" | "search" | "document";

/** Approximate per-action token cost shown next to action buttons. */
export const ACTION_COST: Record<ChatAction, number> = {
  image: 30,
  video: 100,
  search: 3,
  document: 20,
};

/** Inline attachment kinds rendered inside an assistant message. */
export type AttachmentKind = "image" | "video" | "document" | "search_results";

export interface ChatAttachment {
  id: string;
  kind: AttachmentKind;
  url?: string;
  name?: string;
  mimeType?: string;
  sizeBytes?: number;
  /** Optional textual preview / caption rendered alongside the asset. */
  caption?: string;
  /** Structured payload (e.g. search results array). */
  data?: unknown;
}

/** Conversation turn role. Mirrors backend roles minus internal "summary". */
export type ChatRole = "user" | "assistant" | "system";

/** Lifecycle status of an assistant message during streaming. */
export type ChatMessageStatus = "pending" | "streaming" | "complete" | "error";

export interface ChatMessage {
  id: string;
  role: ChatRole;
  content: string;
  createdAt: number;
  status: ChatMessageStatus;
  /** Mode used when the user sent (for assistant reply: which mode answered). */
  mode?: AgentMode;
  /** Tokens actually spent (assistant) or estimated upper bound (user). */
  tokensSpent?: number;
  attachments?: ChatAttachment[];
  /** Human-readable error surfaced to the bubble when status === "error". */
  error?: string;
}

/** Pending attachment staged in the composer before sending. */
export interface PendingAttachment {
  id: string;
  kind: "image" | "document";
  name: string;
  sizeBytes: number;
  mimeType: string;
  /** Local object URL used for preview while staged. */
  previewUrl: string;
  /** Base64 payload sent to the backend on submit. */
  base64: string;
}
