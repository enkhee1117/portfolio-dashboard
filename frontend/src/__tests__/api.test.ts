import { describe, it, expect, vi, beforeEach } from "vitest";

// Mock firebase auth before importing apiCall
vi.mock("../lib/firebase", () => ({
  auth: { currentUser: null },
}));

import { apiCall } from "../lib/api";
import { auth } from "../lib/firebase";

describe("apiCall", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
    (auth as any).currentUser = null;
  });

  it("sends request without auth header when user is not logged in", async () => {
    const mockFetch = vi.fn().mockResolvedValue(new Response("{}"));
    vi.stubGlobal("fetch", mockFetch);

    await apiCall("/api/portfolio");

    const headers = mockFetch.mock.calls[0][1].headers;
    expect(headers.Authorization).toBeUndefined();
  });

  it("attaches Bearer token when user is logged in", async () => {
    (auth as any).currentUser = {
      getIdToken: vi.fn().mockResolvedValue("test-token-123"),
    };
    const mockFetch = vi.fn().mockResolvedValue(new Response("{}"));
    vi.stubGlobal("fetch", mockFetch);

    await apiCall("/api/portfolio");

    const headers = mockFetch.mock.calls[0][1].headers;
    expect(headers.Authorization).toBe("Bearer test-token-123");
  });

  it("returns Response object that callers must check .ok on", async () => {
    const mockFetch = vi.fn().mockResolvedValue(
      new Response('{"detail":"Not authenticated"}', { status: 401 })
    );
    vi.stubGlobal("fetch", mockFetch);

    const res = await apiCall("/api/portfolio");

    expect(res.ok).toBe(false);
    expect(res.status).toBe(401);
    // Parsing the body should give an object, NOT an array
    const body = await res.json();
    expect(Array.isArray(body)).toBe(false);
  });
});
