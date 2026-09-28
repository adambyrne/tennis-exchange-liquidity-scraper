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
from .models import LiquiditySnapshot
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
.actions{display:flex;align-items:center;gap:12px}.distribution{background:linear-gradient(135deg,#fff 35%,#f0f5ff);border:1px solid #dfe7f5;border-radius:14px;padding:10px 12px;max-width:100%;overflow-x:auto;box-shadow:0 8px 22px #18376010}
.distribution table{border-collapse:collapse;min-width:340px;width:auto}.distribution th,.distribution td{padding:6px 8px;border-bottom:1px solid #e9eef7;font-size:.72rem;white-space:nowrap}
.distribution th{font-size:.62rem;letter-spacing:.06em}.distribution td.num{text-align:right;font-variant-numeric:tabular-nums}
.grade-chip{display:inline-block;padding:3px 7px;border-radius:99px;background:#edf2ff;color:#344f9a;font-size:.68rem;font-weight:700}
.share-cell{display:flex;align-items:center;justify-content:flex-end;gap:6px}.mini-bar{display:inline-block;width:38px;height:5px;background:#e8edf5;border-radius:10px;overflow:hidden}
.mini-bar i{display:block;height:100%;border-radius:inherit;background:linear-gradient(90deg,#60a5fa,#2563eb)}.mini-bar.kalshi i{background:linear-gradient(90deg,#fbbf24,#d97706)}
.filter{display:flex;align-items:center;gap:8px;margin:18px 0;color:#657089;font-size:.9rem}
select{border:1px solid #d7deea;border-radius:8px;background:#fff;padding:8px 30px 8px 10px;color:#172033}
.notice{padding:12px 16px;margin-bottom:16px;border-radius:10px;display:none}.notice.show{display:block}
.success{background:#e8f7ee;color:#17663a}.error{background:#fff0f0;color:#a32929}
.table-wrap{overflow-x:auto}table{width:100%;border-collapse:collapse;min-width:720px}
th,td{text-align:left;padding:14px 16px;border-bottom:1px solid #edf0f5}th{font-size:.78rem;text-transform:uppercase;color:#657089}
th button{padding:0;background:none;color:inherit;font:inherit;text-transform:inherit;border-radius:0}
th button:hover,th button[aria-sort="ascending"],th button[aria-sort="descending"]{color:#172033}
.sort-indicator{display:inline-block;width:1em;margin-left:4px;color:#2563eb}
td{font-variant-numeric:tabular-nums}.match{font-weight:700}.sub{font-size:.8rem;color:#7b879d;margin-top:4px}
.winner{font-weight:700}.pm{color:#2563eb}.ka{color:#b45309}.tie{color:#657089}.empty{text-align:center;color:#657089;padding:40px}
.badge{display:inline-block;border-radius:99px;padding:4px 9px;font-size:.78rem;background:#eef2ff}
.expand-button{width:28px;height:28px;padding:0;margin-right:8px;border-radius:8px;background:#eef2ff;color:#334b82;font-size:1rem;line-height:1}
.expand-button[aria-expanded="true"]{transform:rotate(90deg);background:#dbe7ff}.detail-cell{padding:16px 24px!important;background:#f8faff}
.market-panels{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:14px}.market-panel{border:1px solid #e1e8f3;background:white;border-radius:12px;padding:14px}
.market-panel h3{margin:0 0 10px;font-size:.9rem}.market-item{display:flex;justify-content:space-between;gap:12px;padding:8px 0;border-top:1px solid #edf0f5}
.market-name{font-weight:600}.market-selection{display:block;color:#718096;font-size:.78rem;margin-top:3px}.market-amount{font-variant-numeric:tabular-nums;font-weight:700;white-space:nowrap}
@media(max-width:720px){.market-panels{grid-template-columns:1fr}.distribution{width:100%}}
@media(max-width:650px){.shell{padding:22px 12px}header{align-items:flex-start;flex-direction:column}.actions{width:100%;align-items:stretch;flex-direction:column}.distribution{justify-content:space-around}button#run{width:100%}}
</style></head>
<body><main class="shell"><header><div><h1>Tennis liquidity</h1><p>Current displayed order-book depth across Polymarket and Kalshi.</p></div>
<div class="actions"><section class="distribution" aria-label="Liquidity distribution by tournament">
<table><thead><tr><th>Tournament Type</th><th>Polymarket %</th><th>Kalshi %</th><th>Total Matches</th></tr></thead>
<tbody id="distribution"><tr><td colspan="4">No matched data</td></tr></tbody></table>
</section><button id="run" onclick="runScraper()">Refresh data</button></div></header>
<div id="notice" class="notice"></div><div class="meta"><span>Last updated: <strong id="updated">-</strong></span><span>Matches: <strong id="count">0</strong></span></div>
<label class="filter" for="tournament-filter">Tournament type
<select id="tournament-filter"><option value="all">All tournaments</option></select></label>
<section class="card"><div class="table-wrap"><table><thead><tr>
<th><button data-sort="match">Match <span class="sort-indicator"></span></button></th>
<th><button data-sort="polymarket">Polymarket <span class="sort-indicator"></span></button></th>
<th><button data-sort="kalshi">Kalshi <span class="sort-indicator"></span></button></th>
<th><button data-sort="difference">Difference / leader <span class="sort-indicator"></span></button></th>
</tr></thead>
<tbody id="rows"><tr><td colspan="4" class="empty">No matched data yet. Run the scraper to load results.</td></tr></tbody></table></div></section></main>
<script>
const money = value => new Intl.NumberFormat(undefined,{style:"currency",currency:"USD",maximumFractionDigits:2}).format(Number(value)||0);
const esc = value => String(value).replace(/[&<>"']/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
let currentResults=[], sortColumn="total", sortDirection="descending", selectedGrade="all", expandedMatches=new Set();
function show(message, kind){const n=document.getElementById("notice");n.textContent=message;n.className="notice show "+kind}
const gradeLabel=grade=>({grand_slam:"Grand Slam",atp:"ATP",wta:"WTA",atp_challenger:"ATP Challenger",itf:"ITF",utr:"UTR",unknown:"Unknown"}[grade]||grade.toUpperCase());
function updateSortIndicators(){document.querySelectorAll("th button[data-sort]").forEach(button=>{const active=button.dataset.sort===sortColumn;const defaultTotal=sortColumn==="total"&&button.dataset.sort==="match";button.setAttribute("aria-sort",defaultTotal?"other":active?sortDirection:"none");const indicator=button.querySelector(".sort-indicator");indicator.textContent=defaultTotal?(sortDirection==="ascending"?"Σ↑":"Σ↓"):active?(sortDirection==="ascending"?"↑":"↓"):"";indicator.title=defaultTotal?"Sorted by combined liquidity":"";button.setAttribute("aria-label",defaultTotal?"Match; sorted by combined liquidity descending":button.textContent.trim())})}
function filteredResults(){return selectedGrade==="all"?currentResults:currentResults.filter(result=>result.grade===selectedGrade)}
function sortedResults(){const sign=sortDirection==="ascending"?1:-1;return [...filteredResults()].sort((a,b)=>{let left,right;
 if(sortColumn==="total"){left=Number(a.polymarket_liquidity)+Number(a.kalshi_liquidity);right=Number(b.polymarket_liquidity)+Number(b.kalshi_liquidity)}
 else if(sortColumn==="polymarket"){left=Number(a.polymarket_liquidity);right=Number(b.polymarket_liquidity)}
 else if(sortColumn==="kalshi"){left=Number(a.kalshi_liquidity);right=Number(b.kalshi_liquidity)}
 else if(sortColumn==="difference"){left=Number(a.difference);right=Number(b.difference)}
 else {left=a.competitors.toLocaleLowerCase();right=b.competitors.toLocaleLowerCase()}
 const result=typeof left==="string"?left.localeCompare(right):left-right;return result===0?a.competitors.localeCompare(b.competitors):result*sign})}
function marketPanel(title,markets,venue){const body=markets.length?markets.map(m=>`<div class="market-item"><span><span class="market-name">${esc(m.name||"Match Winner")}</span>${m.selection?`<span class="market-selection">${esc(m.selection)}</span>`:""}</span><span class="market-amount">${money(m.liquidity)} ${esc(m.currency||"USD")}</span></div>`).join(""):'<div class="sub">No market details available in this snapshot.</div>';return `<section class="market-panel"><h3 class="${venue}">${esc(title)}</h3>${body}</section>`}
function renderRows(){const results=filteredResults(),rows=document.getElementById("rows");document.getElementById("count").textContent=results.length;if(!results.length){rows.innerHTML='<tr><td colspan="4" class="empty">No conservatively matched fixtures found for this tournament type.</td></tr>';return}
 rows.innerHTML=sortedResults().map(r=>{const pm=Number(r.polymarket_liquidity),ka=Number(r.kalshi_liquidity),winner=r.more_liquid==="Tie"?"Tie":r.more_liquid+" higher";const cls=r.more_liquid==="Polymarket"?"pm":r.more_liquid==="Kalshi"?"ka":"tie",expanded=expandedMatches.has(r.id);
 const summary=`<tr><td><button class="expand-button" data-expand="${esc(r.id)}" aria-expanded="${expanded}" aria-label="${expanded?"Collapse":"Expand"} market details">›</button><span class="match">${esc(r.competitors)}</span><div class="sub">${esc(gradeLabel(r.grade))} · ${esc(r.phase)}</div></td><td class="${r.more_liquid==="Polymarket"?"winner":""}">${money(pm)}</td><td class="${r.more_liquid==="Kalshi"?"winner":""}">${money(ka)}</td><td class="${cls}">${money(r.difference)} <span class="badge">${esc(winner)}</span></td></tr>`;
 const details=`<tr class="details-row" data-detail-for="${esc(r.id)}" ${expanded?"":"hidden"}><td colspan="4" class="detail-cell"><div class="market-panels">${marketPanel("Polymarket",r.markets.polymarket,"pm")}${marketPanel("Kalshi",r.markets.kalshi,"ka")}</div></td></tr>`;
 return summary+details}).join("")}
function renderDistribution(){const grouped=new Map();for(const result of filteredResults()){const grade=result.grade||"unknown";if(!grouped.has(grade))grouped.set(grade,{total:0,pm:0,kalshi:0});const row=grouped.get(grade);row.total++;if(result.more_liquid==="Polymarket")row.pm++;if(result.more_liquid==="Kalshi")row.kalshi++}
 const body=document.getElementById("distribution");if(!grouped.size){body.innerHTML='<tr><td colspan="4">No matched data</td></tr>';return}
 body.innerHTML=[...grouped.entries()].sort((a,b)=>gradeLabel(a[0]).localeCompare(gradeLabel(b[0]))).map(([grade,row])=>{const pm=Math.round(row.pm/row.total*100),kalshi=Math.round(row.kalshi/row.total*100);return `<tr><td><span class="grade-chip">${esc(gradeLabel(grade))}</span></td><td><div class="share-cell">${pm}%<span class="mini-bar"><i style="width:${pm}%"></i></span></div></td><td><div class="share-cell">${kalshi}%<span class="mini-bar kalshi"><i style="width:${kalshi}%"></i></span></div></td><td class="num">${row.total}</td></tr>`}).join("")}
function render(data){currentResults=data.results||[];document.getElementById("updated").textContent=data.updated_at?new Date(data.updated_at).toLocaleString():"-";const filter=document.getElementById("tournament-filter"),previous=selectedGrade,grades=[...new Set(currentResults.map(result=>result.grade||"unknown"))].sort();filter.innerHTML='<option value="all">All tournaments</option>'+grades.map(grade=>`<option value="${esc(grade)}">${esc(gradeLabel(grade))}</option>`).join("");selectedGrade=grades.includes(previous)?previous:"all";filter.value=selectedGrade;updateSortIndicators();renderRows();renderDistribution()}
document.querySelectorAll("th button[data-sort]").forEach(button=>button.addEventListener("click",()=>{if(sortColumn===button.dataset.sort)sortDirection=sortDirection==="ascending"?"descending":"ascending";else{sortColumn=button.dataset.sort;sortDirection="ascending"}updateSortIndicators();renderRows()}));updateSortIndicators();
document.getElementById("rows").addEventListener("click",event=>{const button=event.target.closest("button[data-expand]");if(!button)return;const id=button.dataset.expand;if(expandedMatches.has(id))expandedMatches.delete(id);else expandedMatches.add(id);const details=document.querySelector(`[data-detail-for="${CSS.escape(id)}"]`);if(details)details.hidden=!expandedMatches.has(id);button.setAttribute("aria-expanded",String(expandedMatches.has(id)));button.setAttribute("aria-label",expandedMatches.has(id)?"Collapse market details":"Expand market details")});
document.getElementById("tournament-filter").addEventListener("change",event=>{selectedGrade=event.target.value;renderRows();renderDistribution()});
async function load(){const response=await fetch("/api/results");if(response.ok)render(await response.json())}
async function runScraper(){const button=document.getElementById("run");button.disabled=true;button.textContent="Refreshing…";show("Collecting current markets from Polymarket and Kalshi…","success");
 try{const response=await fetch("/api/scrape",{method:"POST"});const data=await response.json();if(!response.ok)throw new Error(data.error||"Scrape failed");show(`Scrape complete: ${data.count} snapshots collected.`,"success");render(data)}catch(error){show(error.message,"error")}finally{button.disabled=false;button.textContent="Refresh data"}}
load();
</script></body></html>"""


def _comparison_json(comparison: LiquidityComparison) -> dict[str, Any]:
    def market_details(
        snapshot: LiquiditySnapshot, visible_liquidity: Any,
    ) -> list[dict[str, str]]:
        details = snapshot.raw.get("ui_markets")
        if isinstance(details, list) and details:
            return [
                {
                    "name": str(item.get("name") or snapshot.market_name),
                    "selection": str(item.get("selection") or ""),
                    "liquidity": str(item.get("liquidity") or "0"),
                    "currency": str(item.get("currency") or snapshot.currency),
                }
                for item in details if isinstance(item, dict)
            ]
        return [{
            "name": snapshot.market_name,
            "selection": "",
            "liquidity": str(visible_liquidity),
            "currency": snapshot.currency,
        }]

    return {
        "id": f"{comparison.polymarket.source_event_id}|{comparison.kalshi.source_event_id}",
        "competitors": " vs ".join(comparison.polymarket.competitor_names),
        "grade": (
            comparison.polymarket.grade
            if comparison.polymarket.grade.value != "unknown"
            else comparison.kalshi.grade
        ).value,
        "phase": comparison.polymarket.phase.value,
        "polymarket_liquidity": str(comparison.polymarket_liquidity),
        "kalshi_liquidity": str(comparison.kalshi_liquidity),
        "difference": str(comparison.difference),
        "more_liquid": comparison.more_liquid,
        "match_confidence": comparison.confidence,
        "markets": {
            "polymarket": market_details(comparison.polymarket, comparison.polymarket_liquidity),
            "kalshi": market_details(comparison.kalshi, comparison.kalshi_liquidity),
        },
    }


def _liquidity_distribution(comparisons: list[LiquidityComparison]) -> list[dict[str, Any]]:
    grouped: dict[str, dict[str, int]] = {}
    for comparison in comparisons:
        grade = (
            comparison.polymarket.grade
            if comparison.polymarket.grade.value != "unknown"
            else comparison.kalshi.grade
        ).value
        row = grouped.setdefault(grade, {"total": 0, "polymarket_wins": 0, "kalshi_wins": 0})
        row["total"] += 1
        row["polymarket_wins"] += comparison.more_liquid == "Polymarket"
        row["kalshi_wins"] += comparison.more_liquid == "Kalshi"
    result = []
    for grade, row in sorted(grouped.items()):
        total = row["total"]
        result.append({
            "tournament_type": grade,
            "polymarket_percent": f"{row['polymarket_wins'] / total:.0%}",
            "kalshi_percent": f"{row['kalshi_wins'] / total:.0%}",
            "total_matches": total,
        })
    return result


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
            if self.updated_at is None:
                latest = connection.execute(
                    "SELECT MAX(observed_at) FROM liquidity_snapshots"
                ).fetchone()[0]
                if latest:
                    self.updated_at = datetime.fromisoformat(latest.replace("Z", "+00:00")).isoformat()
            return {
                "status": self.status,
                "updated_at": self.updated_at,
                "results": [_comparison_json(item) for item in comparisons],
                "distribution": _liquidity_distribution(comparisons),
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
