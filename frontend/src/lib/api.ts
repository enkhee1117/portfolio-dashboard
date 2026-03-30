import { auth } from "./firebase";

// Threshold for logging slow requests (ms)
const SLOW_REQUEST_MS = 2000;
const SLOW_CRUD_MS = 500;

/**
 * Authenticated API call wrapper.
 * Attaches Firebase Auth ID token as Bearer token to every request.
 * Logs slow requests in development for performance monitoring.
 */
export async function apiCall(
  endpoint: string,
  options: RequestInit = {}
): Promise<Response> {
  const start = performance.now();

  const headers: Record<string, string> = {
    ...(options.headers as Record<string, string> || {}),
  };

  // Attach auth token if user is logged in
  const user = auth.currentUser;
  if (user) {
    const token = await user.getIdToken();
    headers["Authorization"] = `Bearer ${token}`;
  }

  // Only set Content-Type for non-FormData requests
  if (!(options.body instanceof FormData) && !headers["Content-Type"]) {
    headers["Content-Type"] = "application/json";
  }

  const response = await fetch(endpoint, {
    ...options,
    headers,
  });

  // Performance monitoring: log slow requests
  const duration = Math.round(performance.now() - start);
  const method = options.method || "GET";
  const isCrud = method !== "GET" && (endpoint.includes("/trades") || endpoint.includes("/assets"));
  const threshold = isCrud ? SLOW_CRUD_MS : SLOW_REQUEST_MS;

  if (duration > threshold) {
    console.warn(
      `[SLOW API] ${method} ${endpoint} took ${duration}ms (threshold: ${threshold}ms, status: ${response.status})`
    );
  }

  // Read server-side timing header if available
  const serverTime = response.headers.get("X-Response-Time-Ms");
  if (serverTime && parseInt(serverTime) > threshold) {
    console.warn(
      `[SLOW SERVER] ${method} ${endpoint} server took ${serverTime}ms`
    );
  }

  return response;
}
