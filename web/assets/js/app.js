// web/assets/js/app.js
const API_SETTINGS = '/api/settings.php';
const API_METRICS = '/api/metrics.php';
const API_EXINFO = '/api/exchange_info.php';
const API_HEALTH = '/api/health.php';

/* ---------- 基礎工具 ---------- */
async function fetchJSON(url, opt = {}) {
  const r = await fetch(url, { credentials: 'same-origin', ...opt });
  if (!r.ok) throw new Error(`HTTP ${r.status}`);
  return await r.json();
}
const $ = (id) => document.getElementById(id);
const setText = (id, v) => {
  const el = $(id);
  if (el) el.textContent = v;
};
const setVal = (id, v) => {
  const el = $(id);
  if (el) el.value = v;
};
const getVal = (id) => {
  const el = $(id);
  return el ? el.value : '';
};
const setIfNumber = (id, v) => {
  if (v !== null && v !== undefined && v !== '') setVal(id, String(v));
};
function clampLev(v) {
  return Math.max(1, Math.min(150, Number(v || 1)));
}
function fmtTimeAgo(ms) {
  if (!ms) return '--';
  const diff = Date.now() - Number(ms);
  if (diff < 0) return '剛剛';
  const s = Math.floor(diff / 1000);
  if (s < 60) return `${s}s 前`;
  const m = Math.floor(s / 60);
  if (m < 60) return `${m}m 前`;
  const h = Math.floor(m / 60);
  if (h < 24) return `${h}h 前`;
  const d = Math.floor(h / 24);
  return `${d}d 前`;
}

// 金額格式化 & 正負上色
function fmtUSD(n) {
  const x = Number(n || 0);
  return x.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}
function paintSign(el, val) {
  if (!el) return;
  // 先清空 class 與 inline color
  el.classList.remove('pos', 'neg', 'zero');
  el.style.color = '';
  el.style.opacity = '';

  if (val > 0) {
    el.classList.add('pos');
    el.style.color = '#e74c3c';
  } else if (val < 0) {
    el.classList.add('neg');
    el.style.color = '#2ecc71';
  } else {
    el.classList.add('zero');
    el.style.opacity = '0.85';
  }
}

// 立刻把任務進度區塊清空（不等 API 回應）
function resetJobProgressUI() {
  setText('jobId', '--');
  setText('phase', '--');
  if ($('progressBar')) $('progressBar').style.width = '0%';
  setText('progressText', '--');

  // 健康徽章同時先顯示初始化狀態（避免紅色）
  const badge = $('healthBadge');
  if (badge) {
    badge.className = 'badge warn';
    badge.title = '初始化中';
  }
}

/* ---------- 幣安下拉初始化 ---------- */
async function initDropdowns() {
  try {
    const j = await fetchJSON(API_EXINFO);
    const syms = (j.symbols || []).filter((s) => s.endsWith('USDT'));
    const ivs = j.intervals || ['1m', '15m', '1h', '4h'];

    const symSel = $('symbolSelect');
    const ivSel = $('intervalSelect');
    if (!symSel || !ivSel) return;

    symSel.innerHTML = '';
    ivSel.innerHTML = '';
    syms.forEach((s) => {
      const o = document.createElement('option');
      o.value = s;
      o.textContent = s;
      symSel.appendChild(o);
    });
    ivs.forEach((i) => {
      const o = document.createElement('option');
      o.value = i;
      o.textContent = i;
      ivSel.appendChild(o);
    });

    if (syms.includes('BTCUSDT')) symSel.value = 'BTCUSDT';
    if (ivs.includes('1m')) ivSel.value = '1m';
  } catch (e) {
    console.error('initDropdowns error', e);
  }
}

/* ---------- 槓桿控件 ---------- */
function bindLeverageControls() {
  const range = $('levRange');
  const num = $('levNum');
  const dec = $('levDec');
  const inc = $('levInc');
  if (!range || !num || !dec || !inc) return;
  const sync = (v) => {
    v = clampLev(v);
    range.value = String(v);
    num.value = String(v);
  };

  range.addEventListener('input', () => sync(range.value));
  num.addEventListener('input', () => sync(num.value));
  dec.addEventListener('click', () => sync(Number(num.value) - 1));
  inc.addEventListener('click', () => sync(Number(num.value) + 1));
}

/* ---------- 進階區塊開關 ---------- */
function bindAdvancedToggle() {
  const toggle = $('advToggle');
  const panel = $('advPanel');
  const chev = $('advChevron');
  if (!toggle || !panel || !chev) return;
  panel.style.display = 'none';
  chev.textContent = '展開 ▼';
  toggle.addEventListener('click', (e) => {
    if (e.target && e.target.id === 'useAdv') return;
    const show = panel.style.display === 'none';
    panel.style.display = show ? 'block' : 'none';
    chev.textContent = show ? '收合 ▲' : '展開 ▼';
  });
}

/* ---------- 依模式顯示/隱藏「二次保險」 ---------- */
function toggleLiveArmedVisibility() {
  const modeSel = $('tradeMode');
  const block = $('liveArmedBlock');
  const armedCb = $('liveArmed');
  if (!modeSel || !block || !armedCb) return;

  const isLive = modeSel.value === 'LIVE';
  block.style.display = isLive ? 'block' : 'none';

  // 在 SIM 模式時，自動取消勾選，避免殘留狀態誤送
  if (!isLive) armedCb.checked = false;
}

/* ---------- 啟動中鎖定（把進階風控也鎖） ---------- */
function setCoreControlsDisabled(disabled) {
  const ids = [
    'symbolSelect',
    'intervalSelect',
    'levRange',
    'levNum',
    'levDec',
    'levInc',
    'investNum',
    'useAdv',
    'max_risk_pct',
    'max_daily_dd_pct',
    'max_consec_losses',
    'entry_threshold',
    'reverse_gap',
    'cooldown_bars',
    'min_hold_bars',
    'exitHorizonAuto',
    'tradeMode',
    'liveArmed',
  ];
  ids.forEach((id) => {
    const el = $(id);
    if (el) el.disabled = !!disabled;
  });
}

/* ---------- 讀取 DB 設定，填到 UI ---------- */
async function loadSettings() {
  try {
    const row = await fetchJSON(API_SETTINGS);
    const enabled = Number(row.is_enabled || 0) === 1;

    if ($('statusDot')) {
      $('statusDot').textContent = enabled ? '啟動中' : '關閉中';
      $('statusDot').className = `pill ${enabled ? 'ok' : 'warn'}`;
    }
    if ($('btnToggle')) {
      $('btnToggle').textContent = enabled ? '關閉 AI 機器人' : '啟動 AI 機器人';
      $('btnToggle').dataset.running = enabled ? '1' : '0';
    }
    setCoreControlsDisabled(enabled);

    let symbols = [],
      intervals = [],
      levMap = {},
      invMap = {};
    try {
      symbols = JSON.parse(row.symbols_json || '[]');
    } catch (e) {}
    try {
      intervals = JSON.parse(row.intervals_json || '[]');
    } catch (e) {}
    try {
      levMap = JSON.parse(row.leverage_json || '{}');
    } catch (e) {}
    try {
      invMap = JSON.parse(row.invest_usdt_json || '{}');
    } catch (e) {}

    const symSel = $('symbolSelect');
    const ivSel = $('intervalSelect');

    if (symSel) {
      if (
        !symSel.dataset.userSelected &&
        symbols.length &&
        [...symSel.options].some((o) => o.value === symbols[0])
      ) {
        symSel.value = symbols[0];
      }
    }
    if (ivSel) {
      if (
        !ivSel.dataset.userSelected &&
        intervals.length &&
        [...ivSel.options].some((o) => o.value === intervals[0])
      ) {
        ivSel.value = intervals[0];
      }
    }

    const curSym = symSel ? symSel.value : 'BTCUSDT';
    const lev = clampLev((levMap && levMap[curSym]) ?? 10);
    const inv = Math.max(1, Number((invMap && invMap[curSym]) ?? 100));
    setVal('levRange', String(lev));
    setVal('levNum', String(lev));
    setVal('investNum', String(inv));

    setIfNumber('max_risk_pct', row.max_risk_pct);
    setIfNumber('max_daily_dd_pct', row.max_daily_dd_pct);
    setIfNumber('max_consec_losses', row.max_consec_losses);
    setIfNumber('entry_threshold', row.entry_threshold);
    setIfNumber('reverse_gap', row.reverse_gap);
    setIfNumber('cooldown_bars', row.cooldown_bars);
    setIfNumber('min_hold_bars', row.min_hold_bars);
    if ($('exitHorizonAuto'))
      $('exitHorizonAuto').checked = Number(row.exit_horizon_auto || 0) === 1;
    if ($('useAdv')) $('useAdv').checked = Number(row.adv_enabled || 0) === 1;
    if ($('tradeMode')) $('tradeMode').value = row.trade_mode === 'LIVE' ? 'LIVE' : 'SIM';
    if ($('liveArmed')) $('liveArmed').checked = Number(row.live_armed || 0) === 1;
    toggleLiveArmedVisibility();
  } catch (e) {
    console.error('loadSettings error', e);
  }
}

/* ---------- 任務進度 / 績效 / 交易統計 ---------- */
async function loadMetrics() {
  try {
    const j = await fetchJSON(API_METRICS);

    const vSession = Number(j.pnl_session ?? 0);
    const vToday = Number(j.pnl_today ?? 0);
    const v7d = Number(j.pnl_7d ?? 0);

    setText('pnlSession', fmtUSD(vSession));
    setText('pnlToday', fmtUSD(vToday));
    setText('pnl7d', fmtUSD(v7d));

    paintSign($('pnlSession'), vSession);
    paintSign($('pnlToday'), vToday);
    paintSign($('pnl7d'), v7d);

    setText('sessionLabel', j.session_id ? `Session #${j.session_id}` : 'Session #--');

    const enabled = Number(j.is_enabled || 0) === 1;
    if ($('statusDot')) {
      $('statusDot').textContent = enabled ? '啟動中' : '關閉中';
      $('statusDot').className = `pill ${enabled ? 'ok' : 'warn'}`;
    }
    if ($('btnToggle')) {
      $('btnToggle').textContent = enabled ? '關閉 AI 機器人' : '啟動 AI 機器人';
      $('btnToggle').dataset.running = enabled ? '1' : '0';
    }
    setCoreControlsDisabled(enabled);

    const p = j.progress || null;
    const pct = p ? Number(p.pct || 0) : 0;
    setText('jobId', p ? p.job_id : '--');
    setText('phase', p ? p.phase : '--');
    if ($('progressBar')) $('progressBar').style.width = `${pct}%`;
    setText('progressText', p ? `${pct}%  (${p.step}/${p.total})` : '--');

    const st = j.stats || { long: 0, short: 0, hold: 0 };
    setText('statLong', String(st.long ?? 0));
    setText('statShort', String(st.short ?? 0));
    setText('statHold', String(st.hold ?? 0));
  } catch (e) {
    console.error('loadMetrics error', e);
  }
}

/* ---------- 健康徽章（任務進度標題旁） ---------- */
async function loadHealth() {
  try {
    const j = await fetchJSON(API_HEALTH);
    const jobs = j.jobs || [];
    const badge = $('healthBadge');
    if (!badge) return;

    if (!jobs.length) {
      badge.className = 'badge warn';
      badge.title = '無心跳';
      return;
    }

    let ok = 0,
      stale = 0,
      err = 0;
    jobs.forEach((x) => {
      if (x.ok) ok++;
      else if (x.message === 'STALE') stale++;
      else err++;
    });

    // 顏色規則：有 ERROR → 紅；否則有 STALE → 黃；全 OK → 綠
    if (err >= 1) badge.className = 'badge crit';
    else if (stale >= 1) badge.className = 'badge warn';
    else badge.className = 'badge ok';

    badge.title = `OK ${ok}｜STALE ${stale}｜ERROR ${err}`;
  } catch (e) {
    console.warn('loadHealth error', e);
    const badge = $('healthBadge');
    if (badge) {
      badge.className = 'badge crit';
      badge.title = 'API 錯誤';
    }
  }
}

/* ---------- Modal（啟動/關閉二次確認） ---------- */
const modal = {
  mask: null,
  title: null,
  body: null,
  ok: null,
  cancel: null,
  close: null,
  show({ title, body, onok }) {
    if (!this.mask) return;
    this.mask.style.display = 'flex';
    this.title.textContent = title || '確認';
    this.body.textContent =
      typeof body === 'string' && body.length ? body : '（沒有可顯示的內容）';
    const clear = () => {
      this.ok.onclick = null;
      this.cancel.onclick = null;
      this.close.onclick = null;
      this.mask.style.display = 'none';
    };
    this.ok.onclick = async () => {
      try {
        await onok?.();
      } finally {
        clear();
      }
    };
    this.cancel.onclick = clear;
    this.close.onclick = clear;
  },
  init() {
    this.mask = $('modalMask');
    this.title = $('modalTitle');
    this.body = $('modalBody');
    this.ok = $('modalOk');
    this.cancel = $('modalCancel');
    this.close = $('modalClose');
  },
};

const ADV_LABELS_ZH = {
  max_risk_pct: '單筆最大風險（max_risk_pct）',
  max_daily_dd_pct: '單日最大回撤（max_daily_dd_pct）',
  max_consec_losses: '最大連虧次數（max_consec_losses）',
  entry_threshold: '進場閾值（entry_threshold）',
  reverse_gap: '反向差值（reverse_gap）',
  cooldown_bars: '冷卻棒數（cooldown_bars）',
  min_hold_bars: '最小持有棒數（min_hold_bars）',
  exit_horizon_auto: '自動學習出場上限（k_max）',
};

function summarizeCurrentSettings() {
  const sym = getVal('symbolSelect') || 'BTCUSDT';
  const iv = getVal('intervalSelect') || '1m';
  const lev = clampLev(getVal('levNum') || getVal('levRange') || 10);
  const inv = Math.max(1, Number(getVal('investNum') || 100));
  const useAdv = $('useAdv') ? $('useAdv').checked : false;

  // —— 這兩行是關鍵：直接讀 UI 的下拉與勾選 —
  const mode = $('tradeMode') ? $('tradeMode').value : 'SIM'; // SIM / LIVE
  const armed = $('liveArmed') && $('liveArmed').checked ? 'ON' : 'OFF'; // ON / OFF

  const modeLine =
    mode === 'LIVE'
      ? `模式: 真實下單 ｜ 二次保險: ${armed === 'ON' ? '啟用' : '未啟用'}`
      : `模式: 模擬下單`;

  const modeText =
    mode === 'LIVE'
      ? `⚠️ 真實單模式
  二次保險：${armed === 'ON' ? '啟用 ✅（會實際下單）' : '未啟用 ❌（僅記錄動作）'}`
      : `⚠️ 模擬單模式
  不會下單，僅模擬交易結果`;

  const adv = {
    max_risk_pct: getVal('max_risk_pct'),
    max_daily_dd_pct: getVal('max_daily_dd_pct'),
    max_consec_losses: getVal('max_consec_losses'),
    entry_threshold: getVal('entry_threshold'),
    reverse_gap: getVal('reverse_gap'),
    cooldown_bars: getVal('cooldown_bars'),
    min_hold_bars: getVal('min_hold_bars'),
  };

  const advLines =
    Object.entries(adv)
      .filter(([, v]) => v !== '' && v !== null && v !== undefined)
      .map(([k, v]) => `  ${ADV_LABELS_ZH[k] || k}: ${v}`)
      .join('\n') || '  （使用預設值）';
  const autoK = $('exitHorizonAuto') && $('exitHorizonAuto').checked ? '啟用' : '未啟用';
  const out = `幣種: ${sym}
週期: ${iv}
槓桿: ${lev}x
投入: ${inv} USD
${modeLine}
${modeText}
自動 k_max（exit_horizon_auto）: ${autoK}
進階風控: ${useAdv ? '啟用' : '未啟用'}
${useAdv ? advLines : ''}`;

  return out; // ★ 不能少
}

function numOrNull(id) {
  const v = getVal(id);
  if (v === '') return null;
  const n = Number(v);
  return isFinite(n) ? n : null;
}

function buildCorePayload(extra = {}) {
  const sym = getVal('symbolSelect') || 'BTCUSDT';
  const iv = getVal('intervalSelect') || '1m';
  const lev = clampLev(getVal('levNum') || getVal('levRange') || 10);
  const inv = Math.max(1, Number(getVal('investNum') || 100));
  const useAdv = $('useAdv') ? $('useAdv').checked : false;

  const payload = {
    symbols_json: [sym],
    intervals_json: [iv],
    leverage_json: { [sym]: lev },
    invest_usdt_json: { [sym]: inv },
    ...extra,
  };
  if (useAdv) {
    const adv = {
      max_risk_pct: numOrNull('max_risk_pct'),
      max_daily_dd_pct: numOrNull('max_daily_dd_pct'),
      max_consec_losses: numOrNull('max_consec_losses'),
      entry_threshold: numOrNull('entry_threshold'),
      reverse_gap: numOrNull('reverse_gap'),
      cooldown_bars: numOrNull('cooldown_bars'),
      min_hold_bars: numOrNull('min_hold_bars'),
    };
    Object.keys(adv).forEach((k) => {
      if (adv[k] === null) delete adv[k];
    });
    Object.assign(payload, adv);
  }
  payload.trade_mode = $('tradeMode') ? $('tradeMode').value : 'SIM';
  payload.live_armed = $('liveArmed') && $('liveArmed').checked ? 1 : 0;
  // ★ SIM 模式一律關閉 live_armed（保險）
  if (payload.trade_mode !== 'LIVE') payload.live_armed = 0;
  payload.adv_enabled = useAdv ? 1 : 0;
  payload.exit_horizon_auto = $('exitHorizonAuto') && $('exitHorizonAuto').checked ? 1 : 0;
  return payload;
}

async function toggleBot() {
  const running = $('btnToggle') && $('btnToggle').dataset.running === '1';
  if (!running) {
    let body = summarizeCurrentSettings();
    // ← 若 summarize 拿不到字串，就用中文後備字串
    if (!body || typeof body !== 'string') {
      const mode = $('tradeMode') ? $('tradeMode').value : 'SIM';
      const armed = $('liveArmed') && $('liveArmed').checked ? 'ON' : 'OFF';
      body =
        mode === 'LIVE'
          ? `模式: 真實下單 ｜ 二次保險：${armed === 'ON' ? '啟用' : '未啟用'}`
          : `模式: 模擬下單`;
    }
    modal.show({
      title: '確認啟動 AI 機器人',
      body,
      onok: async () => {
        // ★ 按下確認就立刻把畫面清空（不等後端）
        resetJobProgressUI();
        const payload = buildCorePayload({ is_enabled: 1 });
        await fetchJSON(API_SETTINGS, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(payload),
        });
        await loadSettings();
        await loadMetrics();
        await loadHealth();
      },
    });
  } else {
    const pnlToday = $('pnlToday') ? $('pnlToday').textContent : '0';
    const pnl7d = $('pnl7d') ? $('pnl7d').textContent : '0';
    const pnlSession = $('pnlSession') ? $('pnlSession').textContent : '0';

    const body = `確定要關閉嗎？
目前獲利（參考）：
  本次啟動累計：${pnlSession} USD
  今日：${pnlToday} USD
  近 7 日：${pnl7d} USD`;

    modal.show({
      title: '確認關閉 AI 機器人',
      body,
      onok: async () => {
        const payload = buildCorePayload({ is_enabled: 0 });
        await fetchJSON(API_SETTINGS, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(payload),
        });
        await loadSettings();
        await loadMetrics();
        await loadHealth();
      },
    });
  }
}

/* ---------- 啟動 ---------- */
document.addEventListener('DOMContentLoaded', async () => {
  modal.init();
  bindLeverageControls();
  bindAdvancedToggle();
  if ($('tradeMode')) $('tradeMode').addEventListener('change', toggleLiveArmedVisibility);
  await initDropdowns();
  await loadSettings();
  toggleLiveArmedVisibility(); // ★ 首次進頁也跑一次，確保狀態正確
  await loadMetrics();
  await loadHealth();

  if ($('btnToggle')) $('btnToggle').addEventListener('click', toggleBot);
  if ($('symbolSelect'))
    $('symbolSelect').addEventListener('change', () => {
      $('symbolSelect').dataset.userSelected = '1';
    });
  if ($('intervalSelect'))
    $('intervalSelect').addEventListener('change', () => {
      $('intervalSelect').dataset.userSelected = '1';
    });

  setInterval(loadMetrics, 10_000);
  setInterval(loadHealth, 10_000);
});
