# Diagrams

Source-of-truth JSON IR in `src/`, rendered to self-contained interactive HTML
alongside it. Rendered with [archify](https://github.com/tt-a1i/archify) (MIT).

| Diagram | Source | Shows |
|---|---|---|
| `chat-turn.html` | `src/chat-turn.dataflow.json` | One chat turn: three retrievers → rank fusion → styled reply |
| `system.html` | `src/system.architecture.json` | Services, stores, fallbacks, and where secrets stay |
| `ingest.html` | `src/ingest.sequence.json` | What happens when one memory is added |

## Regenerating

The JSON is the source; the HTML is a build artifact. After editing a source
file, re-render it:

```bash
npx skills add tt-a1i/archify -g          # once

node ~/.agents/skills/archify/bin/archify.mjs \
  deliver dataflow src/chat-turn.dataflow.json chat-turn.html --quality showcase
node ~/.agents/skills/archify/bin/archify.mjs \
  deliver architecture src/system.architecture.json system.html --quality showcase
node ~/.agents/skills/archify/bin/archify.mjs \
  deliver sequence src/ingest.sequence.json ingest.html --quality showcase

cp chat-turn.html system.html ingest.html ../frontend/public/diagrams/
```

`validate` runs the same checks without writing output. All three pass showcase
composition with 0 errors and 0 warnings.

`visual-check` additionally reports a containment failure on all three — it
wants the whole page, diagram plus explanation cards, inside a single 1440x900
viewport without scrolling. Archify's own shipped examples fail the same check,
so it is treated as aspirational rather than a defect. The diagrams scroll.
