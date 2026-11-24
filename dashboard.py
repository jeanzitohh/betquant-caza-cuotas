import argparse
import json
import threading
import urllib.parse
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from bot_scanner import DEFAULT_LEAGUES, run_scan_pipeline, run_settle_pipeline
from paper_db import PaperTradingDB

HTML_PAGE = """<!DOCTYPE html>
<html lang="es">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>BetQuant • Radar Deportivo &amp; Paper Trading</title>
  <link rel="preconnect" href="https://fonts.googleapis.com" />
  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin />
  <link href="https://fonts.googleapis.com/css2?family=Fira+Code:wght@500;600&family=Fira+Sans:wght@400;500;600;700&display=swap" rel="stylesheet" />
  <style>
    :root {
      --bg: #F8FAFC;
      --surface: #FFFFFF;
      --surface-alt: #F1F5F9;
      --border: #E2E8F0;
      --border-strong: #CBD5E1;
      --text: #0F172A;
      --text-sub: #475569;
      --text-muted: #64748B;
      --primary: #1E40AF;
      --primary-hover: #1D4ED8;
      --primary-soft: #EFF6FF;
      --accent: #D97706;
      --accent-soft: #FEF3C7;
      --green: #15803D;
      --green-soft: #DCFCE7;
      --red: #B91C1C;
      --red-soft: #FEE2E2;
      --shadow-sm: 0 1px 2px rgba(15, 23, 42, 0.05);
      --shadow-md: 0 6px 18px rgba(15, 23, 42, 0.07);
      --radius: 12px;
    }

    * { box-sizing: border-box; }
    body {
      margin: 0;
      background: var(--bg);
      color: var(--text);
      font-family: 'Fira Sans', system-ui, -apple-system, Segoe UI, sans-serif;
      font-size: 14px;
      line-height: 1.5;
      -webkit-font-smoothing: antialiased;
    }
    .mono { font-family: 'Fira Code', ui-monospace, monospace; font-variant-numeric: tabular-nums; }

    /* Top Nav */
    .topbar {
      position: sticky; top: 0; z-index: 30;
      background: rgba(255, 255, 255, 0.92);
      backdrop-filter: blur(8px);
      border-bottom: 1px solid var(--border);
    }
    .topbar-inner {
      max-width: 1260px; margin: 0 auto; padding: 12px 24px;
      display: flex; flex-wrap: wrap; align-items: center; justify-content: space-between; gap: 14px;
    }
    .brand { display: flex; align-items: center; gap: 11px; }
    .brand-icon {
      width: 36px; height: 36px; border-radius: 10px;
      background: linear-gradient(135deg, #1E40AF 0%, #3B82F6 100%);
      color: #fff; display: grid; place-items: center; box-shadow: var(--shadow-sm);
    }
    .brand h1 { margin: 0; font-size: 16px; font-weight: 700; letter-spacing: -0.01em; }
    .brand p { margin: 0; font-size: 12px; color: var(--text-muted); }

    .actions { display: flex; flex-wrap: wrap; align-items: center; gap: 10px; }
    .segmented {
      display: inline-flex; background: var(--surface-alt); padding: 3px;
      border-radius: 9px; border: 1px solid var(--border);
    }
    .seg-btn {
      border: 0; background: transparent; color: var(--text-sub); padding: 6px 12px;
      border-radius: 7px; font-size: 12px; font-weight: 600; cursor: pointer; transition: all 0.15s;
    }
    .seg-btn.active { background: var(--surface); color: var(--primary); box-shadow: var(--shadow-sm); }

    .toggle-save {
      display: inline-flex; align-items: center; gap: 6px; font-size: 12px; font-weight: 500;
      color: var(--text-sub); padding: 6px 10px; border-radius: 8px; background: var(--surface-alt);
      border: 1px solid var(--border); cursor: pointer;
    }
    .toggle-save input { accent-color: var(--primary); cursor: pointer; }

    .btn {
      display: inline-flex; align-items: center; gap: 7px; border: 0; border-radius: 9px;
      padding: 8px 14px; font-size: 13px; font-weight: 600; cursor: pointer;
      transition: transform 0.12s, background 0.15s, box-shadow 0.15s;
      min-height: 38px;
    }
    .btn:focus-visible, .seg-btn:focus-visible, .tab-btn:focus-visible {
      outline: 2px solid var(--primary); outline-offset: 2px;
    }
    .btn-primary { background: var(--primary); color: #fff; box-shadow: var(--shadow-sm); }
    .btn-primary:hover { background: var(--primary-hover); }
    .btn-secondary { background: var(--surface); color: var(--text); border: 1px solid var(--border-strong); }
    .btn-secondary:hover { background: var(--surface-alt); }
    .btn:disabled { opacity: 0.6; cursor: wait; }

    /* Main container */
    .container { max-width: 1260px; margin: 0 auto; padding: 20px 24px 48px; }

    /* Status Toast Bar */
    .status-strip {
      display: flex; flex-wrap: wrap; align-items: center; justify-content: space-between; gap: 10px;
      padding: 10px 14px; border-radius: 10px; background: var(--primary-soft); border: 1px solid #BFDBFE;
      color: #1E3A8A; font-size: 13px; margin-bottom: 18px;
    }
    .status-left { display: flex; align-items: center; gap: 8px; font-weight: 500; }
    .dot-pulse { width: 8px; height: 8px; border-radius: 50%; background: #2563EB; flex-shrink: 0; }
    .dot-pulse.loading { animation: pulse 1s infinite ease-in-out; }
    @keyframes pulse { 0%,100% { opacity: 1; transform: scale(1); } 50% { opacity: 0.35; transform: scale(0.8); } }

    /* KPIs */
    .kpi-grid {
      display: grid; grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
      gap: 14px; margin-bottom: 20px;
    }
    .kpi-card {
      background: var(--surface); border: 1px solid var(--border); border-radius: var(--radius);
      padding: 16px 18px; box-shadow: var(--shadow-sm); position: relative; overflow: hidden;
    }
    .kpi-top { display: flex; align-items: center; justify-content: space-between; color: var(--text-muted); font-size: 12px; font-weight: 600; text-transform: uppercase; letter-spacing: 0.03em; }
    .kpi-val { font-size: 26px; font-weight: 700; margin-top: 8px; letter-spacing: -0.02em; }
    .kpi-foot { margin-top: 6px; font-size: 12px; color: var(--text-muted); }

    /* Tabs */
    .tabs-bar {
      display: flex; flex-wrap: wrap; align-items: center; justify-content: space-between; gap: 12px;
      border-bottom: 1px solid var(--border); margin-bottom: 18px;
    }
    .tabs { display: flex; flex-wrap: wrap; gap: 4px; }
    .tab-btn {
      border: 0; background: transparent; color: var(--text-sub); font-weight: 600; font-size: 13px;
      padding: 10px 14px; border-bottom: 2px solid transparent; cursor: pointer;
      display: inline-flex; align-items: center; gap: 7px; transition: color 0.15s;
    }
    .tab-btn:hover { color: var(--text); }
    .tab-btn.active { color: var(--primary); border-bottom-color: var(--primary); }
    .count-pill {
      background: var(--surface-alt); color: var(--text-sub); border-radius: 999px;
      padding: 1px 7px; font-size: 11px; font-weight: 700;
    }
    .tab-btn.active .count-pill { background: var(--primary-soft); color: var(--primary); }

    .tab-panel { display: none; }
    .tab-panel.active { display: block; }

    /* Bet Ticket Cards Grid */
    .cards-grid {
      display: grid; grid-template-columns: repeat(auto-fill, minmax(360px, 1fr)); gap: 14px;
    }
    .ticket {
      background: var(--surface); border: 1px solid var(--border); border-radius: var(--radius);
      padding: 16px; box-shadow: var(--shadow-sm); display: flex; flex-direction: column; gap: 12px;
      transition: transform 0.16s ease, box-shadow 0.16s ease;
    }
    .ticket:hover { transform: translateY(-2px); box-shadow: var(--shadow-md); }
    .ticket-head { display: flex; justify-content: space-between; align-items: center; gap: 8px; }
    .league-tag {
      font-size: 11px; font-weight: 700; color: var(--primary); background: var(--primary-soft);
      padding: 3px 8px; border-radius: 6px;
    }
    .time-tag { font-size: 12px; color: var(--text-muted); }

    .legs-box { display: flex; flex-direction: column; gap: 8px; }
    .leg-row {
      background: var(--bg); border: 1px solid var(--border); border-radius: 9px;
      padding: 9px 11px; font-size: 13px; color: var(--text);
    }
    .leg-title { font-weight: 600; }
    .leg-pick { color: var(--primary); font-weight: 600; font-size: 12px; margin-top: 2px; }

    .ticket-foot {
      display: flex; align-items: center; justify-content: space-between; gap: 10px;
      padding-top: 10px; border-top: 1px dashed var(--border-strong);
    }
    .odds-pill {
      background: #0F172A; color: #fff; border-radius: 8px; padding: 5px 11px;
      font-size: 14px; font-weight: 700;
    }
    .prob-meta { flex: 1; }
    .prob-labels { display: flex; justify-content: space-between; font-size: 11px; color: var(--text-sub); margin-bottom: 4px; }
    .bar-track { height: 6px; background: var(--surface-alt); border-radius: 999px; overflow: hidden; }
    .bar-fill { height: 100%; border-radius: 999px; background: var(--primary); }

    .badge {
      display: inline-flex; align-items: center; gap: 4px; padding: 3px 9px;
      border-radius: 999px; font-size: 11px; font-weight: 700; white-space: nowrap;
    }
    .b-pos { background: var(--green-soft); color: var(--green); }
    .b-warn { background: var(--accent-soft); color: #92400E; }
    .b-lost { background: var(--red-soft); color: var(--red); }
    .b-pend { background: var(--primary-soft); color: var(--primary); }

    /* Filters bar inside matches/history */
    .filter-row {
      display: flex; flex-wrap: wrap; align-items: center; justify-content: space-between; gap: 10px;
      margin-bottom: 12px;
    }
    .search-input {
      border: 1px solid var(--border-strong); background: var(--surface); color: var(--text);
      border-radius: 9px; padding: 8px 12px; font-size: 13px; min-width: 240px;
    }
    .search-input:focus { outline: 2px solid var(--primary); border-color: transparent; }

    /* Clean Data Table */
    .table-card {
      background: var(--surface); border: 1px solid var(--border); border-radius: var(--radius);
      box-shadow: var(--shadow-sm); overflow-x: auto;
    }
    table { width: 100%; border-collapse: collapse; font-size: 13px; }
    th {
      background: var(--surface-alt); color: var(--text-sub); font-weight: 600; font-size: 11px;
      text-transform: uppercase; letter-spacing: 0.04em; text-align: left; padding: 11px 12px;
      border-bottom: 1px solid var(--border);
    }
    td { padding: 12px; border-bottom: 1px solid var(--border); vertical-align: middle; }
    tr:last-child td { border-bottom: 0; }
    tr:hover td { background: #F8FAFC; }

    .match-name { font-weight: 700; color: var(--text); font-size: 13.5px; }
    .form-row { display: flex; align-items: center; gap: 5px; margin-top: 4px; flex-wrap: wrap; }
    .form-lbl { font-size: 11px; color: var(--text-muted); width: 28px; }
    .wdl {
      width: 16px; height: 16px; border-radius: 4px; font-size: 10px; font-weight: 700;
      display: inline-grid; place-items: center; color: #fff;
    }
    .w { background: #16A34A; }
    .d { background: #64748B; }
    .l { background: #DC2626; }

    .odds-trio { display: flex; gap: 5px; }
    .odd-chip {
      background: var(--surface-alt); border: 1px solid var(--border); border-radius: 6px;
      padding: 4px 8px; font-size: 12px; font-weight: 600; text-align: center; min-width: 48px;
    }
    .odd-chip span { display: block; font-size: 9px; color: var(--text-muted); font-weight: 500; }

    /* Drawer Modal */
    .drawer-backdrop {
      position: fixed; inset: 0; background: rgba(15, 23, 42, 0.42); z-index: 50;
      display: none; justify-content: flex-end;
    }
    .drawer-backdrop.open { display: flex; }
    .drawer {
      width: min(560px, 100%); background: var(--surface); height: 100%; overflow-y: auto;
      padding: 22px; box-shadow: -8px 0 30px rgba(15, 23, 42, 0.16);
    }
    .drawer-head {
      display: flex; justify-content: space-between; align-items: flex-start; gap: 12px;
      padding-bottom: 14px; border-bottom: 1px solid var(--border); margin-bottom: 16px;
    }
    .close-btn {
      border: 1px solid var(--border); background: var(--surface-alt); border-radius: 8px;
      padding: 6px 10px; cursor: pointer; font-weight: 700; color: var(--text-sub);
    }
    .stat-split {
      display: grid; grid-template-columns: 1fr 1fr; gap: 10px; margin-bottom: 16px;
    }
    .team-box {
      background: var(--bg); border: 1px solid var(--border); border-radius: 10px; padding: 12px;
    }
    .team-box h4 { margin: 0 0 6px 0; font-size: 13px; }
    .empty-state {
      background: var(--surface); border: 1px dashed var(--border-strong); border-radius: var(--radius);
      padding: 36px 20px; text-align: center; color: var(--text-muted);
    }
    @media (max-width: 640px) {
      .topbar-inner, .container { padding-left: 14px; padding-right: 14px; }
      .cards-grid { grid-template-columns: 1fr; }
      .stat-split { grid-template-columns: 1fr; }
    }
  </style>
</head>
<body>
  <header class="topbar">
    <div class="topbar-inner">
      <div class="brand">
        <div class="brand-icon" aria-hidden="true">
          <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><path d="M3 3v18h18"/><path d="m19 9-5 5-4-4-3 3"/></svg>
        </div>
        <div>
          <h1>BetQuant Monitor</h1>
          <p>Liga BetPlay &amp; Europa • Simulación sin dinero real • Hora Colombia</p>
        </div>
      </div>

      <div class="actions">
        <div class="segmented" role="group" aria-label="Filtro de ligas">
          <button class="seg-btn active" id="scopeCol" onclick="setScope('col.1')">Solo Colombia</button>
          <button class="seg-btn" id="scopeAll" onclick="setScope('all')">Colombia + Europa</button>
        </div>
        <label class="toggle-save" id="saveToggleLabel">
          <input type="checkbox" id="saveFlag" checked />
          Guardar en historial
        </label>
        <button class="btn btn-primary" id="btnScan" onclick="runScan()">
          <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><circle cx="11" cy="11" r="8"/><path d="m21 21-4.3-4.3"/></svg>
          Escanear Ahora
        </button>
        <button class="btn btn-secondary" id="btnSettle" onclick="runSettle()">
          <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><path d="M20 6 9 17l-5-5"/></svg>
          Liquidar
        </button>
      </div>
    </div>
  </header>

  <main class="container">
    <div class="status-strip" role="status" aria-live="polite">
      <div class="status-left">
        <span class="dot-pulse" id="statusDot"></span>
        <span id="statusText">Iniciando escáner en vivo...</span>
      </div>
      <div id="apiBadge" class="mono" style="font-size:11px; color:#1E40AF;">Fuente: ESPN en vivo</div>
    </div>

    <section class="kpi-grid" id="kpis"></section>

    <div class="tabs-bar">
      <div class="tabs" role="tablist">
        <button class="tab-btn active" onclick="switchTab('tabMatches', this)">Radar de Partidos <span class="count-pill" id="cntMatches">0</span></button>
        <button class="tab-btn" onclick="switchTab('tabOptA', this)">Combinadas (Opción A) <span class="count-pill" id="cntOptA">0</span></button>
        <button class="tab-btn" onclick="switchTab('tabOptB', this)">Bet Builder (Opción B) <span class="count-pill" id="cntOptB">0</span></button>
        <button class="tab-btn" onclick="switchTab('tabHistory', this)">Historial Simulado <span class="count-pill" id="cntHistory">0</span></button>
      </div>
    </div>

    <section id="tabMatches" class="tab-panel active">
      <div class="filter-row">
        <input type="search" id="searchMatch" class="search-input" placeholder="Buscar equipo o liga (ej. América, Millonarios)..." oninput="renderMatches()" />
        <span style="font-size:12px; color:var(--text-muted);">Haz clic en <strong>Analizar</strong> para ver los 17 mercados y el porqué de cada regla.</span>
      </div>
      <div class="table-card">
        <table>
          <thead>
            <tr>
              <th>Hora COL</th>
              <th>Partido &amp; Racha (últ. 10)</th>
              <th>Stats Loc / Vis</th>
              <th>Cuotas 1 | X | 2</th>
              <th>Fórmula (1.20–1.90)</th>
              <th></th>
            </tr>
          </thead>
          <tbody id="matchesBody"></tbody>
        </table>
      </div>
    </section>

    <section id="tabOptA" class="tab-panel">
      <div class="cards-grid" id="optAGrid"></div>
    </section>

    <section id="tabOptB" class="tab-panel">
      <div class="cards-grid" id="optBGrid"></div>
    </section>

    <section id="tabHistory" class="tab-panel">
      <div class="filter-row">
        <div class="segmented">
          <button class="seg-btn active" onclick="setHistFilter('ALL', this)">Todos</button>
          <button class="seg-btn" onclick="setHistFilter('PENDING', this)">Pendientes</button>
          <button class="seg-btn" onclick="setHistFilter('WON', this)">Ganadas</button>
          <button class="seg-btn" onclick="setHistFilter('LOST', this)">Perdidas</button>
        </div>
      </div>
      <div class="table-card">
        <table>
          <thead>
            <tr><th>#</th><th>Fecha</th><th>Estrategia</th><th>Jugada</th><th>Mercado</th><th>Cuota</th><th>Estado</th><th>Neto</th></tr>
          </thead>
          <tbody id="tradesBody"></tbody>
        </table>
      </div>
    </section>
  </main>

  <div class="drawer-backdrop" id="drawerBackdrop" onclick="if(event.target===this) closeDrawer()">
    <aside class="drawer" aria-label="Análisis detallado del partido">
      <div class="drawer-head">
        <div>
          <span class="league-tag" id="drLeague"></span>
          <h2 id="drTitle" style="margin:6px 0 2px; font-size:18px;"></h2>
          <div id="drSub" style="font-size:12px; color:var(--text-muted);"></div>
        </div>
        <button class="close-btn" onclick="closeDrawer()">Cerrar</button>
      </div>
      <div id="drBody"></div>
    </aside>
  </div>

  <script>
    const STATIC_MODE = false;
    let currentScope = 'col.1';
    let fullStaticData = null;
    let lastScan = { matches: [], parlays_a: [], opt_b: [], sharp_picks: [] };
    let lastReport = { recent: [] };
    let histFilter = 'ALL';

    function setScope(scope) {
      currentScope = scope;
      document.getElementById('scopeCol').classList.toggle('active', scope === 'col.1');
      document.getElementById('scopeAll').classList.toggle('active', scope === 'all');
      if (STATIC_MODE && fullStaticData) {
        applyStaticScope();
      } else {
        runScan();
      }
    }

    function switchTab(id, btn) {
      document.querySelectorAll('.tab-panel').forEach(p => p.classList.remove('active'));
      document.querySelectorAll('.tab-btn').forEach(b => b.classList.remove('active'));
      document.getElementById(id).classList.add('active');
      btn.classList.add('active');
    }

    function setHistFilter(val, btn) {
      histFilter = val;
      btn.parentElement.querySelectorAll('.seg-btn').forEach(b => b.classList.remove('active'));
      btn.classList.add('active');
      renderHistory();
    }

    function evBadge(ev) {
      if (ev > 0) return `<span class="badge b-pos">+${ev}% +EV</span>`;
      return `<span class="badge b-warn">${ev}% margen</span>`;
    }

    function formDots(scores) {
      if (!scores || !scores.length) return '<span style="font-size:11px;color:var(--text-muted)">Sin datos</span>';
      return scores.map(s => {
        const [gf, ga] = s.split('-').map(Number);
        const cls = gf > ga ? 'w' : (gf === ga ? 'd' : 'l');
        const txt = gf > ga ? 'G' : (gf === ga ? 'E' : 'P');
        return `<span class="wdl ${cls}" title="${s}">${txt}</span>`;
      }).join('');
    }

    function setLoading(isLoading, msg) {
      document.getElementById('statusDot').classList.toggle('loading', isLoading);
      document.getElementById('statusText').textContent = msg;
      document.getElementById('btnScan').disabled = isLoading;
      document.getElementById('btnSettle').disabled = isLoading;
    }

    function renderReportData(d) {
      lastReport = d;
      const winRate = d.settled > 0 ? ((d.won / d.settled) * 100).toFixed(1) + '%' : '—';
      const roiColor = d.roi_pct >= 0 ? 'var(--green)' : 'var(--red)';

      document.getElementById('kpis').innerHTML = `
        <div class="kpi-card">
          <div class="kpi-top"><span>Bankroll Simulado</span></div>
          <div class="kpi-val mono">${d.bankroll_u.toFixed(2)}u</div>
          <div class="kpi-foot">Base inicial: 100.00u (stake 2u)</div>
        </div>
        <div class="kpi-card">
          <div class="kpi-top"><span>ROI Acumulado</span></div>
          <div class="kpi-val mono" style="color:${roiColor}">${d.roi_pct >= 0 ? '+' : ''}${d.roi_pct}%</div>
          <div class="kpi-foot">Ganancia neta: ${d.total_profit_u >= 0 ? '+' : ''}${d.total_profit_u.toFixed(2)}u</div>
        </div>
        <div class="kpi-card">
          <div class="kpi-top"><span>Acierto Real</span></div>
          <div class="kpi-val mono">${winRate}</div>
          <div class="kpi-foot">${d.won} ganadas • ${d.lost} perdidas</div>
        </div>
        <div class="kpi-card">
          <div class="kpi-top"><span>Pendientes por Jugar</span></div>
          <div class="kpi-val mono" style="color:var(--primary)">${d.pending}</div>
          <div class="kpi-foot">${d.total_trades} jugadas totales registradas</div>
        </div>
      `;
      document.getElementById('cntHistory').textContent = d.total_trades;
      renderHistory();
    }

    async function loadReport() {
      if (STATIC_MODE) return;
      const r = await fetch('/api/report');
      renderReportData(await r.json());
    }

    function renderHistory() {
      const rows = (lastReport.recent || []).slice().reverse().filter(t => histFilter === 'ALL' || t.status === histFilter);
      document.getElementById('tradesBody').innerHTML = rows.map(t => {
        const cls = t.status === 'WON' ? 'b-pos' : (t.status === 'LOST' ? 'b-lost' : 'b-pend');
        return `<tr>
          <td class="mono">#${t.id}</td>
          <td class="mono">${t.match_date}</td>
          <td><span style="font-weight:600;font-size:12px;">${t.strategy}</span></td>
          <td>${t.title}</td>
          <td class="mono">${t.market}</td>
          <td class="mono"><strong>${t.odds.toFixed(2)}</strong></td>
          <td><span class="badge ${cls}">${t.status}</span></td>
          <td class="mono" style="color:${t.profit_u>0?'var(--green)':(t.profit_u<0?'var(--red)':'var(--text-muted)')}">${t.profit_u>=0?'+':''}${t.profit_u.toFixed(2)}u</td>
        </tr>`;
      }).join('') || '<tr><td colspan="8" style="text-align:center;color:var(--text-muted);padding:26px;">No hay jugadas en este filtro.</td></tr>';
    }

    function renderMatches() {
      const q = document.getElementById('searchMatch').value.trim().toLowerCase();
      const list = (lastScan.matches || []).filter(m =>
        !q || m.home.toLowerCase().includes(q) || m.away.toLowerCase().includes(q) || m.league_label.toLowerCase().includes(q)
      );

      document.getElementById('matchesBody').innerHTML = list.map((m, idx) => {
        const hs = m.h_stat, as_ = m.a_stat;
        const origIdx = lastScan.matches.indexOf(m);
        const picksHtml = [
          m.opt_a_leg ? `<div><span class="badge b-pend">A</span> ${m.opt_a_leg.market_name} <strong class="mono">@${m.opt_a_leg.odds.toFixed(2)}</strong></div>` : '',
          m.opt_b_pick ? `<div style="margin-top:4px;"><span class="badge ${m.opt_b_pick.ev_pct>0?'b-pos':'b-warn'}">B</span> ${m.opt_b_pick.market_name} <strong class="mono">@~${m.opt_b_pick.odds.toFixed(2)}</strong></div>` : '',
        ].filter(Boolean).join('') || '<span style="color:var(--text-muted);font-size:12px;">Sin señal 1.20–1.90</span>';

        return `<tr>
          <td>
            <div class="mono" style="font-weight:600;">${m.kickoff_col}</div>
            <div style="font-size:11px;color:var(--text-muted);">${m.league}</div>
          </td>
          <td>
            <div class="match-name">${m.home} vs ${m.away}</div>
            <div class="form-row"><span class="form-lbl">Loc:</span>${formDots(m.h_recent_scores)}</div>
            <div class="form-row"><span class="form-lbl">Vis:</span>${formDots(m.a_recent_scores)}</div>
          </td>
          <td style="font-size:12px;">
            <div>Loc: <strong>${(hs.win_pct*100).toFixed(0)}%</strong> G • <strong>${(hs.unbeaten_pct*100).toFixed(0)}%</strong> 1X • ${hs.gf_avg.toFixed(2)} GF</div>
            <div>Vis: <strong>${(as_.win_pct*100).toFixed(0)}%</strong> G • <strong>${(as_.unbeaten_pct*100).toFixed(0)}%</strong> X2 • ${as_.gf_avg.toFixed(2)} GF</div>
          </td>
          <td>
            <div class="odds-trio mono">
              <div class="odd-chip"><span>1</span>${m.o1.toFixed(2)}</div>
              <div class="odd-chip"><span>X</span>${m.ox.toFixed(2)}</div>
              <div class="odd-chip"><span>2</span>${m.o2.toFixed(2)}</div>
            </div>
            <div style="font-size:11px;color:var(--text-muted);margin-top:4px;">${m.ou_line ? 'O/U ' + m.ou_line : ''} • ${m.provider}</div>
          </td>
          <td>${picksHtml}</td>
          <td><button class="btn btn-secondary" style="padding:6px 10px;min-height:32px;font-size:12px;" onclick="openDrawer(${origIdx})">Analizar</button></td>
        </tr>`;
      }).join('') || '<tr><td colspan="6" style="text-align:center;color:var(--text-muted);padding:26px;">No se encontraron partidos para este filtro.</td></tr>';
    }

    function renderTickets() {
      const pa = lastScan.parlays_a || [];
      document.getElementById('cntOptA').textContent = pa.length;
      document.getElementById('optAGrid').innerHTML = pa.map(p => `
        <article class="ticket">
          <div class="ticket-head">
            <span class="league-tag">Combinada 2 Partidos</span>
            <span class="time-tag mono">${p.kickoff_col}</span>
          </div>
          <div class="legs-box">
            <div class="leg-row">
              <div class="leg-title">${p.leg1.split(':')[0]}</div>
              <div class="leg-pick">${p.leg1.split(':').slice(1).join(':')}</div>
            </div>
            <div class="leg-row">
              <div class="leg-title">${p.leg2.split(':')[0]}</div>
              <div class="leg-pick">${p.leg2.split(':').slice(1).join(':')}</div>
            </div>
          </div>
          <div class="ticket-foot">
            <span class="odds-pill mono">@${p.combo_odds.toFixed(3)}</span>
            <div class="prob-meta">
              <div class="prob-labels"><span>Est: <strong>${p.prob_est}%</strong></span><span>Impl: ${p.prob_impl}%</span></div>
              <div class="bar-track"><div class="bar-fill" style="width:${Math.min(100, p.prob_est)}%;background:${p.ev_pct>0?'#16A34A':'#D97706'}"></div></div>
            </div>
            ${evBadge(p.ev_pct)}
          </div>
        </article>
      `).join('') || '<div class="empty-state">Ninguna combinada Opción A cumplió los filtros en este rango. Prueba cambiar a <strong>Colombia + Europa</strong>.</div>';

      const pb = lastScan.opt_b || [];
      document.getElementById('cntOptB').textContent = pb.length;
      document.getElementById('optBGrid').innerHTML = pb.map(b => `
        <article class="ticket">
          <div class="ticket-head">
            <span class="league-tag">${b.league} • Bet Builder</span>
            <span class="time-tag mono">${b.kickoff_col}</span>
          </div>
          <div class="legs-box">
            <div class="leg-row">
              <div class="leg-title">${b.title}</div>
              <div class="leg-pick">${b.market_name}</div>
            </div>
          </div>
          <div class="ticket-foot">
            <span class="odds-pill mono">@~${b.odds.toFixed(3)}</span>
            <div class="prob-meta">
              <div class="prob-labels"><span>Est: <strong>${b.prob_est}%</strong></span><span>Impl: ${b.prob_impl}%</span></div>
              <div class="bar-track"><div class="bar-fill" style="width:${Math.min(100, b.prob_est)}%;background:${b.ev_pct>0?'#16A34A':'#D97706'}"></div></div>
            </div>
            ${evBadge(b.ev_pct)}
          </div>
        </article>
      `).join('') || '<div class="empty-state">Ningún Bet Builder cumplió las reglas 1.20–1.90 en esta selección.</div>';
    }

    function openDrawer(idx) {
      const m = lastScan.matches[idx];
      if (!m) return;
      document.getElementById('drLeague').textContent = m.league_label;
      document.getElementById('drTitle').textContent = `${m.home} vs ${m.away}`;
      document.getElementById('drSub').textContent = `Hora Colombia: ${m.kickoff_col} • Casa: ${m.provider} • Goles esperados Poisson: ${m.lam_h} - ${m.lam_a}`;

      const hs = m.h_stat, as_ = m.a_stat;
      const rowsHtml = (m.all_markets || []).map(mk => `
        <tr>
          <td style="font-weight:500;">${mk.name}</td>
          <td class="mono"><strong>${mk.odds.toFixed(2)}</strong></td>
          <td class="mono">${mk.prob}% / ${mk.impl}%</td>
          <td>${evBadge(mk.ev_pct)}</td>
        </tr>
      `).join('');

      document.getElementById('drBody').innerHTML = `
        <div class="stat-split">
          <div class="team-box">
            <h4>${m.home} (Local)</h4>
            <div style="font-size:12px;color:var(--text-sub);">
              Victorias: <strong>${(hs.win_pct*100).toFixed(0)}%</strong> • No pierde: <strong>${(hs.unbeaten_pct*100).toFixed(0)}%</strong><br>
              Anota +0.5: <strong>${(hs.o05_pct*100).toFixed(0)}%</strong> • GF: <strong>${hs.gf_avg.toFixed(2)}</strong> / GA: <strong>${hs.ga_avg.toFixed(2)}</strong>
            </div>
            <div class="form-row" style="margin-top:8px;">${formDots(m.h_recent_scores)}</div>
          </div>
          <div class="team-box">
            <h4>${m.away} (Visitante)</h4>
            <div style="font-size:12px;color:var(--text-sub);">
              Victorias: <strong>${(as_.win_pct*100).toFixed(0)}%</strong> • No pierde: <strong>${(as_.unbeaten_pct*100).toFixed(0)}%</strong><br>
              Anota +0.5: <strong>${(as_.o05_pct*100).toFixed(0)}%</strong> • GF: <strong>${as_.gf_avg.toFixed(2)}</strong> / GA: <strong>${as_.ga_avg.toFixed(2)}</strong>
            </div>
            <div class="form-row" style="margin-top:8px;">${formDots(m.a_recent_scores)}</div>
          </div>
        </div>
        <h3 style="margin:0 0 8px;font-size:14px;">Todos los Mercados Evaluados (Prob. Poisson vs Implícita)</h3>
        <div class="table-card">
          <table>
            <thead><tr><th>Mercado</th><th>Cuota</th><th>Est / Impl</th><th>EV</th></tr></thead>
            <tbody>${rowsHtml}</tbody>
          </table>
        </div>
      `;
      document.getElementById('drawerBackdrop').classList.add('open');
    }

    function closeDrawer() {
      document.getElementById('drawerBackdrop').classList.remove('open');
    }

    async function runScan() {
      const save = document.getElementById('saveFlag').checked ? '1' : '0';
      setLoading(true, 'Consultando partidos en vivo y calculando estadísticas...');
      try {
        const res = await fetch(`/api/scan?scope=${currentScope}&days=5&save=${save}`);
        lastScan = await res.json();
        document.getElementById('cntMatches').textContent = lastScan.total_matches;
        document.getElementById('apiBadge').textContent = lastScan.apifootball_note
          ? 'API-Football Free (2022–2024) • Usando ESPN en vivo'
          : 'ESPN en vivo (gratis)';
        setLoading(false, `${lastScan.total_matches} partidos próximos analizados. ${save==='1' ? lastScan.saved_count + ' nuevas jugadas guardadas.' : ''}`);
        renderMatches();
        renderTickets();
        await loadReport();
      } catch (e) {
        setLoading(false, 'Error consultando datos. Revisa tu conexión a internet.');
      }
    }

    async function runSettle() {
      setLoading(true, 'Comprobando marcadores finales en ESPN...');
      try {
        const r = await fetch('/api/settle');
        const d = await r.json();
        setLoading(false, `Liquidación completada: ${d.settled_now} actualizadas, ${d.still_pending} pendientes.`);
        await loadReport();
      } catch (e) {
        setLoading(false, 'Error al liquidar resultados.');
      }
    }

    function applyStaticScope() {
      const s = fullStaticData.scan;
      if (currentScope === 'col.1') {
        lastScan = {
          ...s,
          matches: (s.matches || []).filter(m => m.league === 'col.1'),
          opt_b: (s.opt_b || []).filter(b => b.league === 'col.1'),
          parlays_a: (s.parlays_a || []).filter(p => p.leg1.includes('(col.1)') || p.leg2.includes('(col.1)')),
          sharp_picks: (s.sharp_picks || []).filter(x => x.league === 'col.1'),
        };
      } else {
        lastScan = s;
      }
      document.getElementById('cntMatches').textContent = lastScan.matches.length;
      renderMatches();
      renderTickets();
    }

    async function initStatic() {
      document.getElementById('saveToggleLabel').style.display = 'none';
      document.getElementById('btnScan').style.display = 'none';
      document.getElementById('btnSettle').style.display = 'none';
      setLoading(true, 'Cargando último reporte publicado por GitHub Actions...');
      try {
        const res = await fetch('./data.json?t=' + Date.now());
        fullStaticData = await res.json();
        renderReportData(fullStaticData.report);
        document.getElementById('apiBadge').textContent = 'GitHub Pages (Estático) • Auto-actualizado';
        setLoading(false, `Última actualización automática: ${fullStaticData.generated_col} hora Colombia`);
        applyStaticScope();
      } catch (e) {
        setLoading(false, 'No se pudo cargar data.json. Ejecuta el workflow de GitHub Actions.');
      }
    }

    if (STATIC_MODE) {
      initStatic();
    } else {
      loadReport();
      runScan();
    }
  </script>
</body>
</html>
"""


class DashboardHandler(BaseHTTPRequestHandler):
    def _send_json(self, data: dict, code: int = 200) -> None:
        body = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:
        parsed = urllib.parse.urlparse(self.path)
        qs = urllib.parse.parse_qs(parsed.query)

        if parsed.path == "/":
            body = HTML_PAGE.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        elif parsed.path == "/api/report":
            self._send_json(PaperTradingDB().get_summary())
        elif parsed.path == "/api/settle":
            self._send_json(run_settle_pipeline())
        elif parsed.path == "/api/scan":
            scope = qs.get("scope", ["all"])[0]
            days = int(qs.get("days", ["5"])[0])
            save = qs.get("save", ["0"])[0] == "1"
            leagues = ["col.1"] if scope == "col.1" else DEFAULT_LEAGUES
            self._send_json(run_scan_pipeline(leagues=leagues, days=days, save=save))
        else:
            self._send_json({"error": "Not found"}, code=404)

    def log_message(self, format, *args) -> None:
        pass


def main() -> None:
    parser = argparse.ArgumentParser(description="Dashboard Web Local para Bot de Apuestas")
    parser.add_argument("--port", type=int, default=8055)
    parser.add_argument("--no-browser", action="store_true")
    args = parser.parse_args()

    server = ThreadingHTTPServer(("127.0.0.1", args.port), DashboardHandler)
    url = f"http://127.0.0.1:{args.port}"
    print(f"Dashboard abierto en {url} (presiona Ctrl+C para cerrar)")
    if not args.no_browser:
        threading.Timer(0.8, lambda: webbrowser.open(url)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        server.server_close()


if __name__ == "__main__":
    main()
