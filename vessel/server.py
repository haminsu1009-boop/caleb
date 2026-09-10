"""
vessel/server.py
두 채널을 한 서버에서 서비스한다:

  POST /api/vessel/track   — 웹사이트 챗위젯 백엔드 (assets/vessel-widget.js 가 호출)
  POST /kakao/skill        — 카카오톡 채널 챗봇 스킬 서버 (카카오 i 오픈빌더)
  GET  /healthz            — 헬스체크

설정 & 실행:
  pip install flask
  python vessel/server.py                      # http://0.0.0.0:8787

배포 후:
  · 카카오: 카카오 i 오픈빌더 → 스킬 → URL에 https://<도메인>/kakao/skill 등록
  · 웹위젯: assets/vessel-widget.js 맨 위 API_BASE 값을 서버 주소로 맞추기
  · .env 의 VESSEL_WIDGET_ORIGIN 에 실제 사이트 도메인을 넣으면
    CORS가 그 도메인으로만 제한된다(비우면 전체 허용 — 개발용).
"""

from __future__ import annotations

import os

from dotenv import load_dotenv
from flask import Flask, jsonify, request

from vessel.tracker import track, track_from_text

load_dotenv()

app = Flask(__name__)
WIDGET_ORIGIN = os.getenv("VESSEL_WIDGET_ORIGIN", "*")


@app.after_request
def add_cors_headers(resp):
    resp.headers["Access-Control-Allow-Origin"] = WIDGET_ORIGIN
    resp.headers["Access-Control-Allow-Headers"] = "Content-Type"
    resp.headers["Access-Control-Allow-Methods"] = "POST, OPTIONS"
    return resp


@app.route("/healthz", methods=["GET"])
def healthz():
    return jsonify({"ok": True})


@app.route("/api/vessel/track", methods=["POST", "OPTIONS"])
def api_track():
    if request.method == "OPTIONS":
        return ("", 204)

    data = request.get_json(silent=True) or {}
    vessel_name = (data.get("vessel_name") or "").strip()
    voyage_no = (data.get("voyage_no") or "").strip() or None
    message = data.get("message")

    result = track(vessel_name, voyage_no) if vessel_name else track_from_text(message or "")

    return jsonify({
        "ok": result.ok,
        "kind": result.kind,
        "reply": result.message,
        "vessel_name": result.vessel_name,
        "voyage_no": result.voyage_no,
        "position": result.position.to_dict() if result.position else None,
    })


@app.route("/kakao/skill", methods=["POST"])
def kakao_skill():
    """카카오 i 오픈빌더 스킬 응답 포맷.
    참고: https://i.kakao.com/docs/skill-response-format
    """
    body = request.get_json(silent=True) or {}
    utterance = body.get("userRequest", {}).get("utterance", "")
    result = track_from_text(utterance)
    return jsonify(_kakao_simple_text(result.message))


def _kakao_simple_text(text: str) -> dict:
    return {
        "version": "2.0",
        "template": {"outputs": [{"simpleText": {"text": text[:1000]}}]},
    }


if __name__ == "__main__":
    port = int(os.getenv("VESSEL_SERVER_PORT", "8787"))
    print(f"🚢 선박 추적 서버 시작 — http://0.0.0.0:{port}")
    print(f"   웹위젯 API: POST /api/vessel/track")
    print(f"   카카오 스킬: POST /kakao/skill")
    app.run(host="0.0.0.0", port=port, debug=False)
