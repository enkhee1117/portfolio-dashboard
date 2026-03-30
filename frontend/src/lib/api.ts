import { auth } from "./firebase";

/**
 * Authenticated API call wrapper.
 * Attaches Firebase Auth ID token as Bearer token to every request.
 * Falls back to unauthenticated for public endpoints.
 */
export async function apiCall(
  endpoint: string,
  options: RequestInit = {}
): Promise<Response> {
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

  return fetch(endpoint, {
    ...options,
    headers,
  });
}
