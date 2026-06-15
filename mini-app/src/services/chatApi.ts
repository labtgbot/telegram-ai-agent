import { apiClient } from "@/services/apiClient";
import { getInitData } from "@/services/telegram";
import { MODE_COST, type AgentMode } from "@/types/chat";

const DEFAULT_BASE_URL = "/api/v1";

/** Lightweight estimator used for the pre-send "≈ N tokens" indicator.
 *
 * The backend charges a flat per-mode price (`MODE_COST`), so a token
 * estimate is just `MODE_COST[mode]` for the text call itself. Attachments
 * add their own flat cost which the caller can sum in.
 */
export function estimateMessageCost(mode: AgentMode): number {
  return MODE_COST[mode];
}

export interface SendMessageRequest {
  prompt: string;
  mode: AgentMode;
  threadId: string;
  systemPrompt?: string;
  signal?: AbortSignal;
}

export type StreamEvent =
  | { event: "start"; request_id: string }
  | { event: "delta"; content: string }
  | {
      event: "final";
      text: string;
      tokens_spent: number;
      new_balance: number;
      mode: AgentMode;
      request_id: string;
      thread_id?: string | null;
    }
  | { event: "error"; error: string; message: string }
  | { event: "done" };

export interface StreamHandlers {
  onStart?: (requestId: string) => void;
  onDelta?: (content: string) => void;
  onFinal?: (final: Extract<StreamEvent, { event: "final" }>) => void;
  onError?: (err: { error: string; message: string }) => void;
}

function resolveBaseUrl(): string {
  return import.meta.env.VITE_API_BASE_URL ?? DEFAULT_BASE_URL;
}

/**
 * Stream a text-generation response via Server-Sent Events.
 *
 * Implementation note: the `fetch` + `ReadableStream` route is preferred
 * over `EventSource` so we can attach the Telegram `initData` header
 * (EventSource only supports GET + cookies).
 */
export async function streamTextGeneration(
  request: SendMessageRequest,
  handlers: StreamHandlers,
  fetchImpl: typeof fetch = fetch.bind(globalThis),
): Promise<void> {
  const headers = new Headers({
    "Content-Type": "application/json",
    Accept: "text/event-stream",
  });
  const initData = getInitData();
  if (initData) headers.set("X-Telegram-Init-Data", initData);

  const body = JSON.stringify({
    prompt: request.prompt,
    mode: request.mode,
    thread_id: request.threadId,
    system_prompt: request.systemPrompt,
  });

  const response = await fetchImpl(`${resolveBaseUrl()}/generate/text/stream`, {
    method: "POST",
    headers,
    body,
    signal: request.signal,
  });

  if (!response.ok || !response.body) {
    let detail: unknown = null;
    try {
      detail = await response.json();
    } catch {
      /* not JSON */
    }
    handlers.onError?.({
      error: `http_${response.status}`,
      message: detail && typeof detail === "object" && "detail" in detail
        ? String((detail as { detail: unknown }).detail)
        : `Request failed (${response.status})`,
    });
    return;
  }

  const reader = response.body.getReader();
  const decoder = new TextDecoder("utf-8");
  let buffer = "";
  let done = false;

  while (!done) {
    const chunk = await reader.read();
    done = chunk.done;
    if (chunk.value) buffer += decoder.decode(chunk.value, { stream: true });

    // SSE frames are separated by a blank line.
    let sepIdx: number;
    while ((sepIdx = buffer.indexOf("\n\n")) !== -1) {
      const rawFrame = buffer.slice(0, sepIdx);
      buffer = buffer.slice(sepIdx + 2);
      dispatchFrame(rawFrame, handlers);
    }
  }

  if (buffer.trim().length > 0) {
    dispatchFrame(buffer, handlers);
  }
}

function dispatchFrame(rawFrame: string, handlers: StreamHandlers): void {
  const lines = rawFrame.split("\n");
  const dataParts: string[] = [];
  for (const line of lines) {
    if (line.startsWith("data:")) dataParts.push(line.slice(5).trimStart());
  }
  if (dataParts.length === 0) return;

  const payload = dataParts.join("\n");
  let parsed: StreamEvent;
  try {
    parsed = JSON.parse(payload) as StreamEvent;
  } catch {
    return;
  }

  switch (parsed.event) {
    case "start":
      handlers.onStart?.(parsed.request_id);
      break;
    case "delta":
      handlers.onDelta?.(parsed.content);
      break;
    case "final":
      handlers.onFinal?.(parsed);
      break;
    case "error":
      handlers.onError?.({ error: parsed.error, message: parsed.message });
      break;
    case "done":
    default:
      break;
  }
}

// ------------------------------------------------------------ side actions

export interface SearchResult {
  title: string;
  url: string;
  snippet?: string | null;
  source?: string | null;
}

export interface SearchResponse {
  query: string;
  results: SearchResult[];
  summary: string | null;
  tokens_spent: number;
  new_balance: number;
  request_id: string;
}

export function runWebSearch(query: string, maxResults = 5): Promise<SearchResponse> {
  return apiClient.post<SearchResponse>("/generate/search", {
    query,
    max_results: maxResults,
  });
}

export interface ImageGenerationResponse {
  result_url: string;
  prompt: string;
  tokens_spent: number;
  new_balance: number;
  request_id: string;
}

export function generateImage(
  prompt: string,
  quality: "standard" | "hd" | "ultra_hd" = "standard",
): Promise<ImageGenerationResponse> {
  return apiClient.post<ImageGenerationResponse>("/generate/image", { prompt, quality });
}

export interface VideoJobResponse {
  job_id: number;
  status: "pending" | "queued" | "in_progress" | "succeeded" | "failed" | "refunded";
  result_url: string | null;
  tokens_cost: number;
  new_balance?: number;
  prompt: string;
  request_id: string;
}

export function submitVideoJob(
  prompt: string,
  tariff: "short_5s" | "medium_15s" | "long_60s" = "short_5s",
): Promise<VideoJobResponse> {
  return apiClient.post<VideoJobResponse>("/generate/video", { prompt, tariff });
}

export interface DocumentAnalysisResponse {
  text: string;
  summary: string | null;
  answer: string | null;
  format: "pdf" | "docx" | "txt";
  tokens_spent: number;
  new_balance: number;
  request_id: string;
}

export interface AnalyseDocumentInput {
  base64: string;
  filename: string;
  fileSizeBytes: number;
  question?: string;
}

export function analyseDocument(
  input: AnalyseDocumentInput,
): Promise<DocumentAnalysisResponse> {
  return apiClient.post<DocumentAnalysisResponse>("/generate/document", {
    document_base64: input.base64,
    filename: input.filename,
    file_size_bytes: input.fileSizeBytes,
    question: input.question,
  });
}

// ---------------------------------------------------------- file utilities

/** Read a `File` as raw base64 (no `data:` prefix). */
export function readFileAsBase64(file: File): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onerror = () => reject(reader.error ?? new Error("file_read_failed"));
    reader.onload = () => {
      const result = reader.result;
      if (typeof result !== "string") {
        reject(new Error("file_read_invalid"));
        return;
      }
      const commaIdx = result.indexOf(",");
      resolve(commaIdx === -1 ? result : result.slice(commaIdx + 1));
    };
    reader.readAsDataURL(file);
  });
}
