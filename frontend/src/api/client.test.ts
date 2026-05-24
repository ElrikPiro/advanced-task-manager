import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { HttpApiClient, buildQueryWithArgs, encodeArgs } from "./client";

interface FetchMockResult {
  status: number;
  body: string;
  contentType?: string;
}

interface WindowLocationLike {
  origin: string;
}

interface WindowLike {
  location: WindowLocationLike;
}

function hasWindow(value: unknown): value is WindowLike {
  if (typeof value !== "object" || value === null) {
    return false;
  }

  const candidate = value as Partial<WindowLike>;
  if (typeof candidate.location !== "object" || candidate.location === null) {
    return false;
  }

  return typeof (candidate.location as Partial<WindowLocationLike>).origin === "string";
}

function createFetchResponse(result: FetchMockResult): Response {
  return new Response(result.body, {
    status: result.status,
    headers: {
      "Content-Type": result.contentType ?? "application/json",
    },
  });
}

describe("encodeArgs", () => {
  it("joins and trims args", () => {
    const value = encodeArgs(["  one", "two  ", "", "three"]);
    expect(value).toBe("one two three");
  });
});

describe("buildQueryWithArgs", () => {
  it("builds query when args are provided", () => {
    const query = buildQueryWithArgs(["hello", "world"]);
    expect(query?.get("args")).toBe("hello world");
  });

  it("returns undefined for empty args", () => {
    expect(buildQueryWithArgs([])).toBeUndefined();
    expect(buildQueryWithArgs(["   "])).toBeUndefined();
    expect(buildQueryWithArgs()).toBeUndefined();
  });
});

describe("HttpApiClient", () => {
  const baseUrl = "http://localhost:8080";
  const token = "demo";

  beforeEach(() => {
    vi.stubGlobal("fetch", vi.fn());
    const baseWindow = hasWindow(globalThis.window)
      ? globalThis.window
      : {
          location: {
            origin: "http://localhost:5173",
          },
        };

    vi.stubGlobal(
      "window",
      Object.assign(baseWindow, {
        location: {
          origin: "http://localhost:5173",
        },
      }),
    );
  });

  afterEach(() => {
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
  });

  it("returns parsed JSON payload", async () => {
    vi.mocked(fetch).mockResolvedValueOnce(
      createFetchResponse({
        status: 200,
        body: JSON.stringify({ name: "ok" }),
      }),
    );

    const client = new HttpApiClient({ baseUrl, token });
    const response = await client.get<{ name: string }>("list");

    expect(response.data).toEqual({ name: "ok" });
    expect(response.text).toBeUndefined();
  });

  it("falls back to text when JSON is invalid", async () => {
    vi.mocked(fetch).mockResolvedValueOnce(
      createFetchResponse({
        status: 200,
        body: "{'error': 'not-json'}",
      }),
    );

    const client = new HttpApiClient({ baseUrl, token });
    const response = await client.get<unknown>("list");

    expect(response.data).toBeUndefined();
    expect(response.text).toBe("{'error': 'not-json'}");
  });

  it("maps 401 errors to api error message", async () => {
    vi.mocked(fetch).mockResolvedValueOnce(
      createFetchResponse({
        status: 401,
        body: "Unauthorized: Invalid token",
        contentType: "text/plain",
      }),
    );

    const client = new HttpApiClient({ baseUrl, token });

    await expect(client.get("list")).rejects.toMatchObject({
      status: 401,
      message: "Unauthorized: invalid bearer token",
    });
  });

  it("supports relative /api base URLs without preflight headers", async () => {
    vi.mocked(fetch).mockResolvedValueOnce(
      createFetchResponse({
        status: 200,
        body: JSON.stringify({ ok: true }),
      }),
    );

    const client = new HttpApiClient({ baseUrl: "/api", token });
    await client.get<{ ok: boolean }>("list");

    expect(fetch).toHaveBeenCalledTimes(1);
    const [requestUrl, requestInit] = vi.mocked(fetch).mock.calls[0];
    expect(String(requestUrl)).toBe("http://localhost:5173/api/list");
    expect((requestInit as RequestInit).method).toBe("GET");
    expect((requestInit as RequestInit).headers).toEqual({
      Authorization: `Bearer ${token}`,
    });
  });

  it("normalizes cross-origin absolute backend URL to /api", async () => {
    vi.mocked(fetch).mockResolvedValueOnce(
      createFetchResponse({
        status: 200,
        body: JSON.stringify({ ok: true }),
      }),
    );

    const client = new HttpApiClient({ baseUrl: "http://127.0.0.1:8080", token });
    const response = await client.get<{ ok: boolean }>("list");

    expect(response.data).toEqual({ ok: true });
    expect(fetch).toHaveBeenCalledTimes(1);
    const [requestUrl, requestInit] = vi.mocked(fetch).mock.calls[0];
    expect(String(requestUrl)).toBe("http://localhost:5173/api/list");
    expect((requestInit as RequestInit).method).toBe("GET");
    expect((requestInit as RequestInit).headers).toEqual({
      Authorization: `Bearer ${token}`,
      "X-Atm-Target": "http://127.0.0.1:8080",
    });
  });

  it("keeps same-origin absolute URL without proxy target header", async () => {
    vi.mocked(fetch).mockResolvedValueOnce(
      createFetchResponse({
        status: 200,
        body: JSON.stringify({ ok: true }),
      }),
    );

    const client = new HttpApiClient({ baseUrl: "http://localhost:5173", token });
    await client.get<{ ok: boolean }>("list");

    const [requestUrl, requestInit] = vi.mocked(fetch).mock.calls[0];
    expect(String(requestUrl)).toBe("http://localhost:5173/list");
    expect((requestInit as RequestInit).headers).toEqual({
      Authorization: `Bearer ${token}`,
    });
  });
});
