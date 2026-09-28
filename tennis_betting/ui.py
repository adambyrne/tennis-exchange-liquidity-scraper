from __future__ import annotations

import json
import threading
from datetime import datetime, timezone
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from .matching import LiquidityComparison
from .providers import KalshiPublicLiquidityProvider, PolymarketPublicLiquidityProvider
from .scraper import collect_once
from .storage import connect_database, load_latest_comparisons


HTML = """<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Tennis liquidity comparison</title>
<style>
:root{font-family:Inter,system-ui,-apple-system,Segoe UI,sans-serif;color:#172033;background:#f5f7fb}
*{box-sizing:border-box}body{margin:0}.shell{max-width:1180px;margin:auto;padding:32px 18px}
header{display:flex;align-items:center;justify-content:space-between;gap:18px;margin-bottom:24px}
h1{font-size:clamp(1.5rem,3vw,2.25rem);margin:0 0 6px}p{color:#657089;margin:0}
button{border:0;border-radius:10px;background:#2563eb;color:#fff;font-weight:700;padding:12px 18px;cursor:pointer}
button:disabled{opacity:.6;cursor:wait}.meta{display:flex;gap:16px;flex-wrap:wrap;margin:18px 0}
.card{background:#fff;border:1px solid #e3e8f1;border-radius:14px;box-shadow:0 5px 18px #14213d0b;overflow:hidden}
.notice{padding:12px 16px;margin-bottom:16px;border-radius:10px;display:none}.notice.show{display:block}
.success{background:#e8f7ee;color:#17663a}.error{background:#fff0f0;color:#a32929}
.table-wrap{overflow-x:auto}table{width:100%;border-collapse:collapse;min-width:720px}
th,td{text-align:left;padding:14px 16px;border-bottom:1px solid #edf0f5}th{font-size:.78rem;text-transform:uppercase;color:#657089}
td{font-variant-numeric:tabular-nums}.match{font-weight:700}.sub{font-size:.8rem;color:#7b879d;margin-top:4px}
.winner{font-weight:700}.pm{color:#2563eb}.ka{color:#b45309}.tie{color:#657089}.empty{text-align:center;color:#657089;padding:40px}
.badge{display:inline-block;border-radius:99px;padding:4px 9px;font-size:.78rem;background:#eef2ff}
@media(max-width:650px){.shell{padding:22px 12px}header{align-items:flex-start;flex-direction:column}button{width:100%}}
</style></head>
<body><main class="shell"><header><div><h1>Tennis liquidity</h1><p>Current displayed order-book depth across Polymarket and Kalshi.</p></div>
<button id="run" onclick="runScraper()">Refresh data</button></header>
<div id="notice" class="notice"></div><div class="meta"><span>Last updated: <strong id="updated">-</strong></span><span>Matches: <strong id="count">0</strong></span></div>
<section class="card"><div class="table-wrap"><table><thead><tr><th>Match</th><th>Polymarket</th><th>Kalshi</th><th>Difference / leader</th></tr></thead>
<tbody id="rows"><tr><td colspan="4" class="empty">No matched data yet. Run the scraper to load results.</td></tr></tbody></table></div></section></main>
<script>
const money = value => new Intl.NumberFormat(undefined,{style:"currency",currency:"USD",maximumFractionDigits:2}).format(Number(value)||0);
const esc = value => String(value).replace(/[&<>"']/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
function show(message, kind){const n=document.getElementById("notice");n.textContent=message;n.className="notice show "+kind}
function render(data){document.getElementById("updated").textContent=data.updated_at?new Date(data.updated_at).toLocaleString():"-";document.getElementById("count").textContent=data.results.length;
 const rows=document.getElementById("rows"); if(!data.results.length){rows.innerHTML='<tr><td colspan="4" class="empty">No conservatively matched fixtures found.</td></tr>';return}
 rows.innerHTML=data.results.map(r=>{const pm=Number(r.polymarket_liquidity),ka=Number(r.kalshi_liquidity),winner=r.more_liquid==="Tie"?"Tie":r.more_liquid+" higher";const cls=r.more_liquid==="Polymarket"?"pm":r.more_liquid==="Kalshi"?"ka":"tie";
 return `<tr><td><div class="match">${esc(r.competitors)}</div><div class="sub">${esc(r.grade)} · ${esc(r.phase)}</div></td><td class="${r.more_liquid==="Polymarket"?"winner":""}">${money(pm)}</td><td class="${r.more_liquid==="Kalshi"?"winner":""}">${money(ka)}</td><td class="${cls}">${money(r.difference)} <span class="badge">${esc(winner)}</span></td></tr>`}).join("")}
async function load(){const response=await fetch("/api/results");if(response.ok)render(await response.json())}
async function runScraper(){const button=document.getElementById("run");button.disabled=true;button.textContent="Refreshing…";show("Collecting current markets from Polymarket and Kalshi…","success");
 try{const response=await fetch("/api/scrape",{method:"POST"});const data=await response.json();if(!response.ok)throw new Error(data.error||"Scrape failed");show(`Scrape complete: ${data.count} snapshots collected.`,"success");render(data)}catch(error){show(error.message,"error")}finally{button.disabled=false;button.textContent="Refresh data"}}
load();setInterval(async()=>{const response=await fetch("/api/status");const status=await response.json();if(status.status==="complete")load()},3000);
</script></body></html>"""


def _comparison_json(comparison: LiquidityComparison) -> dict[str, Any]:
    return {
        "competitors": " vs ".join(comparison.polymarket.competitor_names),
        "grade": comparison.polymarket.grade.value,
        "phase": comparison.polymarket.phase.value,
        "polymarket_liquidity": str(comparison.polymarket_liquidity),
        "kalshi_liquidity": str(comparison.kalshi_liquidity),
        "difference": str(comparison.difference),
        "more_liquid": comparison.more_liquid,
        "match_confidence": comparison.confidence,
    }


class LiquidityUI:
    def __init__(self, db_path: str | Path) -> None:
        self.db_path = Path(db_path)
        self.lock = threading.Lock()
        self.status = "idle"
        self.error: str | None = None
        self.updated_at: str | None = None

    def results(self) -> dict[str, Any]:
        connection = connect_database(self.db_path)
        try:
            comparisons = load_latest_comparisons(connection)
            if comparisons and self.updated_at is None:
                self.updated_at = max(
                    item.polymarket.observed_at for item in comparisons
                ).isoformat()
            return {
                "status": self.status,
                "updated_at": self.updated_at,
                "results": [_comparison_json(item) for item in comparisons],
            }
        finally:
            connection.close()

    def scrape(self) -> dict[str, Any]:
        if not self.lock.acquire(blocking=False):
            raise RuntimeError("A scrape is already running")
        self.status, self.error = "running", None
        try:
            connection = connect_database(self.db_path)
            try:
                snapshots = collect_once([
                    PolymarketPublicLiquidityProvider(),
                    KalshiPublicLiquidityProvider(),
                ], connection)
            finally:
                connection.close()
            self.updated_at = max((item.observed_at for item in snapshots), default=datetime.now(timezone.utc)).isoformat()
            self.status = "complete"
            payload = self.results()
            payload["count"] = len(snapshots)
            return payload
        except Exception as error:
            self.status, self.error = "error", str(error)
            raise
        finally:
            self.lock.release()


def create_server(db_path: str | Path, host: str = "127.0.0.1", port: int = 8000) -> ThreadingHTTPServer:
    app = LiquidityUI(db_path)

    class Handler(BaseHTTPRequestHandler):
        def _send(self, payload: object, status: HTTPStatus = HTTPStatus.OK) -> None:
            body = json.dumps(payload).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self) -> None:
            if urlsplit(self.path).path == "/api/results":
                self._send(app.results())
            elif urlsplit(self.path).path == "/api/status":
                self._send({"status": app.status, "error": app.error})
            else:
                body = HTML.encode("utf-8")
                self.send_response(HTTPStatus.OK)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

        def do_POST(self) -> None:
            if urlsplit(self.path).path != "/api/scrape":
                self._send({"error": "not found"}, HTTPStatus.NOT_FOUND)
                return
            try:
                self._send(app.scrape())
            except RuntimeError as error:
                self._send({"error": str(error)}, HTTPStatus.CONFLICT)
            except Exception as error:
                self._send({"error": str(error)}, HTTPStatus.INTERNAL_SERVER_ERROR)

        def log_message(self, format: str, *args: object) -> None:
            return

    return ThreadingHTTPServer((host, port), Handler)


def serve(db_path: str | Path, host: str = "127.0.0.1", port: int = 8000) -> None:
    server = create_server(db_path, host, port)
    print(f"Liquidity UI running at http://{host}:{port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopping liquidity UI")
    finally:
        server.server_close()
