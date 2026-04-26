import type { ApiClientConfig, ApiError, ApiResponse } from "../types/api";

const DEFAULT_TIMEOUT_MS = 10_000;

function toApiError(status: number, message: string, details?: string): ApiError {
  return {
    status,
    message,
    details,
  };
}

function getErrorMessage(status: number, fallback: string): string {
  if (/ECONNREFUSED|http proxy error/i.test(fallback)) {
    return "Connection refused by backend target. Start backend in HTTP mode (APP_MODE 5/6) and verify HTTP_PORT/ATM_BACKEND_TARGET.";
  }

  if (status === 401) {
    return "Unauthorized: invalid bearer token";
  }

  if (status === 403) {
    return "Forbidden: backend requires HTTPS";
  }

  if (status === 408) {
    return "Request timed out in backend";
  }

  if (status >= 500) {
    return "Backend internal error";
  }

  return fallback;
}

function isAbsoluteHttpUrl(value: string): boolean {
  return value.startsWith("http://") || value.startsWith("https://");
}

function resolveBaseUrl(baseUrl: string): { baseUrl: string; proxyTarget?: string } {
  const trimmed = baseUrl.trim();
  if (!trimmed) {
    return { baseUrl: "/api" };
  }

  if (isAbsoluteHttpUrl(trimmed)) {
    try {
      const parsed = new URL(trimmed);
      const normalizedPath = parsed.pathname === "/" ? "" : parsed.pathname.replace(/\/$/, "");
      const normalizedAbsolute = `${parsed.origin}${normalizedPath}`;

      if (typeof window !== "undefined" && parsed.origin !== window.location.origin) {
        return {
          baseUrl: "/api",
          proxyTarget: normalizedAbsolute,
        };
      }

      return { baseUrl: normalizedAbsolute };
    } catch {
      return { baseUrl: "/api" };
    }
  }

  const withLeadingSlash = trimmed.startsWith("/") ? trimmed : `/${trimmed}`;
  return { baseUrl: withLeadingSlash.replace(/\/$/, "") };
}

function buildUrl(baseUrl: string, path: string): URL {
  const commandPath = path.replace(/^\//, "");

  if (isAbsoluteHttpUrl(baseUrl)) {
    return new URL(`${baseUrl}/${commandPath}`);
  }

  return new URL(`${baseUrl}/${commandPath}`, window.location.origin);
}

export class HttpApiClient {
  private readonly baseUrl: string;

  private readonly proxyTarget?: string;

  private readonly token: string;

  private readonly timeoutMs: number;

  public constructor(config: ApiClientConfig) {
    const resolved = resolveBaseUrl(config.baseUrl);
    this.baseUrl = resolved.baseUrl;
    this.proxyTarget = resolved.proxyTarget;
    this.token = config.token;
    this.timeoutMs = config.timeoutMs ?? DEFAULT_TIMEOUT_MS;
  }

  public async get<T>(path: string, query?: URLSearchParams): Promise<ApiResponse<T>> {
    const url = buildUrl(this.baseUrl, path);
    if (query) {
      url.search = query.toString();
    }

    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), this.timeoutMs);

    try {
      const headers: Record<string, string> = {
        Authorization: `Bearer ${this.token}`,
      };

      if (this.proxyTarget) {
        headers["X-Atm-Target"] = this.proxyTarget;
      }

      const response = await fetch(url, {
        method: "GET",
        headers,
        signal: controller.signal,
      });

      const raw = await response.text();
      const parsed = this.parseBody<T>(raw, response.headers.get("content-type"));

      if (!response.ok) {
        const message = getErrorMessage(response.status, raw || response.statusText);
        throw toApiError(response.status, message, raw || response.statusText);
      }

      return {
        status: response.status,
        headers: response.headers,
        data: parsed.data,
        text: parsed.text,
      };
    } catch (error) {
      if (error instanceof DOMException && error.name === "AbortError") {
        throw toApiError(0, "Request aborted by client timeout");
      }

      if (this.isApiError(error)) {
        throw error;
      }

      throw toApiError(0, "Network error", String(error));
    } finally {
      clearTimeout(timeout);
    }
  }

  private parseBody<T>(raw: string, contentType: string | null): { data?: T; text?: string } {
    const trimmed = raw.trim();
    if (trimmed.length === 0) {
      return {};
    }

    const isJson = contentType?.includes("application/json") ?? false;
    if (isJson || trimmed.startsWith("{") || trimmed.startsWith("[")) {
      try {
        return {
          data: JSON.parse(trimmed) as T,
        };
      } catch {
        return {
          text: raw,
        };
      }
    }

    return {
      text: raw,
    };
  }

  private isApiError(value: unknown): value is ApiError {
    if (typeof value !== "object" || value === null) {
      return false;
    }

    const candidate = value as Partial<ApiError>;
    return typeof candidate.status === "number" && typeof candidate.message === "string";
  }
}

export function encodeArgs(args: string[]): string {
  return args
    .map((value) => value.trim())
    .filter((value) => value.length > 0)
    .join(" ");
}

export function buildQueryWithArgs(args?: string[]): URLSearchParams | undefined {
  if (!args || args.length === 0) {
    return undefined;
  }

  const joined = encodeArgs(args);
  if (!joined) {
    return undefined;
  }

  const query = new URLSearchParams();
  query.set("args", joined);
  return query;
}
