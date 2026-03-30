import { describe, it, expect } from "vitest";

/**
 * These tests verify the patterns that prevent the r.slice crash.
 * They test the defensive coding patterns, not specific components.
 */
describe("Error resilience patterns", () => {
  it("401 response body is not an array", async () => {
    // Simulates what the backend returns for unauthenticated requests
    const response = new Response(
      JSON.stringify({ detail: "Authentication required" }),
      { status: 401 }
    );

    const body = await response.json();

    // This is what caused the crash: code assumed response was always an array
    expect(Array.isArray(body)).toBe(false);
    expect(() => body.slice(0, 10)).toThrow(); // TypeError: body.slice is not a function
  });

  it("safe pattern: check r.ok before parsing", async () => {
    const response = new Response(
      JSON.stringify({ detail: "Authentication required" }),
      { status: 401 }
    );

    // The correct pattern used in our codebase
    let data: any[] = [];
    if (response.ok) {
      data = await response.json();
    }

    expect(data).toEqual([]);
    expect(() => data.slice(0, 10)).not.toThrow();
  });

  it("safe pattern: validate array before using array methods", async () => {
    const response = new Response(
      JSON.stringify({ detail: "Server error" }),
      { status: 500 }
    );

    // Even if someone skips the r.ok check, Array.isArray guards against crash
    const body = await response.json();
    const safeData = Array.isArray(body) ? body : [];

    expect(safeData).toEqual([]);
    expect(() => safeData.slice(0, 10)).not.toThrow();
  });

  it("500 response with HTML body does not crash json parse", async () => {
    const response = new Response("<html>Server Error</html>", { status: 500 });

    // The r.ok check prevents attempting to parse HTML as JSON
    let data: any[] = [];
    if (response.ok) {
      data = await response.json();
    }

    expect(data).toEqual([]);
  });
});
