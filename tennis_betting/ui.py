from __future__ import annotations

import json
import threading
from datetime import datetime, timezone
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from .matching import LiquidityComparison, displayed_orderbook_depth
from .models import LiquiditySnapshot
from .providers import KalshiPublicLiquidityProvider, PolymarketPublicLiquidityProvider
from .scraper import collect_once
from .storage import connect_database, load_latest_comparisons


HTML = """<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Tennis matched-volume comparison</title>
<style>
:root{font-family:Inter,system-ui,-apple-system,Segoe UI,sans-serif;color:#172033;background:#f5f7fb}
*{box-sizing:border-box}body{margin:0}.shell{max-width:1320px;margin:auto;padding:38px 24px}
header{display:flex;align-items:center;justify-content:space-between;gap:22px;margin-bottom:28px}
h1{font-size:clamp(2rem,4vw,2.75rem);letter-spacing:-.035em;margin:0 0 8px}p{color:#657089;margin:0}
button{border:0;border-radius:10px;background:#2563eb;color:#fff;font-weight:700;padding:12px 18px;cursor:pointer}
button:disabled{opacity:.6;cursor:wait}.meta{display:flex;gap:18px;flex-wrap:wrap;margin:20px 0 18px;color:#63708a;font-size:.92rem}
.card{background:#fff;border:1px solid #e3e8f1;border-radius:16px;box-shadow:0 8px 25px #14213d0c;overflow:hidden}
.actions{display:flex;align-items:center;gap:14px}.summary-grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:16px;max-width:100%;margin:24px 0}
.distribution{background:linear-gradient(145deg,#fff 30%,#f5f8ff);border:1px solid #dfe7f3;border-radius:16px;padding:18px;max-width:100%;overflow-x:auto;box-shadow:0 6px 20px #1837600d}
.distribution table{border-collapse:collapse;min-width:360px;width:100%}.distribution th,.distribution td{padding:11px 12px;border-bottom:1px solid #e9eef7;font-size:.82rem;white-space:nowrap}
.distribution th{font-size:.68rem;letter-spacing:.06em;color:#657089}.distribution td.num{text-align:right;font-variant-numeric:tabular-nums}
.distribution th.pm-column,.distribution td.pm-column .share-cell{color:#2563eb}.distribution th.ka-column,.distribution td.ka-column .share-cell{color:#b45309}
.distribution tr.total-row td{border-top:2px solid #cfd9e9;font-weight:800;background:#edf3ff}
.unit-note{font-size:.72rem!important;margin:10px 12px 0;color:#718096!important}
.top-actions{display:flex;align-items:center;justify-content:flex-end;gap:12px;flex-wrap:wrap}
.view-toggle{display:flex;align-items:center;gap:3px;padding:5px;border:1px solid #d6e0f0;border-radius:13px;background:#e9eff8;width:max-content;max-width:100%;box-shadow:inset 0 1px 2px #15294a0a}
.view-toggle button{padding:11px 16px;background:transparent;color:#53617a;border-radius:9px;white-space:nowrap}
.view-toggle button[aria-pressed="true"]{background:#fff;color:#1749a5;box-shadow:0 3px 9px #1720331c}
button#run{padding:13px 19px;box-shadow:0 5px 12px #2563eb2b}
.grade-chip{display:inline-flex;align-items:center;padding:5px 9px;border-radius:99px;background:#edf2ff;color:#344f9a;font-size:.72rem;font-weight:700}
.share-cell{display:flex;align-items:center;justify-content:flex-end;gap:8px}.mini-bar{display:inline-block;width:54px;height:7px;background:#e8edf5;border-radius:99px;overflow:hidden}
.mini-bar i{display:block;height:100%;border-radius:99px;background:linear-gradient(90deg,#60a5fa,#2563eb)}.mini-bar.kalshi i{background:linear-gradient(90deg,#fbbf24,#d97706)}
.filters{display:flex;align-items:end;gap:18px;flex-wrap:wrap;padding:18px 20px;margin:22px 0;background:#f0f4fa;border:1px solid #dfe6f0;border-radius:15px}
.filter{display:flex;flex-direction:column;gap:7px;color:#526079;font-size:.82rem;font-weight:700}
select{min-width:175px;border:1px solid #d1dae8;border-radius:9px;background:#fff;padding:10px 36px 10px 12px;color:#172033;font:inherit}
.reset-button{background:transparent;color:#35517e;border:1px solid #c8d4e5;padding:10px 14px}
.reset-button:hover{background:#fff}
.notice{padding:13px 16px;margin:0 0 16px;border-radius:10px;display:none}.notice.show{display:block}
.success{background:#e8f7ee;color:#17663a}.error{background:#fff0f0;color:#a32929}
.table-wrap{overflow-x:auto}table{width:100%;border-collapse:collapse;min-width:820px}
th,td{text-align:left;padding:16px 18px;border-bottom:1px solid #edf0f5}th{font-size:.76rem;text-transform:uppercase;color:#657089}
th button{padding:0;background:none;color:inherit;font:inherit;text-transform:inherit;border-radius:0}
th button:hover,th button[aria-sort="ascending"],th button[aria-sort="descending"]{color:#172033}
.sort-indicator{display:inline-block;width:1em;margin-left:4px;color:#2563eb}
#polymarket-heading{color:#2563eb}#kalshi-heading{color:#b45309}
td{font-variant-numeric:tabular-nums}.match{font-weight:750;font-size:1rem}.sub{font-size:.8rem;color:#7b879d;margin-top:7px}
.winner{font-weight:700}.pm{color:#2563eb}.ka{color:#b45309}.tie{color:#657089}.empty{text-align:center;color:#657089;padding:42px}
.badge{display:inline-flex;align-items:center;border-radius:99px;padding:5px 9px;font-size:.72rem;font-weight:700;background:#eef2ff}
.status-badge{display:inline-flex;margin-left:6px;border-radius:99px;padding:4px 8px;font-size:.67rem;font-weight:750}
.status-live{background:#dcfce7;color:#167344}.status-pre{background:#dbeafe;color:#2455a7}.status-unknown{background:#edf0f5;color:#657089}
.match-badges{display:flex;align-items:center;gap:5px;flex-wrap:wrap;margin-top:7px}
.expand-button{width:30px;height:30px;padding:0;margin-right:10px;border-radius:9px;background:#eaf0fb;color:#334b82;font-size:1rem;line-height:1}
.expand-cue{display:inline-block;margin-right:3px;font-size:.68rem;vertical-align:1px;color:#61759b}
tbody#rows>tr.match-row.row-alt{background:#f8fafd}
tbody#rows>tr:not(.details-row){transition:background .15s ease,box-shadow .15s ease}
tbody#rows>tr:not(.details-row):hover{background:#eef4ff;box-shadow:inset 3px 0 #6c96e8}
tbody#rows>tr:not(.details-row):hover .expand-button{background:#dbe7ff}
.expand-button[aria-expanded="true"]{transform:rotate(90deg);background:#dbe7ff}.detail-cell{padding:20px 26px!important;background:#f2f6fc}
.market-panels{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:18px}.market-panel{border:1px solid #dfe7f2;background:white;border-radius:14px;padding:18px;box-shadow:0 4px 14px #1837600a}
.market-panel h3{display:flex;align-items:center;gap:9px;margin:0 0 13px;font-size:.95rem}.market-icon{display:inline-grid;place-items:center;width:28px;height:28px;border-radius:8px;background:#edf3ff;color:#2563eb;font-size:.9rem}
.market-panel.kalshi-panel h3 .market-icon{background:#fff3dc;color:#b45309}
.market-item{display:flex;justify-content:space-between;align-items:center;gap:14px;padding:11px 4px;border-top:1px solid #edf0f5}
.market-name{font-weight:650}.market-selection{display:block;color:#718096;font-size:.78rem;margin-top:4px}.market-amount{font-variant-numeric:tabular-nums;font-weight:750;white-space:nowrap}
.empty-state{padding:28px;text-align:center;color:#66748e}.empty-icon{display:block;font-size:1.7rem;margin-bottom:8px}.empty-state strong{display:block;color:#34425c;margin-bottom:5px}
.skeleton{position:relative;overflow:hidden;background:#e7edf5;border-radius:7px}
.skeleton:after{position:absolute;inset:0;content:"";transform:translateX(-100%);background:linear-gradient(90deg,transparent,#ffffffa8,transparent);animation:shimmer 1.3s infinite}
.skeleton-row{height:18px;margin:8px 0}.skeleton-row.short{width:55%}.skeleton-summary{height:15px;width:70px;margin:8px}
.progress-track{height:3px;background:#dbe6f7;overflow:hidden;border-radius:9px;margin-top:10px}
.progress-track i{display:block;height:100%;width:35%;background:#2563eb;border-radius:inherit;animation:progress 1.15s ease-in-out infinite}
.progress-track.complete i{width:100%;animation:none;background:linear-gradient(90deg,#2563eb,#16a36a)}
@keyframes shimmer{100%{transform:translateX(100%)}}@keyframes progress{0%{transform:translateX(-110%)}100%{transform:translateX(310%)}}
@media(max-width:980px){header{align-items:flex-start;flex-direction:column}.top-actions{width:100%;justify-content:flex-start}}
@media(max-width:720px){.market-panels,.summary-grid{grid-template-columns:1fr}.distribution{width:100%}.filters{align-items:stretch}.filter{flex:1 1 180px}select{width:100%}}
@media(max-width:650px){.shell{padding:24px 13px}.top-actions{align-items:stretch;flex-direction:column}.view-toggle{width:100%}.view-toggle button{flex:1;padding:10px 8px}button#run{width:100%}.detail-cell{padding:15px!important}}
</style></head>
<body><main class="shell"><header><div><h1>Tennis market volume</h1><p>Compare matched amounts or current order-book depth across Polymarket and Kalshi.</p></div>
<div class="top-actions"><div class="view-toggle" role="group" aria-label="Data display">
<button type="button" data-view="matched" aria-pressed="true">Matched Amount</button>
<button type="button" data-view="depth" aria-pressed="false">Order Book Depth</button>
</div><button id="run" onclick="runScraper()">Refresh data</button></div></header>
<div id="notice" class="notice" role="status" aria-live="polite"></div><div id="scrape-progress" class="progress-track" role="progressbar" aria-valuemin="0" aria-valuemax="100" hidden aria-label="Scrape progress"><i></i></div>
<div class="meta"><span>Last updated: <strong id="updated">-</strong></span><span>Matches: <strong id="count">0</strong></span></div>
<section class="filters" aria-label="Match filters">
<label class="filter" for="tournament-filter">Tournament type
<select id="tournament-filter"><option value="all">All tournaments</option></select></label>
<label class="filter" for="status-filter">Match status
<select id="status-filter"><option value="both">Both</option><option value="pre_match">Pre-Match</option><option value="in_play">In-Play</option></select></label>
<button type="button" class="reset-button" id="reset-filters">Reset filters</button>
</section>
<div class="summary-grid">
<section class="distribution" aria-label="Reported matched-volume distribution by tournament">
<table><thead><tr><th>Tournament Type</th><th class="pm-column">Polymarket %</th><th class="ka-column">Kalshi %</th><th>Total Matches</th></tr></thead>
<tbody id="distribution"><tr><td colspan="4">No matched data</td></tr></tbody></table>
<p class="unit-note">Matched volume: USD vs contracts; indicative only.</p>
</section>
<section class="distribution" aria-label="Match distribution by combined liquidity range">
<table><thead><tr><th>Liquidity Range</th><th>Count</th><th class="pm-column">Polymarket %</th><th class="ka-column">Kalshi %</th></tr></thead>
<tbody id="range-distribution"><tr><td colspan="4">No matched data</td></tr></tbody></table>
<p class="unit-note" id="range-unit-note">Ranges use the combined amount in the selected view.</p>
</section></div>
<section class="card"><div class="table-wrap"><table><thead><tr>
<th><button data-sort="match">Match <span class="sort-indicator"></span></button></th>
<th><button data-sort="polymarket"><span id="polymarket-heading">Polymarket matched volume (USD)</span> <span class="sort-indicator"></span></button></th>
<th><button data-sort="kalshi"><span id="kalshi-heading">Kalshi matched volume (contracts)</span> <span class="sort-indicator"></span></button></th>
<th><button data-sort="leader"><span id="leader-heading">Reported-volume leader*</span> <span class="sort-indicator"></span></button></th>
</tr></thead>
<tbody id="rows"><tr><td colspan="4" class="empty">No matched data yet. Run the scraper to load results.</td></tr></tbody></table></div></section></main>
<script>
const number = value => new Intl.NumberFormat(undefined,{maximumFractionDigits:2}).format(Number(value)||0);
const esc = value => String(value).replace(/[&<>"']/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
let currentResults=[], sortColumn="polymarket", sortDirection="descending", selectedGrade="all", selectedStatus="both", dataView="matched", expandedMatches=new Set(), progressTimer;
function show(message, kind){const n=document.getElementById("notice");n.textContent=message;n.className="notice show "+kind}
const gradeLabel=grade=>({grand_slam:"Grand Slam",atp:"ATP",wta:"WTA",atp_challenger:"ATP Challenger",itf:"ITF",utr:"UTR",unknown:"Unknown"}[grade]||grade.toUpperCase());
function updateSortIndicators(){document.querySelectorAll("th button[data-sort]").forEach(button=>{const active=button.dataset.sort===sortColumn;button.setAttribute("aria-sort",active?sortDirection:"none");const indicator=button.querySelector(".sort-indicator");indicator.textContent=active?(sortDirection==="ascending"?"↑":"↓"):"";button.setAttribute("aria-label",button.textContent.trim())})}
function filteredResults(){return currentResults.filter(result=>(selectedGrade==="all"||result.grade===selectedGrade)&&(selectedStatus==="both"||result.phase===selectedStatus))}
function amountFor(result,venue){return Number(dataView==="matched"?result[venue+"_volume"]:result[venue+"_depth"])||0}
function leaderFor(result){const pm=amountFor(result,"polymarket"),kalshi=amountFor(result,"kalshi");return pm===kalshi?"Tie":pm>kalshi?"Polymarket":"Kalshi"}
function sortedResults(){const sign=sortDirection==="ascending"?1:-1;return [...filteredResults()].sort((a,b)=>{let left,right;
 if(sortColumn==="polymarket"){left=amountFor(a,"polymarket");right=amountFor(b,"polymarket")}
 else if(sortColumn==="kalshi"){left=amountFor(a,"kalshi");right=amountFor(b,"kalshi")}
 else if(sortColumn==="leader"){left=leaderFor(a);right=leaderFor(b)}
 else {left=a.competitors.toLocaleLowerCase();right=b.competitors.toLocaleLowerCase()}
 const result=typeof left==="string"?left.localeCompare(right):left-right;return result===0?a.competitors.localeCompare(b.competitors):result*sign})}
function marketPanel(title,markets,venue){const depth=dataView==="depth",visibleMarkets=depth?markets:[...new Map(markets.map(m=>[`${m.name}|${m.matched_volume}`,{...m,selection:""}])).values()],icon=depth?"▤":"◉",body=visibleMarkets.length?visibleMarkets.map(m=>`<div class="market-item"><span><span class="market-name">${esc(m.name||"Match Winner")}</span>${m.selection?`<span class="market-selection">${esc(m.selection)}</span>`:""}</span><span class="market-amount">${number(depth?m.liquidity:m.matched_volume)} ${esc(depth?(m.currency||"USD"):m.volume_currency||"")}</span></div>`).join(""):'<div class="empty-state"><strong>No market details available</strong>Try refreshing the data to retrieve current markets.</div>';return `<section class="market-panel ${venue==="ka"?"kalshi-panel":"polymarket-panel"}"><h3><span class="market-icon" aria-hidden="true">${icon}</span><span class="${venue}">${esc(title)} ${depth?"order-book depth":"matched volume"}</span></h3>${body}</section>`}
function summaryPercent(wins,total){return total?Math.round(wins/total*100):0}
function tournamentRowMarkup(label,row,totalRow=false){const pm=summaryPercent(row.pm,row.total),kalshi=summaryPercent(row.kalshi,row.total);return `<tr class="${totalRow?"total-row":""}"><td><span class="grade-chip">${esc(label)}</span></td><td class="pm-column"><div class="share-cell">${pm}%<span class="mini-bar"><i style="width:${pm}%"></i></span></div></td><td class="ka-column"><div class="share-cell">${kalshi}%<span class="mini-bar kalshi"><i style="width:${kalshi}%"></i></span></div></td><td class="num">${row.total}</td></tr>`}
function rangeRowMarkup(row,totalRow=false){const pm=summaryPercent(row.pm,row.total),kalshi=summaryPercent(row.kalshi,row.total);return `<tr class="${totalRow?"total-row":""}"><td><span class="grade-chip">${esc(row.label)}</span></td><td class="num">${row.total}</td><td class="pm-column"><div class="share-cell">${pm}%<span class="mini-bar"><i style="width:${pm}%"></i></span></div></td><td class="ka-column"><div class="share-cell">${kalshi}%<span class="mini-bar kalshi"><i style="width:${kalshi}%"></i></span></div></td></tr>`}
function renderRows(){const results=filteredResults(),rows=document.getElementById("rows");document.getElementById("count").textContent=results.length;if(!results.length){const empty=currentResults.length?'<span class="empty-icon" aria-hidden="true">⌕</span><strong>No matches for these filters</strong>Try a different tournament or status, or reset filters.':'<span class="empty-icon" aria-hidden="true">🎾</span><strong>No matched fixtures yet</strong>Refresh data to collect current matches.';rows.innerHTML=`<tr><td colspan="4" class="empty"><div class="empty-state">${empty}${currentResults.length?'<button type="button" class="reset-button" data-reset-empty>Reset filters</button>':''}</div></td></tr>`;return}
 const unit=dataView==="matched"?["USD","contracts"]:["USD","USD"];
 rows.innerHTML=sortedResults().map((r,index)=>{const pm=amountFor(r,"polymarket"),ka=amountFor(r,"kalshi"),leader=leaderFor(r),winner=leader==="Tie"?"Tie":leader+" higher";const cls=leader==="Polymarket"?"pm":leader==="Kalshi"?"ka":"tie",expanded=expandedMatches.has(r.id),statusClass=r.phase==="in_play"?"status-live":r.phase==="pre_match"?"status-pre":"status-unknown",statusLabel=r.phase==="in_play"?"In-Play":r.phase==="pre_match"?"Pre-Match":"Unknown";
 const summary=`<tr class="match-row ${index%2?"row-alt":""}"><td><button class="expand-button" data-expand="${esc(r.id)}" aria-expanded="${expanded}" aria-label="${expanded?"Collapse":"Expand"} market details"><span class="expand-cue" aria-hidden="true">⌄</span>›</button><span class="match">${esc(r.competitors)}</span><div class="match-badges"><span class="grade-chip">${esc(gradeLabel(r.grade))}</span><span class="status-badge ${statusClass}">${statusLabel}</span></div></td><td class="pm ${leader==="Polymarket"?"winner":""}">${number(pm)} ${unit[0]}</td><td class="ka ${leader==="Kalshi"?"winner":""}">${number(ka)} ${unit[1]}</td><td class="${cls}"><span class="badge">${esc(winner)}</span></td></tr>`;
 const details=`<tr class="details-row" data-detail-for="${esc(r.id)}" ${expanded?"":"hidden"}><td colspan="4" class="detail-cell"><div class="market-panels">${marketPanel("Polymarket",r.markets.polymarket,"pm")}${marketPanel("Kalshi",r.markets.kalshi,"ka")}</div></td></tr>`;
 return summary+details}).join("")}
function renderDistribution(){const grouped=new Map();for(const result of filteredResults()){const grade=result.grade||"unknown";if(!grouped.has(grade))grouped.set(grade,{total:0,pm:0,kalshi:0});const row=grouped.get(grade);row.total++;const leader=leaderFor(result);if(leader==="Polymarket")row.pm++;if(leader==="Kalshi")row.kalshi++}
 const body=document.getElementById("distribution");if(!grouped.size){body.innerHTML='<tr><td colspan="4">No matched data</td></tr>';return}
 const total=[...grouped.values()].reduce((sum,row)=>({total:sum.total+row.total,pm:sum.pm+row.pm,kalshi:sum.kalshi+row.kalshi}),{total:0,pm:0,kalshi:0});
 body.innerHTML=[...grouped.entries()].sort((a,b)=>gradeLabel(a[0]).localeCompare(gradeLabel(b[0]))).map(([grade,row])=>tournamentRowMarkup(gradeLabel(grade),row)).join("")+tournamentRowMarkup("Total",total,true)}
function renderRangeDistribution(){const bands=[{label:"<5k",min:0,max:5000},{label:"5k-25k",min:5000,max:25000},{label:"25k-100k",min:25000,max:100000},{label:"100k+",min:100000,max:Infinity}];const rows=bands.map(band=>({label:band.label,total:0,pm:0,kalshi:0}));for(const result of filteredResults()){const combined=amountFor(result,"polymarket")+amountFor(result,"kalshi"),index=bands.findIndex(band=>combined>=band.min&&combined<band.max);if(index<0)continue;const row=rows[index],leader=leaderFor(result);row.total++;if(leader==="Polymarket")row.pm++;if(leader==="Kalshi")row.kalshi++}
 const body=document.getElementById("range-distribution"),total=rows.reduce((sum,row)=>({label:"Total",total:sum.total+row.total,pm:sum.pm+row.pm,kalshi:sum.kalshi+row.kalshi}),{label:"Total",total:0,pm:0,kalshi:0});body.innerHTML=rows.map(row=>rangeRowMarkup(row)).join("")+rangeRowMarkup(total,true)}
function updateViewLabels(){const depth=dataView==="depth";document.getElementById("polymarket-heading").textContent=depth?"Polymarket order-book depth (USD)":"Polymarket matched volume (USD)";document.getElementById("kalshi-heading").textContent=depth?"Kalshi order-book depth (USD)":"Kalshi matched volume (contracts)";document.getElementById("leader-heading").textContent=depth?"Order-book depth leader":"Reported-volume leader*";document.getElementById("range-unit-note").textContent=depth?"Ranges use combined USD order-book depth.":"Ranges use combined reported amounts (USD + contracts), indicative only.";document.querySelectorAll("[data-view]").forEach(button=>button.setAttribute("aria-pressed",String(button.dataset.view===dataView)))}
function renderDisplays(){for(const id of ["rows","distribution","range-distribution"])document.getElementById(id).setAttribute("aria-busy","false");renderRows();renderDistribution();renderRangeDistribution()}
function renderSkeletons(){for(const id of ["rows","distribution","range-distribution"])document.getElementById(id).setAttribute("aria-busy","true");document.getElementById("rows").innerHTML=Array.from({length:4},()=>'<tr><td><div class="skeleton skeleton-row"></div><div class="skeleton skeleton-row short"></div></td><td><div class="skeleton skeleton-row"></div></td><td><div class="skeleton skeleton-row"></div></td><td><div class="skeleton skeleton-row short"></div></td></tr>').join("");for(const id of ["distribution","range-distribution"]){document.getElementById(id).innerHTML=Array.from({length:4},()=>'<tr><td><div class="skeleton skeleton-summary"></div></td><td><div class="skeleton skeleton-summary"></div></td><td><div class="skeleton skeleton-summary"></div></td><td><div class="skeleton skeleton-summary"></div></td></tr>').join("")}}
function resetFilters(){selectedGrade="all";selectedStatus="both";document.getElementById("tournament-filter").value="all";document.getElementById("status-filter").value="both";renderDisplays()}
function setScrapeProgress(active,complete=false){const progress=document.getElementById("scrape-progress");progress.hidden=!active&&!complete;progress.classList.toggle("complete",complete);progress.setAttribute("aria-valuetext",complete?"Scrape complete":"Scrape in progress");if(complete)progress.setAttribute("aria-valuenow","100");else progress.removeAttribute("aria-valuenow")}
function render(data){currentResults=data.results||[];document.getElementById("updated").textContent=data.updated_at?new Date(data.updated_at).toLocaleString():"-";const filter=document.getElementById("tournament-filter"),previous=selectedGrade,grades=[...new Set(currentResults.map(result=>result.grade||"unknown"))].sort();filter.innerHTML='<option value="all">All tournaments</option>'+grades.map(grade=>`<option value="${esc(grade)}">${esc(gradeLabel(grade))}</option>`).join("");selectedGrade=grades.includes(previous)?previous:"all";filter.value=selectedGrade;updateViewLabels();updateSortIndicators();renderDisplays()}
document.querySelectorAll("th button[data-sort]").forEach(button=>button.addEventListener("click",()=>{if(sortColumn===button.dataset.sort)sortDirection=sortDirection==="ascending"?"descending":"ascending";else{sortColumn=button.dataset.sort;sortDirection="ascending"}updateSortIndicators();renderRows()}));updateSortIndicators();
document.getElementById("rows").addEventListener("click",event=>{const button=event.target.closest("button[data-expand]");if(!button)return;const id=button.dataset.expand;if(expandedMatches.has(id))expandedMatches.delete(id);else expandedMatches.add(id);const details=document.querySelector(`[data-detail-for="${CSS.escape(id)}"]`);if(details)details.hidden=!expandedMatches.has(id);button.setAttribute("aria-expanded",String(expandedMatches.has(id)));button.setAttribute("aria-label",expandedMatches.has(id)?"Collapse market details":"Expand market details")});
document.getElementById("tournament-filter").addEventListener("change",event=>{selectedGrade=event.target.value;renderDisplays()});
document.getElementById("status-filter").addEventListener("change",event=>{selectedStatus=event.target.value;renderDisplays()});
document.querySelectorAll("[data-view]").forEach(button=>button.addEventListener("click",()=>{dataView=button.dataset.view;updateViewLabels();renderDisplays()}));
document.getElementById("reset-filters").addEventListener("click",resetFilters);
document.getElementById("rows").addEventListener("click",event=>{if(event.target.closest("[data-reset-empty]"))resetFilters()});
async function load(){const response=await fetch("/api/results");if(response.ok)render(await response.json())}
async function runScraper(){const button=document.getElementById("run");clearTimeout(progressTimer);button.disabled=true;button.textContent="Refreshing…";show("Collecting current markets from Polymarket and Kalshi…","success");setScrapeProgress(true);renderSkeletons();
 try{const response=await fetch("/api/scrape",{method:"POST"});const data=await response.json();if(!response.ok)throw new Error(data.error||"Scrape failed");render(data);setScrapeProgress(true,true);show(`Scrape complete: ${data.count} snapshots collected.`,"success");progressTimer=setTimeout(()=>setScrapeProgress(false),1400)}catch(error){renderDisplays();setScrapeProgress(false);show(error.message,"error")}finally{button.disabled=false;button.textContent="Refresh data"}}
load();
</script></body></html>"""


def _comparison_json(comparison: LiquidityComparison) -> dict[str, Any]:
    def market_details(
        snapshot: LiquiditySnapshot,
    ) -> list[dict[str, str]]:
        details = snapshot.raw.get("ui_markets")
        if isinstance(details, list) and details:
            return [
                {
                    "name": str(item.get("name") or snapshot.market_name),
                    "selection": str(item.get("selection") or ""),
                    "liquidity": str(item.get("liquidity") or "0"),
                    "matched_volume": str(item.get("matched_volume") or "0"),
                    "currency": str(item.get("currency") or snapshot.currency),
                    "volume_currency": "contracts" if snapshot.provider == "kalshi" else "USD",
                }
                for item in details if isinstance(item, dict)
            ]
        return [{
            "name": snapshot.market_name,
            "selection": "",
            "liquidity": str(displayed_orderbook_depth(snapshot)),
            "currency": snapshot.currency,
            "matched_volume": str(snapshot.matched_volume),
            "volume_currency": "contracts" if snapshot.provider == "kalshi" else "USD",
        }]

    phases = {comparison.polymarket.phase.value, comparison.kalshi.phase.value}
    phase = (
        "in_play" if "in_play" in phases
        else "pre_match" if phases == {"pre_match"}
        else "unknown"
    )
    return {
        "id": f"{comparison.polymarket.source_event_id}|{comparison.kalshi.source_event_id}",
        "competitors": " vs ".join(comparison.polymarket.competitor_names),
        "grade": (
            comparison.polymarket.grade
            if comparison.polymarket.grade.value != "unknown"
            else comparison.kalshi.grade
        ).value,
        "phase": phase,
        "polymarket_volume": str(comparison.polymarket_volume),
        "kalshi_volume": str(comparison.kalshi_volume),
        "polymarket_depth": str(displayed_orderbook_depth(comparison.polymarket)),
        "kalshi_depth": str(displayed_orderbook_depth(comparison.kalshi)),
        "volume_leader": comparison.volume_leader,
        "match_confidence": comparison.confidence,
        "markets": {
            "polymarket": market_details(comparison.polymarket),
            "kalshi": market_details(comparison.kalshi),
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
        row["polymarket_wins"] += comparison.volume_leader == "Polymarket"
        row["kalshi_wins"] += comparison.volume_leader == "Kalshi"
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
