import { useEffect, useState } from "react";
import { health } from "./api";

type Status = "warming" | "ok" | "down";

export default function App() {
  const [status, setStatus] = useState<Status>("warming");

  useEffect(() => {
    health()
      .then(() => setStatus("ok"))
      .catch(() => setStatus("down"));
  }, []);

  return (
    <div className="flex h-full items-center justify-center">
      <div className="text-center">
        <h1 className="text-4xl font-semibold tracking-tight text-white">ALTER EGO</h1>
        <p className="mt-2 text-sm text-ink-400">
          A digital twin with hybrid graph + vector + keyword memory.
        </p>
        <p className="mt-6 text-sm">
          backend:{" "}
          <span
            className={
              status === "ok"
                ? "text-accent-soft"
                : status === "down"
                  ? "text-red-400"
                  : "text-ink-400"
            }
          >
            {status === "warming" ? "waking up…" : status}
          </span>
        </p>
      </div>
    </div>
  );
}
