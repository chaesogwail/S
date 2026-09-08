/* SUT watch — shared data layer (no build step, plain ES2017) */
window.SUT = (function () {
  const TOKEN = '0x98965474ecbec2f532f1f780ee37b0b05f77ca55';
  const RPCS = ['https://polygon-rpc.com', 'https://polygon.llamarpc.com', 'https://polygon-bor-rpc.publicnode.com', 'https://1rpc.io/matic', 'https://polygon.drpc.org'];
  const GATE = 'https://api.gateio.ws/api/v4/spot';
  const NAMES = { gate: '게이트 거래소', pool: '유니스왑 풀(주+보조)', sell: '회사 매도지갑', mpc: 'MPC 금고', fx: '회사 환전지갑' };

  const fmt = {
    n: v => v == null ? '—' : Math.round(v).toLocaleString('ko-KR'),
    k: v => v == null ? '—' : (Math.abs(v) >= 1e6 ? (v / 1e6).toFixed(2) + 'M' : Math.abs(v) >= 1e3 ? (v / 1e3).toFixed(0) + 'k' : Math.round(v)),
    p: v => v == null ? '—' : (v * 100).toFixed(1) + '%',
    sp: v => v == null ? '—' : (v >= 0 ? '+' : '') + (v * 100).toFixed(1) + '%',
    px: v => v == null ? '—' : Number(v).toFixed(4),
    t: d => d.toLocaleString('ko-KR', { hour12: false, month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' }),
  };

  async function loadJSON(path) {
    const r = await fetch(path + '?_=' + Date.now(), { cache: 'no-store' });
    if (!r.ok) throw new Error(path + ' ' + r.status);
    return r.json();
  }

  /* ---- live balances: ERC-20 balanceOf via public RPC (no key) ---- */
  function balanceCall(addr) {
    return { jsonrpc: '2.0', id: 1, method: 'eth_call',
      params: [{ to: TOKEN, data: '0x70a08231' + addr.toLowerCase().replace('0x', '').padStart(64, '0') }, 'latest'] };
  }
  async function rpcBalance(addr) {
    let lastErr;
    for (const url of RPCS) {
      try {
        const r = await fetch(url, { method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify(balanceCall(addr)) });
        const j = await r.json();
        if (j.result) return Number(BigInt(j.result)) / 1e18;
      } catch (e) { lastErr = e; }
    }
    throw lastErr || new Error('rpc');
  }
  async function liveBalances(wallets) {
    const out = {};
    await Promise.all(Object.entries(wallets).map(async ([k, a]) => { try { out[k] = await rpcBalance(a); } catch (e) { out[k] = null; } }));
    if (out.pool_main != null && out.pool_aux != null) out.pool = out.pool_main + out.pool_aux;
    return out;
  }

  /* ---- live price from Gate (may be blocked by CORS on some setups; caller must tolerate failure) ---- */
  async function livePrice() {
    const r = await fetch(GATE + '/tickers?currency_pair=SUT_USDT');
    const j = await r.json();
    const t = j[0];
    return { last: Number(t.last), change24h: Number(t.change_percentage) / 100, high24h: Number(t.high_24h), low24h: Number(t.low_24h), quoteVol24h: Number(t.quote_volume) };
  }
  async function todayCandle() {
    // daily candle for the current UTC day (= KST 09:00 boundary)
    const r = await fetch(GATE + '/candlesticks?currency_pair=SUT_USDT&interval=1d&limit=2');
    const j = await r.json();
    return j.map(c => ({ t: Number(c[0]), v: Number(c[1]), c: Number(c[2]), h: Number(c[3]), l: Number(c[4]), o: Number(c[5]) }));
  }

  /* ---- anomaly rules (same as the offline builder, applied to the latest day + live deltas) ---- */
  function robustStats(arr) {
    const s = arr.filter(x => x != null).slice().sort((a, b) => a - b);
    if (!s.length) return { med: 0, mad: 0 };
    const med = s[Math.floor(s.length / 2)];
    const dev = s.map(x => Math.abs(x - med)).sort((a, b) => a - b);
    return { med, mad: dev[Math.floor(dev.length / 2)] };
  }
  function flagsForDay(days, idx, live) {
    const d = days[idx]; const prev = days.slice(Math.max(0, idx - 30), idx);
    const flags = [];
    const f = d.f || {};
    if (f.vault_to_sellers > 0) flags.push({ lvl: 'alert', text: `MPC 금고 → 매도경로 이관 ${fmt.n(f.vault_to_sellers)} SUT. 과거 사례: 1~4일 뒤 거래소 도착 → 매도.` });
    if (f.fx_in > 0) flags.push({ lvl: 'alert', text: `환전지갑에 ${fmt.n(f.fx_in)} SUT 유입. 가장 앞선 매도 신호(9월: 유입 후 1~4일 내 게이트 도착).` });
    if (f.company_to_gate > 0) flags.push({ lvl: 'alert', text: `회사 물량 ${fmt.n(f.company_to_gate)} SUT 게이트 도착. 9/7 사례에서 도착일부터 하락.` });
    if (f.sell_out > 0) flags.push({ lvl: 'alert', text: `매도지갑에서 ${fmt.n(f.sell_out)} SUT 유출(시장 매도).` });
    const gateTot = (f.gate_in || 0) + (f.gate_out || 0);
    const st = robustStats(prev.map(x => (x.f.gate_in || 0) + (x.f.gate_out || 0)));
    if (st.med > 0 && (gateTot >= 10 * st.med || (st.mad > 0 && (gateTot - st.med) / (1.4826 * st.mad) >= 5)))
      flags.push({ lvl: 'watch', text: `게이트 이동량 ${fmt.n(gateTot)} SUT — 30일 중앙값의 ${(gateTot / st.med).toFixed(1)}배. 6월 사례에서는 거래소 내부 정리였고 가격과 무관.` });
    const poolTot = (f.public_buy_from_pool || 0) + (f.public_sell_to_pool || 0);
    const sp = robustStats(prev.map(x => (x.f.public_buy_from_pool || 0) + (x.f.public_sell_to_pool || 0)));
    if (sp.med > 0 && poolTot >= 8 * sp.med) flags.push({ lvl: 'watch', text: `풀 거래량 ${fmt.n(poolTot)} SUT — 평소의 ${(poolTot / sp.med).toFixed(1)}배.` });
    const avgPool = days.reduce((a, x) => a + x.pool, 0) / days.length;
    const poolNow = (live && live.pool != null) ? live.pool : d.pool;
    if (poolNow < 0.25 * avgPool) flags.push({ lvl: 'watch', text: `풀 재고 ${fmt.n(poolNow)} SUT — 평균의 ${(poolNow / avgPool * 100).toFixed(0)}%. 얇은 재고에서는 작은 매수도 큰 등락을 만든다(9월 초 사례).` });
    if (live && live.sell != null && d.sell != null && live.sell < d.sell - 1000)
      flags.push({ lvl: 'alert', text: `매도지갑 잔고가 마지막 집계(${fmt.n(d.sell)}) 대비 ${fmt.n(d.sell - live.sell)} SUT 줄었습니다 — 회사가 팔고 있습니다.` });
    if (live && live.fx != null && live.fx > 1000)
      flags.push({ lvl: 'alert', text: `환전지갑에 지금 ${fmt.n(live.fx)} SUT가 있습니다 — 거래소 이동 대기 물량.` });
    return flags;
  }

  return { TOKEN, NAMES, fmt, loadJSON, liveBalances, livePrice, todayCandle, flagsForDay, robustStats };
})();
