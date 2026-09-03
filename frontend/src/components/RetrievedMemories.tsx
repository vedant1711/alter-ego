import type { RetrievedMemory } from "../types";

const LEG_STYLES: Record<string, string> = {
  graph: "border-emerald-800 bg-emerald-950/40 text-emerald-300",
  vector: "border-violet-800 bg-violet-950/40 text-violet-300",
  keyword: "border-amber-800 bg-amber-950/40 text-amber-300",
};

export default function RetrievedMemories({ memories }: { memories: RetrievedMemory[] }) {
  return (
    <div className="flex min-h-0 flex-col">
      <header className="px-4 py-3">
        <h3 className="text-xs font-medium tracking-wide text-white uppercase">
          Memories used for the last reply
        </h3>
        <p className="mt-1 text-xs text-ink-400">
          Tagged by which retrieval leg surfaced them.
        </p>
      </header>

      <div className="min-h-0 flex-1 space-y-2 overflow-y-auto px-4 pb-4">
        {memories.length === 0 ? (
          <p className="py-6 text-center text-xs text-ink-600">
            Send a message to see what the twin recalled.
          </p>
        ) : (
          memories.map((m, i) => (
            <article key={i} className="rounded-lg border border-ink-800 bg-ink-900 p-3">
              <div className="mb-1.5 flex flex-wrap items-center gap-1.5">
                {m.source.map((leg) => (
                  <span
                    key={leg}
                    className={`rounded border px-1.5 py-0.5 text-[10px] font-medium ${
                      LEG_STYLES[leg] ?? "border-ink-700 bg-ink-800 text-ink-400"
                    }`}
                  >
                    {leg}
                  </span>
                ))}
                <span className="rounded border border-ink-700 px-1.5 py-0.5 text-[10px] text-ink-400">
                  {m.source_type}
                </span>
                <span className="ml-auto font-mono text-[10px] text-ink-600">
                  {m.score.toFixed(3)}
                </span>
              </div>
              <p className="text-xs leading-relaxed text-ink-200">{m.text}</p>
            </article>
          ))
        )}
      </div>
    </div>
  );
}
