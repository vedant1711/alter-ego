import { useEffect, useRef, useState, type FormEvent } from "react";
import type { ChatMessage } from "../types";

interface Props {
  messages: ChatMessage[];
  busy: boolean;
  disabled: boolean;
  onSend: (text: string) => void;
}

export default function ChatPanel({ messages, busy, disabled, onSend }: Props) {
  const [draft, setDraft] = useState("");
  const endRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: "smooth", block: "end" });
  }, [messages]);

  function submit(e: FormEvent) {
    e.preventDefault();
    const text = draft.trim();
    if (!text || busy || disabled) return;
    onSend(text);
    setDraft("");
  }

  return (
    <section className="flex h-full min-h-0 flex-col">
      <header className="border-b border-ink-800 px-5 py-3">
        <h2 className="text-sm font-medium text-white">Chat with your twin</h2>
        <p className="text-xs text-ink-400">
          Replies are generated from your memories, in your voice.
        </p>
      </header>

      <div className="min-h-0 flex-1 space-y-4 overflow-y-auto px-5 py-5">
        {messages.length === 0 && (
          <div className="mx-auto mt-16 max-w-sm text-center text-sm text-ink-400">
            <p className="text-ink-200">Nothing in memory yet.</p>
            <p className="mt-2">
              Load the example persona on the left, or add a writing sample and a few facts,
              then say hello.
            </p>
          </div>
        )}

        {messages.map((m) => (
          <Bubble key={m.id} message={m} />
        ))}
        <div ref={endRef} />
      </div>

      <form onSubmit={submit} className="border-t border-ink-800 p-4">
        <div className="flex items-end gap-2">
          <textarea
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && !e.shiftKey) submit(e);
            }}
            rows={2}
            placeholder={disabled ? "Connecting…" : "Ask your twin something…"}
            disabled={disabled}
            className="min-h-[3rem] flex-1 resize-none rounded-lg border border-ink-700 bg-ink-900 px-3 py-2 text-sm text-ink-200 outline-none placeholder:text-ink-600 focus:border-accent disabled:opacity-50"
          />
          <button
            type="submit"
            disabled={busy || disabled || !draft.trim()}
            className="h-[3rem] rounded-lg bg-accent px-4 text-sm font-medium text-white transition hover:bg-accent-soft disabled:cursor-not-allowed disabled:opacity-40"
          >
            {busy ? "…" : "Send"}
          </button>
        </div>
      </form>
    </section>
  );
}

function Bubble({ message }: { message: ChatMessage }) {
  const isUser = message.role === "user";
  return (
    <div className={isUser ? "flex justify-end" : "flex justify-start"}>
      <div
        className={[
          "max-w-[85%] rounded-2xl px-4 py-2.5 text-sm leading-relaxed whitespace-pre-wrap",
          isUser
            ? "bg-accent text-white"
            : message.error
              ? "border border-red-900 bg-red-950/40 text-red-300"
              : "border border-ink-700 bg-ink-850 text-ink-200",
        ].join(" ")}
      >
        {message.text}
        {message.streaming && <span className="ml-0.5 animate-pulse text-accent-soft">▍</span>}
      </div>
    </div>
  );
}
