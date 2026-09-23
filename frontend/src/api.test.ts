import { afterEach, describe, expect, it, vi } from "vitest";
import { chat } from "./api";

/**
 * Builds a fake fetch Response whose body streams `chunks` verbatim.
 *
 * The chunk boundaries matter: a real network splits the byte stream at
 * arbitrary points, including in the middle of a "\r\n" pair, and the parser
 * has to survive that.
 */
function streamOf(chunks: string[]): Response {
  const encoder = new TextEncoder();
  const body = new ReadableStream<Uint8Array>({
    start(controller) {
      for (const chunk of chunks) controller.enqueue(encoder.encode(chunk));
      controller.close();
    },
  });
  return new Response(body, { status: 200, headers: { "Content-Type": "text/event-stream" } });
}

function mockFetch(chunks: string[]) {
  const fn = vi.fn().mockResolvedValue(streamOf(chunks));
  vi.stubGlobal("fetch", fn);
  return fn;
}

async function collect(chunks: string[]) {
  mockFetch(chunks);
  const tokens: string[] = [];
  let meta: unknown = null;
  let error: string | null = null;
  await chat("s1", "hi", {
    onToken: (t) => tokens.push(t),
    onMeta: (m) => (meta = m),
    onError: (e) => (error = e),
  });
  return { tokens, meta, error };
}

afterEach(() => vi.unstubAllGlobals());

describe("SSE frame parsing", () => {
  // sse-starlette terminates frames with CRLF. A parser that only looks for
  // "\n\n" finds no boundary in "\r\n\r\n" and silently drops every frame,
  // which renders as an empty reply bubble. This is a regression guard.
  it("parses CRLF-terminated frames, as sse-starlette emits them", async () => {
    const { tokens, error } = await collect([
      'event: token\r\ndata: {"text": "hello "}\r\n\r\n',
      'event: token\r\ndata: {"text": "world"}\r\n\r\n',
    ]);
    expect(error).toBeNull();
    expect(tokens.join("")).toBe("hello world");
  });

  it("parses LF-terminated frames too", async () => {
    const { tokens } = await collect(['event: token\ndata: {"text": "plain lf"}\n\n']);
    expect(tokens.join("")).toBe("plain lf");
  });

  it("survives a chunk boundary that splits a CRLF pair", async () => {
    const { tokens } = await collect([
      'event: token\r\ndata: {"text": "split"}\r',
      '\n\r\nevent: token\r\ndata: {"text": "-ok"}\r\n\r\n',
    ]);
    expect(tokens.join("")).toBe("split-ok");
  });

  it("reassembles a frame split across several chunks", async () => {
    const { tokens } = await collect(["event: tok", 'en\r\ndata: {"te', 'xt": "abc"}\r\n\r\n']);
    expect(tokens.join("")).toBe("abc");
  });

  it("routes the terminal meta event", async () => {
    const { meta } = await collect([
      'event: token\r\ndata: {"text": "x"}\r\n\r\n',
      'event: meta\r\ndata: {"retrieved_memories": [{"text": "m", "source": ["graph"], "score": 1, "source_type": "graph"}], "graph_delta": null}\r\n\r\n',
    ]);
    expect(meta).toMatchObject({
      retrieved_memories: [{ source: ["graph"] }],
    });
  });

  it("routes an error event", async () => {
    const { error } = await collect(['event: error\r\ndata: {"message": "quota spent"}\r\n\r\n']);
    expect(error).toBe("quota spent");
  });

  it("still dispatches a final frame with no trailing blank line", async () => {
    const { tokens } = await collect(['event: token\r\ndata: {"text": "last"}']);
    expect(tokens.join("")).toBe("last");
  });

  it("ignores keepalive comments and malformed payloads", async () => {
    const { tokens, error } = await collect([
      ": ping\r\n\r\n",
      "event: token\r\ndata: {not json}\r\n\r\n",
      'event: token\r\ndata: {"text": "survived"}\r\n\r\n',
    ]);
    expect(error).toBeNull();
    expect(tokens.join("")).toBe("survived");
  });
});
