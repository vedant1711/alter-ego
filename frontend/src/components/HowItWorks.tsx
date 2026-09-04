import type { ReactNode } from "react";
import DiagramFrame from "./DiagramFrame";

export default function HowItWorks() {
  return (
    <section className="flex h-full min-h-0 flex-col">
      <header className="shrink-0 border-b border-ink-800 px-5 py-3">
        <h2 className="text-sm font-medium text-white">How it works</h2>
        <p className="text-xs text-ink-400">
          The memory system, end to end — and the parts that were harder than they look.
        </p>
      </header>

      <div className="min-h-0 flex-1 overflow-y-auto px-5 py-5">
        <div className="mx-auto max-w-2xl">
          <p className="text-sm leading-relaxed text-ink-200">
            A twin is just memory plus voice. You give it a few things you wrote and a few
            facts about yourself; every message after that is answered from what it can
            actually recall, phrased the way you phrase things. The interesting part is not
            the model — it is deciding <em className="text-white not-italic">which</em> of your
            memories a given question deserves.
          </p>

          <Section n="01" title="One chat turn">
            <P>
              A message fans out to three retrievers at once, their results are merged into a
              single ranking, and the winners become the grounding facts for a reply written in
              your voice. Nothing is invented: if the memories do not cover the question, the
              twin is told to say so.
            </P>
            <DiagramFrame
              src="/diagrams/chat-turn.html"
              title="One chat turn"
              caption="Query → three retrievers → rank fusion → styled, streamed reply."
              height={560}
            />
          </Section>

          <Section n="02" title="Why three retrievers">
            <P>
              Each leg is good at exactly what the others are bad at. Running one alone loses
              recall in a way you would not notice until it mattered.
            </P>
            <div className="my-4 overflow-x-auto">
              <table className="w-full border-collapse text-xs">
                <thead>
                  <tr className="border-b border-ink-700 text-left text-ink-400">
                    <Th>Leg</Th>
                    <Th>Finds</Th>
                    <Th>Misses</Th>
                  </tr>
                </thead>
                <tbody className="text-ink-200">
                  <Tr
                    leg="Vector"
                    color="text-violet-300"
                    finds="Paraphrases — “what do you do?” recalls “I work at Meridian”"
                    misses="Rare proper nouns it never saw in training"
                  />
                  <Tr
                    leg="Keyword"
                    color="text-amber-300"
                    finds="Exact names, jargon, project names"
                    misses="Rewordings with no shared vocabulary"
                  />
                  <Tr
                    leg="Graph"
                    color="text-emerald-300"
                    finds="Multi-hop structure — who you work with, on what, where"
                    misses="Anything not expressible as a relationship"
                  />
                </tbody>
              </table>
            </div>
            <P>
              The panel on the right tags every recalled memory with the legs that found it, so
              this is visible rather than claimed.
            </P>
          </Section>

          <Section n="03" title="Fusion by rank, not score">
            <P>
              Cosine similarity, BM25 saturation and graph adjacency are on completely
              incomparable scales — averaging them would be meaningless. So results are merged
              by their <em className="text-white not-italic">position</em> in each leg's ranking
              instead:
            </P>
            <Formula>score(memory) = Σ over legs of weight(leg) / (60 + rank)</Formula>
            <P>
              Reciprocal Rank Fusion needs no normalisation and no tuning, and it gives the
              property this system wants for free: a memory two legs agree on outranks one only
              a single leg found.
            </P>
            <Callout label="The failure mode this creates">
              Rewarding agreement systematically buries whichever leg overlaps least with the
              others. In a well-stocked session, vector and keyword agree on the same verbatim
              memories and take every slot, and the graph's terse triples — which share almost
              no vocabulary with them — get dropped entirely, taking the structural facts with
              them. The example persona exposed this exactly: six slots, zero graph results. So
              after fusion, each leg that found something is guaranteed one slot, displacing the
              weakest memory whose own legs stay covered without it.
            </Callout>
          </Section>

          <Section n="04" title="Adding a memory">
            <P>
              Ingestion is two model calls: one embedding, one extraction. The text becomes a
              vector <em className="text-white not-italic">and</em> a set of typed graph edges,
              and the keyword index is invalidated rather than rebuilt.
            </P>
            <DiagramFrame
              src="/diagrams/ingest.html"
              title="Ingesting one memory"
              caption="Meter first, then parse, then encrypt and persist across all three stores."
              height={560}
            />
            <P>
              Extraction is best-effort by design. If the model returns something unparseable,
              the ingest still succeeds — you lose graph edges for that memory, not the memory.
              Relationship types are sanitised to a fixed shape before they are ever
              interpolated into a Cypher query.
            </P>
          </Section>

          <Section n="05" title="Memory that ages">
            <P>
              Once a session holds more than a dozen live memories of a kind, the oldest eight
              are compressed into a single summary and flagged, which removes them from recall
              without deleting them. Summaries are compacted by the same rule, so old context
              decays in resolution instead of vanishing.
            </P>
            <P>
              The originals are only retired once the summary is safely stored, so a failure
              part-way through loses nothing — it simply retries on the next turn.
            </P>
          </Section>

          <Section n="06" title="Where everything runs">
            <P>
              Every external service is on a free tier, and every one of them is optional. An
              unconfigured store falls back to an in-process equivalent behind the same
              interface, so the app degrades instead of failing.
            </P>
            <DiagramFrame
              src="/diagrams/system.html"
              title="System architecture"
              caption="Services, stores, fallbacks, and the boundary secrets never cross."
              height={520}
            />
          </Section>

          <Section n="07" title="Privacy and isolation">
            <P>
              Sessions are anonymous and ephemeral — no accounts, no login. Each visitor gets a
              122-bit random session id, which is the only credential.
            </P>
            <ul className="my-3 space-y-2 text-sm leading-relaxed text-ink-200">
              <Li>
                Memory text is <strong className="font-medium text-white">encrypted at rest</strong>.
                Encryption lives inside the store's own serialisation, so no call site can write
                plaintext by forgetting to.
              </Li>
              <Li>
                Keys are <strong className="font-medium text-white">per session</strong>, derived
                from a master key with the session id as salt. One session's key cannot decrypt
                another's, so a filter bug could not produce readable text.
              </Li>
              <Li>
                Every store read filters on the session id — every Cypher clause, every vector
                search, and the keyword index is built per session from scratch.
              </Li>
            </ul>
            <Callout label="The documented tradeoff">
              Graph entity labels are stored in plaintext. They drive the visualisation and are
              queried by name during traversal, so encrypting them would mean decrypting the
              whole graph on every read or giving up name-based lookup. The sentence “I work at
              Meridian as a senior product designer” is ciphertext; the node “Meridian” is not.
            </Callout>
          </Section>

          <p className="mt-8 border-t border-ink-800 pt-5 text-xs leading-relaxed text-ink-400">
            Diagrams rendered with{" "}
            <a
              href="https://github.com/tt-a1i/archify"
              target="_blank"
              rel="noreferrer"
              className="text-accent-soft underline underline-offset-2"
            >
              archify
            </a>
            . Their JSON sources live in <code className="text-ink-200">diagrams/src/</code> and
            are regenerable — see <code className="text-ink-200">diagrams/README.md</code>.
          </p>
        </div>
      </div>
    </section>
  );
}

function Section({ n, title, children }: { n: string; title: string; children: ReactNode }) {
  return (
    <section className="mt-8">
      <h3 className="flex items-baseline gap-2.5 text-sm font-medium text-white">
        <span className="font-mono text-[11px] text-accent">{n}</span>
        {title}
      </h3>
      <div className="mt-2">{children}</div>
    </section>
  );
}

function P({ children }: { children: ReactNode }) {
  return <p className="my-3 text-sm leading-relaxed text-ink-200">{children}</p>;
}

function Li({ children }: { children: ReactNode }) {
  return (
    <li className="relative pl-4">
      <span className="absolute top-2 left-0 h-1 w-1 rounded-full bg-accent" />
      {children}
    </li>
  );
}

function Formula({ children }: { children: ReactNode }) {
  return (
    <pre className="my-3 overflow-x-auto rounded-lg border border-ink-700 bg-ink-900 px-4 py-3 font-mono text-xs text-accent-soft">
      {children}
    </pre>
  );
}

function Callout({ label, children }: { label: string; children: ReactNode }) {
  return (
    <aside className="my-4 rounded-lg border border-ink-700 bg-ink-850 p-4">
      <p className="text-[10px] font-medium tracking-wide text-accent uppercase">{label}</p>
      <p className="mt-1.5 text-xs leading-relaxed text-ink-200">{children}</p>
    </aside>
  );
}

function Th({ children }: { children: ReactNode }) {
  return <th className="pb-2 pr-3 font-medium">{children}</th>;
}

function Tr({
  leg,
  color,
  finds,
  misses,
}: {
  leg: string;
  color: string;
  finds: string;
  misses: string;
}) {
  return (
    <tr className="border-b border-ink-800 align-top">
      <td className={`py-2 pr-3 font-medium whitespace-nowrap ${color}`}>{leg}</td>
      <td className="py-2 pr-3">{finds}</td>
      <td className="py-2 text-ink-400">{misses}</td>
    </tr>
  );
}
