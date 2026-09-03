/** Thin client for the ALTER EGO backend. */

// Empty in dev: Vite proxies /api to the local backend (see vite.config.ts).
// In production this is the Render URL, injected at build time.
export const API_BASE = (import.meta.env.VITE_API_BASE ?? "").replace(/\/$/, "");

function url(path: string): string {
  return `${API_BASE}/api${path}`;
}

export interface Health {
  status: string;
  offline: boolean;
}

export async function health(): Promise<Health> {
  const res = await fetch(url("/health"));
  if (!res.ok) throw new Error(`health failed: ${res.status}`);
  return res.json();
}

export async function createSession(): Promise<string> {
  const res = await fetch(url("/session"), { method: "POST" });
  if (!res.ok) throw new Error(`session failed: ${res.status}`);
  return (await res.json()).session_id;
}

export interface ChatMeta {
  retrieved_memories: unknown[];
  graph_delta: unknown;
}

export interface ChatHandlers {
  onToken: (text: string) => void;
  onMeta?: (meta: ChatMeta) => void;
  onError?: (message: string) => void;
}

/**
 * Consume the SSE stream from POST /api/chat.
 *
 * The native EventSource API is GET-only, so the message is POSTed and the
 * `text/event-stream` body is parsed off the fetch ReadableStream instead.
 */
export async function chat(
  sessionId: string,
  message: string,
  handlers: ChatHandlers,
  signal?: AbortSignal
): Promise<void> {
  const res = await fetch(url("/chat"), {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ session_id: sessionId, message }),
    signal,
  });

  if (!res.ok || !res.body) {
    const detail = await res.text().catch(() => "");
    throw new Error(detail || `chat failed: ${res.status}`);
  }

  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";

  for (;;) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });

    // SSE frames are separated by a blank line.
    let split: number;
    while ((split = buffer.indexOf("\n\n")) !== -1) {
      const frame = buffer.slice(0, split);
      buffer = buffer.slice(split + 2);
      dispatch(frame, handlers);
    }
  }
}

function dispatch(frame: string, handlers: ChatHandlers): void {
  let event = "message";
  const dataLines: string[] = [];

  for (const line of frame.split("\n")) {
    if (line.startsWith("event:")) event = line.slice(6).trim();
    else if (line.startsWith("data:")) dataLines.push(line.slice(5).trim());
  }
  if (dataLines.length === 0) return;

  let payload: any;
  try {
    payload = JSON.parse(dataLines.join("\n"));
  } catch {
    return;
  }

  if (event === "token") handlers.onToken(payload.text ?? "");
  else if (event === "meta") handlers.onMeta?.(payload as ChatMeta);
  else if (event === "error") handlers.onError?.(payload.message ?? "unknown error");
}
