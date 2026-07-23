const TOKEN_KEY = "drg_token";

export function getToken(): string | null {
  return localStorage.getItem(TOKEN_KEY);
}

export function setToken(token: string | null) {
  if (token) localStorage.setItem(TOKEN_KEY, token);
  else localStorage.removeItem(TOKEN_KEY);
}

export class ApiError extends Error {
  status: number;
  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

async function request<T>(method: string, path: string, body?: unknown): Promise<T> {
  const headers: Record<string, string> = { "Content-Type": "application/json" };
  const token = getToken();
  if (token) headers.Authorization = `Bearer ${token}`;
  const res = await fetch(path, {
    method,
    headers,
    body: body !== undefined ? JSON.stringify(body) : undefined,
  });
  if (!res.ok) {
    const text = await res.text().catch(() => res.statusText);
    // FastAPI errors are {"detail": "..."}; surface that readable string
    // rather than the raw JSON body. Fall back to the body as-is otherwise.
    let message = text;
    try {
      const parsed = JSON.parse(text);
      if (typeof parsed?.detail === "string") {
        message = parsed.detail;
      } else if (Array.isArray(parsed?.detail)) {
        // Pydantic 422 validation errors: [{loc, msg, ...}, ...] — join the
        // human-readable msgs rather than dumping the raw JSON.
        const msgs = parsed.detail.map((d: { msg?: string }) => d?.msg).filter(Boolean);
        if (msgs.length) message = msgs.join("; ");
      }
    } catch {
      // not JSON — keep the raw text
    }
    throw new ApiError(res.status, message);
  }
  if (res.status === 204) return undefined as T;
  return (await res.json()) as T;
}

export const api = {
  get: <T,>(path: string) => request<T>("GET", path),
  post: <T,>(path: string, body?: unknown) => request<T>("POST", path, body),
  put: <T,>(path: string, body?: unknown) => request<T>("PUT", path, body),
  del: <T,>(path: string) => request<T>("DELETE", path),
};

/**
 * Download a file from an authenticated endpoint. Bearer-token auth (not
 * cookies) means a plain `<a href>` can't carry the Authorization header —
 * this fetches as a blob (bypassing request()'s JSON-only response
 * handling, same reason streamLines below does its own manual fetch) and
 * triggers the download via a synthetic anchor click.
 */
export async function downloadFile(path: string, filename: string): Promise<void> {
  const headers: Record<string, string> = {};
  const token = getToken();
  if (token) headers.Authorization = `Bearer ${token}`;
  const res = await fetch(path, { headers });
  if (!res.ok) throw new ApiError(res.status, await res.text().catch(() => res.statusText));
  const blob = await res.blob();
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  a.click();
  URL.revokeObjectURL(url);
}

/**
 * Consume a text/event-stream endpoint line by line. TESTING ONLY — backs the
 * dev live-grading terminal; not a general-purpose SSE client.
 */
export async function streamLines(
  path: string,
  onLine: (line: string) => void,
  onDone: (status: string) => void,
): Promise<void> {
  const headers: Record<string, string> = {};
  const token = getToken();
  if (token) headers.Authorization = `Bearer ${token}`;
  const res = await fetch(path, { headers });
  if (!res.ok || !res.body) {
    onDone("error");
    return;
  }
  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  for (;;) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    const chunks = buffer.split("\n\n");
    buffer = chunks.pop() ?? "";
    for (const chunk of chunks) {
      const eventMatch = chunk.match(/^event: (.*)$/m);
      const dataMatch = chunk.match(/^data: (.*)$/m);
      const data = dataMatch ? dataMatch[1] : "";
      if (eventMatch?.[1] === "done") {
        onDone(data);
        return;
      }
      if (data) onLine(data);
    }
  }
  onDone("complete");
}
