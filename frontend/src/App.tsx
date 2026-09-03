import { useCallback, useEffect, useRef, useState } from "react";
import {
  chat,
  createSession,
  getGraph,
  health,
  ingest,
  loadExample,
  type IngestSource,
} from "./api";
import ChatPanel from "./components/ChatPanel";
import GraphView from "./components/GraphView";
import Onboarding from "./components/Onboarding";
import RetrievedMemories from "./components/RetrievedMemories";
import type { ChatMessage, GraphData, RetrievedMemory } from "./types";

type Boot = "warming" | "ready" | "failed";

let idSeq = 0;
const nextId = () => `m${++idSeq}`;

export default function App() {
  const [boot, setBoot] = useState<Boot>("warming");
  const [offline, setOffline] = useState(false);
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [retrieved, setRetrieved] = useState<RetrievedMemory[]>([]);
  const [graph, setGraph] = useState<GraphData>({ nodes: [], edges: [] });
  const [busy, setBusy] = useState(false);
  const [exampleLoaded, setExampleLoaded] = useState(false);
  const [suggestions, setSuggestions] = useState<string[]>([]);
  const sessionId = useRef<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        // Render Free sleeps after 15 min idle; this ping absorbs the cold start.
        const h = await health();
        const sid = await createSession();
        if (cancelled) return;
        sessionId.current = sid;
        setOffline(h.offline);
        setBoot("ready");
      } catch {
        if (!cancelled) setBoot("failed");
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  const refreshGraph = useCallback(async () => {
    const sid = sessionId.current;
    if (!sid) return;
    try {
      setGraph(await getGraph(sid));
    } catch {
      // A failed refresh just leaves the last good graph on screen.
    }
  }, []);

  const addMemory = useCallback(
    async (text: string, source: IngestSource) => {
      const sid = sessionId.current;
      if (!sid) throw new Error("no session");
      await ingest(sid, text, source);
      await refreshGraph();
    },
    [refreshGraph]
  );

  const seedExample = useCallback(async () => {
    const sid = sessionId.current;
    if (!sid) throw new Error("no session");
    const persona = await loadExample(sid);
    setExampleLoaded(true);
    setSuggestions(persona.suggested_questions);
    await refreshGraph();
  }, [refreshGraph]);

  const send = useCallback(async (text: string) => {
    const sid = sessionId.current;
    if (!sid) return;

    const replyId = nextId();
    setMessages((prev) => [
      ...prev,
      { id: nextId(), role: "user", text },
      { id: replyId, role: "twin", text: "", streaming: true },
    ]);
    setBusy(true);
    setSuggestions([]);

    const patch = (fn: (m: ChatMessage) => ChatMessage) =>
      setMessages((prev) => prev.map((m) => (m.id === replyId ? fn(m) : m)));

    try {
      await chat(sid, text, {
        onToken: (chunk) => patch((m) => ({ ...m, text: m.text + chunk })),
        onMeta: (meta) => {
          setRetrieved(meta.retrieved_memories ?? []);
          // The delta says whether the turn changed the graph at all.
          const delta = meta.graph_delta;
          if (delta && (delta.nodes.length > 0 || delta.edges.length > 0)) void refreshGraph();
        },
        onError: (msg) => patch((m) => ({ ...m, text: msg, error: true })),
      });
    } catch (err) {
      patch((m) => ({ ...m, text: String(err), error: true }));
    } finally {
      patch((m) => ({ ...m, streaming: false }));
      setBusy(false);
    }
  }, [refreshGraph]);

  const notReady = boot !== "ready";

  return (
    <div className="flex h-full flex-col">
      <header className="flex shrink-0 items-center justify-between border-b border-ink-800 px-5 py-3">
        <div>
          <h1 className="text-base font-semibold tracking-tight text-white">ALTER EGO</h1>
          <p className="text-xs text-ink-400">
            A digital twin with hybrid graph + vector + keyword memory.
          </p>
        </div>
        <StatusDot boot={boot} />
      </header>

      {offline && (
        <p className="shrink-0 border-b border-amber-900/60 bg-amber-950/30 px-5 py-2 text-xs text-amber-300">
          Offline mode — no <code>GEMINI_API_KEY</code> is configured, so replies are templated
          rather than generated.
        </p>
      )}

      <main className="grid min-h-0 flex-1 grid-cols-1 lg:grid-cols-[20rem_1fr_22rem]">
        <div className="min-h-0 border-ink-800 lg:border-r">
          <Onboarding
            disabled={notReady}
            onIngest={addMemory}
            exampleLoaded={exampleLoaded}
            onLoadExample={seedExample}
          />
        </div>
        <div className="min-h-0">
          <ChatPanel
            messages={messages}
            busy={busy}
            disabled={notReady}
            suggestions={suggestions}
            onSend={send}
          />
        </div>
        <aside className="flex min-h-0 flex-col divide-y divide-ink-800 overflow-y-auto border-ink-800 lg:border-l">
          <GraphView data={graph} />
          <RetrievedMemories memories={retrieved} />
        </aside>
      </main>
    </div>
  );
}

function StatusDot({ boot }: { boot: Boot }) {
  const label =
    boot === "warming" ? "waking backend…" : boot === "ready" ? "connected" : "backend unreachable";
  const color =
    boot === "ready" ? "bg-accent" : boot === "failed" ? "bg-red-500" : "bg-ink-600 animate-pulse";
  return (
    <span className="flex items-center gap-2 text-xs text-ink-400">
      <span className={`h-2 w-2 rounded-full ${color}`} />
      {label}
    </span>
  );
}
