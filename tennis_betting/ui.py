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
#reload-published{background:#e9eff8;color:#35517e;border:1px solid #d6e0f0}
#reload-published:hover{background:#dce7f6}
.card{background:#fff;border:1px solid #e3e8f1;border-radius:16px;box-shadow:0 8px 25px #14213d0c;overflow:hidden}
.actions{display:flex;align-items:center;gap:14px}.summary-grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:16px;max-width:100%;margin:24px 0}
.distribution{background:linear-gradient(145deg,#fff 30%,#f5f8ff);border:1px solid #dfe7f3;border-radius:16px;padding:18px;max-width:100%;overflow-x:auto;box-shadow:0 6px 20px #1837600d}
.distribution table{border-collapse:collapse;min-width:360px;width:100%}.distribution th,.distribution td{padding:11px 12px;border-bottom:1px solid #e9eef7;font-size:.82rem;white-space:nowrap}
.distribution th{font-size:.68rem;letter-spacing:.06em;color:#657089}.distribution td.num{text-align:right;font-variant-numeric:tabular-nums}
.distribution th.pm-column,.distribution td.pm-column .share-cell{color:#2563eb}.distribution th.ka-column,.distribution td.ka-column .share-cell{color:#b45309}
.distribution th.zero-column,.distribution td.zero-column .share-cell{color:#64748b}
.mini-bar.zero i{background:linear-gradient(90deg,#cbd5e1,#64748b)}
.distribution tr.total-row td{border-top:2px solid #cfd9e9;font-weight:800;background:#edf3ff}
.distribution .average-staked{text-align:right;font-variant-numeric:tabular-nums}
.tournament-distribution{overflow-x:hidden}
.tournament-distribution table{table-layout:fixed;min-width:0}
.tournament-distribution th,.tournament-distribution td{padding:9px 5px;font-size:.74rem;white-space:normal;overflow-wrap:anywhere}
.tournament-distribution th:first-child,.tournament-distribution td:first-child{width:19%}
.tournament-distribution th:nth-child(2),.tournament-distribution th:nth-child(3),.tournament-distribution th:nth-child(4){width:15%}
.tournament-distribution th:nth-child(5){width:13%}
.tournament-distribution th:nth-child(6){width:23%}
.tournament-distribution .grade-chip{white-space:normal}
.tournament-distribution .share-cell{gap:3px;font-size:.72rem}
.tournament-distribution .mini-bar{width:28px}
.range-expand-button{width:26px;height:26px;padding:0;margin-right:8px;border:1px solid #d6e0f0;background:#f4f7fc;color:#35517e;border-radius:8px;line-height:1}
.range-expand-button:disabled{opacity:.35;cursor:default}
.range-expand-button[aria-expanded="true"]{transform:rotate(90deg);background:#dbe7ff}
.range-detail-row td{padding:14px 18px 14px 38px;background:#f2f6fc}
.range-detail-table{width:100%;border-collapse:collapse}
.range-detail-table th,.range-detail-table td{padding:8px 10px;font-size:.77rem;border-bottom:1px solid #e1e7f0}
.range-detail-table th{text-transform:none;letter-spacing:0}
.range-detail-table td.num{text-align:right;font-variant-numeric:tabular-nums}
.range-detail-empty{text-align:center;color:#657089}
.history-card{margin:24px 0;padding:0;overflow:hidden}
.history-card>summary{padding:18px 20px;cursor:pointer;font-weight:800;font-size:1.05rem;color:#24324a}
.history-card[open]>summary{border-bottom:1px solid #e3e8f1}
.history-card>.history-title{margin:0;padding:18px 20px;font-size:1.05rem;color:#24324a;border-bottom:1px solid #e3e8f1}
.history-wrap{overflow-x:auto;padding:0 18px 18px}
.history-table{min-width:850px;border-collapse:collapse}
.history-table th,.history-table td{padding:12px 14px;border-bottom:1px solid #edf0f5;white-space:nowrap}
.history-table th button{padding:0;background:none;color:inherit;font:inherit;text-transform:inherit}
.history-table td.pm-history{color:#2563eb;font-weight:700}
.history-table td.ka-history{color:#b45309;font-weight:700}
.history-table td.liquidity-average{font-variant-numeric:tabular-nums}
.history-table td.grade-average{font-variant-numeric:tabular-nums;text-align:right}
.history-table tr.history-total-row td{border-top:2px solid #cfd9e9;font-weight:800;background:#edf3ff}
.history-table tr.history-total-row td.pm-history{color:#2563eb}
.history-table tr.history-total-row td.ka-history{color:#b45309}
.history-detail-button{padding:6px 9px;border:1px solid #d6e0f0;background:#f4f7fc;color:#35517e}
.history-detail-row td{padding:16px;background:#f7f9fc}
.history-breakdowns{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:14px}
.history-breakdown{overflow-x:auto;padding:12px;border:1px solid #e1e7f0;border-radius:11px;background:#fff}
.history-breakdown h3{margin:0 0 8px;font-size:.88rem}
.history-breakdown table{min-width:420px;width:100%;border-collapse:collapse}
.history-breakdown th,.history-breakdown td{padding:8px;border-bottom:1px solid #edf0f5;font-size:.78rem;text-transform:none}
.history-empty{text-align:center;padding:24px;color:#657089}
.activity-card{margin:24px 0;padding:18px;overflow:hidden}
.activity-card h2{margin:0 0 8px;font-size:1.05rem;color:#24324a}
.activity-card .activity-note{font-size:.78rem;line-height:1.5;margin-bottom:12px}
.activity-wrap{overflow-x:auto}
.activity-table{min-width:920px;width:100%;border-collapse:collapse}
.activity-table th,.activity-table td{padding:10px 12px;border-bottom:1px solid #e9eef7;white-space:nowrap;font-size:.78rem}
.activity-table th{font-size:.66rem;color:#657089}
.activity-table td.activity-total{text-align:right;font-variant-numeric:tabular-nums}
.activity-table tr.total-row td{border-top:2px solid #cfd9e9;font-weight:800;background:#edf3ff}
.activity-share{display:flex;align-items:center;justify-content:flex-end;gap:6px}
.activity-bar{display:inline-block;width:46px;height:6px;background:#e8edf5;border-radius:99px;overflow:hidden}
.activity-bar i{display:block;height:100%;border-radius:inherit}
.activity-before_24h i{background:#2563eb}.activity-before_24_12h i{background:#0d9488}.activity-before_12_2h i{background:#d97706}.activity-before_2_0h i{background:#dc4f5f}.activity-in_play i{background:#7c3aed}
.activity-detail-table{width:100%;min-width:660px;border-collapse:collapse;margin-top:12px}
.activity-detail-table th,.activity-detail-table td{padding:8px;border-bottom:1px solid #e1e7f0;font-size:.76rem}
.activity-detail-table td.num{text-align:right;font-variant-numeric:tabular-nums}
.unit-note{font-size:.72rem!important;margin:10px 12px 0;color:#718096!important}
.top-actions{display:flex;align-items:center;justify-content:flex-end;gap:12px;flex-wrap:wrap}
.page-tabs{display:flex;gap:8px;margin:0 0 22px;padding:5px;border:1px solid #dfe6f0;border-radius:13px;background:#e9eff8;width:max-content;max-width:100%}
.page-tab{padding:10px 16px;background:transparent;color:#53617a;border-radius:9px;white-space:nowrap}
.page-tab[aria-pressed="true"]{background:#fff;color:#1749a5;box-shadow:0 3px 9px #1720331c}
.page-panel[hidden]{display:none}
.view-toggle{display:flex;align-items:center;gap:3px;padding:5px;border:1px solid #d6e0f0;border-radius:13px;background:#e9eff8;width:max-content;max-width:100%;box-shadow:inset 0 1px 2px #15294a0a}
.view-toggle button{padding:11px 16px;background:transparent;color:#53617a;border-radius:9px;white-space:nowrap}
.view-toggle button[aria-pressed="true"]{background:#fff;color:#1749a5;box-shadow:0 3px 9px #1720331c}
.display-control{display:flex;flex-direction:column;align-items:flex-start;gap:7px}
.mode-description{display:flex;align-items:flex-start;gap:7px;max-width:390px;padding:8px 11px;border:1px solid #e1e7f0;border-radius:9px;background:#f7f9fc;color:#6b768a;font-size:.75rem;line-height:1.45;text-align:left}
.mode-description-icon{flex:none;color:#7486a4;font-weight:800}
.mode-description.fade-in{animation:description-in .22s ease-out}
@keyframes description-in{from{opacity:0;transform:translateY(-3px)}to{opacity:1;transform:translateY(0)}}
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
@media(max-width:650px){.shell{padding:24px 13px}.top-actions{align-items:stretch;flex-direction:column}.display-control,.view-toggle,.mode-description{width:100%}.view-toggle button{flex:1;padding:10px 8px}.page-tabs{width:100%}.page-tab{flex:1;padding:10px 8px}button#run{width:100%}.detail-cell{padding:15px!important}.history-breakdowns{grid-template-columns:1fr}}
</style></head>
<body><main class="shell"><header><div><h1>Tennis market volume</h1><p>Compare matched amounts or current order-book depth across Polymarket and Kalshi.</p></div>
<div class="top-actions"><div class="display-control"><div class="view-toggle" role="group" aria-label="Data display">
<button type="button" data-view="matched" aria-pressed="true">Matched Amount</button>
<button type="button" data-view="depth" aria-pressed="false">Order Book Depth</button>
</div><div class="mode-description" id="mode-description" aria-live="polite"><span class="mode-description-icon" aria-hidden="true">ⓘ</span><span id="mode-description-text"></span></div></div><button id="run" onclick="runScraper()">Refresh data</button><button id="reload-published" type="button" onclick="reloadPublished()" hidden>Reload published data</button></div></header>
<div id="notice" class="notice" role="status" aria-live="polite"></div><div id="scrape-progress" class="progress-track" role="progressbar" aria-valuemin="0" aria-valuemax="100" hidden aria-label="Scrape progress"><i></i></div>
<div class="meta"><span>Last updated: <strong id="updated">-</strong></span><span>Matches: <strong id="count">0</strong></span></div>
<nav class="page-tabs" role="group" aria-label="Dashboard views">
<button type="button" class="page-tab" data-page-tab="main" aria-pressed="true">Main</button>
<button type="button" class="page-tab" data-page-tab="historical" aria-pressed="false">Historical Data</button>
</nav>
<div id="main-panel" class="page-panel">
<section class="filters" aria-label="Match filters">
<label class="filter" for="tournament-filter">Tournament type
<select id="tournament-filter"><option value="all">All tournaments</option></select></label>
<label class="filter" for="status-filter">Match status
<select id="status-filter"><option value="both">Both</option><option value="pre_match">Pre-Match</option><option value="in_play">In-Play</option></select></label>
<button type="button" class="reset-button" id="reset-filters">Reset filters</button>
</section>
<div class="summary-grid">
<section class="distribution tournament-distribution" aria-label="Matched-notional distribution by tournament">
<table><thead><tr><th>Tournament Type</th><th class="pm-column">Polymarket %</th><th class="ka-column">Kalshi %</th><th class="zero-column">Zero Liquidity %</th><th>Total Matches</th><th>Avg Staked (USD)</th></tr></thead>
<tbody id="distribution"><tr><td colspan="6">No matched data</td></tr></tbody></table>
<p class="unit-note">Matched notional in USD on both platforms.</p>
</section>
<section class="distribution" aria-label="Match distribution by combined liquidity range">
<table><thead><tr><th>Liquidity Range</th><th>Count</th><th class="pm-column">Polymarket %</th><th class="ka-column">Kalshi %</th><th class="zero-column">Zero Liquidity %</th></tr></thead>
<tbody id="range-distribution"><tr><td colspan="5">No matched data</td></tr></tbody></table>
<p class="unit-note" id="range-unit-note">Ranges use the combined amount in the selected view.</p>
</section></div>
<section class="card"><div class="table-wrap"><table><thead><tr>
<th><button data-sort="match">Match <span class="sort-indicator"></span></button></th>
<th><button data-sort="polymarket"><span id="polymarket-heading">Polymarket matched volume (USD)</span> <span class="sort-indicator"></span></button></th>
<th><button data-sort="kalshi"><span id="kalshi-heading">Kalshi matched notional (USD)</span> <span class="sort-indicator"></span></button></th>
<th><button data-sort="leader"><span id="leader-heading">Reported-volume leader*</span> <span class="sort-indicator"></span></button></th>
</tr></thead>
<tbody id="rows"><tr><td colspan="4" class="empty">No matched data yet. Run the scraper to load results.</td></tr></tbody></table></div></section>
</div>
<div id="historical-panel" class="page-panel" hidden>
<section class="activity-card card" aria-labelledby="activity-heading"><h2 id="activity-heading">Betting Activity by Time Window</h2>
<p class="activity-note">Share of newly observed matched-volume increases in the retained refresh history, grouped by scheduled start time at observation. "In-Play" means the scheduled start has passed; live match status is not independently verified. The first observation of a match is only a baseline, and matches without a scheduled start time are omitted.</p>
<div class="activity-wrap"><table class="activity-table"><thead><tr id="activity-header"></tr></thead><tbody id="activity-rows"><tr><td colspan="7" class="history-empty">Refresh data again to begin measuring volume changes.</td></tr></tbody></table></div></section>
<section class="history-card card" aria-labelledby="history-heading"><h2 class="history-title" id="history-heading">Performance History</h2>
<div class="history-wrap"><table class="history-table"><thead><tr id="history-header"></tr></thead><tbody id="history-rows"><tr><td colspan="8" class="history-empty">No refresh history yet.</td></tr></tbody></table></div></section>
</div>
</main>
<script>
const number = value => new Intl.NumberFormat(undefined,{maximumFractionDigits:2}).format(Number(value)||0);
const usd = value => new Intl.NumberFormat(undefined,{style:"currency",currency:"USD",minimumFractionDigits:2,maximumFractionDigits:2}).format(Number(value)||0);
const esc = value => String(value).replace(/[&<>"']/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
const STATIC_MODE = false;
const REFRESH_API_BASE = "";
const HISTORY_GRADE_ORDER=["grand_slam","atp","wta","itf"],HISTORY_EXCLUDED_GRADES=["atp_challenger","utr","unknown"];
const ACTIVITY_BUCKETS=[{key:"before_24h",label:"24h+ Before"},{key:"before_24_12h",label:"24-12h Before"},{key:"before_12_2h",label:"12-2h Before"},{key:"before_2_0h",label:"2-0h Before"},{key:"in_play",label:"In-Play"}];
let currentResults=[], allHistory=[], refreshSession=null, sortColumn="polymarket", sortDirection="descending", selectedGrade="all", selectedStatus="both", dataView="matched", expandedMatches=new Set(), expandedRanges=new Set(), expandedHistory=new Set(), historySortColumn="refresh", historySortDirection="descending", progressTimer;
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
function summaryShares(row){if(!row.total)return {polymarket:0,kalshi:0,zero:0};const counts=[row.pm,row.kalshi,row.zero],shares=counts.map(count=>count*100/row.total),rounded=shares.map(Math.floor);for(let remainder=100-rounded.reduce((sum,value)=>sum+value,0),order=shares.map((value,index)=>({index,remainder:value-rounded[index]})).sort((a,b)=>b.remainder-a.remainder),i=0;remainder>0;remainder--,i++)rounded[order[i%order.length].index]++;return {polymarket:rounded[0],kalshi:rounded[1],zero:rounded[2]}}
function recordLiquidityLeader(row,result){row.total++;const polymarket=amountFor(result,"polymarket"),kalshi=amountFor(result,"kalshi");if(polymarket<=0||kalshi<=0){row.zero++;return}if(polymarket===kalshi){row.pm+=0.5;row.kalshi+=0.5}else if(polymarket>kalshi)row.pm++;else row.kalshi++}
function shareCell(value,kind){const modifier=kind==="kalshi"?" kalshi":kind==="zero"?" zero":"";return `<div class="share-cell">${value}%<span class="mini-bar${modifier}"><i style="width:${value}%"></i></span></div>`}
function tournamentRowMarkup(label,row,totalRow=false){const shares=summaryShares(row);return `<tr class="${totalRow?"total-row":""}"><td><span class="grade-chip">${esc(label)}</span></td><td class="pm-column">${shareCell(shares.polymarket,"polymarket")}</td><td class="ka-column">${shareCell(shares.kalshi,"kalshi")}</td><td class="zero-column">${shareCell(shares.zero,"zero")}</td><td class="num">${row.total}</td><td class="average-staked">${usd(row.combined/row.total)}</td></tr>`}
function rangeRowMarkup(row,totalRow=false,index=0){const shares=summaryShares(row),expanded=expandedRanges.has(row.label),button=!totalRow&&row.total?`<button type="button" class="range-expand-button" data-range-expand="${esc(row.label)}" aria-controls="range-detail-${index}" aria-expanded="${expanded}" aria-label="${expanded?"Collapse":"Expand"} ${esc(row.label)} grade breakdown">›</button>`:"";return `<tr class="${totalRow?"total-row":""}"><td>${button}<span class="grade-chip">${esc(row.label)}</span></td><td class="num">${row.total}</td><td class="pm-column">${shareCell(shares.polymarket,"polymarket")}</td><td class="ka-column">${shareCell(shares.kalshi,"kalshi")}</td><td class="zero-column">${shareCell(shares.zero,"zero")}</td></tr>`}
function rangeBreakdownMarkup(row,index){if(!row.total)return "";const expanded=expandedRanges.has(row.label),grades=[...row.grades.entries()].sort((a,b)=>gradeLabel(a[0]).localeCompare(gradeLabel(b[0])));return `<tr class="range-detail-row" id="range-detail-${index}" ${expanded?"":"hidden"}><td colspan="5"><table class="range-detail-table"><thead><tr><th>Competition Grade</th><th class="num">Count</th><th class="pm-column">Polymarket %</th><th class="ka-column">Kalshi %</th><th class="zero-column">Zero Liquidity %</th></tr></thead><tbody>${grades.map(([grade,stats])=>{const shares=summaryShares(stats);return `<tr><td><span class="grade-chip">${esc(gradeLabel(grade))}</span></td><td class="num">${stats.total}</td><td class="pm-column">${shareCell(shares.polymarket,"polymarket")}</td><td class="ka-column">${shareCell(shares.kalshi,"kalshi")}</td><td class="zero-column">${shareCell(shares.zero,"zero")}</td></tr>`}).join("")}</tbody></table></td></tr>`}
function renderRows(){const results=filteredResults(),rows=document.getElementById("rows");document.getElementById("count").textContent=results.length;if(!results.length){const empty=currentResults.length?'<span class="empty-icon" aria-hidden="true">⌕</span><strong>No matches for these filters</strong>Try a different tournament or status, or reset filters.':'<span class="empty-icon" aria-hidden="true">🎾</span><strong>No matched fixtures yet</strong>Refresh data to collect current matches.';rows.innerHTML=`<tr><td colspan="4" class="empty"><div class="empty-state">${empty}${currentResults.length?'<button type="button" class="reset-button" data-reset-empty>Reset filters</button>':''}</div></td></tr>`;return}
 const unit=["USD","USD"];
 rows.innerHTML=sortedResults().map((r,index)=>{const pm=amountFor(r,"polymarket"),ka=amountFor(r,"kalshi"),leader=leaderFor(r),winner=leader==="Tie"?"Tie":leader+" higher";const cls=leader==="Polymarket"?"pm":leader==="Kalshi"?"ka":"tie",expanded=expandedMatches.has(r.id),statusClass=r.phase==="in_play"?"status-live":r.phase==="pre_match"?"status-pre":"status-unknown",statusLabel=r.phase==="in_play"?"In-Play":r.phase==="pre_match"?"Pre-Match":"Unknown";
 const summary=`<tr class="match-row ${index%2?"row-alt":""}"><td><button class="expand-button" data-expand="${esc(r.id)}" aria-expanded="${expanded}" aria-label="${expanded?"Collapse":"Expand"} market details"><span class="expand-cue" aria-hidden="true">⌄</span>›</button><span class="match">${esc(r.competitors)}</span><div class="match-badges"><span class="grade-chip">${esc(gradeLabel(r.grade))}</span><span class="status-badge ${statusClass}">${statusLabel}</span></div></td><td class="pm ${leader==="Polymarket"?"winner":""}">${number(pm)} ${unit[0]}</td><td class="ka ${leader==="Kalshi"?"winner":""}">${number(ka)} ${unit[1]}</td><td class="${cls}"><span class="badge">${esc(winner)}</span></td></tr>`;
 const details=`<tr class="details-row" data-detail-for="${esc(r.id)}" ${expanded?"":"hidden"}><td colspan="4" class="detail-cell"><div class="market-panels">${marketPanel("Polymarket",r.markets.polymarket,"pm")}${marketPanel("Kalshi",r.markets.kalshi,"ka")}</div></td></tr>`;
 return summary+details}).join("")}
function renderDistribution(){const grouped=new Map();for(const result of filteredResults()){const grade=result.grade||"unknown";if(!grouped.has(grade))grouped.set(grade,{total:0,pm:0,kalshi:0,zero:0,combined:0});const row=grouped.get(grade);row.combined+=amountFor(result,"polymarket")+amountFor(result,"kalshi");recordLiquidityLeader(row,result)}
 const body=document.getElementById("distribution");if(!grouped.size){body.innerHTML='<tr><td colspan="6">No matched data</td></tr>';return}
 const total=[...grouped.values()].reduce((sum,row)=>({total:sum.total+row.total,pm:sum.pm+row.pm,kalshi:sum.kalshi+row.kalshi,zero:sum.zero+row.zero,combined:sum.combined+row.combined}),{total:0,pm:0,kalshi:0,zero:0,combined:0});
 body.innerHTML=[...grouped.entries()].sort((a,b)=>gradeLabel(a[0]).localeCompare(gradeLabel(b[0]))).map(([grade,row])=>tournamentRowMarkup(gradeLabel(grade),row)).join("")+tournamentRowMarkup("Total",total,true)}
function renderRangeDistribution(){const bands=[{label:"<5k",min:0,max:5000},{label:"5k-25k",min:5000,max:25000},{label:"25k-100k",min:25000,max:100000},{label:"100k+",min:100000,max:Infinity}];const rows=bands.map(band=>({label:band.label,total:0,pm:0,kalshi:0,zero:0,grades:new Map()}));for(const result of filteredResults()){const combined=amountFor(result,"polymarket")+amountFor(result,"kalshi"),index=bands.findIndex(band=>combined>=band.min&&combined<band.max);if(index<0)continue;const row=rows[index],grade=result.grade||"unknown";if(!row.grades.has(grade))row.grades.set(grade,{total:0,pm:0,kalshi:0,zero:0});const gradeStats=row.grades.get(grade);recordLiquidityLeader(row,result);recordLiquidityLeader(gradeStats,result)}
 const body=document.getElementById("range-distribution"),total=rows.reduce((sum,row)=>({label:"Total",total:sum.total+row.total,pm:sum.pm+row.pm,kalshi:sum.kalshi+row.kalshi,zero:sum.zero+row.zero}),{label:"Total",total:0,pm:0,kalshi:0,zero:0});body.innerHTML=rows.map((row,index)=>rangeRowMarkup(row,false,index)+rangeBreakdownMarkup(row,index)).join("")+rangeRowMarkup(total,true)}
function historyBreakdownMarkup(title,rows){const showAverage=rows.some(row=>row.average_liquidity!==undefined);return `<section class="history-breakdown"><h3>${esc(title)}</h3><table><thead><tr><th>Breakdown</th><th>Count</th><th class="pm-column">Polymarket %</th><th class="ka-column">Kalshi %</th>${showAverage?'<th>Average Liquidity (USD)</th>':""}</tr></thead><tbody>${rows.map(row=>`<tr><td>${esc(row.label)}</td><td>${number(row.total_matches)}</td><td class="pm-history">${number(row.polymarket_percent)}%</td><td class="ka-history">${number(row.kalshi_percent)}%</td>${showAverage?`<td class="liquidity-average">${Number(row.total_matches)>0&&row.average_liquidity!==undefined?usd(row.average_liquidity):"-"}</td>`:""}</tr>`).join("")||`<tr><td colspan="${showAverage?5:4}">No matches</td></tr>`}</tbody></table></section>`}
function activityShares(buckets,total){if(total<=0)return Object.fromEntries(ACTIVITY_BUCKETS.map(bucket=>[bucket.key,0]));const raw=ACTIVITY_BUCKETS.map(bucket=>({key:bucket.key,value:(Number(buckets[bucket.key])||0)/total*100})),shares=raw.map(item=>Math.floor(item.value));for(let remainder=100-shares.reduce((sum,value)=>sum+value,0),order=raw.map((item,index)=>({index,fraction:item.value-shares[index]})).sort((a,b)=>b.fraction-a.fraction),i=0;remainder>0;remainder--,i++)shares[order[i%order.length].index]++;return Object.fromEntries(raw.map((item,index)=>[item.key,shares[index]]))}
function activityCell(percent,key){return `<td><div class="activity-share">${percent}%<span class="activity-bar activity-${key}"><i style="width:${percent}%"></i></span></div></td>`}
function activityHeaderMarkup(){return `<th>Grade</th>${ACTIVITY_BUCKETS.map(bucket=>`<th>${bucket.label}</th>`).join("")}<th>Total Activity (USD)</th>`}
function renderActivityHistory(){const body=document.getElementById("activity-rows"),aggregates=new Map(),bucketTotals=Object.fromEntries(ACTIVITY_BUCKETS.map(bucket=>[bucket.key,0]));for(const entry of allHistory){const activity=entry.betting_activity;if(!activity)continue;for(const gradeRow of activity.grades||[]){const row=aggregates.get(gradeRow.label)||{label:gradeRow.label,buckets:Object.fromEntries(ACTIVITY_BUCKETS.map(bucket=>[bucket.key,0])),total_volume:0};for(const bucket of ACTIVITY_BUCKETS){const amount=Number(gradeRow.buckets?.[bucket.key])||0;row.buckets[bucket.key]+=amount;bucketTotals[bucket.key]+=amount}row.total_volume+=Number(gradeRow.total_volume)||0;aggregates.set(gradeRow.label,row)}}const rows=[...aggregates.values()].sort((a,b)=>gradeLabel(a.label).localeCompare(gradeLabel(b.label)));document.getElementById("activity-header").innerHTML=activityHeaderMarkup();if(!rows.length){body.innerHTML='<tr><td colspan="7" class="history-empty">No volume increases observed yet. Refresh again after the baseline snapshot.</td></tr>';return}const totalVolume=Object.values(bucketTotals).reduce((sum,value)=>sum+value,0),totalShares=activityShares(bucketTotals,totalVolume),totalRow=`<tr class="total-row"><td>Total</td>${ACTIVITY_BUCKETS.map(bucket=>activityCell(totalShares[bucket.key],bucket.key)).join("")}<td class="activity-total">${usd(totalVolume)}</td></tr>`;body.innerHTML=rows.map(row=>{const shares=activityShares(row.buckets,row.total_volume);return `<tr><td><span class="grade-chip">${esc(gradeLabel(row.label))}</span></td>${ACTIVITY_BUCKETS.map(bucket=>activityCell(shares[bucket.key],bucket.key)).join("")}<td class="activity-total">${usd(row.total_volume)}</td></tr>`}).join("")+totalRow}
function activityDetailMarkup(activity){if(!activity||!activity.grades?.length)return '<p class="history-empty">No classifiable matched-volume increases in this refresh interval.</p>';return `<table class="activity-detail-table"><thead><tr><th>Grade</th>${ACTIVITY_BUCKETS.map(bucket=>`<th>${bucket.label} (USD)</th>`).join("")}<th>Total (USD)</th></tr></thead><tbody>${activity.grades.map(row=>`<tr><td>${esc(gradeLabel(row.label))}</td>${ACTIVITY_BUCKETS.map(bucket=>`<td class="num">${usd(row.buckets?.[bucket.key]||0)}</td>`).join("")}<td class="num">${usd(row.total_volume||0)}</td></tr>`).join("")}</tbody></table>`}
function historyHeaderMarkup(grades){return `<th><button type="button" data-history-sort="refresh">Refresh # <span class="history-sort-indicator"></span></button></th><th><button type="button" data-history-sort="timestamp">Timestamp <span class="history-sort-indicator"></span></button></th><th>View type</th><th><button type="button" data-history-sort="polymarket_percent">Polymarket % <span class="history-sort-indicator"></span></button></th><th><button type="button" data-history-sort="kalshi_percent">Kalshi % <span class="history-sort-indicator"></span></button></th><th><button type="button" data-history-sort="total_matches">Total Matches <span class="history-sort-indicator"></span></button></th><th>Avg Liquidity (USD)</th>${grades.map(grade=>`<th>${esc(gradeLabel(grade))} Avg (USD)</th>`).join("")}<th>Details</th>`}
function weightedAverageLiquidity(rows,grade=null){let amount=0,matches=0;for(const entry of rows){const summary=entry.views?.[dataView==="matched"?"matched":"depth"];if(!summary)continue;if(grade===null){if(summary.average_liquidity===undefined)continue;const count=Number(summary.total_matches)||0;amount+=Number(summary.average_liquidity)*count;matches+=count}else{const row=(summary.tournaments||[]).find(item=>item.label===grade);if(!row||row.average_liquidity===undefined)continue;const count=Number(row.total_matches)||0;amount+=Number(row.average_liquidity)*count;matches+=count}}return matches?amount/matches:null}
function updateHistorySortIndicators(){document.querySelectorAll("[data-history-sort]").forEach(button=>{const active=button.dataset.historySort===historySortColumn;button.setAttribute("aria-sort",active?historySortDirection:"none");button.querySelector(".history-sort-indicator").textContent=active?(historySortDirection==="ascending"?"↑":"↓"):""})}
function renderHistory(){const body=document.getElementById("history-rows"),view=dataView==="matched"?"matched":"depth",viewLabel=view==="matched"?"Matched Amount":"Order Book Depth";const rows=allHistory.filter(entry=>entry.views&&entry.views[view]).sort((a,b)=>{const left=a.views[view][historySortColumn]??a[historySortColumn],right=b.views[view][historySortColumn]??b[historySortColumn];const comparison=typeof left==="string"?left.localeCompare(right):Number(left)-Number(right);return comparison===0?a.refresh-b.refresh:comparison*(historySortDirection==="ascending"?1:-1)}),grades=[...new Set([...HISTORY_GRADE_ORDER,...rows.flatMap(entry=>(entry.views[view].tournaments||[]).map(row=>row.label))])].filter(grade=>!HISTORY_EXCLUDED_GRADES.includes(grade)).sort((a,b)=>gradeLabel(a).localeCompare(gradeLabel(b))),columnCount=8+grades.length;document.getElementById("history-header").innerHTML=historyHeaderMarkup(grades);if(!rows.length){body.innerHTML=`<tr><td colspan="${columnCount}" class="history-empty">No refresh history yet. Run a manual refresh to record the first snapshot.</td></tr>`;updateHistorySortIndicators();return}
 const average=key=>rows.reduce((sum,entry)=>sum+Number(entry.views[view][key]||0),0)/rows.length,overallAverage=weightedAverageLiquidity(rows);
 const totalRow=`<tr class="history-total-row"><td>${number(rows.length)} refreshes</td><td>-</td><td>Average (${viewLabel})</td><td class="pm-history">${number(average("polymarket_percent"))}%</td><td class="ka-history">${number(average("kalshi_percent"))}%</td><td>${number(average("total_matches"))}</td><td class="liquidity-average">${overallAverage===null?"-":usd(overallAverage)}</td>${grades.map(grade=>{const value=weightedAverageLiquidity(rows,grade);return `<td class="grade-average">${value===null?"-":usd(value)}</td>`}).join("")}<td></td></tr>`;
 body.innerHTML=rows.map(entry=>{const summary=entry.views[view],expanded=expandedHistory.has(entry.refresh),timestamp=entry.timestamp?new Date(entry.timestamp).toLocaleString():"-",gradeRows=new Map((summary.tournaments||[]).map(row=>[row.label,row]));return `<tr><td>${number(entry.refresh)}</td><td>${esc(timestamp)}</td><td>${viewLabel}</td><td class="pm-history">${number(summary.polymarket_percent)}%<span class="mini-bar"><i style="width:${summary.polymarket_percent}%"></i></span></td><td class="ka-history">${number(summary.kalshi_percent)}%<span class="mini-bar kalshi"><i style="width:${summary.kalshi_percent}%"></i></span></td><td>${number(summary.total_matches)}</td><td class="liquidity-average">${Number(summary.total_matches)>0&&summary.average_liquidity!==undefined?usd(summary.average_liquidity):"-"}</td>${grades.map(grade=>{const gradeSummary=gradeRows.get(grade),value=gradeSummary?.average_liquidity;return `<td class="grade-average">${Number(gradeSummary?.total_matches)>0&&value!==undefined?usd(value):"-"}</td>`}).join("")}<td><button type="button" class="history-detail-button" data-history-expand="${entry.refresh}" aria-expanded="${expanded}">${expanded?"Hide":"View"}</button></td></tr><tr class="history-detail-row" ${expanded?"":"hidden"}><td colspan="${columnCount}"><div class="history-breakdowns">${historyBreakdownMarkup("Tournament type",summary.tournaments||[])}${historyBreakdownMarkup("Liquidity range",summary.ranges||[])}</div>${activityDetailMarkup(entry.betting_activity)}</td></tr>`}).join("")+totalRow;updateHistorySortIndicators()}
function updateViewLabels(){const depth=dataView==="depth";document.getElementById("polymarket-heading").textContent=depth?"Polymarket order-book depth (USD)":"Polymarket matched volume (USD)";document.getElementById("kalshi-heading").textContent=depth?"Kalshi order-book depth (USD)":"Kalshi matched notional (USD)";document.getElementById("leader-heading").textContent=depth?"Order-book depth leader":"Matched-notional leader";document.getElementById("range-unit-note").textContent=depth?"Ranges use combined USD order-book depth.":"Ranges use combined USD matched notional.";const description=document.getElementById("mode-description-text");description.textContent=depth?"Current order-book depth; the total liquidity available in the order book across all price levels on each platform.":"Provider-reported matched volume; the total USD amount or contracts that have been matched on each platform.";const container=document.getElementById("mode-description");container.classList.remove("fade-in");void container.offsetWidth;container.classList.add("fade-in");document.querySelectorAll("[data-view]").forEach(button=>button.setAttribute("aria-pressed",String(button.dataset.view===dataView)))}
function renderDisplays(){for(const id of ["rows","distribution","range-distribution"])document.getElementById(id).setAttribute("aria-busy","false");renderRows();renderDistribution();renderRangeDistribution();renderHistory();renderActivityHistory()}
function renderSkeletons(){for(const id of ["rows","distribution","range-distribution"])document.getElementById(id).setAttribute("aria-busy","true");document.getElementById("rows").innerHTML=Array.from({length:4},()=>'<tr><td><div class="skeleton skeleton-row"></div><div class="skeleton skeleton-row short"></div></td><td><div class="skeleton skeleton-row"></div></td><td><div class="skeleton skeleton-row"></div></td><td><div class="skeleton skeleton-row short"></div></td></tr>').join("");document.getElementById("distribution").innerHTML=Array.from({length:4},()=>'<tr><td><div class="skeleton skeleton-summary"></div></td><td><div class="skeleton skeleton-summary"></div></td><td><div class="skeleton skeleton-summary"></div></td><td><div class="skeleton skeleton-summary"></div></td><td><div class="skeleton skeleton-summary"></div></td><td><div class="skeleton skeleton-summary"></div></td></tr>').join("");document.getElementById("range-distribution").innerHTML=Array.from({length:4},()=>'<tr><td><div class="skeleton skeleton-summary"></div></td><td><div class="skeleton skeleton-summary"></div></td><td><div class="skeleton skeleton-summary"></div></td><td><div class="skeleton skeleton-summary"></div></td><td><div class="skeleton skeleton-summary"></div></td></tr>').join("")}
function resetFilters(){selectedGrade="all";selectedStatus="both";document.getElementById("tournament-filter").value="all";document.getElementById("status-filter").value="both";renderDisplays()}
function setScrapeProgress(active,complete=false){const progress=document.getElementById("scrape-progress");progress.hidden=!active&&!complete;progress.classList.toggle("complete",complete);progress.setAttribute("aria-valuetext",complete?"Scrape complete":"Scrape in progress");if(complete)progress.setAttribute("aria-valuenow","100");else progress.removeAttribute("aria-valuenow")}
function render(data,history=[]){currentResults=data.results||[];allHistory=history;document.getElementById("updated").textContent=data.updated_at?new Date(data.updated_at).toLocaleString():"-";const filter=document.getElementById("tournament-filter"),previous=selectedGrade,grades=[...new Set(currentResults.map(result=>result.grade||"unknown"))].sort();filter.innerHTML='<option value="all">All tournaments</option>'+grades.map(grade=>`<option value="${esc(grade)}">${esc(gradeLabel(grade))}</option>`).join("");selectedGrade=grades.includes(previous)?previous:"all";filter.value=selectedGrade;updateViewLabels();updateSortIndicators();renderDisplays()}
document.querySelectorAll("th button[data-sort]").forEach(button=>button.addEventListener("click",()=>{if(sortColumn===button.dataset.sort)sortDirection=sortDirection==="ascending"?"descending":"ascending";else{sortColumn=button.dataset.sort;sortDirection="ascending"}updateSortIndicators();renderRows()}));updateSortIndicators();
document.getElementById("rows").addEventListener("click",event=>{const button=event.target.closest("button[data-expand]");if(!button)return;const id=button.dataset.expand;if(expandedMatches.has(id))expandedMatches.delete(id);else expandedMatches.add(id);const details=document.querySelector(`[data-detail-for="${CSS.escape(id)}"]`);if(details)details.hidden=!expandedMatches.has(id);button.setAttribute("aria-expanded",String(expandedMatches.has(id)));button.setAttribute("aria-label",expandedMatches.has(id)?"Collapse market details":"Expand market details")});
document.getElementById("range-distribution").addEventListener("click",event=>{const button=event.target.closest("button[data-range-expand]");if(!button)return;const label=button.dataset.rangeExpand;if(expandedRanges.has(label))expandedRanges.delete(label);else expandedRanges.add(label);renderRangeDistribution()});
document.getElementById("tournament-filter").addEventListener("change",event=>{selectedGrade=event.target.value;renderDisplays()});
document.getElementById("status-filter").addEventListener("change",event=>{selectedStatus=event.target.value;renderDisplays()});
document.querySelectorAll("[data-view]").forEach(button=>button.addEventListener("click",()=>{dataView=button.dataset.view;updateViewLabels();renderDisplays()}));
document.querySelectorAll("[data-page-tab]").forEach(button=>button.addEventListener("click",()=>{const historical=button.dataset.pageTab==="historical";document.getElementById("main-panel").hidden=historical;document.getElementById("historical-panel").hidden=!historical;document.querySelectorAll("[data-page-tab]").forEach(tab=>tab.setAttribute("aria-pressed",String(tab===button)))}));
document.querySelectorAll("[data-history-sort]").forEach(button=>button.addEventListener("click",()=>{if(historySortColumn===button.dataset.historySort)historySortDirection=historySortDirection==="ascending"?"descending":"ascending";else{historySortColumn=button.dataset.historySort;historySortDirection="ascending"}renderHistory()}));
document.getElementById("history-rows").addEventListener("click",event=>{const button=event.target.closest("[data-history-expand]");if(!button)return;const refresh=Number(button.dataset.historyExpand);if(expandedHistory.has(refresh))expandedHistory.delete(refresh);else expandedHistory.add(refresh);renderHistory()});
document.getElementById("reset-filters").addEventListener("click",resetFilters);
document.getElementById("rows").addEventListener("click",event=>{if(event.target.closest("[data-reset-empty]"))resetFilters()});
async function load(){const response=await fetch(STATIC_MODE?"./data.json?ts="+Date.now():"/api/results",{cache:"no-store"});if(!response.ok)throw new Error("Unable to load the latest published dashboard data.");const data=await response.json();let history=[];if(STATIC_MODE){const historyResponse=await fetch("./history.json?ts="+Date.now(),{cache:"no-store"});if(historyResponse.ok)history=await historyResponse.json();else if(historyResponse.status!==404)throw new Error("Unable to load performance history.")}render(data,history)}
async function reloadPublished(){const button=document.getElementById("reload-published");button.disabled=true;try{await load();show("Loaded the latest successfully published data.","success")}catch(error){show(error.message,"error")}finally{button.disabled=false}}
function authorizeRefresh(){if(refreshSession)return Promise.resolve(refreshSession);return new Promise((resolve,reject)=>{const popup=window.open(`${REFRESH_API_BASE}/auth/start`,"tennis-liquidity-refresh","popup,width=640,height=760");if(!popup){reject(new Error("Allow pop-ups to sign in to GitHub and refresh the data."));return}const expectedOrigin=new URL(REFRESH_API_BASE).origin,timeout=setTimeout(()=>{window.removeEventListener("message",receive);reject(new Error("GitHub sign-in timed out. Try refreshing again."))},300000);function receive(event){if(event.origin!==expectedOrigin||event.data?.type!=="refresh-session"||typeof event.data.token!=="string")return;clearTimeout(timeout);window.removeEventListener("message",receive);refreshSession=event.data.token;resolve(refreshSession)}window.addEventListener("message",receive)})}
async function runHostedScrape(button){if(!REFRESH_API_BASE){window.open("https://github.com/adambyrne/tennis-exchange-liquidity-scraper/actions/workflows/publish-dashboard.yml","_blank","noopener");show("Direct refresh is not configured yet. GitHub Actions opened as a fallback; sign in with repository write access and select Run workflow.","success");return}button.disabled=true;button.textContent="Authorizing…";try{const token=await authorizeRefresh();button.textContent="Starting scrape…";const response=await fetch(`${REFRESH_API_BASE}/api/refresh`,{method:"POST",headers:{Authorization:`Bearer ${token}`}}),payload=await response.json();if(!response.ok)throw new Error(payload.error||"Could not start the scrape.");const since=payload.requested_at;button.textContent="Scraping…";show("Scrape started. Collecting provider data and publishing the refreshed dashboard…","success");setScrapeProgress(true);renderSkeletons();const deadline=Date.now()+15*60*1000;while(Date.now()<deadline){await new Promise(resolve=>setTimeout(resolve,10000));const statusResponse=await fetch(`${REFRESH_API_BASE}/api/refresh/status?since=${encodeURIComponent(since)}`,{headers:{Authorization:`Bearer ${token}`}}),status=await statusResponse.json();if(!statusResponse.ok)throw new Error(status.error||"Could not read scrape status.");if(status.status==="completed"){if(status.conclusion!=="success")throw new Error(`Scrape failed (${status.conclusion||"unknown"}). Open the workflow run for details.`);await load();setScrapeProgress(true,true);show("Scrape complete. The latest published results and performance history are loaded.","success");progressTimer=setTimeout(()=>setScrapeProgress(false),1400);return}if(status.status==="in_progress")show("Scrape is running. The dashboard will update automatically when publishing finishes.","success")}throw new Error("The scrape is taking longer than expected. Check its GitHub Actions run and reload published data when it completes.")}catch(error){renderDisplays();setScrapeProgress(false);show(error.message,"error")}finally{button.disabled=false;button.textContent="Refresh data"}}
async function runScraper(){const button=document.getElementById("run");if(STATIC_MODE){await runHostedScrape(button);return}clearTimeout(progressTimer);button.disabled=true;button.textContent="Refreshing…";show("Collecting current markets from Polymarket and Kalshi…","success");setScrapeProgress(true);renderSkeletons();
 try{const response=await fetch("/api/scrape",{method:"POST"});const data=await response.json();if(!response.ok)throw new Error(data.error||"Scrape failed");render(data);setScrapeProgress(true,true);show(`Scrape complete: ${data.count} snapshots collected.`,"success");progressTimer=setTimeout(()=>setScrapeProgress(false),1400)}catch(error){renderDisplays();setScrapeProgress(false);show(error.message,"error")}finally{button.disabled=false;button.textContent="Refresh data"}}
updateViewLabels();document.getElementById("run").textContent=STATIC_MODE?"Refresh data":"Refresh data";document.getElementById("reload-published").hidden=!STATIC_MODE||Boolean(REFRESH_API_BASE);load().catch(error=>show(error.message,"error"));
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
                    "volume_currency": "USD",
                }
                for item in details if isinstance(item, dict)
            ]
        return [{
            "name": snapshot.market_name,
            "selection": "",
            "liquidity": str(displayed_orderbook_depth(snapshot)),
            "currency": snapshot.currency,
            "matched_volume": str(snapshot.matched_volume),
            "volume_currency": "USD",
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
        "start_time": comparison.polymarket.start_time.isoformat(),
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
