import type { Warning } from "../types";

/**
 * Severity per warning code.
 *
 * "info" is for conditions that are expected and already being handled — a
 * cold start is slow, not broken, and saying so stops it reading as a fault.
 * "warn" is for degradations the user may want to act on.
 */
const SEVERITY: Record<string, "info" | "warn"> = {
  cold_start: "info",
  offline_mode: "info",
  graph_unavailable: "warn",
  graph_auth: "warn",
  graph_error: "warn",
};

const STYLES = {
  info: {
    box: "border-sky-900/60 bg-sky-950/30",
    label: "text-sky-300",
    body: "text-sky-200/80",
  },
  warn: {
    box: "border-amber-900/60 bg-amber-950/30",
    label: "text-amber-300",
    body: "text-amber-200/80",
  },
} as const;

interface Props {
  warnings: Warning[];
  onDismiss: (code: string) => void;
}

export default function Warnings({ warnings, onDismiss }: Props) {
  if (warnings.length === 0) return null;

  return (
    <div className="flex shrink-0 flex-col">
      {warnings.map((w) => {
        const tone = STYLES[SEVERITY[w.code] ?? "warn"];
        return (
          <div
            key={w.code}
            role="status"
            className={`flex items-start gap-3 border-b px-5 py-2.5 text-xs ${tone.box}`}
          >
            <div className="min-w-0 flex-1">
              <p className={`font-medium ${tone.label}`}>{w.message}</p>
              {w.action && <p className={`mt-0.5 leading-relaxed ${tone.body}`}>{w.action}</p>}
            </div>
            <button
              onClick={() => onDismiss(w.code)}
              aria-label="Dismiss"
              className={`shrink-0 rounded px-1.5 leading-none opacity-60 transition hover:opacity-100 ${tone.label}`}
            >
              ×
            </button>
          </div>
        );
      })}
    </div>
  );
}
