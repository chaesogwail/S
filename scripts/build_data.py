"""
data/daily.json 과 data/anomalies.json 을 갱신한다. GitHub Actions 에서 15분마다 실행되도록 돼 있다.

  POLYSCAN_KEY=... python scripts/build_data.py

동작
  1) 게이트 일봉(1d)을 API로 받아 가격 갱신 (2026-03-01부터; 최근 1000일 한도)
  2) Etherscan V2 tokentx 로 감시 지갑 6곳의 SUT 전송을 data/state.json 의 마지막 블록 이후만 이어받아 data/transfers.csv 에 누적
  3) 각 지갑의 현재 잔고를 tokenbalance 로 실측하고, 누적 순유입에서 거꾸로 빼서 과거 일별 잔고를 만든다 (앵커 = 오늘)
  4) 지갑별 30일 중앙값 대비 이상 이동 + 회사 매도 사슬 사건을 anomalies.json 에 쓴다
"""
import os, sys, json, time, urllib.parse
from datetime import datetime, timezone
import requests, pandas as pd, numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, "data"); os.makedirs(DATA, exist_ok=True)
SUT = "0x98965474ecbec2f532f1f780ee37b0b05f77ca55"
W = {"gate": "0x0d0707963952f2fba59dd06f2b425ace40b492fe", "pool_main": "0x092295c92bab5e734c4a60dbc0f0ffdcdfc4e165",
     "pool_aux": "0xb700d11b26707015c04c0e03edbe905e08056878", "sell": "0x686a2630ab724f07a1a1de7e2590efb621c5a6a6",
     "fx": "0x1600ef50319d38a42dafcde831b06b55640a42ea", "mpc_vault": "0xf46e16da9cf96c19bfc5c5d550857c7a53ea7bc8"}
COMPANY_SRC = {"0x7cc2f8914b4d77b68355757286f146373f4bf7ad", "0x6973766e354b42d4cc255ef48ed1d2708fd84461", "0xf11d0da941625c2e6df119c6b30df9d42ad0a964",
               "0xe6e7ec8dfbacc0dbfc8e838ff2a49a252ab4ff85", "0xaaa4d5dd26eb1a2afe5fd5fb529fc24cee89cc2c", W["sell"], W["fx"], W["mpc_vault"]}
START = "2026-03-01"
KEY = os.environ.get("POLYSCAN_KEY")
S = requests.Session()


def es(params, tries=6):
    url = "https://api.etherscan.io/v2/api?chainid=137&apikey=" + KEY + "&" + urllib.parse.urlencode(params)
    for i in range(tries):
        try:
            d = S.get(url, timeout=60).json()
        except Exception:
            time.sleep(2); continue
        r = d.get("result")
        if isinstance(r, list) or (isinstance(r, str) and r.isdigit()):
            return r
        if "No transactions" in str(r):
            return []
        time.sleep(2)
    return []


def tokentx(addr, start):
    out = []
    while True:
        r = es(dict(module="account", action="tokentx", contractaddress=SUT, address=addr, startblock=start, endblock=99999999, page=1, offset=1000, sort="asc"))
        if not r: break
        out += r
        if len(r) < 1000: break
        last = int(r[-1]["blockNumber"]); start = last + 1 if last == start else last; time.sleep(0.25)
    return out


def gate_daily():
    t0 = int(pd.Timestamp(START, tz="UTC").timestamp())
    r = S.get("https://api.gateio.ws/api/v4/spot/candlesticks", params=dict(currency_pair="SUT_USDT", interval="1d", **{"from": t0}), timeout=30)
    r.raise_for_status()
    rows = [dict(d=datetime.fromtimestamp(int(c[0]), tz=timezone.utc).strftime("%Y-%m-%d"), o=float(c[5]), h=float(c[3]), l=float(c[4]), c=float(c[2]), v=float(c[1])) for c in r.json()]
    return pd.DataFrame(rows).set_index("d")


def main():
    if not KEY: print("POLYSCAN_KEY missing"); sys.exit(1)
    st_path = os.path.join(DATA, "state.json"); tf_path = os.path.join(DATA, "transfers.csv")
    state = json.load(open(st_path)) if os.path.exists(st_path) else {"last_block": {}}
    T = pd.read_csv(tf_path) if os.path.exists(tf_path) else pd.DataFrame(columns=["ts", "block", "frm", "to", "sut", "tx", "li"])
    new = []
    for k, a in W.items():
        start = int(state["last_block"].get(k, 0))
        for x in tokentx(a, start):
            new.append(dict(ts=int(x["timeStamp"]), block=int(x["blockNumber"]), frm=x["from"].lower(), to=x["to"].lower(), sut=int(x["value"]) / 1e18, tx=x["hash"], li=x.get("logIndex", "")))
        if new: state["last_block"][k] = max(state["last_block"].get(k, 0), max(n["block"] for n in new))
        print(k, "new transfers:", sum(1 for n in new))
    if new:
        T = pd.concat([T, pd.DataFrame(new)], ignore_index=True).drop_duplicates(["tx", "li", "frm", "to", "sut"])
    T.to_csv(tf_path, index=False); json.dump(state, open(st_path, "w"))
    T["day"] = pd.to_datetime(T.ts, unit="s", utc=True).dt.strftime("%Y-%m-%d")
    tag = {v: k for k, v in W.items()}
    T["tf"] = T.frm.map(tag).fillna("other"); T["tt"] = T.to.map(tag).fillna("other")
    T["company_from"] = T.frm.isin(COMPANY_SRC)
    days = pd.date_range(START, datetime.now(timezone.utc).strftime("%Y-%m-%d"), freq="1D").strftime("%Y-%m-%d")
    D = pd.DataFrame(index=days)
    for k in W:
        D[f"{k}_in"] = T[T.tt == k].groupby("day").sut.sum().reindex(days).fillna(0)
        D[f"{k}_out"] = T[T.tf == k].groupby("day").sut.sum().reindex(days).fillna(0)
    flow = lambda m, name: D.__setitem__(name, T[m].groupby("day").sut.sum().reindex(days).fillna(0))
    flow(T.company_from & (T.tt == "gate"), "company_to_gate"); flow((T.tf == "other") & (T.tt == "gate"), "public_to_gate")
    flow((T.tf == "gate") & (T.tt == "other"), "gate_to_public"); flow((T.tf == "mpc_vault") & T.tt.isin(["sell", "fx"]), "vault_to_sellers")
    flow((T.tf == "sell"), "sell_out"); flow(T.tt == "fx", "fx_in"); flow(T.tf == "fx", "fx_out"); flow(T.tf == "mpc_vault", "mpc_vault_out")
    flow((T.tf.isin(["pool_main", "pool_aux"])) & (T.tt == "other"), "public_buy_from_pool"); flow((T.tf == "other") & T.tt.isin(["pool_main", "pool_aux"]), "public_sell_to_pool")
    # balances anchored to live balanceOf (today)
    bal = {}
    for k, a in W.items():
        now = int(es(dict(module="account", action="tokenbalance", contractaddress=SUT, address=a, tag="latest")) or 0) / 1e18
        cum = (D[f"{k}_in"] - D[f"{k}_out"]).cumsum(); bal[k] = cum + (now - cum.iloc[-1])
    px = gate_daily().reindex(days)
    pool = bal["pool_main"] + bal["pool_aux"]
    avg = dict(gate=float(bal["gate"].mean()), pool=float(pool.mean()), sell=float(bal["sell"].mean()), mpc_vault=float(bal["mpc_vault"].mean()))
    out_days = []
    fcols = ["gate_in", "gate_out", "company_to_gate", "vault_to_sellers", "sell_out", "fx_in", "fx_out", "mpc_vault_out", "public_buy_from_pool", "public_sell_to_pool", "gate_to_public", "public_to_gate"]
    nz = lambda v, r=4: None if pd.isna(v) else round(float(v), r)
    for d in days:
        r = px.loc[d] if d in px.index else None
        out_days.append(dict(d=d, o=nz(r.o) if r is not None else None, h=nz(r.h) if r is not None else None, l=nz(r.l) if r is not None else None, c=nz(r.c) if r is not None else None,
                             v=nz(r.v, 0) if r is not None else None, gate=round(float(bal["gate"][d])), pool=round(float(pool[d])), sell=round(float(bal["sell"][d])),
                             mpc=round(float(bal["mpc_vault"][d])), fx=round(float(bal["fx"][d])), f={c: round(float(D.loc[d, c])) for c in fcols}))
    meta = dict(generated=datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"), anchor_date=days[-1], avg=avg, wallets=W, token=SUT)
    json.dump(dict(meta=meta, days=out_days), open(os.path.join(DATA, "daily.json"), "w"), ensure_ascii=False)
    # anomalies
    close = px.c.reindex(days); ret = np.log(close).diff()
    NM = {"gate": "게이트 거래소", "pool_main": "유니스왑 주풀", "pool_aux": "유니스왑 보조풀", "sell": "회사 매도지갑", "fx": "회사 환전지갑", "mpc_vault": "MPC 금고"}
    rets = lambda d: dict(ret=nz(np.exp(ret[d]) - 1), n1=nz(np.exp(ret.shift(-1)[d]) - 1), n3=nz(np.exp(ret.shift(-1).rolling(3).sum().shift(-2)[d]) - 1))
    rows = []
    for k in NM:
        tot = D[f"{k}_in"] + D[f"{k}_out"]; med = tot.rolling(30, min_periods=20).median().shift(1); mad = (tot - med).abs().rolling(30, min_periods=20).median().shift(1)
        z = (tot - med) / (1.4826 * mad.replace(0, np.nan))
        for d in days:
            if tot[d] <= 0 or pd.isna(z[d]): continue
            if z[d] >= 5 or (med[d] > 0 and tot[d] >= 10 * med[d]):
                key = "pool" if k.startswith("pool") else k; b = pool[d] if key == "pool" else bal[k][d]
                rows.append(dict(d=d, w=k, name=NM[k], total=round(float(tot[d])), net=round(float(D.loc[d, f"{k}_in"] - D.loc[d, f"{k}_out"])), ratio=None if med[d] <= 0 else round(float(tot[d] / med[d]), 1),
                                 z=round(float(z[d]), 1), bal=round(float(b)), bal_vs_avg=None if key not in avg else round(float(b / avg[key]), 3), kind="flow", **rets(d)))
    for d in days:
        for col, lab in [("vault_to_sellers", "금고→매도경로 이관"), ("company_to_gate", "회사 물량 게이트 도착"), ("sell_out", "매도지갑 매도")]:
            if D.loc[d, col] > 0:
                rows.append(dict(d=d, w="company", name=lab, total=round(float(D.loc[d, col])), net=None, ratio=None, z=None, bal=round(float(bal["sell"][d])), bal_vs_avg=None, kind="company", **rets(d)))
    rows.sort(key=lambda r: (r["d"], r["kind"]))
    json.dump(rows, open(os.path.join(DATA, "anomalies.json"), "w"), ensure_ascii=False)
    print("done", len(out_days), "days", len(rows), "anomalies")


if __name__ == "__main__":
    main()
