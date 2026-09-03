/** Thin client for the ALTER EGO backend. */

// Empty in dev: Vite proxies /api to the local backend (see vite.config.ts).
// In production this is the Render URL, injected at build time.
export const API_BASE = (import.meta.env.VITE_API_BASE ?? "").replace(/\/$/, "");

function url(path: string): string {
  return `${API_BASE}/api${path}`;
}

export async function health(): Promise<{ status: string }> {
  const res = await fetch(url("/health"));
  if (!res.ok) throw new Error(`health failed: ${res.status}`);
  return res.json();
}
