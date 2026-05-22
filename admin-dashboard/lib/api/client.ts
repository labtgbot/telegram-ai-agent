import { ApiError } from "@/lib/api/errors";

export interface ApiClientOptions {
  baseUrl: string;
  /** Returns the current bearer token (or undefined while logged out). */
  getAccessToken?: () => string | undefined | Promise<string | undefined>;
  /**
   * Invoked on 401 to attempt token rotation. Should return the new access
   * token, or undefined if the session is dead.
   */
  refreshAccessToken?: () => Promise<string | undefined>;
  /** Invoked when the session is irrecoverable (401 after refresh, or 403). */
  onAuthLost?: (status: 401 | 403) => void | Promise<void>;
  fetchImpl?: typeof fetch;
}

export interface RequestOptions {
  method?: "GET" | "POST" | "PATCH" | "PUT" | "DELETE";
  query?: Record<string, string | number | boolean | undefined>;
  body?: unknown;
  headers?: Record<string, string>;
  signal?: AbortSignal;
}

export class ApiClient {
  private readonly opts: ApiClientOptions;
  private readonly fetchImpl: typeof fetch;

  constructor(opts: ApiClientOptions) {
    this.opts = opts;
    this.fetchImpl = opts.fetchImpl ?? globalThis.fetch.bind(globalThis);
  }

  async request<T = unknown>(path: string, options: RequestOptions = {}): Promise<T> {
    return this.executeWithAuth<T>(path, options, false);
  }

  get<T = unknown>(path: string, options: Omit<RequestOptions, "method" | "body"> = {}): Promise<T> {
    return this.request<T>(path, { ...options, method: "GET" });
  }

  post<T = unknown>(
    path: string,
    body?: unknown,
    options: Omit<RequestOptions, "method" | "body"> = {},
  ): Promise<T> {
    return this.request<T>(path, { ...options, method: "POST", body });
  }

  patch<T = unknown>(
    path: string,
    body?: unknown,
    options: Omit<RequestOptions, "method" | "body"> = {},
  ): Promise<T> {
    return this.request<T>(path, { ...options, method: "PATCH", body });
  }

  delete<T = unknown>(
    path: string,
    options: Omit<RequestOptions, "method" | "body"> = {},
  ): Promise<T> {
    return this.request<T>(path, { ...options, method: "DELETE" });
  }

  private async executeWithAuth<T>(
    path: string,
    options: RequestOptions,
    retrying: boolean,
  ): Promise<T> {
    const url = this.buildUrl(path, options.query);
    const headers = new Headers(options.headers ?? {});
    if (options.body !== undefined && !headers.has("Content-Type")) {
      headers.set("Content-Type", "application/json");
    }
    const token = await this.opts.getAccessToken?.();
    if (token) headers.set("Authorization", `Bearer ${token}`);

    const response = await this.fetchImpl(url, {
      method: options.method ?? "GET",
      headers,
      body: options.body === undefined ? undefined : JSON.stringify(options.body),
      signal: options.signal,
      credentials: "include",
    });

    if (response.status === 401 && !retrying && this.opts.refreshAccessToken) {
      const next = await this.opts.refreshAccessToken();
      if (next) {
        return this.executeWithAuth<T>(path, options, true);
      }
      await this.opts.onAuthLost?.(401);
      throw await this.toApiError(response);
    }
    if (response.status === 401) {
      await this.opts.onAuthLost?.(401);
      throw await this.toApiError(response);
    }
    if (response.status === 403) {
      await this.opts.onAuthLost?.(403);
      throw await this.toApiError(response);
    }
    if (!response.ok) {
      throw await this.toApiError(response);
    }
    if (response.status === 204) {
      return undefined as T;
    }
    const contentType = response.headers.get("content-type") ?? "";
    if (contentType.includes("application/json")) {
      return (await response.json()) as T;
    }
    return (await response.text()) as unknown as T;
  }

  private buildUrl(path: string, query?: RequestOptions["query"]): string {
    const base = this.opts.baseUrl.endsWith("/") ? this.opts.baseUrl.slice(0, -1) : this.opts.baseUrl;
    const suffix = path.startsWith("/") ? path : `/${path}`;
    const url = new URL(`${base}${suffix}`);
    if (query) {
      for (const [key, value] of Object.entries(query)) {
        if (value === undefined) continue;
        url.searchParams.set(key, String(value));
      }
    }
    return url.toString();
  }

  private async toApiError(response: Response): Promise<ApiError> {
    const status = response.status;
    let code = `http_${status}`;
    let message: string | undefined;
    let payload: unknown;
    try {
      const contentType = response.headers.get("content-type") ?? "";
      if (contentType.includes("application/json")) {
        payload = await response.json();
        if (payload && typeof payload === "object") {
          const detail = (payload as { detail?: unknown }).detail;
          if (typeof detail === "string") {
            code = detail;
            message = detail;
          } else if (detail && typeof detail === "object" && "code" in detail) {
            code = String((detail as { code: unknown }).code);
            message = code;
          }
        }
      } else {
        message = await response.text();
      }
    } catch {
      // ignore parse errors — keep generic code
    }
    return new ApiError(status, code, message, payload);
  }
}
