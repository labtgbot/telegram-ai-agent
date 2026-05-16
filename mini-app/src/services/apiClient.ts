import { getInitData } from "@/services/telegram";

const DEFAULT_BASE_URL = "/api/v1";

export interface ApiClientOptions {
  baseUrl?: string;
  getInitData?: () => string;
  fetchImpl?: typeof fetch;
}

export interface RequestOptions extends Omit<RequestInit, "body" | "headers"> {
  query?: Record<string, string | number | boolean | undefined | null>;
  headers?: HeadersInit;
  json?: unknown;
}

export class ApiError extends Error {
  readonly status: number;
  readonly body: unknown;

  constructor(message: string, status: number, body: unknown) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.body = body;
  }
}

function joinUrl(base: string, path: string): string {
  const normBase = base.endsWith("/") ? base.slice(0, -1) : base;
  const normPath = path.startsWith("/") ? path : `/${path}`;
  return `${normBase}${normPath}`;
}

function buildQuery(params?: RequestOptions["query"]): string {
  if (!params) return "";
  const search = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    if (value === undefined || value === null) continue;
    search.append(key, String(value));
  }
  const qs = search.toString();
  return qs ? `?${qs}` : "";
}

/**
 * Lightweight fetch wrapper that:
 *  - prefixes all requests with `baseUrl`
 *  - automatically attaches `X-Telegram-Init-Data` from the WebApp SDK
 *  - serialises `json` payloads and parses JSON responses
 *  - throws `ApiError` on non-2xx with the parsed body
 */
export class ApiClient {
  private readonly baseUrl: string;
  private readonly getInitDataImpl: () => string;
  private readonly fetchImpl: typeof fetch;

  constructor(options: ApiClientOptions = {}) {
    this.baseUrl = options.baseUrl ?? import.meta.env.VITE_API_BASE_URL ?? DEFAULT_BASE_URL;
    this.getInitDataImpl = options.getInitData ?? getInitData;
    this.fetchImpl = options.fetchImpl ?? fetch.bind(globalThis);
  }

  async request<T = unknown>(path: string, options: RequestOptions = {}): Promise<T> {
    const { query, json, headers, ...rest } = options;
    const url = `${joinUrl(this.baseUrl, path)}${buildQuery(query)}`;

    const mergedHeaders = new Headers(headers);
    const initData = this.getInitDataImpl();
    if (initData && !mergedHeaders.has("X-Telegram-Init-Data")) {
      mergedHeaders.set("X-Telegram-Init-Data", initData);
    }
    if (!mergedHeaders.has("Accept")) {
      mergedHeaders.set("Accept", "application/json");
    }

    let body: BodyInit | undefined;
    if (json !== undefined) {
      body = JSON.stringify(json);
      if (!mergedHeaders.has("Content-Type")) {
        mergedHeaders.set("Content-Type", "application/json");
      }
    }

    const response = await this.fetchImpl(url, {
      ...rest,
      headers: mergedHeaders,
      body,
    });

    return parseResponse<T>(response);
  }

  get<T = unknown>(path: string, options?: Omit<RequestOptions, "json">): Promise<T> {
    return this.request<T>(path, { ...options, method: "GET" });
  }

  post<T = unknown>(path: string, json?: unknown, options?: RequestOptions): Promise<T> {
    return this.request<T>(path, { ...options, method: "POST", json });
  }

  put<T = unknown>(path: string, json?: unknown, options?: RequestOptions): Promise<T> {
    return this.request<T>(path, { ...options, method: "PUT", json });
  }

  patch<T = unknown>(path: string, json?: unknown, options?: RequestOptions): Promise<T> {
    return this.request<T>(path, { ...options, method: "PATCH", json });
  }

  delete<T = unknown>(path: string, options?: Omit<RequestOptions, "json">): Promise<T> {
    return this.request<T>(path, { ...options, method: "DELETE" });
  }
}

async function parseResponse<T>(response: Response): Promise<T> {
  const contentType = response.headers.get("content-type") ?? "";
  const isJson = contentType.includes("application/json");
  const payload: unknown = isJson
    ? await response.json().catch(() => null)
    : await response.text().catch(() => "");

  if (!response.ok) {
    const message =
      isJson && payload && typeof payload === "object" && "detail" in payload
        ? String((payload as { detail: unknown }).detail)
        : `Request failed with status ${response.status}`;
    throw new ApiError(message, response.status, payload);
  }

  return payload as T;
}

export const apiClient = new ApiClient();
