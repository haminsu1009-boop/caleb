"""
tools/tg_notify.py
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
GitHub Actions에서 텔레그램으로 알린다 (비밀값 TG_BOT_TOKEN · TG_CHAT_ID).

    python tools/tg_notify.py data     --workflow "이름" --result success
        데이터 수집이 끝났을 때. 최근 커밋에서 무엇이 갱신됐는지 묶어서
        보여 주고, 42종 4시간봉·일봉이 언제까지 들어 있는지 알린다.
    python tools/tg_notify.py research --file reports/research/2026-10-05.md
        매일 연구 보고서가 올라왔을 때. 요약·결론 부분을 보낸다.
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""
from __future__ import annotations
import argparse
import os
import re
import subprocess
import sys
from collections import Counter

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
LIMIT = 3900          # 텔레그램 한 메시지 4096자


def send(text: str):
    tok, chat = os.getenv("TG_BOT_TOKEN"), os.getenv("TG_CHAT_ID")
    print(text)
    if not tok or not chat:
        print("TG_BOT_TOKEN / TG_CHAT_ID 없음 — 보내지 않음")
        return
    import requests
    for i in range(0, len(text), LIMIT):
        r = requests.post(f"https://api.telegram.org/bot{tok}/sendMessage",
                          json={"chat_id": chat, "text": text[i:i + LIMIT]}, timeout=20)
        print("텔레그램:", "보냄" if r.ok else f"실패 {r.status_code}")


def git(*a) -> str:
    return subprocess.run(["git", *a], capture_output=True, text=True, cwd=ROOT).stdout


def data_report(workflow: str, result: str, hours: int) -> str:
    msgs = [l.strip() for l in git("log", f"--since={hours} hours ago", "--format=%s").splitlines()
            if l.startswith("data:")]
    kinds = Counter()
    for m in msgs:
        if "OHLCV" in m or "1d/4h" in m:
            kinds["가격 (4시간봉·일봉)"] += 1
        elif "선물 메트릭" in m:
            kinds["선물 지표 (미결제약정·롱숏비)"] += 1
        elif "호가창" in m:
            kinds["호가창 1분 요약"] += 1
        elif "funding" in m:
            kinds["펀딩비"] += 1
        elif "upbit" in m:
            kinds["업비트"] += 1
        else:
            kinds["기타"] += 1
    ok = result == "success"
    lines = [f"{'📥' if ok else '❌'} 데이터 수집 {'완료' if ok else '실패'} — {workflow}"]
    if not ok:
        lines.append("GitHub Actions 탭에서 실패한 작업을 확인하세요.")
    if msgs:
        lines.append(f"최근 {hours}시간 커밋 {len(msgs)}건")
        lines += [f" · {k} {v}건" for k, v in kinds.most_common()]
    else:
        lines.append(f"최근 {hours}시간 새로 들어온 데이터 없음 (아직 안 올라왔거나 변경 없음)")

    # 42종 가격 데이터가 언제까지 있나
    try:
        import pandas as pd
        from bot.oversold import strategy as S
        last = {}
        for s in S.SYMBOLS:
            p = os.path.join(ROOT, "data", f"{s}_4h_all.csv.gz")
            if os.path.exists(p):
                d = pd.read_csv(p, usecols=[0])
                last[s] = pd.to_datetime(d.iloc[-1, 0], format="mixed")
        if last:
            newest = max(last.values())
            stale = sorted(s[:-4] for s, t in last.items() if t < newest - pd.Timedelta(days=2))
            lines.append(f"42종 4시간봉: {newest:%m/%d %H시}까지 ({len(last)}종)")
            if stale:
                lines.append(f"⚠️ 갱신 늦은 종목 {len(stale)}개: {', '.join(stale[:8])}")
        sys.path.insert(0, os.path.join(ROOT, "bybit"))
        from collect_history import CANDIDATE_SYMBOLS
        got = [c for c in CANDIDATE_SYMBOLS if os.path.exists(os.path.join(ROOT, "data", f"{c}_4h_all.csv.gz"))]
        lines.append(f"확장 후보: {len(got)}/{len(CANDIDATE_SYMBOLS)}종 수집됨 (아직 거래 안 함)")
    except Exception as e:
        lines.append(f"(가격 데이터 확인 실패: {e})")
    return "\n".join(lines)


def research_report(path: str) -> str:
    txt = open(os.path.join(ROOT, path), encoding="utf-8").read()
    date = os.path.basename(path)[:10]
    first = txt.splitlines()[0].removeprefix("요약:").strip() if txt else ""
    # 보고서 전체를 보낸다 (표 구분선만 뺀다). 길면 여러 메시지로 나뉜다.
    keep = [l for l in txt.splitlines()[1:] if not re.match(r"^\|?\s*:?-{3}", l)]
    out = [f"🔬 매일 연구 {date}", f"요약: {first}", ""] + keep
    url = f"https://github.com/haminsu1009-boop/caleb/blob/claude/quant-trading-bot-tkjtd/{path}"
    text = "\n".join(out).strip()
    if len(text) > LIMIT * 2:
        text = text[:LIMIT * 2] + "\n…(생략)"
    return text + f"\n\n전체: {url}"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("kind", choices=("data", "research"))
    ap.add_argument("--workflow", default="")
    ap.add_argument("--result", default="success")
    ap.add_argument("--hours", type=int, default=3)
    ap.add_argument("--file", default="")
    a = ap.parse_args()
    if a.kind == "data":
        send(data_report(a.workflow, a.result, a.hours))
    else:
        files = [f for f in a.file.split() if f.endswith(".md")]
        for f in files:
            send(research_report(f))


if __name__ == "__main__":
    main()
