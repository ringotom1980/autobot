// assets/js/trades.js
(() => {
  const API_BASE = '/api/trades.php';
  const $ = (q) => document.querySelector(q);

  const el = {
    tableBody: $('#tradesBody'),
    empty: $('#tradesEmpty'),
    pager: $('#tradesPager'),
    btnMore: $('#btnToggleTrades'),
    pgInfo: $('#pgInfo'),
    pgPrev: $('#pgPrev'),
    pgNext: $('#pgNext'),
    symbol: $('#symbolSelect'),
    interval: $('#intervalSelect'),
    table: $('#tradesTable'),
  };

  // 狀態
  let mode = 'recent';   // 'recent' = 近5筆；'all' = 全部（10 筆/頁）
  let page = 1;
  const pageSize = 10;   // 需求 #3：顯示更多改為 10 筆且有分頁
  const POLL_MS = 5000;  // 需求 #4：自動更新輪詢

  function centerHeader() {
    // 需求 #2：把表頭也置中（不改 HTML/CSS，用 JS 設置）
    if (!el.table) return;
    el.table.querySelectorAll('th').forEach(th => th.style.textAlign = 'center');
  }

  function fmtTs(ms) {
    if (!ms) return '-';
    const d = new Date(Number(ms));
    const y = d.getFullYear();
    const M = String(d.getMonth() + 1).padStart(2, '0');
    const D = String(d.getDate()).padStart(2, '0');
    const h = String(d.getHours()).padStart(2, '0');
    const m = String(d.getMinutes()).padStart(2, '0');
    const s = String(d.getSeconds()).padStart(2, '0');
    return `${y}-${M}-${D} ${h}:${m}:${s}`;
  }

  function fmtPx(x) {
    if (x === null || x === undefined || x === '') return '-';
    const v = Number(x);
    return Number.isFinite(v) ? v.toFixed(4) : '-';
  }

  function fmtPnl(x) {
    const v = Number(x || 0);
    const color = v > 0 ? '#e74c3c' : (v < 0 ? '#2ecc71' : 'inherit'); // 正紅負綠
    return `<span style="color:${color};">${v.toFixed(2)}</span>`;
  }

  function sideLabel(side) {
    return side === 'LONG' ? '買多' : (side === 'SHORT' ? '買空' : side || '-');
  }

  function renderRows(rows) {
    if (!rows || rows.length === 0) {
      el.tableBody.innerHTML = '';
      el.empty.style.display = 'block';
      return;
    }
    el.empty.style.display = 'none';
    el.tableBody.innerHTML = rows.map(r => {
      return `
        <tr>
          <td style="padding:8px; text-align:center;">${fmtTs(r.exit_ts || r.entry_ts)}</td>
          <td style="padding:8px; text-align:center;">${sideLabel(r.side)}</td>
          <td style="padding:8px; text-align:center;">${fmtPx(r.entry_price)}</td>
          <td style="padding:8px; text-align:center;">${fmtPx(r.exit_price)}</td>
          <td style="padding:8px; text-align:center;">${r.template_id ?? '-'}</td>
          <td style="padding:8px; text-align:center;">${fmtPnl(r.pnl_after_cost)}</td>
        </tr>
      `;
    }).join('');
  }

  async function fetchTrades() {
    const symbol = el.symbol?.value || '';
    const interval = el.interval?.value || '';
    const params = new URLSearchParams();

    // 需求 #1：後端會自動限定目前 session_id，前端不用管；只傳 symbol/interval 即可
    if (symbol) params.set('symbol', symbol);
    if (interval) params.set('interval', interval);

    if (mode === 'recent') {
      params.set('mode', 'recent');
      params.set('limit', '5'); // 需求 #3：預設近5筆
    } else {
      params.set('mode', 'all');
      params.set('page', String(page));
      params.set('page_size', String(pageSize)); // 10 筆/頁
    }

    const url = `${API_BASE}?${params.toString()}`;
    const res = await fetch(url, { cache: 'no-store' });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const data = await res.json();

    renderRows(data.rows || []);
    if (mode === 'all') {
      const total = Number(data.total || 0);
      const totalPages = Math.max(1, Math.ceil(total / pageSize));
      el.pager.style.display = 'flex';
      el.pgInfo.textContent = `第 ${page} / ${totalPages} 頁`;
      el.pgPrev.disabled = (page <= 1);
      el.pgNext.disabled = (page >= totalPages);
    } else {
      el.pager.style.display = 'none';
    }
  }

  function toggleMode() {
    if (mode === 'recent') {
      mode = 'all';
      el.btnMore.textContent = '回到近5筆';
      page = 1;
    } else {
      mode = 'recent';
      el.btnMore.textContent = '顯示更多';
    }
    fetchTrades().catch(console.error);
  }

  // 綁事件
  el.btnMore?.addEventListener('click', toggleMode);
  el.pgPrev?.addEventListener('click', () => { if (page > 1) { page--; fetchTrades().catch(console.error); }});
  el.pgNext?.addEventListener('click', () => { page++; fetchTrades().catch(console.error); });
  el.symbol?.addEventListener('change', () => { page = 1; fetchTrades().catch(console.error); });
  el.interval?.addEventListener('change', () => { page = 1; fetchTrades().catch(console.error); });

  // 自動輪詢（需求 #4）
  let pollTimer = null;
  function startPolling() {
    stopPolling();
    pollTimer = setInterval(() => {
      // 只有在頁面可見時才抓，避免切到背景浪費資源
      if (document.visibilityState === 'visible') {
        fetchTrades().catch(() => {});
      }
    }, POLL_MS);
  }
  function stopPolling() {
    if (pollTimer) {
      clearInterval(pollTimer);
      pollTimer = null;
    }
  }
  document.addEventListener('visibilitychange', () => {
    if (document.visibilityState === 'visible') {
      fetchTrades().then(startPolling).catch(startPolling);
    } else {
      stopPolling();
    }
  });

  // 首次載入
  document.addEventListener('DOMContentLoaded', () => {
    centerHeader();
    // 等 app.js 把 symbol/interval 清單載好後再抓一次
    setTimeout(() => {
      fetchTrades().then(startPolling).catch(startPolling);
    }, 300);
  });
})();
