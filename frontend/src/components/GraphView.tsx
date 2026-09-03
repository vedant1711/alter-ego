import { useEffect, useMemo, useRef, useState } from "react";
import ForceGraph2D from "react-force-graph-2d";
import type { GraphData } from "../types";

/** One colour per entity type, matching the legend below the canvas. */
const TYPE_COLORS: Record<string, string> = {
  Person: "#7c5cff",
  Place: "#34d399",
  Organization: "#38bdf8",
  Project: "#fbbf24",
  Preference: "#f472b6",
  Event: "#fb923c",
  Object: "#a3a3a3",
  Concept: "#94a3b8",
};

const FALLBACK_COLOR = "#94a3b8";

interface ForceNode {
  id: string;
  label: string;
  type: string;
  x?: number;
  y?: number;
}

interface ForceLink {
  source: string;
  target: string;
  type: string;
}

export default function GraphView({ data }: { data: GraphData }) {
  const wrapper = useRef<HTMLDivElement>(null);
  const [size, setSize] = useState({ width: 0, height: 0 });

  // ForceGraph needs explicit pixel dimensions, so track the container.
  useEffect(() => {
    const el = wrapper.current;
    if (!el) return;
    const observer = new ResizeObserver(([entry]) => {
      const { width, height } = entry.contentRect;
      setSize({ width, height });
    });
    observer.observe(el);
    return () => observer.disconnect();
  }, []);

  // ForceGraph mutates the objects it is handed (it writes x/y onto nodes and
  // swaps link endpoints for node refs), so hand it a fresh copy each time.
  const graph = useMemo(
    () => ({
      nodes: data.nodes.map((n) => ({ ...n })) as ForceNode[],
      links: data.edges.map((e) => ({ ...e })) as ForceLink[],
    }),
    [data]
  );

  const types = useMemo(
    () => Array.from(new Set(data.nodes.map((n) => n.type))).sort(),
    [data.nodes]
  );

  return (
    <div className="flex min-h-0 flex-col">
      <header className="px-4 py-3">
        <h3 className="text-xs font-medium tracking-wide text-white uppercase">
          Knowledge graph
        </h3>
        <p className="mt-1 text-xs text-ink-400">
          {data.nodes.length === 0
            ? "Grows as you add facts."
            : `${data.nodes.length} entities · ${data.edges.length} relationships`}
        </p>
      </header>

      <div ref={wrapper} className="relative h-64 shrink-0 bg-ink-900/60">
        {data.nodes.length === 0 ? (
          <p className="absolute inset-0 flex items-center justify-center px-6 text-center text-xs text-ink-600">
            Add a fact like “I work at Acme as a designer” and watch the nodes appear.
          </p>
        ) : (
          size.width > 0 && (
            <ForceGraph2D
              graphData={graph}
              width={size.width}
              height={size.height}
              backgroundColor="rgba(0,0,0,0)"
              cooldownTicks={80}
              d3VelocityDecay={0.3}
              linkColor={() => "#333849"}
              linkDirectionalArrowLength={3}
              linkDirectionalArrowRelPos={1}
              linkLabel={(l: any) => l.type}
              nodeLabel={(n: any) => `${n.label} (${n.type})`}
              nodeRelSize={4}
              nodeCanvasObject={(node: any, ctx, scale) => {
                const color = TYPE_COLORS[node.type] ?? FALLBACK_COLOR;
                ctx.beginPath();
                ctx.arc(node.x, node.y, 4, 0, 2 * Math.PI);
                ctx.fillStyle = color;
                ctx.fill();

                // Labels only once zoomed in enough to stay readable.
                if (scale > 1.2) {
                  ctx.font = `${11 / scale}px ui-sans-serif, system-ui, sans-serif`;
                  ctx.textAlign = "center";
                  ctx.textBaseline = "top";
                  ctx.fillStyle = "#c3c9d8";
                  ctx.fillText(node.label, node.x, node.y + 6);
                }
              }}
              nodePointerAreaPaint={(node: any, color, ctx) => {
                ctx.beginPath();
                ctx.arc(node.x, node.y, 6, 0, 2 * Math.PI);
                ctx.fillStyle = color;
                ctx.fill();
              }}
            />
          )
        )}
      </div>

      {types.length > 0 && (
        <ul className="flex flex-wrap gap-x-3 gap-y-1 px-4 py-2 text-[10px] text-ink-400">
          {types.map((t) => (
            <li key={t} className="flex items-center gap-1">
              <span
                className="h-1.5 w-1.5 rounded-full"
                style={{ backgroundColor: TYPE_COLORS[t] ?? FALLBACK_COLOR }}
              />
              {t}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
