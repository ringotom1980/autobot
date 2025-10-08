// assets/js/metrics.js (v2)
// 本檔只處理：策略模板池摘要 + 近 7 日演化趨勢
// 依賴 app.js 內的 fetchJSON 與 API_METRICS 常數（請確保先載入 app.js）

(function () {
  const POLL_MS = 10_000;

  // --------- 策略模板池：渲染 ---------
  function renderTplPool(poolArr) {
    const elBadge  = document.getElementById('tplPoolBadge');
    const elActive = document.getElementById('tplActive');
    const elFrozen = document.getElementById('tplFrozen');
    const elTotal  = document.getElementById('tplTotal');

    if (!elBadge || !elActive || !elFrozen || !elTotal) return;

    try {
      let active = 0, frozen = 0;
      (poolArr || []).forEach(r => {
        const status = String(r.status || '').toUpperCase();
        const c = Number(r.c || 0);
        if (status === 'ACTIVE') active += c;
        else if (status === 'FROZEN') frozen += c;
      });
      const total = active + frozen;

      elActive.textContent = String(active);
      elFrozen.textContent = String(frozen);
      elTotal.textContent  = String(total);

      // 狀態小圓點：有 ACTIVE => 綠；無 ACTIVE 但有總數 => 黃；讀不到 => 紅
      elBadge.classList.remove('ok','warn','crit');
      if (total === 0) {
        elBadge.classList.add('warn');
        elBadge.title = '無策略啟用（或尚未建立）';
      } else if (active > 0) {
        elBadge.classList.add('ok');
        elBadge.title = '策略池正常運作';
      } else {
        elBadge.classList.add('warn');
        elBadge.title = '僅有凍結策略，建議啟用或產生新策略';
      }
    } catch (e) {
      elBadge?.classList.remove('ok','warn');
      elBadge?.classList.add('crit');
      if (elBadge) elBadge.title = '讀取錯誤';
    }
  }

  // --------- 近 7 日演化：繪圖 ---------
  function drawEvoChart(rows) {
    const cvs = document.getElementById('evoChart');
    const empty = document.getElementById('evoEmpty');
    if (!cvs) return;

    const data = (rows || []).map(r => ({
      d: String(r.d || ''),
      m: Number(r.n_mutate || 0),
      c: Number(r.n_cross  || 0),
      f: Number(r.n_freeze || 0),
    }));

    if (!data.length) {
      if (empty) empty.style.display = 'block';
      const ctx0 = cvs.getContext('2d');
      ctx0 && ctx0.clearRect(0, 0, cvs.width, cvs.height);
      return;
    } else {
      if (empty) empty.style.display = 'none';
    }

    // DPR 調整，避免字與線模糊
    const dpr = window.devicePixelRatio || 1;
    const cssWidth  = cvs.clientWidth || 600;
    const cssHeight = 180;
    cvs.width  = Math.floor(cssWidth * dpr);
    cvs.height = Math.floor(cssHeight * dpr);
    const ctx = cvs.getContext('2d');
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.clearRect(0, 0, cssWidth, cssHeight);

    // 佈局參數
    const PAD_L = 32, PAD_R = 8, PAD_T = 16, PAD_B = 24;
    const W = cssWidth  - PAD_L - PAD_R;
    const H = cssHeight - PAD_T - PAD_B;

    // Y 軸最大值
    const maxY = Math.max(1, ...data.map(x => x.m + x.c + x.f, 1), ...data.map(x=>Math.max(x.m,x.c,x.f)));
    const stepY = Math.max(1, Math.ceil(maxY / 4));

    // 座標軸
    ctx.strokeStyle = '#28406d';
    ctx.lineWidth = 1;
    ctx.beginPath();
    ctx.moveTo(PAD_L, PAD_T);
    ctx.lineTo(PAD_L, PAD_T + H);
    ctx.lineTo(PAD_L + W, PAD_T + H);
    ctx.stroke();

    // Y 刻度
    ctx.fillStyle = '#8aa0c2';
    ctx.font = '12px system-ui';
    for (let y = 0; y <= maxY; y += stepY) {
      const yy = PAD_T + H - (y / maxY) * H;
      ctx.globalAlpha = 0.25;
      ctx.beginPath();
      ctx.moveTo(PAD_L, yy);
      ctx.lineTo(PAD_L + W, yy);
      ctx.stroke();
      ctx.globalAlpha = 1;
      ctx.fillText(String(y), 4, yy + 4);
    }

    // X 軸（日期）
    const bw = Math.max(10, W / data.length * 0.7);     // 每個日期的群組柱寬
    const gap = Math.max(10, (W / data.length) - bw);   // 群組之間間距
    const barW = (bw - 8) / 3;                          // 三種事件各自的柱寬
    const colors = { mutate: '#6fa8dc', cross: '#a3d977', freeze: '#ffb366' };

    data.forEach((row, i) => {
      const groupX = PAD_L + i * (bw + gap);

      // 柱高轉 y
      const hM = (row.m / maxY) * H;
      const hC = (row.c / maxY) * H;
      const hF = (row.f / maxY) * H;

      // mutate
      ctx.fillStyle = colors.mutate;
      ctx.fillRect(groupX, PAD_T + H - hM, barW, hM);
      // cross
      ctx.fillStyle = colors.cross;
      ctx.fillRect(groupX + barW + 4, PAD_T + H - hC, barW, hC);
      // freeze
      ctx.fillStyle = colors.freeze;
      ctx.fillRect(groupX + 2*(barW + 4), PAD_T + H - hF, barW, hF);

      // X 標籤（只顯示月-日）
      ctx.fillStyle = '#8aa0c2';
      ctx.textAlign = 'center';
      ctx.fillText(row.d.slice(5), groupX + bw/2, PAD_T + H + 16);
      ctx.textAlign = 'left';
    });
  }

  // --------- 載入資料 ---------
  async function loadMetricsExtra() {
    try {
      const j = await fetchJSON(API_METRICS);

      // 策略模板池
      const pool = j?.evolution?.pool || [];
      renderTplPool(pool);

      // 7 日演化
      const evo7 = j?.evolution?.by_day_7d || [];
      drawEvoChart(evo7);
    } catch (e) {
      // 標記錯誤狀態
      const elBadge = document.getElementById('tplPoolBadge');
      elBadge?.classList.remove('ok','warn');
      elBadge?.classList.add('crit');
      if (elBadge) elBadge.title = '讀取錯誤';
      drawEvoChart([]);
      // 不 console.error，避免壓爆主控台；必要時可打開
      // console.error('metrics.js load error', e);
    }
  }

  document.addEventListener('DOMContentLoaded', () => {
    loadMetricsExtra();
    setInterval(loadMetricsExtra, POLL_MS);
  });
})();
