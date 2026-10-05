"""
bot/oversold/monitor.py
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
실거래 봇 감시 — 이상할 때만 텔레그램으로 알린다

봇과 따로 돈다(systemd 타이머, 1시간마다). 봇이 죽어도 감시는 산다.
주문은 내지 않는다. 읽기만 한다.

알리는 것 (같은 내용은 12시간에 한 번만)
  · 봇이 멈췄다 — 서비스가 꺼졌거나 30분 넘게 점검 기록이 없다
  · 최근 1시간에 오류가 났다
  · 고점 대비 낙폭이 10% / 15%를 넘었다, 차단기가 켜졌다
  · 손절이 안 걸린 포지션, 봇 기록과 거래소가 다른 포지션
  · 승률이 백테스트보다 "우연으로 보기 어려울 만큼" 낮다
      종류마다(롱·숏·다이버) 실제 청산 거래를 모아, 백테스트 승률이
      맞다면 이 정도로 나쁠 확률이 2% 미만일 때만 알린다. 거래 몇 건
      졌다고 울리지 않는다 — 롱은 승률 85%라도 7건 중 2~3건 지는 일이
      흔하다.
  · 매일 아침 8시(한국시간) 하루 요약 — 이건 이상이 없어도 보낸다
  · 거래가 닫힐 때마다 손익 결과 (매수·매도 순간 알림은 봇이 직접 보낸다)

거래 결과는 거래소의 청산 손익 기록(closed-pnl)에서 읽는다. 거래소에서
손절이 체결된 것도 빠짐없이 잡힌다. 어느 전략의 거래인지는 감시가 매번
봇 기록(state_live.json)을 보고 기억해 둔 것으로 맞춘다.

설정 (.env — 화면에 띄우지 말 것)
    TG_BOT_TOKEN=...      텔레그램 @BotFather 에서 받은 토큰
    TG_CHAT_ID=...        --setup 이 찾아 준다

사용법
    python -m bot.oversold.monitor --setup     # 채팅 ID 찾기 + 시험 메시지
    python -m bot.oversold.monitor             # 한 번 점검 (타이머가 부른다)
    python -m bot.oversold.monitor --summary   # 하루 요약을 지금 보낸다
    python -m bot.oversold.monitor --dry       # 보내지 않고 화면에만
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""
from __future__ import annotations
import argparse
import json
import math
import os
import subprocess
import sys
import time
from datetime import datetime, timedelta, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)

from bot.oversold import executor as E
from bot.oversold import regime as REG

MON_PATH = os.path.join(ROOT, "state", "monitor.json")
KST = timezone(timedelta(hours=9))
REPEAT_H = 12            # 같은 경고는 12시간에 한 번만
SERVICE = "oversold-bot"

# 백테스트 승률(2019~, 4배·bear 롱 끔, ml/module_winrate.py)의 아래쪽 끝.
# 실제가 이보다 낮게 나올 확률이 2% 미만이면 알린다.
EXPECT = {"long": 0.84, "short": 0.76, "div": 0.65}
NAME = {"long": "롱", "short": "숏", "div": "다이버", "crash": "급락반등", "?": "미확인"}
MIN_N = 5
P_ALERT = 0.02


# ── 작은 도구 ───────────────────────────────────────────────────────────
def load_mon() -> dict:
    try:
        return json.load(open(MON_PATH, encoding="utf-8"))
    except Exception:
        return {"kinds": {}, "seen": [], "trades": [], "alerts": {}, "last_summary": ""}


def save_mon(m: dict):
    os.makedirs(os.path.dirname(MON_PATH), exist_ok=True)
    m["seen"] = m["seen"][-500:]
    m["trades"] = m["trades"][-2000:]
    tmp = MON_PATH + ".tmp"
    json.dump(m, open(tmp, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    os.replace(tmp, MON_PATH)


def sh(cmd) -> str:
    try:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=30).stdout
    except Exception:
        return ""


def binom_cdf(k: int, n: int, p: float) -> float:
    """승률 p가 맞을 때 n건 중 k건 이하로 이길 확률."""
    return sum(math.comb(n, i) * p ** i * (1 - p) ** (n - i) for i in range(k + 1))


def send(text: str, dry: bool = False) -> bool:
    if dry:
        print("── 보낼 메시지 ──\n" + text + "\n")
        return True
    tok, chat = os.getenv("TG_BOT_TOKEN"), os.getenv("TG_CHAT_ID")
    if not tok or not chat:
        print("TG_BOT_TOKEN / TG_CHAT_ID 가 .env 에 없다 — 화면에만 찍는다\n" + text)
        return False
    import requests
    for k in range(3):
        try:
            r = requests.post(f"https://api.telegram.org/bot{tok}/sendMessage",
                              json={"chat_id": chat, "text": text}, timeout=20)
            if r.ok:
                return True
            print(f"텔레그램 전송 실패: {r.status_code} {r.text[:200]}")
        except Exception as e:
            print(f"텔레그램 전송 실패: {e}")
        time.sleep(2 ** k)
    return False


# ── 수집 ────────────────────────────────────────────────────────────────
def remember_kinds(m: dict, st: dict):
    """지금 열린 포지션이 어느 전략 것인지 기억한다. 청산 기록에는
    전략 이름이 없으므로, 닫힌 뒤에 이 기억으로 맞춘다."""
    for sym in st.get("positions", {}):
        m["kinds"][sym] = "long"
    for sym, p in st.get("mod_positions", {}).items():
        m["kinds"][sym] = p.get("kind", "?")


def collect_closed(ex, m: dict) -> list:
    """거래소 청산 손익 기록에서 새로 닫힌 거래를 가져온다."""
    start = int((time.time() - 6 * 86400) * 1000)
    rows, cursor = [], ""
    for _ in range(10):
        kw = dict(category="linear", limit=100, startTime=start)
        if cursor:
            kw["cursor"] = cursor
        r = ex.session.get_closed_pnl(**kw)["result"]
        rows += r.get("list", [])
        cursor = r.get("nextPageCursor") or ""
        if not cursor:
            break
    seen = set(m["seen"])
    new = []
    for x in sorted(rows, key=lambda x: int(x.get("updatedTime") or x.get("createdTime") or 0)):
        oid = x.get("orderId")
        if not oid or oid in seen:
            continue
        sym = x["symbol"]
        if sym not in E.S.SYMBOLS:
            continue
        pnl = float(x.get("closedPnl") or 0)
        entry = float(x.get("avgEntryPrice") or 0)
        exit_ = float(x.get("avgExitPrice") or 0)
        side = x.get("side")                     # 청산 주문의 방향
        ret = 0.0
        if entry > 0:
            ret = (exit_ / entry - 1) * 100 * (1 if side == "Sell" else -1)
        t = {"id": oid, "sym": sym, "kind": m["kinds"].get(sym, "?"),
             "pnl": pnl, "ret": ret,
             "ts": int(x.get("updatedTime") or x.get("createdTime") or 0)}
        new.append(t)
        m["seen"].append(oid)
    # 분할 체결로 한 번의 청산이 여러 줄로 올 수 있다 — 같은 종목·1시간 안이면 합친다
    merged = []
    for t in new:
        last = merged[-1] if merged else None
        if last and last["sym"] == t["sym"] and abs(t["ts"] - last["ts"]) < 3600_000:
            last["pnl"] += t["pnl"]
            continue
        merged.append(t)
    m["trades"] += merged
    return merged


# ── 판정 ────────────────────────────────────────────────────────────────
def summarize_errors(log: str) -> list:
    """로그에서 경고·오류를 뽑는다. Traceback은 제목 대신 마지막 줄(실제
    원인, 예: "KeyError: 'x'")과 그 직전 코드 위치를 보여 준다."""
    lines = log.splitlines()
    out, i = [], 0
    while i < len(lines):
        l = lines[i]
        if "Traceback" in l:
            j = i + 1
            where = ""
            while j < len(lines) and (lines[j].startswith((" ", "\t")) or not lines[j].strip()):
                if lines[j].strip().startswith("File "):
                    where = lines[j].strip()
                j += 1
            cause = lines[j].strip() if j < len(lines) else "(원인 줄 없음)"
            loc = ""
            if where:
                import re as _re
                m = _re.search(r'File ".*?([^/]+)", line (\d+), in (\S+)', where)
                if m:
                    loc = f" @ {m.group(1)}:{m.group(2)} {m.group(3)}"
            out.append(f"💥 {cause[:140]}{loc}")
            i = j + 1
            continue
        if any(k in l for k in ("ERROR", "⚠️", "응답 지연")) and "최소주문량 미달" not in l:
            out.append(l.strip())
        i += 1
    return out


def checks(ex, m: dict, st: dict) -> list:
    """(키, 메시지) 목록. 키가 같으면 12시간 안에 다시 보내지 않는다."""
    out = []
    act = sh(["systemctl", "is-active", SERVICE]).strip()
    if act and act != "active":
        out.append(("svc", f"🛑 봇이 꺼져 있습니다 ({act}).\nsudo systemctl start {SERVICE}"))
    else:
        log30 = sh(["journalctl", "-u", SERVICE, "--since", "-30min", "-o", "cat", "--no-pager"])
        if act and not any("자본" in l and "노출" in l for l in log30.splitlines()):
            out.append(("stall", "⏸ 30분 넘게 점검 기록이 없습니다. 봇이 멈춰 있을 수 있어요.\n"
                                 f"journalctl -u {SERVICE} -n 50 --no-pager"))
    log1 = sh(["journalctl", "-u", SERVICE, "--since", "-1h", "-o", "cat", "--no-pager"])
    errs = summarize_errors(log1)
    # 바이빗 응답 지연은 한두 번은 흔하다. 한 시간에 5번 이상일 때만 알린다.
    blips = [e for e in errs if "응답 지연" in e]
    errs = [e for e in errs if "응답 지연" not in e]
    if len(blips) >= 5:
        out.append(("net", f"🌐 바이빗 연결 불안정 — 최근 1시간 응답 지연 {len(blips)}번.\n"
                           "계속되면 서버 네트워크나 바이빗 상태를 확인하세요."))
    if errs:
        out.append(("err", f"⚠️ 최근 1시간 경고 {len(errs)}건\n" + "\n".join(e[:120] for e in errs[-3:])))

    eq = ex.equity()
    peak = max(st.get("peak_equity") or 0, eq)
    dd = 1 - eq / peak if peak else 0
    if dd >= 0.15:
        out.append(("dd15", f"📉 고점 대비 -{dd*100:.1f}% ({peak:,.0f} → {eq:,.0f} USDT).\n"
                            "20%에서 차단기가 켜져 30일 쉽니다."))
    elif dd >= 0.10:
        out.append(("dd10", f"📉 고점 대비 -{dd*100:.1f}% ({peak:,.0f} → {eq:,.0f} USDT)"))
    if st.get("halted_until"):
        out.append(("halt", f"⛔ 차단기 작동 중 — {st['halted_until']} 까지 신규 진입 없음"))

    live = ex.positions()
    tracked, mods = st.get("positions", {}), st.get("mod_positions", {})
    for sym, lp in live.items():
        if sym in tracked and not lp["stop"]:
            out.append((f"nostop:{sym}", f"🚨 {sym} 롱에 손절이 안 걸려 있습니다."))
        if sym in E.S.SYMBOLS and sym not in tracked and sym not in mods:
            out.append((f"orphan:{sym}", f"❓ {sym} 포지션이 거래소에만 있습니다 (봇이 연 게 아님)."))

    # 승률 — 우연으로 보기 어려울 만큼 낮을 때만
    for kind, p in EXPECT.items():
        allk = [t for t in m["trades"] if t["kind"] == kind]
        # 전체 누적과 최근 20건을 따로 본다 — 처음엔 잘 되다가 나중에
        # 나빠지는 경우는 누적에 묻힌다.
        for lab, ts in (("누적", allk), ("최근 20건", allk[-20:] if len(allk) > 20 else [])):
            n = len(ts)
            if n < MIN_N:
                continue
            k = sum(t["pnl"] > 0 for t in ts)
            pr = binom_cdf(k, n, p)
            if pr < P_ALERT:
                out.append((f"wr:{kind}:{lab}:{len(allk)}",
                            f"🔻 {NAME[kind]} 승률이 백테스트보다 낮습니다 ({lab})\n"
                            f"실제 {k}/{n}건 = {k/n*100:.0f}% · 백테스트 {p*100:.0f}% 이상\n"
                            f"백테스트대로라면 이렇게 나쁠 확률 {pr*100:.1f}% — 전략 점검이 필요합니다."))
    return out


def summary(ex, m: dict, st: dict) -> str:
    eq = ex.equity()
    now = datetime.now(KST)
    hist = m.setdefault("equity_hist", [])
    def ago(days):
        t0 = int((now - timedelta(days=days)).timestamp() * 1000) + 3600_000
        return next((v for t, v in reversed(hist) if t <= t0), None)
    chg = [f"{(eq/v-1)*100:+.1f}% / {d}일" for d, v in ((1, ago(1)), (7, ago(7)), (30, ago(30))) if v]
    lines = [f"📊 봇 하루 요약 {now:%m/%d}",
             f"자본 {eq:,.2f} USDT" + (f" ({' · '.join(chg)})" if chg else "")]
    peak = max(st.get("peak_equity") or 0, eq)
    lines.append(f"고점 대비 {-(1 - eq/peak)*100 if peak else 0:.1f}% · {REG.describe()}")
    ab = st.get("auto_bear") or {}
    if ab.get("day"):
        lines.append(f"자동 폭락장 {'켜짐 (새 롱 낮은 배율)' if ab.get('on') else '꺼짐'} · BTC 60일 {ab.get('r60')}%")
    lines.append(f"보유: 롱 {len(st.get('positions', {}))} · 숏/다이버 {len(st.get('mod_positions', {}))}")
    day = int((now - timedelta(days=1)).timestamp() * 1000)
    wk = int((now - timedelta(days=7)).timestamp() * 1000)
    for lab, t0 in (("24시간", day), ("7일", wk)):
        ts = [t for t in m["trades"] if t["ts"] >= t0]
        lines.append(f"{lab} 청산 {len(ts)}건 · 손익 {sum(t['pnl'] for t in ts):+.2f} USDT")
    for kind, p in EXPECT.items():
        ts = [t for t in m["trades"] if t["kind"] == kind]
        if ts:
            k = sum(t["pnl"] > 0 for t in ts)
            lines.append(f"누적 {NAME[kind]}: {k}/{len(ts)}승 ({k/len(ts)*100:.0f}%, 백테스트 {p*100:.0f}%+)")
    if not m["trades"]:
        lines.append("아직 청산된 거래가 없습니다 (신호는 드물게 옵니다).")
    return "\n".join(lines)


# ── 실행 ────────────────────────────────────────────────────────────────
def setup():
    tok = os.getenv("TG_BOT_TOKEN")
    if not tok:
        raise SystemExit("먼저 .env 에 TG_BOT_TOKEN=... 을 넣으세요 (@BotFather 에서 받은 토큰)")
    import requests
    r = requests.get(f"https://api.telegram.org/bot{tok}/getUpdates", timeout=20).json()
    if not r.get("ok"):
        # 404 = 텔레그램이 이 토큰을 모른다. 토큰을 잘못 옮겼거나(앞뒤 공백·
        # "bot" 접두어·줄바꿈), BotFather에서 /revoke 로 바뀐 경우다.
        raise SystemExit(f"토큰이 맞지 않습니다 ({r.get('error_code')} {r.get('description')}).\n"
                         "  .env 의 TG_BOT_TOKEN 을 BotFather가 준 값 그대로 다시 넣으세요 "
                         "(형식: 숫자:영문자, 앞에 bot 붙이지 않음).")
    chats = {u["message"]["chat"]["id"] for u in r.get("result", []) if "message" in u}
    if not chats:
        raise SystemExit("텔레그램에서 만든 봇에게 아무 메시지나 하나 보낸 뒤 다시 실행하세요.")
    for c in chats:
        print(f"채팅 ID: {c}")
    chat = sorted(chats)[0]
    os.environ["TG_CHAT_ID"] = str(chat)
    ok = send("✅ 과매도 봇 감시가 연결됐습니다. 이상이 있을 때만 알려드립니다.")
    print("시험 메시지 " + ("보냄" if ok else "실패"))
    print(f"\n.env 에 다음 줄을 추가하세요:\n  TG_CHAT_ID={chat}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--setup", action="store_true", help="채팅 ID 찾기 + 시험 메시지")
    ap.add_argument("--summary", action="store_true", help="하루 요약을 지금 보낸다")
    ap.add_argument("--dry", action="store_true", help="보내지 않고 화면에만")
    a = ap.parse_args()
    E.load_env()
    if a.setup:
        return setup()

    ex = E.Exchange(live=True)
    st = (json.load(open(E.LIVE_STATE_PATH, encoding="utf-8"))
          if os.path.exists(E.LIVE_STATE_PATH) else {})
    m = load_mon()
    remember_kinds(m, st)
    now_ms = int(time.time() * 1000)

    try:
        new = collect_closed(ex, m)
    except Exception as e:
        new = []
        print(f"청산 기록 조회 실패: {e}")
    for t in new:
        print(f"청산: {t['sym']} [{NAME.get(t['kind'], t['kind'])}] {t['pnl']:+.2f} USDT")
        # 거래마다 결과를 알린다 — 거래소에서 체결된 손절·익절도 여기서 잡힌다
        icon = "✅" if t["pnl"] > 0 else "❌"
        send(f"{icon} 거래 결과 {t['sym']} [{NAME.get(t['kind'], t['kind'])}]\n"
             f"손익 {t['pnl']:+.2f} USDT · 가격 변동 {t['ret']:+.1f}%\n"
             f"자본 {ex.equity():,.2f} USDT", a.dry)

    for key, msg in checks(ex, m, st):
        last = m["alerts"].get(key, 0)
        if now_ms - last < REPEAT_H * 3600_000:
            continue
        if send(msg, a.dry):
            m["alerts"][key] = now_ms

    # 매시간 자본을 적어 둔다 — 1·7·30일 변화 계산용
    hist = m.setdefault("equity_hist", [])
    if not hist or now_ms - hist[-1][0] > 50 * 60_000:
        hist.append([now_ms, ex.equity()])
        m["equity_hist"] = hist[-24 * 40:]          # 40일치

    kst = datetime.now(KST)
    tag = kst.strftime("%Y-%m-%d")
    if a.summary or (kst.hour >= 8 and m.get("last_summary") != tag):
        if send(summary(ex, m, st), a.dry) and not a.summary:
            m["last_summary"] = tag

    save_mon(m)


if __name__ == "__main__":
    main()
