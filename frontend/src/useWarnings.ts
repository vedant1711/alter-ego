import { useCallback, useRef, useState } from "react";
import type { Warning } from "./types";

/**
 * Tracks the degradations currently worth showing.
 *
 * Every response that can carry warnings reports the *whole* current set, so
 * the banner self-heals: once Aura is resumed, the next request reports no
 * warnings and the banner clears on its own without anyone reloading.
 *
 * Dismissal is remembered only while the condition persists. If a warning
 * clears and later returns, it is shown again — a dismissal means "I have read
 * this", not "never tell me about this again".
 */
export function useWarnings() {
  const [warnings, setWarnings] = useState<Warning[]>([]);
  const dismissed = useRef<Set<string>>(new Set());

  const report = useCallback((incoming: Warning[] | undefined) => {
    const next = incoming ?? [];
    const present = new Set(next.map((w) => w.code));
    for (const code of [...dismissed.current]) {
      if (!present.has(code)) dismissed.current.delete(code);
    }
    setWarnings(next.filter((w) => !dismissed.current.has(w.code)));
  }, []);

  const dismiss = useCallback((code: string) => {
    dismissed.current.add(code);
    setWarnings((prev) => prev.filter((w) => w.code !== code));
  }, []);

  return { warnings, report, dismiss };
}

export const COLD_START: Warning = {
  code: "cold_start",
  message: "Waking the backend — this is the first visit in a while.",
  action:
    "The free hosting tier sleeps after 15 minutes idle, so the first request can take up to 30 seconds. Retrying automatically.",
};

export const OFFLINE_MODE: Warning = {
  code: "offline_mode",
  message: "Offline mode — no GEMINI_API_KEY is configured.",
  action: "Replies are templated rather than generated. Everything else works normally.",
};
