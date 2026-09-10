/*
 * assets/vessel-widget.js
 * 선박 추적 챗위젯 — 모선명 + 항차번호만 입력하면 vessel/server.py 의
 * POST /api/vessel/track 를 호출해서 실시간 위치를 보여준다.
 *
 * 사용법: 이 스크립트를 페이지에 넣고, 아래 API_BASE를 vessel/server.py를
 * 배포한 주소로 바꾸면 된다. (로컬 테스트: python vessel/server.py 실행 후
 * http://localhost:8787 그대로 사용)
 *
 *   <script src="assets/vessel-widget.js"></script>
 */
(function () {
  "use strict";

  // ── 설정 ────────────────────────────────────────────────
  // TODO: vessel/server.py 를 배포한 실제 주소로 교체하세요.
  var API_BASE = window.VESSEL_API_BASE || "http://localhost:8787";
  var API_URL = API_BASE.replace(/\/$/, "") + "/api/vessel/track";

  // ── DOM 구성 ────────────────────────────────────────────
  var fab = document.createElement("button");
  fab.className = "vt-fab";
  fab.type = "button";
  fab.setAttribute("aria-label", "선박 위치 추적");
  fab.innerHTML = "🚢";

  var panel = document.createElement("div");
  panel.className = "vt-panel";
  panel.innerHTML =
    '<div class="vt-header">' +
      '<span>🚢 선박 위치 추적</span>' +
      '<button type="button" class="vt-close" aria-label="닫기">✕</button>' +
    "</div>" +
    '<div class="vt-messages"></div>' +
    '<div class="vt-input-row">' +
      '<input type="text" class="vt-input" placeholder="예) HMM 코펜하겐, 0526E" />' +
      '<button type="button" class="vt-send">전송</button>' +
    "</div>";

  document.addEventListener("DOMContentLoaded", function () {
    document.body.appendChild(fab);
    document.body.appendChild(panel);
    addBotMessage("안녕하세요! 모선명과 항차번호를 알려주시면 실시간 위치를 알려드릴게요.\n예) HMM 코펜하겐, 0526E");
  });

  var messagesEl = panel.querySelector(".vt-messages");
  var inputEl = panel.querySelector(".vt-input");
  var sendBtn = panel.querySelector(".vt-send");
  var closeBtn = panel.querySelector(".vt-close");

  function addMessage(text, who) {
    var bubble = document.createElement("div");
    bubble.className = "vt-msg vt-msg-" + who;
    bubble.textContent = text;
    messagesEl.appendChild(bubble);
    messagesEl.scrollTop = messagesEl.scrollHeight;
    return bubble;
  }
  function addBotMessage(text) { return addMessage(text, "bot"); }
  function addUserMessage(text) { return addMessage(text, "user"); }

  function send() {
    var text = inputEl.value.trim();
    if (!text) return;
    addUserMessage(text);
    inputEl.value = "";
    inputEl.disabled = true;
    sendBtn.disabled = true;

    var loading = addBotMessage("조회 중...");

    fetch(API_URL, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ message: text }),
    })
      .then(function (r) { return r.json(); })
      .then(function (data) {
        loading.textContent = data.reply || "조회 결과가 없어요.";
      })
      .catch(function () {
        loading.textContent =
          "⚠️ 추적 서버에 연결할 수 없어요. 잠시 후 다시 시도해 주세요.";
      })
      .finally(function () {
        inputEl.disabled = false;
        sendBtn.disabled = false;
        inputEl.focus();
      });
  }

  fab.addEventListener("click", function () {
    panel.classList.toggle("vt-open");
    if (panel.classList.contains("vt-open")) inputEl.focus();
  });
  closeBtn.addEventListener("click", function () {
    panel.classList.remove("vt-open");
  });
  sendBtn.addEventListener("click", send);
  inputEl.addEventListener("keydown", function (e) {
    if (e.key === "Enter") send();
  });
})();
