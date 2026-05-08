/* ============================================================
   (주)태엔종합물류 — Main JavaScript
   ============================================================ */

document.addEventListener('DOMContentLoaded', () => {

  /* ── HERO CANVAS: Global Logistics Network Animation ── */
  (function initHeroCanvas() {
    const canvas = document.getElementById('heroCanvas');
    if (!canvas) return;
    const ctx = canvas.getContext('2d');

    function resize() {
      const hero = canvas.parentElement;
      canvas.width  = hero.offsetWidth  || window.innerWidth;
      canvas.height = hero.offsetHeight || window.innerHeight;
    }
    resize();
    window.addEventListener('resize', resize, { passive: true });

    // Major port nodes [xRatio, yRatio, label]
    const nodes = [
      [0.81, 0.36, '부산'],
      [0.79, 0.41, '상하이'],
      [0.77, 0.54, '싱가포르'],
      [0.47, 0.27, '로테르담'],
      [0.13, 0.42, 'LA'],
      [0.23, 0.31, '뉴욕'],
      [0.60, 0.44, '두바이'],
      [0.84, 0.71, '시드니'],
      [0.76, 0.47, '홍콩'],
      [0.50, 0.34, '함부르크'],
      [0.35, 0.55, '상파울루'],
      [0.40, 0.24, '런던'],
    ];

    // Route pairs [from, to]
    const routes = [
      [0, 3], [0, 4], [1, 4], [2, 3],
      [8, 5], [6, 3], [0, 6], [7, 3],
      [1, 5], [3, 11],[2, 6], [4, 10],
      [0, 8], [3, 9],
    ];

    // One particle per route, staggered start positions
    const particles = routes.map((r, i) => ({
      route: r,
      t: (i / routes.length),
      speed: 0.0008 + Math.random() * 0.0012,
    }));
    // Add a second wave
    routes.forEach((r, i) => particles.push({
      route: r,
      t: (i / routes.length + 0.5) % 1,
      speed: 0.0006 + Math.random() * 0.001,
    }));

    const bezierPt = (ax, ay, bx, by, t) => {
      const cpx = (ax + bx) / 2;
      const cpy = Math.min(ay, by) - canvas.height * 0.14;
      const u = 1 - t;
      return [u*u*ax + 2*u*t*cpx + t*t*bx, u*u*ay + 2*u*t*cpy + t*t*by];
    };

    let raf;
    function draw() {
      const W = canvas.width, H = canvas.height;
      // Background
      const bg = ctx.createLinearGradient(0, 0, W, H);
      bg.addColorStop(0,   '#030c20');
      bg.addColorStop(0.5, '#071833');
      bg.addColorStop(1,   '#030c20');
      ctx.fillStyle = bg;
      ctx.fillRect(0, 0, W, H);

      // Draw routes
      routes.forEach(([a, b]) => {
        const [ax, ay] = [nodes[a][0]*W, nodes[a][1]*H];
        const [bx, by] = [nodes[b][0]*W, nodes[b][1]*H];
        const cpx = (ax+bx)/2, cpy = Math.min(ay,by) - H*0.14;
        ctx.beginPath();
        ctx.moveTo(ax, ay);
        ctx.quadraticCurveTo(cpx, cpy, bx, by);
        ctx.strokeStyle = 'rgba(53,104,212,0.22)';
        ctx.lineWidth = 1;
        ctx.stroke();
      });

      // Draw nodes
      nodes.forEach(([rx, ry]) => {
        const x = rx*W, y = ry*H;
        const grd = ctx.createRadialGradient(x,y,0, x,y,14);
        grd.addColorStop(0, 'rgba(80,140,255,0.70)');
        grd.addColorStop(1, 'rgba(53,104,212,0)');
        ctx.fillStyle = grd;
        ctx.beginPath(); ctx.arc(x,y,14,0,Math.PI*2); ctx.fill();
        ctx.fillStyle = '#fff';
        ctx.beginPath(); ctx.arc(x,y,3,0,Math.PI*2); ctx.fill();
        ctx.strokeStyle = 'rgba(255,255,255,0.4)';
        ctx.lineWidth = 1;
        ctx.beginPath(); ctx.arc(x,y,6,0,Math.PI*2); ctx.stroke();
      });

      // Draw particles
      particles.forEach(p => {
        p.t = (p.t + p.speed) % 1;
        const [a, b] = p.route;
        const [ax,ay] = [nodes[a][0]*W, nodes[a][1]*H];
        const [bx,by] = [nodes[b][0]*W, nodes[b][1]*H];
        const [px,py] = bezierPt(ax,ay,bx,by,p.t);
        const alpha = p.t < 0.1 ? p.t/0.1 : p.t > 0.9 ? (1-p.t)/0.1 : 1;
        ctx.fillStyle = `rgba(255,190,60,${0.85*alpha})`;
        ctx.beginPath(); ctx.arc(px,py,2.2,0,Math.PI*2); ctx.fill();
        // Trail
        if (p.t > 0.02) {
          const [px2,py2] = bezierPt(ax,ay,bx,by, Math.max(0,p.t-0.04));
          ctx.beginPath();
          ctx.moveTo(px2,py2); ctx.lineTo(px,py);
          ctx.strokeStyle = `rgba(255,190,60,${0.25*alpha})`;
          ctx.lineWidth = 1.5; ctx.stroke();
        }
      });

      raf = requestAnimationFrame(draw);
    }
    draw();
  })();

  /* ── HEADER: scroll effect ── */
  const header = document.getElementById('header');
  const onScroll = () => {
    header.classList.toggle('scrolled', window.scrollY > 60);
    scrollTopBtn.classList.toggle('visible', window.scrollY > 400);
  };
  window.addEventListener('scroll', onScroll, { passive: true });

  /* ── HAMBURGER MENU ── */
  const hamburger  = document.getElementById('hamburger');
  const mobileMenu = document.getElementById('mobileMenu');
  hamburger.addEventListener('click', () => {
    mobileMenu.classList.toggle('open');
  });
  // Close on nav link click
  mobileMenu.querySelectorAll('a').forEach(link => {
    link.addEventListener('click', () => mobileMenu.classList.remove('open'));
  });

  // Accordion: toggle sub-items on title click
  mobileMenu.querySelectorAll('.mobile-acc-title').forEach(btn => {
    btn.addEventListener('click', () => {
      const item = btn.closest('.mobile-accordion');
      const isOpen = item.classList.contains('open');
      // Close all open accordions
      mobileMenu.querySelectorAll('.mobile-accordion.open').forEach(el => el.classList.remove('open'));
      // Open clicked one if it was closed
      if (!isOpen) item.classList.add('open');
    });
  });

  /* ── HERO SLIDER ── */
  const slides     = document.querySelectorAll('.slide');
  const slideTexts = document.querySelectorAll('.slide-text'); // text panels (hero redesign)
  const dots       = document.querySelectorAll('.dot');
  let current      = 0;
  let autoPlay;

  const goTo = (idx) => {
    slides[current].classList.remove('active');
    if (slideTexts.length) slideTexts[current].classList.remove('active');
    dots[current].classList.remove('active');
    current = (idx + slides.length) % slides.length;
    slides[current].classList.add('active');
    if (slideTexts.length) slideTexts[current].classList.add('active');
    dots[current].classList.add('active');
  };

  const startAuto = () => {
    autoPlay = setInterval(() => goTo(current + 1), 5000);
  };
  const stopAuto = () => clearInterval(autoPlay);

  document.getElementById('slideNext').addEventListener('click', () => { stopAuto(); goTo(current + 1); startAuto(); });
  document.getElementById('slidePrev').addEventListener('click', () => { stopAuto(); goTo(current - 1); startAuto(); });
  dots.forEach(dot => {
    dot.addEventListener('click', () => { stopAuto(); goTo(Number(dot.dataset.idx)); startAuto(); });
  });
  startAuto();

  /* ── SCROLL TO TOP ── */
  const scrollTopBtn = document.getElementById('scrollTop');
  scrollTopBtn.addEventListener('click', () => {
    window.scrollTo({ top: 0, behavior: 'smooth' });
  });

  /* ── SMOOTH SCROLL for anchor links ── */
  document.querySelectorAll('a[href^="#"]').forEach(link => {
    link.addEventListener('click', (e) => {
      const target = document.querySelector(link.getAttribute('href'));
      if (target) {
        e.preventDefault();
        const offset = 72; // header height
        const top = target.getBoundingClientRect().top + window.scrollY - offset;
        window.scrollTo({ top, behavior: 'smooth' });
      }
    });
  });

  /* ── FADE-IN ANIMATION on scroll ── */
  const fadeEls = document.querySelectorAll(
    '.service-card, .why-item, .stat-item, .about-content, .about-img, .network-content, .network-map, .info-box, .contact-item, .contact-form'
  );
  fadeEls.forEach((el, i) => {
    el.classList.add('fade-in');
    if (i % 4 === 1) el.classList.add('fade-in-delay-1');
    if (i % 4 === 2) el.classList.add('fade-in-delay-2');
    if (i % 4 === 3) el.classList.add('fade-in-delay-3');
  });

  const fadeObserver = new IntersectionObserver((entries) => {
    entries.forEach(entry => {
      if (entry.isIntersecting) {
        entry.target.classList.add('visible');
        fadeObserver.unobserve(entry.target);
      }
    });
  }, { threshold: 0.12 });

  fadeEls.forEach(el => fadeObserver.observe(el));

  /* ── STATS COUNTER ANIMATION ── */
  const statNums = document.querySelectorAll('.stat-num');
  const countObserver = new IntersectionObserver((entries) => {
    entries.forEach(entry => {
      if (entry.isIntersecting) {
        const el     = entry.target;
        const target = Number(el.dataset.target);
        const dur    = 1800;
        const step   = 16;
        const inc    = target / (dur / step);
        let current  = 0;
        const timer  = setInterval(() => {
          current += inc;
          if (current >= target) { current = target; clearInterval(timer); }
          el.textContent = Math.floor(current).toLocaleString();
        }, step);
        countObserver.unobserve(el);
      }
    });
  }, { threshold: 0.5 });

  statNums.forEach(el => countObserver.observe(el));

  /* ── CONTACT FORM ── */
  const form = document.getElementById('contactForm');
  if (form) {
    form.addEventListener('submit', (e) => {
      e.preventDefault();
      const btn = form.querySelector('.btn-submit');
      btn.textContent = '전송 중...';
      btn.disabled = true;
      // Simulate async submit
      setTimeout(() => {
        btn.textContent = '문의가 접수되었습니다 ✓';
        btn.style.background = '#2e7d32';
        setTimeout(() => {
          form.reset();
          btn.textContent = '문의 보내기';
          btn.style.background = '';
          btn.disabled = false;
        }, 3000);
      }, 1000);
    });
  }

  /* ── ACTIVE NAV highlight on scroll ── */
  const sections = document.querySelectorAll('section[id]');
  const navLinks = document.querySelectorAll('.gnb a');
  const highlightNav = () => {
    let current = '';
    sections.forEach(sec => {
      if (window.scrollY >= sec.offsetTop - 100) current = sec.id;
    });
    navLinks.forEach(link => {
      link.style.fontWeight = link.getAttribute('href') === `#${current}` ? '700' : '';
    });
  };
  window.addEventListener('scroll', highlightNav, { passive: true });

  /* ── FLOATING ACTION BUTTONS + AI CHAT WIDGET ── */
  (function initFAB() {

    // ── 영업시간 판단 (평일 09:00~18:00) ──
    function isBizHours() {
      const d = new Date(), day = d.getDay(), h = d.getHours();
      return day >= 1 && day <= 5 && h >= 9 && h < 18;
    }

    // ── 규칙 기반 AI 응답 ──
    function getAutoReply(msg) {
      const m = msg.toLowerCase();
      if (/안녕|hello|hi|반가|처음/.test(m))
        return '안녕하세요! 태인종합물류 AI 상담입니다 😊\n해상·항공·육상 운송, 통관, 견적 등 무엇이든 물어보세요!';
      if (/해상|fcl|lcl|컨테이너|선박|배편/.test(m))
        return '해상운송 서비스를 제공합니다.\n\n• FCL (Full Container Load) — 컨테이너 단위\n• LCL (Less Container Load) — 소량 혼재 화물\n\n주요 항로: 중국·동남아·미주·유럽 전세계\n정확한 견적은 화물 정보(품목·중량·출발지·목적지)를 알려주시면 빠르게 안내해드립니다.';
      if (/항공|에어|air|빠른 배송|긴급/.test(m))
        return '항공운송 서비스를 제공합니다.\n\n• 일반 항공화물\n• 긴급·특수화물 (당일/익일 처리 가능)\n\n빠른 글로벌 항공 네트워크로 신속 배송이 가능합니다.';
      if (/육상|내륙|트럭|차량|배달/.test(m))
        return '육상운송 서비스를 제공합니다.\n\n• 전국 배송 네트워크\n• 항만 → 창고 → 수하인 일괄 처리\n• 컨테이너 내륙 운송';
      if (/통관|수출|수입|세관|hs코드|관세/.test(m))
        return '통관 및 포워딩 서비스를 제공합니다.\n\n• 수출통관 / 수입통관\n• HS코드 분류 컨설팅\n• 관세 절감 방안 제시\n\n복잡한 통관 절차를 전문가가 처리합니다.';
      if (/견적|가격|비용|요금|얼마|단가/.test(m))
        return '견적은 화물 정보에 따라 달라집니다.\n\n빠른 견적을 위해 아래 정보를 알려주세요:\n① 품목\n② 중량 / 용적\n③ 출발지 → 목적지\n\n📞 02-3142-4051\n📧 op@ttt3.co.kr';
      if (/전화|연락처|주소|이메일|위치|어디|찾아/.test(m))
        return '📞 대표전화: 02-3142-4051\n📠 팩스: 02-3142-4055\n📧 이메일: op@ttt3.co.kr\n📍 주소: 서울 마포구 월드컵로 112, 4층\n\n영업시간: 평일 09:00 ~ 18:00';
      if (/영업시간|운영시간|몇시|시간|언제/.test(m))
        return '영업시간은 평일 09:00 ~ 18:00입니다.\n(토·일·공휴일 휴무)\n\n영업시간 외에는 이 채팅으로 문의 남겨주시면 다음 영업일에 연락드립니다.';
      if (/wca|네트워크|해외|파트너|나라|국가/.test(m))
        return 'WCA(World Cargo Association) 정식 회원사로서\n40여 개국, 120여 개 해외 파트너 네트워크를 보유합니다.\n\n🌏 아시아 (중국·일본·동남아 등)\n🌍 유럽 (영국·독일·프랑스 등)\n🌎 미주 (미국·캐나다·중남미)\n🦘 호주·오세아니아';
      if (/3pl|4pl|창고|물류 솔루션|풀필먼트|아웃소싱/.test(m))
        return '종합 물류 솔루션을 제공합니다.\n\n• 3PL/4PL 물류 아웃소싱\n• 창고 관리(WMS)\n• SCM 컨설팅\n• ONE-STOP 통합 물류 관리\n\n기업 맞춤형 솔루션 상담: 02-3142-4051';
      if (/감사|고마|수고|잘됐|해결/.test(m))
        return '감사합니다! 더 궁금하신 점이 있으면 언제든지 문의해 주세요 😊';
      // 기본 응답
      return '문의해 주셔서 감사합니다.\n\n현재 ' + (isBizHours() ? '상담원 연결을 도와드리겠습니다.\n📞 02-3142-4051' : '영업시간(평일 09:00~18:00) 외 시간으로 AI가 답변드립니다.\n\n해상·항공·육상 운송, 통관, 견적, 연락처 등을 물어보시면 바로 안내해드릴게요!');
    }

    // ── HTML 주입 ──
    document.body.insertAdjacentHTML('beforeend', `
      <div class="fab-group" id="fabGroup">
        <a href="tel:02-3142-4051" class="fab-btn fab-phone" aria-label="전화 문의">
          <svg viewBox="0 0 24 24" fill="currentColor" width="22" height="22">
            <path d="M6.62 10.79c1.44 2.83 3.76 5.14 6.59 6.59l2.2-2.2c.27-.27.67-.36 1.02-.24 1.12.37 2.33.57 3.57.57.55 0 1 .45 1 1V20c0 .55-.45 1-1 1C9.61 21 3 14.39 3 6c0-.55.45-1 1-1h3.5c.55 0 1 .45 1 1 0 1.25.2 2.45.57 3.57.11.35.03.74-.25 1.02l-2.2 2.2z"/>
          </svg>
        </a>
        <button class="fab-btn fab-chat" id="fabChat" aria-label="실시간 상담">
          <svg viewBox="0 0 24 24" fill="currentColor" width="22" height="22">
            <path d="M20 2H4c-1.1 0-2 .9-2 2v18l4-4h14c1.1 0 2-.9 2-2V4c0-1.1-.9-2-2-2z"/>
          </svg>
        </button>
      </div>

      <div class="chat-widget" id="chatWidget" role="dialog" aria-label="실시간 상담">
        <div class="chat-header">
          <div class="chat-header-info">
            <span class="chat-status-dot" id="chatDot"></span>
            <div>
              <p class="chat-company-name">태인종합물류</p>
              <p class="chat-online-text" id="chatStatusText">불러오는 중...</p>
            </div>
          </div>
          <button class="chat-close" id="chatClose" aria-label="닫기">
            <svg viewBox="0 0 24 24" fill="currentColor" width="11" height="11">
              <path d="M19 6.41L17.59 5 12 10.59 6.41 5 5 6.41 10.59 12 5 17.59 6.41 19 12 13.41 17.59 19 19 17.59 13.41 12z"/>
            </svg>
          </button>
        </div>
        <div class="chat-messages" id="chatMessages"></div>
        <div class="chat-input-area">
          <textarea class="chat-input-field" id="chatInput" placeholder="메시지를 입력하세요..." rows="1"></textarea>
          <button class="chat-input-send" id="chatSend" aria-label="전송">
            <svg viewBox="0 0 24 24" fill="currentColor" width="18" height="18">
              <path d="M2.01 21L23 12 2.01 3 2 10l15 2-15 2z"/>
            </svg>
          </button>
        </div>
      </div>
    `);

    // ── 요소 참조 ──
    const widget   = document.getElementById('chatWidget');
    const fabChat  = document.getElementById('fabChat');
    const msgArea  = document.getElementById('chatMessages');
    const input    = document.getElementById('chatInput');
    const sendBtn  = document.getElementById('chatSend');
    const statusTxt = document.getElementById('chatStatusText');
    const statusDot = document.getElementById('chatDot');

    // ── 상태 표시 ──
    if (isBizHours()) {
      statusTxt.textContent = '상담원 연결 가능';
      statusDot.style.background = '#4ade80';
    } else {
      statusTxt.textContent = 'AI 자동 응답 중';
      statusDot.style.background = '#facc15';
    }

    // ── 말풍선 추가 ──
    let busy = false;
    function ts() {
      return new Date().toLocaleTimeString('ko-KR', { hour: '2-digit', minute: '2-digit' });
    }
    function addMsg(role, text) {
      const div = document.createElement('div');
      div.className = 'chat-msg chat-msg-' + role;
      div.innerHTML = `<div class="chat-msg-bubble">${text.replace(/\n/g,'<br>')}</div><span class="chat-msg-time">${ts()}</span>`;
      msgArea.appendChild(div);
      msgArea.scrollTop = msgArea.scrollHeight;
    }
    function showTyping() {
      const div = document.createElement('div');
      div.id = 'typingEl';
      div.className = 'chat-msg chat-msg-assistant';
      div.innerHTML = '<div class="chat-msg-bubble chat-typing"><span></span><span></span><span></span></div>';
      msgArea.appendChild(div);
      msgArea.scrollTop = msgArea.scrollHeight;
    }
    function hideTyping() {
      const el = document.getElementById('typingEl');
      if (el) el.remove();
    }

    // ── 열기/닫기 ──
    const openChat  = () => {
      widget.classList.add('open');
      fabChat.classList.add('active');
      if (!msgArea.children.length) {
        const greeting = isBizHours()
          ? '안녕하세요! 태인종합물류입니다 😊\n상담원이 곧 답변드립니다.\n해상·항공·육상운송, 통관, 견적 등 무엇이든 물어보세요!'
          : '안녕하세요! 태인종합물류입니다 😊\n현재 영업시간 외 시간으로 AI가 답변드립니다.\n해상·항공·육상운송, 통관, 견적 등 자유롭게 물어보세요!';
        addMsg('assistant', greeting);
      }
      setTimeout(() => input.focus(), 300);
    };
    const closeChat = () => { widget.classList.remove('open'); fabChat.classList.remove('active'); };

    fabChat.addEventListener('click', () => widget.classList.contains('open') ? closeChat() : openChat());
    document.getElementById('chatClose').addEventListener('click', closeChat);
    document.addEventListener('click', (e) => {
      if (!widget.contains(e.target) && !fabChat.contains(e.target)) closeChat();
    });

    // ── 메시지 전송 ──
    async function send() {
      const msg = input.value.trim();
      if (!msg || busy) return;
      busy = true;
      input.value = '';
      input.style.height = 'auto';
      sendBtn.disabled = true;
      addMsg('user', msg);
      showTyping();
      await new Promise(r => setTimeout(r, 700 + Math.random() * 600));
      hideTyping();
      addMsg('assistant', getAutoReply(msg));
      busy = false;
      sendBtn.disabled = false;
      input.focus();
    }

    sendBtn.addEventListener('click', send);
    input.addEventListener('keydown', (e) => {
      if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); send(); }
    });
    // 자동 높이 조절
    input.addEventListener('input', () => {
      input.style.height = 'auto';
      input.style.height = Math.min(input.scrollHeight, 80) + 'px';
    });

  })();

});
