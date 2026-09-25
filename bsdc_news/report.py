"""Run reporting: GitHub Actions job summary (Markdown), JSON history and a
static HTML dashboard (``docs/index.html``) that can be served for free by
GitHub Pages."""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field
from pathlib import Path

from . import APP_NAME, __version__
from .log import get_logger, mask
from .utils import esc, iso, short_hash, utcnow

log = get_logger("report")


@dataclass
class ItemOutcome:
    title: str
    url: str
    source: str
    status: str  # published | skipped | failed | dry-run
    reason: str = ""
    score: float = 0.0
    quality: int | None = None
    provider: str = ""
    post_url: str = ""
    words: int = 0
    category: str = ""
    systemic: bool = False  # skipped because of a system problem (not the article itself)


@dataclass
class RunReport:
    run_id: str = field(default_factory=lambda: utcnow().strftime("%Y%m%d-%H%M%S"))
    started: str = field(default_factory=iso)
    finished: str = ""
    mode: str = "live"
    version: str = __version__
    feeds_ok: int = 0
    feeds_failed: list[str] = field(default_factory=list)
    @property
    def ai(self) -> dict:
        """Deprecated alias for :attr:`writer` (the report used to describe AI providers)."""
        return self.writer

    candidates: int = 0
    filtered: dict[str, int] = field(default_factory=dict)
    outcomes: list[ItemOutcome] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    fatal_errors: list[str] = field(default_factory=list)
    writer: dict = field(default_factory=dict)
    indexing: dict = field(default_factory=dict)
    social: dict = field(default_factory=dict)
    duration_s: float = 0.0
    exit_code: int = 0

    @property
    def run_url(self) -> str:
        server, repo, run = (os.environ.get("GITHUB_SERVER_URL"), os.environ.get("GITHUB_REPOSITORY"),
                             os.environ.get("GITHUB_RUN_ID"))
        return f"{server}/{repo}/actions/runs/{run}" if server and repo and run else ""

    @property
    def published(self) -> list[dict]:
        return [asdict(o) for o in self.outcomes if o.status in ("published", "dry-run")]

    def count(self, status: str) -> int:
        return sum(1 for o in self.outcomes if o.status == status)

    def add(self, outcome: ItemOutcome) -> None:
        self.outcomes.append(outcome)

    def filtered_inc(self, reason: str) -> None:
        key = reason.split("'")[0].strip() or reason
        self.filtered[key] = self.filtered.get(key, 0) + 1

    def warnings_for_notify(self) -> list[str]:
        return [w for w in self.warnings if "🔑" in w or "auth" in w.lower() or "quota" in w.lower()][:5]

    # ── outputs ──
    def to_markdown(self) -> str:
        pub = self.count("published") + self.count("dry-run")
        icon = "✅" if pub and not self.fatal_errors else ("❌" if self.fatal_errors else "⚪")
        lines = [f"## {icon} {APP_NAME} v{self.version} — {self.mode} run",
                 "",
                 "| Published | Skipped | Failed | Feeds OK | Candidates | Duration |",
                 "|---:|---:|---:|---:|---:|---:|",
                 f"| **{pub}** | {self.count('skipped')} | {self.count('failed')} | {self.feeds_ok} | "
                 f"{self.candidates} | {self.duration_s:.0f}s |", ""]
        if self.fatal_errors:
            lines += ["### ❌ Errors", *[f"- {e}" for e in self.fatal_errors], ""]
        if self.warnings:
            lines += ["### ⚠️ Warnings", *[f"- {w}" for w in self.warnings[:15]], ""]
        rows = [o for o in self.outcomes if o.status in ("published", "dry-run", "failed")]
        if rows:
            lines += ["### Articles", "", "| Status | Title | Source | Writer | Quality | Words |",
                      "|---|---|---|---|---:|---:|"]
            for o in rows:
                title = o.title.replace("|", "\\|")[:90]
                link = f"[{title}]({o.post_url})" if o.post_url else title
                status = {"published": "✅", "dry-run": "🧪", "failed": "❌"}[o.status]
                reason = f" — {o.reason}" if o.status == "failed" and o.reason else ""
                lines.append(f"| {status} | {link}{reason} | {o.source} | {o.provider or '-'} | "
                             f"{o.quality if o.quality is not None else '-'} | {o.words or '-'} |")
            lines.append("")
        if self.filtered:
            lines += ["<details><summary>Filtered candidates</summary>", "",
                      *[f"- {k}: {v}" for k, v in sorted(self.filtered.items(), key=lambda x: -x[1])],
                      "", "</details>", ""]
        if self.writer:
            lines += [f"**Writer:** {self.writer.get('engine', 'local')} · "
                      f"{self.writer.get('articles', 0)} articles · "
                      f"{self.writer.get('calls', 0)} API calls · "
                      f"{self.writer.get('cost', 'free')}", ""]
        if self.indexing:
            lines += ["**Indexing:** " + " · ".join(f"{k}: {v}" for k, v in self.indexing.items()), ""]
        if self.feeds_failed:
            lines += ["<details><summary>Feeds with problems</summary>", "",
                      *[f"- {f}" for f in self.feeds_failed], "", "</details>"]
        return "\n".join(lines)

    def write_github_summary(self) -> None:
        path = os.environ.get("GITHUB_STEP_SUMMARY")
        if not path:
            return
        try:
            with open(path, "a", encoding="utf-8") as fh:
                fh.write(mask(self.to_markdown()) + "\n")
        except OSError as exc:
            log.debug("Could not write job summary: %s", exc)

    def write_outputs(self) -> None:
        path = os.environ.get("GITHUB_OUTPUT")
        if not path:
            return
        with open(path, "a", encoding="utf-8") as fh:
            fh.write(f"published={self.count('published')}\n")
            fh.write(f"failed={self.count('failed')}\n")
            fh.write(f"exit_code={self.exit_code}\n")

    def save(self, directory: Path, keep: int = 60) -> Path:
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / f"run-{self.run_id}.json"
        data = asdict(self)
        data["run_url"] = self.run_url
        # Reports are committed to the (public) bot-data branch → mask any secret that
        # might hide inside an error message (e.g. an API key in a request URL).
        payload = mask(json.dumps(data, ensure_ascii=False, indent=1))
        path.write_text(payload, encoding="utf-8")
        runs = sorted(directory.glob("run-*.json"))
        for old in runs[:-keep]:
            old.unlink(missing_ok=True)
        (directory / "latest.json").write_text(payload, encoding="utf-8")
        return path


def build_dashboard(report_dir: Path, state, out_path: Path, site_name: str, site_url: str = "") -> None:
    """Static status page (no JS frameworks, no external assets)."""
    runs = []
    for path in sorted(report_dir.glob("run-*.json"), reverse=True)[:30]:
        try:
            runs.append(json.loads(path.read_text(encoding="utf-8")))
        except (OSError, ValueError):
            continue
    posts = state.published_records()[:40]
    providers = state.data.get("providers", {})
    total_pub = sum(1 for _ in state.data.get("published", {}))
    last = runs[0] if runs else {}

    def run_row(r: dict) -> str:
        pub = sum(1 for o in r.get("outcomes", []) if o.get("status") in ("published", "dry-run"))
        failed = sum(1 for o in r.get("outcomes", []) if o.get("status") == "failed")
        badge = "ok" if pub and not r.get("fatal_errors") else ("err" if r.get("fatal_errors") else "idle")
        link = f'<a href="{esc(r.get("run_url"))}">logs</a>' if r.get("run_url") else ""
        err = esc("; ".join(r.get("fatal_errors", []))[:160])
        return (f"<tr><td>{esc(r.get('started', '')[:16].replace('T', ' '))}</td><td><span class='b {badge}'>"
                f"{badge}</span></td><td>{pub}</td><td>{failed}</td><td>{r.get('duration_s', 0):.0f}s</td>"
                f"<td>{esc(r.get('mode', ''))}</td><td class='muted'>{err}</td><td>{link}</td></tr>")

    def post_row(p: dict) -> str:
        return (f"<tr><td>{esc(p.get('at', '')[:16].replace('T', ' '))}</td>"
                f"<td><a href=\"{esc(p.get('post_url') or p.get('url'))}\">{esc(p.get('title', ''))}</a></td>"
                f"<td>{esc(p.get('category', ''))}</td><td>{esc(p.get('source', ''))}</td>"
                f"<td>{esc(p.get('provider', ''))}</td><td>{esc(p.get('quality', ''))}</td></tr>")

    prov_rows = "".join(
        f"<tr><td>{esc(n)}</td><td>{esc(v.get('successes', 0))}</td><td>{esc(v.get('failures', 0))}</td>"
        f"<td>{esc((v.get('disabled_until') or '')[:16])}</td><td class='muted'>{esc((v.get('last_error') or '')[:140])}</td></tr>"
        for n, v in providers.items())

    html_doc = f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>{esc(site_name)} — publisher status</title>
<meta name="robots" content="noindex">
<style>
body{{font-family:-apple-system,Segoe UI,Roboto,Arial,sans-serif;margin:0;background:#0b1220;color:#e2e8f0}}
main{{max-width:1100px;margin:auto;padding:28px 18px}} h1{{margin:0 0 4px}} h2{{margin-top:34px}}
a{{color:#7dd3fc}} .muted{{color:#94a3b8;font-size:13px}}
.cards{{display:grid;grid-template-columns:repeat(auto-fit,minmax(170px,1fr));gap:12px;margin-top:18px}}
.card{{background:#111a2e;border:1px solid #1f2a44;border-radius:12px;padding:16px}}
.card b{{font-size:28px;display:block}} table{{width:100%;border-collapse:collapse;font-size:14px}}
td,th{{padding:8px;border-bottom:1px solid #1f2a44;text-align:left;vertical-align:top}}
.b{{padding:2px 8px;border-radius:999px;font-size:12px}} .ok{{background:#14532d}} .err{{background:#7f1d1d}}
.idle{{background:#334155}}
</style></head><body><main>
<h1>📰 {esc(site_name)} — Smart Publisher</h1>
<div class="muted">Updated {esc(iso())} · {f'<a href="{esc(site_url)}">{esc(site_url)}</a>' if site_url else ''}</div>
<div class="cards">
<div class="card"><span class="muted">Posts tracked</span><b>{total_pub}</b></div>
<div class="card"><span class="muted">Last run</span><b>{esc((last.get('started') or '-')[:16].replace('T', ' '))}</b></div>
<div class="card"><span class="muted">Consecutive failed runs</span><b>{esc(state.data['runs'].get('consecutive_failures', 0))}</b></div>
<div class="card"><span class="muted">Indexing queue</span><b>{len(state.data.get('indexing_queue', []))}</b></div>
</div>
<h2>Recent runs</h2><table><tr><th>Started (UTC)</th><th>Status</th><th>Published</th><th>Failed</th><th>Time</th><th>Mode</th><th>Errors</th><th></th></tr>
{''.join(run_row(r) for r in runs) or '<tr><td colspan=8>No runs yet</td></tr>'}</table>
<h2>Recently published</h2><table><tr><th>When (UTC)</th><th>Title</th><th>Category</th><th>Source</th><th>Writer</th><th>Quality</th></tr>
{''.join(post_row(p) for p in posts) or '<tr><td colspan=6>Nothing yet</td></tr>'}</table>
<h2>AI providers</h2><table><tr><th>Provider</th><th>OK</th><th>Failures</th><th>Paused until</th><th>Last error</th></tr>
{prov_rows or '<tr><td colspan=5>No AI calls yet</td></tr>'}</table>
<p class="muted">Generated by {esc(APP_NAME)} v{esc(__version__)} · id {short_hash(iso(), 6)}</p>
</main></body></html>"""
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(html_doc, encoding="utf-8")
