import { useState } from "react";
import type { IngestSource } from "../api";

interface Props {
  disabled: boolean;
  onIngest: (text: string, source: IngestSource) => Promise<void>;
}

export default function Onboarding({ disabled, onIngest }: Props) {
  return (
    <section className="flex h-full min-h-0 flex-col overflow-y-auto">
      <header className="border-b border-ink-800 px-5 py-3">
        <h2 className="text-sm font-medium text-white">Build your twin</h2>
        <p className="text-xs text-ink-400">Give it a voice, then give it facts.</p>
      </header>

      <div className="space-y-5 px-5 py-5">
        <IngestBox
          label="Writing samples"
          hint="Paste a few sentences you actually wrote — a message, a post, an email. The twin copies this tone."
          placeholder="shipping beats polishing. every time…"
          source="sample"
          disabled={disabled}
          onIngest={onIngest}
        />
        <IngestBox
          label="Facts about you"
          hint="One or two sentences per fact. These become nodes and edges in the knowledge graph."
          placeholder="I work at Acme as a product designer."
          source="fact"
          disabled={disabled}
          onIngest={onIngest}
        />
        <HowItWorks />
      </div>
    </section>
  );
}

interface BoxProps extends Props {
  label: string;
  hint: string;
  placeholder: string;
  source: IngestSource;
}

function IngestBox({ label, hint, placeholder, source, disabled, onIngest }: BoxProps) {
  const [text, setText] = useState("");
  const [busy, setBusy] = useState(false);
  const [note, setNote] = useState<string | null>(null);

  async function submit() {
    const value = text.trim();
    if (!value || busy) return;
    setBusy(true);
    setNote(null);
    try {
      await onIngest(value, source);
      setText("");
      setNote("Added to memory.");
    } catch (err) {
      setNote(String(err));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div>
      <label className="text-xs font-medium tracking-wide text-ink-200 uppercase">{label}</label>
      <p className="mt-1 mb-2 text-xs leading-relaxed text-ink-400">{hint}</p>
      <textarea
        value={text}
        onChange={(e) => setText(e.target.value)}
        rows={4}
        placeholder={placeholder}
        disabled={disabled}
        className="w-full resize-y rounded-lg border border-ink-700 bg-ink-900 px-3 py-2 text-sm text-ink-200 outline-none placeholder:text-ink-600 focus:border-accent disabled:opacity-50"
      />
      <button
        onClick={submit}
        disabled={disabled || busy || !text.trim()}
        className="mt-2 w-full rounded-lg border border-ink-700 bg-ink-800 py-2 text-xs font-medium text-ink-200 transition hover:border-accent hover:text-white disabled:cursor-not-allowed disabled:opacity-40"
      >
        {busy ? "Adding…" : "Add to memory"}
      </button>
      {note && <p className="mt-1.5 text-xs text-accent-soft">{note}</p>}
    </div>
  );
}

function HowItWorks() {
  const [open, setOpen] = useState(false);
  return (
    <div className="rounded-lg border border-ink-800">
      <button
        onClick={() => setOpen((v) => !v)}
        className="flex w-full items-center justify-between px-3 py-2 text-xs font-medium text-ink-200"
      >
        How it works
        <span className="text-ink-400">{open ? "−" : "+"}</span>
      </button>
      {open && (
        <div className="space-y-2 border-t border-ink-800 px-3 py-3 text-xs leading-relaxed text-ink-400">
          <p>
            Everything you add is parsed into memory: embedded into a{" "}
            <span className="text-ink-200">vector store</span> for semantic recall, indexed for{" "}
            <span className="text-ink-200">keyword</span> search, and extracted into a{" "}
            <span className="text-ink-200">knowledge graph</span> of entities and relationships.
          </p>
          <p>
            Each message runs all three retrievers, merges the results, and feeds the winners to the
            model along with your writing samples — so the reply is grounded in what you said and
            written how you write.
          </p>
          <p>The panel on the right shows exactly which memories were used.</p>
        </div>
      )}
    </div>
  );
}
