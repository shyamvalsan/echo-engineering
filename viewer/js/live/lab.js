// Optional lab server (uv run python -m echo.lab). Detected once at load; every call tolerates absence.
export const LAB_CMD = "uv run python -m echo.lab";
export const CLI_CMD = 'uv run python -m stages.custom --target <file> --name "<label>"';

async function json(url, opts = {}, ms = 4000) {
  const ac = new AbortController(), t = setTimeout(() => ac.abort(), ms);
  try { const r = await fetch(url, { ...opts, signal: ac.signal, cache: "no-cache" });
    const body = await r.json().catch(() => null);
    if (!r.ok) throw new Error(body?.error ?? body?.message ?? `${r.status} ${r.statusText}`);
    return body;
  } finally { clearTimeout(t); }
}

// API root: the server serves the repo root, the viewer lives at /viewer/
const api = (p) => new URL(`../api/${p}`, location.href).href;

export const lab = {
  health: null,
  async detect() {
    try { const h = await json(api("health"), {}, 1500); this.health = h?.ok ? h : null; } catch { this.health = null; }
    return this.health;
  },
  get present() { return !!this.health; },
  async inputs() { return this.present ? json(api("inputs")).catch(() => null) : null; },
  async design({ file, name, maxDuration = 1.0, tier1 = false }) {
    const fd = new FormData(); fd.append("target", file, file.name); fd.append("name", name); fd.append("max_duration_s", String(maxDuration)); fd.append("tier1", tier1 ? "1" : "0");
    return json(api("design"), { method: "POST", body: fd }, 30000);
  },
  async job(id) { return json(api(`jobs/${encodeURIComponent(id)}`)); },
  url: (u) => new URL(u, new URL("../", location.href)).href,
};
