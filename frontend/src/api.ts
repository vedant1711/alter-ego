/** Thin client for the ALTER EGO backend. */

import type { GraphData, RetrievedMemory, Warning } from "./types";

// Empty in dev: Vite proxies /api to the local backend (see vite.config.ts).
// In production this is the Render URL, injected at build time.
export const API_BASE = (import.meta.env.VITE_API_BASE ?? "").replace(/\/$/, "");

function url(path: string): string {
  return `${API_BASE}/api${path}`;
}

export interface Health {
  status: string;
  offline: boolean;
  stores?: Record<string, { durable: boolean; reachable: boolean }>;
  warnings?: Warning[];
}

export async function health(): Promise<Health> {
  const res = await fetch(url("/health"));
  if (!res.ok) throw new Error(`health failed: ${res.status}`);
  return res.json();
}

/**
 * Wake the backend, retrying while it boots.
 *
 * Render Free suspends a service after 15 minutes idle, and the first request
 * back pays a 10-30s cold start that often shows up as a failed fetch rather
 * than a slow one — so this retries instead of giving up.
 */
export async function warmUp(
  onRetry?: (attempt: number) => void,
  attempts = 6,
  delayMs = 4000
): Promise<Health> {
  let lastError: unknown;
  for (let i = 0; i < attempts; i++) {
    try {
      return await health();
    } catch (err) {
      lastError = err;
      if (i < attempts - 1) {
        // The first failure is the signal that we are paying a cold start,
        // not that the backend is down — tell the UI so it can say so.
        onRetry?.(i + 1);
        await new Promise((r) => setTimeout(r, delayMs));
      }
    }
  }
  throw lastError;
}

export async function createSession(): Promise<string> {
  const res = await fetch(url("/session"), { method: "POST" });
  if (!res.ok) throw new Error(`session failed: ${res.status}`);
  return (await res.json()).session_id;
}

export interface ChatMeta {
  retrieved_memories: RetrievedMemory[];
  graph_delta: GraphData | null;
  warnings?: Warning[];
}

export async function getGraph(sessionId: string): Promise<GraphData> {
  const res = await fetch(`${url("/graph")}?session_id=${encodeURIComponent(sessionId)}`);
  if (!res.ok) throw new Error(`graph failed: ${res.status}`);
  return res.json();
}

export type IngestSource = "sample" | "fact";

export interface IngestResult {
  memory_id: string;
  entities_added: number;
  relationships_added: number;
  warnings?: Warning[];
}

export async function ingest(
  sessionId: string,
  text: string,
  source: IngestSource
): Promise<IngestResult> {
  const res = await fetch(url("/ingest"), {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ session_id: sessionId, text, source }),
  });
  if (!res.ok) throw new Error(await detail(res));
  return res.json();
}

export interface ExamplePersona {
  name: string;
  tagline: string;
  memories_added: number;
  entities_added: number;
  relationships_added: number;
  suggested_questions: string[];
  already_loaded: boolean;
  warnings?: Warning[];
}

export async function loadExample(sessionId: string): Promise<ExamplePersona> {
  const res = await fetch(url("/load-example"), {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ session_id: sessionId }),
  });
  if (!res.ok) throw new Error(await detail(res));
  return res.json();
}

/** Surface the backend's own message (rate limits, length caps) when it sends one. */
async function detail(res: Response): Promise<string> {
  try {
    const body = await res.json();
    if (typeof body?.detail === "string") return body.detail;
  } catch {
    // fall through to the status code
  }
  return `Request failed: ${res.status}`;
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
    throw new Error(await detail(res));
  }

  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";

  for (;;) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer = normalizeNewlines(buffer + decoder.decode(value, { stream: true }));

    // SSE frames are separated by a blank line.
    let split: number;
    while ((split = buffer.indexOf("\n\n")) !== -1) {
      const frame = buffer.slice(0, split);
      buffer = buffer.slice(split + 2);
      dispatch(frame, handlers);
    }
  }

  // A final frame with no trailing blank line would otherwise be dropped.
  const tail = normalizeNewlines(buffer + decoder.decode()).trim();
  if (tail) dispatch(tail, handlers);
}

/**
 * Collapse CRLF and lone CR to LF.
 *
 * The SSE spec allows any of the three as a line terminator, and sse-starlette
 * emits CRLF — so frames arrive separated by "\r\n\r\n", which contains no
 * "\n\n" for the frame splitter to find. Without this every frame is silently
 * dropped and the reply renders as an empty bubble.
 *
 * A trailing CR is left alone: it may be the first half of a CRLF that lands
 * in the next chunk, and converting it early would split a frame in two.
 */
function normalizeNewlines(buffer: string): string {
  const danglingCR = buffer.endsWith("\r");
  const head = danglingCR ? buffer.slice(0, -1) : buffer;
  return head.replace(/\r\n|\r/g, "\n") + (danglingCR ? "\r" : "");
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
