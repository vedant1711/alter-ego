import { useCallback, useEffect, useRef, useState } from "react";
import {
  chat,
  createSession,
  getGraph,
  ingest,
  loadExample,
  warmUp,
  type IngestSource,
} from "./api";
import ChatPanel from "./components/ChatPanel";
import GraphView from "./components/GraphView";
import HowItWorks from "./components/HowItWorks";
import Onboarding from "./components/Onboarding";
import RetrievedMemories from "./components/RetrievedMemories";
import Warnings from "./components/Warnings";
import { COLD_START, OFFLINE_MODE, useWarnings } from "./useWarnings";
import type { ChatMessage, GraphData, RetrievedMemory } from "./types";

type Boot = "warming" | "ready" | "failed";

let idSeq = 0;
const nextId = () => `m${++idSeq}`;

export default function App() {
  const [boot, setBoot] = useState<Boot>("warming");
  const [offline, setOffline] = useState(false);
  const [coldStart, setColdStart] = useState(false);
  const { warnings, report, dismiss } = useWarnings();
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [retrieved, setRetrieved] = useState<RetrievedMemory[]>([]);
  const [graph, setGraph] = useState<GraphData>({ nodes: [], edges: [] });
  const [busy, setBusy] = useState(false);
  const [exampleLoaded, setExampleLoaded] = useState(false);
  const [tab, setTab] = useState<"chat" | "how">("chat");
  const [suggestions, setSuggestions] = useState<string[]>([]);
  const sessionId = useRef<string | null>(null);

  const [attempt, setAttempt] = useState(0);

  useEffect(() => {
    let cancelled = false;
    setBoot("warming");
    (async () => {
      try {
        const h = await warmUp(() => {
          if (!cancelled) setColdStart(true);
        });
        const sid = await createSession();
        if (cancelled) return;
        sessionId.current = sid;
        setOffline(h.offline);
        setColdStart(false);
        report(h.warnings);
        setBoot("ready");
      } catch {
        if (!cancelled) {
          setColdStart(false);
          setBoot("failed");
        }
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [attempt]);

  const refreshGraph = useCallback(async () => {
    const sid = sessionId.current;
    if (!sid) return;
    try {
      const g = await getGraph(sid);
      setGraph(g);
      report(g.warnings);
    } catch {
      // A failed refresh just leaves the last good graph on screen.
    }
  }, [report]);

  const addMemory = useCallback(
    async (text: string, source: IngestSource) => {
      const sid = sessionId.current;
      if (!sid) throw new Error("no session");
      const result = await ingest(sid, text, source);
      report(result.warnings);
      await refreshGraph();
    },
    [refreshGraph, report]
  );

  const seedExample = useCallback(async () => {
    const sid = sessionId.current;
    if (!sid) throw new Error("no session");
    const persona = await loadExample(sid);
    setExampleLoaded(true);
    setSuggestions(persona.suggested_questions);
    report(persona.warnings);
    await refreshGraph();
  }, [refreshGraph, report]);

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
    setTab("chat");

    const patch = (fn: (m: ChatMessage) => ChatMessage) =>
      setMessages((prev) => prev.map((m) => (m.id === replyId ? fn(m) : m)));

    try {
      await chat(sid, text, {
        onToken: (chunk) => patch((m) => ({ ...m, text: m.text + chunk })),
        onMeta: (meta) => {
          setRetrieved(meta.retrieved_memories ?? []);
          report(meta.warnings);
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
  }, [refreshGraph, report]);

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

      <Warnings
        warnings={[
          ...(coldStart ? [COLD_START] : []),
          ...(offline ? [OFFLINE_MODE] : []),
          ...warnings,
        ]}
        onDismiss={dismiss}
      />

      {boot === "failed" && (
        <div className="shrink-0 border-b border-red-900/60 bg-red-950/30 px-5 py-2 text-xs text-red-300">
          Could not reach the backend. It may still be waking up from sleep.{" "}
          <button
            onClick={() => setAttempt((n) => n + 1)}
            className="underline underline-offset-2 hover:text-red-200"
          >
            Try again
          </button>
        </div>
      )}

      <main className="grid min-h-0 flex-1 grid-cols-1 overflow-y-auto lg:grid-cols-[20rem_1fr_22rem] lg:overflow-hidden">
        <div className="min-h-0 border-b border-ink-800 lg:border-r lg:border-b-0">
          <Onboarding
            disabled={notReady}
            onIngest={addMemory}
            exampleLoaded={exampleLoaded}
            onLoadExample={seedExample}
          />
        </div>
        <div className="flex min-h-[70vh] flex-col lg:min-h-0">
          <nav className="flex shrink-0 gap-1 border-b border-ink-800 px-3 pt-2">
            <Tab active={tab === "chat"} onClick={() => setTab("chat")}>
              Chat
            </Tab>
            <Tab active={tab === "how"} onClick={() => setTab("how")}>
              How it works
            </Tab>
          </nav>
          <div className="min-h-0 flex-1">
            {/* Both stay mounted: switching tabs must not drop the transcript,
                nor re-download the diagrams. */}
            <div className={tab === "chat" ? "h-full" : "hidden"}>
              <ChatPanel
                messages={messages}
                busy={busy}
                disabled={notReady}
                suggestions={suggestions}
                onSend={send}
              />
            </div>
            <div className={tab === "how" ? "h-full" : "hidden"}>
              <HowItWorks />
            </div>
          </div>
        </div>
        <aside className="flex min-h-0 flex-col divide-y divide-ink-800 border-t border-ink-800 lg:overflow-y-auto lg:border-t-0 lg:border-l">
          <GraphView data={graph} />
          <RetrievedMemories memories={retrieved} />
        </aside>
      </main>
    </div>
  );
}

function Tab({
  active,
  onClick,
  children,
}: {
  active: boolean;
  onClick: () => void;
  children: React.ReactNode;
}) {
  return (
    <button
      onClick={onClick}
      className={[
        "rounded-t-lg px-3 py-1.5 text-xs font-medium transition",
        active
          ? "border-b-2 border-accent text-white"
          : "border-b-2 border-transparent text-ink-400 hover:text-ink-200",
      ].join(" ")}
    >
      {children}
    </button>
  );
}

function StatusDot({ boot }: { boot: Boot }) {
  const label =
    boot === "warming"
      ? "waking backend…"
      : boot === "ready"
        ? "connected"
        : "backend unreachable";
  const color =
    boot === "ready" ? "bg-accent" : boot === "failed" ? "bg-red-500" : "bg-ink-600 animate-pulse";
  return (
    <span className="flex items-center gap-2 text-xs text-ink-400">
      <span className={`h-2 w-2 rounded-full ${color}`} />
      {label}
    </span>
  );
}
