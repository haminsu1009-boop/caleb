"""
ml/verify_live.py
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
모의 실행 로그 ↔ 백테스트 신호 대조

1단계(모의 4~6주)의 목적은 "돈을 버는지"가 아니라 **"봇이 검증한
것과 같은 것을 하는지"** 확인하는 것이다.

이 저장소에서 지금까지 잡은 버그 여섯 개 중 다섯이 그 어긋남이었다.

  · 청산을 종가로 판정 (가짜 '1년 50배')
  · 부분체결을 전량으로 계산 (135배 → 2.93배)
  · 미완성 주봉으로 발화 (주가 닫히기 5일 전)
  · 보유기간을 한 봉 적게 셈 (4주 보유를 2주에 청산)
  · HOLD_BARS 봇 20 / 백테스트 60 (9.13배 대 21.52배)

전부 로그를 대조했으면 몇 주 안에 드러났을 종류다.

쓰는 법 (VPS에서)
    journalctl -u oversold-paper --since "6 weeks ago" --no-pager > paper.log
    python ml/verify_live.py paper.log

무엇을 보나
    · 봇이 낸 신호가 같은 날 백테스트 신호와 일치하는가
    · 백테스트에는 있는데 봇이 놓친 신호가 있는가 (누락)
    · 봇에만 있고 백테스트에 없는 신호가 있는가 (오발)
    · 진입가가 얼마나 차이 나는가 (체결지연 가정 0.196%p 검증)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""

from __future__ import annotations
import os, re, sys, argparse, warnings
warnings.filterwarnings("ignore")
import numpy as np
import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT); os.chdir(ROOT)
from bot.oversold import strategy as S
import ml.short_setups as SS
import ml.unified_pool as UP

# 09-19 03:11:07  🔔 신호 ADAUSDT  종가 0.7431  20MA대비 -13.2%  →  1차 진입 ...
RE_LONG = re.compile(
    r"(\d\d)-(\d\d) (\d\d):(\d\d):\d\d\s+🔔 신호 (\w+)\s+종가 ([\d.eE+-]+)")
# 09-19 03:11:07  🔔 short 신호 CHZUSDT  종가 0.0521 ...
RE_MOD = re.compile(
    r"(\d\d)-(\d\d) (\d\d):(\d\d):\d\d\s+🔔 (\w+) 신호 (\w+)\s+종가 ([\d.eE+-]+)")


def parse(path, year=None):
    """로그에서 신호만 뽑는다. 연도는 파일에 없으므로 추정한다."""
    year = year or pd.Timestamp.utcnow().year
    rows = []
    for line in open(path, encoding="utf-8", errors="replace"):
        m = RE_MOD.search(line)
        if m:
            mo, da, hh, mi, kind, sym, px = m.groups()
        else:
            m = RE_LONG.search(line)
            if not m:
                continue
            mo, da, hh, mi, sym, px = m.groups()
            kind = "long"
        rows.append({"dt": pd.Timestamp(year=year, month=int(mo), day=int(da),
                                        hour=int(hh), minute=int(mi)),
                     "kind": kind, "sym": sym, "price": float(px)})
    d = pd.DataFrame(rows)
    if len(d):
        # 연말 넘김 보정 — 뒤로 갈수록 날짜가 줄면 해가 바뀐 것이다
        back = d["dt"].diff() < -pd.Timedelta(days=300)
        d.loc[back.cumsum() > 0, "dt"] += pd.DateOffset(years=1)
    return d


def expected(since, until):
    """같은 기간 백테스트가 냈어야 할 신호."""
    D = {}
    for s in S.SYMBOLS:
        x = SS.load_daily(s)
        if x is None or len(x) < 400:
            continue
        x["dt"] = pd.to_datetime(x["dt"])
        D[s] = x
    W = {s: SS.to_weekly(d) for s, d in D.items()}
    out = []
    for kind, ts in [("long", UP.make_long(fracs=[.30, .70], hold=S.HOLD_BARS,
                                           bb=True, bb_k=S.BB_K, symbols=list(D))),
                     ("short", UP.make_short(W)),
                     ("div", UP.make_div(D))]:
        for t in ts:
            dt = pd.Timestamp(t["dt"])
            if since <= dt <= until:
                out.append({"dt": dt, "kind": kind, "sym": t["sym"],
                            "price": t["entry"]})
    return pd.DataFrame(out)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("logfile")
    ap.add_argument("--year", type=int, help="로그의 연도 (기본: 올해)")
    ap.add_argument("--tol-hours", type=float, default=8.0,
                    help="같은 신호로 볼 시각 차이 (기본 8시간 = 4시간봉 2개)")
    a = ap.parse_args()

    got = parse(a.logfile, a.year)
    if got.empty:
        print("  로그에서 신호를 하나도 못 찾았다.")
        print("  journalctl -u oversold-paper --no-pager > paper.log 로 받았는지 확인해라.")
        return 1

    since, until = got.dt.min().normalize(), got.dt.max().normalize() + pd.Timedelta(days=1)
    want = expected(since, until)

    print("=" * 88)
    print(f"  모의 로그 ↔ 백테스트 대조   {since:%Y-%m-%d} ~ {until:%Y-%m-%d}")
    print("=" * 88)
    print(f"  봇이 낸 신호 {len(got)}건 · 백테스트 신호 {len(want)}건\n")

    tol = pd.Timedelta(hours=a.tol_hours)
    matched, missed, extra = [], [], list(range(len(got)))
    for i, w in want.iterrows():
        cand = [j for j in extra
                if got.at[j, "sym"] == w["sym"] and got.at[j, "kind"] == w["kind"]
                and abs(got.at[j, "dt"] - w["dt"]) <= tol]
        if cand:
            j = cand[0]
            matched.append((w, got.loc[j]))
            extra.remove(j)
        else:
            missed.append(w)

    print(f"  {'구분':<22s}{'건수':>7s}")
    print("  " + "-" * 32)
    print(f"  {'일치':<22s}{len(matched):>7d}")
    print(f"  {'놓침 (백테스트에만)':<22s}{len(missed):>7d}")
    print(f"  {'오발 (봇에만)':<22s}{len(extra):>7d}")

    if matched:
        dp = np.array([(g["price"] / w["price"] - 1) * 100 for w, g in matched])
        print(f"\n  ■ 진입가 차이 (봇 대비 백테스트)")
        print(f"      중앙 {np.median(dp):+.3f}%  ·  평균 {dp.mean():+.3f}%"
              f"  ·  최대 {np.abs(dp).max():.3f}%")
        print(f"      백테스트가 가정한 체결지연은 0.196%p다.")

    if missed:
        print(f"\n  ■ 놓친 신호 (최대 10건)")
        for w in missed[:10]:
            print(f"      {w['dt']:%m-%d %H:%M}  {w['kind']:<6s}{w['sym']}")
    if extra:
        print(f"\n  ■ 백테스트에 없는 신호 (최대 10건)")
        for j in extra[:10]:
            g = got.loc[j]
            print(f"      {g['dt']:%m-%d %H:%M}  {g['kind']:<6s}{g['sym']}")

    rate = len(matched) / max(len(want), 1) * 100
    print(f"\n  ■ 판정")
    if len(want) == 0:
        print("      기간 안에 백테스트 신호가 없다. 더 돌려라.")
    elif rate >= 80 and len(extra) <= len(want) * 0.2:
        print(f"      일치율 {rate:.0f}% — 통과. 다음 단계(소액 실거래)로 가도 된다.")
    else:
        print(f"      일치율 {rate:.0f}% — **통과 못 했다.** 실거래로 넘어가지 마라.")
        print("      놓침·오발의 원인을 먼저 찾아라. 데이터 출처 차이(바이낸스 대")
        print("      바이빗)인지, 봇 로직이 백테스트와 다른지 구분해야 한다.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
