export class ApiError extends Error {
  readonly status: number;
  readonly code: string;
  readonly payload: unknown;

  constructor(status: number, code: string, message?: string, payload?: unknown) {
    super(message ?? code);
    this.name = "ApiError";
    this.status = status;
    this.code = code;
    this.payload = payload;
  }

  get isUnauthorized(): boolean {
    return this.status === 401;
  }

  get isForbidden(): boolean {
    return this.status === 403;
  }
}

export function isApiError(err: unknown): err is ApiError {
  return err instanceof ApiError;
}
