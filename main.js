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

  /* ── CONTACT FORM (Formspree) ── */
  const form = document.getElementById('homeInquiryForm');
  if (form) {
    form.addEventListener('submit', async (e) => {
      e.preventDefault();
      const btn = form.querySelector('.btn-submit');
      const origText = btn.textContent;
      btn.textContent = '전송 중...';
      btn.disabled = true;
      try {
        const resp = await fetch('https://formspree.io/f/xpwrjvrd', {
          method: 'POST',
          body: new FormData(form),
          headers: { 'Accept': 'application/json' }
        });
        if (resp.ok) {
          btn.textContent = '문의가 접수되었습니다 ✓';
          btn.style.background = '#2e7d32';
          setTimeout(() => {
            form.reset();
            btn.textContent = origText;
            btn.style.background = '';
            btn.disabled = false;
          }, 3000);
        } else {
          throw new Error('submit failed');
        }
      } catch {
        btn.textContent = '전송 실패 — 다시 시도해주세요';
        btn.style.background = '#c62828';
        setTimeout(() => {
          btn.textContent = origText;
          btn.style.background = '';
          btn.disabled = false;
        }, 3000);
      }
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

    // ── 영업시간 체크 (평일 09:00~18:00) ──
    function isBizHours() {
      const now = new Date();
      const day = now.getDay();
      const h = now.getHours();
      return day >= 1 && day <= 5 && h >= 9 && h < 18;
    }

    // ── AI 자동 응답 (사전 설정 키워드만) ──
    function getAutoReply(msg) {
      const m = msg.toLowerCase();
      if (/안녕|hello|hi|반가|처음/.test(m))
        return '안녕하세요! 태인종합물류 AI 상담입니다 😊\n해상·항공·육상 운송, 통관, 견적 등 무엇이든 물어보세요!';
      if (/해상|fcl|lcl|컨테이너|선박|배편/.test(m))
        return '해상운송 서비스를 제공합니다.\n\n• FCL (Full Container Load) — 컨테이너 단위\n• LCL (Less Container Load) — 소량 혼재 화물\n\n주요 항로: 중국·동남아·미주·유럽 전세계\n견적은 품목·중량·출발지·목적지를 알려주시면 빠르게 안내드립니다.';
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
        return '영업시간은 평일 09:00 ~ 18:00입니다.\n(토·일·공휴일 휴무)\n\n영업시간 중에도 AI 상담을 이용하시거나,\n상담사 연결 버튼으로 직접 문의하실 수 있습니다.';
      if (/wca|네트워크|해외|파트너|나라|국가/.test(m))
        return 'WCA(World Cargo Association) 정식 회원사로서\n40여 개국, 120여 개 해외 파트너 네트워크를 보유합니다.\n\n🌏 아시아 (중국·일본·동남아 등)\n🌍 유럽 (영국·독일·프랑스 등)\n🌎 미주 (미국·캐나다·중남미)\n🦘 호주·오세아니아';
      if (/3pl|4pl|창고|물류 솔루션|풀필먼트|아웃소싱/.test(m))
        return '종합 물류 솔루션을 제공합니다.\n\n• 3PL/4PL 물류 아웃소싱\n• 창고 관리(WMS)\n• SCM 컨설팅\n• ONE-STOP 통합 물류 관리\n\n기업 맞춤형 솔루션 상담: 02-3142-4051';
      if (/감사|고마|수고|잘됐|해결/.test(m))
        return '감사합니다! 더 궁금하신 점이 있으면 언제든지 문의해 주세요 😊';
      return '문의해 주셔서 감사합니다.\n\n해상·항공·육상운송, 통관, 견적, 연락처 등 구체적인 내용을 알려주시면 바로 안내해드리겠습니다!\n\n직접 통화를 원하시면 📞 02-3142-4051';
    }

    // ── HTML 주입 ──
    document.body.insertAdjacentHTML('beforeend', `
      <div class="chat-overlay" id="chatOverlay"></div>
      <div class="fab-group" id="fabGroup">
        <a href="tel:02-3142-4051" class="fab-btn fab-phone" aria-label="전화 문의">
          <svg viewBox="0 0 24 24" fill="currentColor" width="22" height="22">
            <path d="M6.62 10.79c1.44 2.83 3.76 5.14 6.59 6.59l2.2-2.2c.27-.27.67-.36 1.02-.24 1.12.37 2.33.57 3.57.57.55 0 1 .45 1 1V20c0 .55-.45 1-1 1C9.61 21 3 14.39 3 6c0-.55.45-1 1-1h3.5c.55 0 1 .45 1 1 0 1.25.2 2.45.57 3.57.11.35.03.74-.25 1.02l-2.2 2.2z"/>
          </svg>
        </a>
        <a href="https://pf.kakao.com/_taeinlogistics" target="_blank" rel="noopener" class="fab-btn fab-kakao" aria-label="카카오톡 상담">
          <svg viewBox="0 0 24 24" fill="currentColor" width="22" height="22">
            <path d="M12 2C6.48 2 2 5.86 2 10.6c0 3.04 1.87 5.72 4.72 7.29L5.6 22l5.02-2.64c.45.06.9.09 1.38.09 5.52 0 10-3.86 10-8.6S17.52 2 12 2z"/>
          </svg>
        </a>
        <button class="fab-btn fab-chat" id="fabChat" aria-label="실시간 상담">
          <svg viewBox="0 0 24 24" fill="currentColor" width="22" height="22">
            <path d="M20 2H4c-1.1 0-2 .9-2 2v18l4-4h14c1.1 0 2-.9 2-2V4c0-1.1-.9-2-2-2z"/>
          </svg>
        </button>
      </div>

      <div class="chat-widget" id="chatWidget" role="dialog" aria-label="AI 상담">
        <div class="chat-header">
          <div class="chat-header-info">
            <span class="chat-status-dot"></span>
            <div>
              <p class="chat-company-name">태인종합물류</p>
              <p class="chat-online-text">AI 자동 상담</p>
            </div>
          </div>
          <button class="chat-close" id="chatClose" tabindex="-1" aria-label="닫기">
            <svg viewBox="0 0 24 24" fill="currentColor" width="11" height="11">
              <path d="M19 6.41L17.59 5 12 10.59 6.41 5 5 6.41 10.59 12 5 17.59 6.41 19 12 13.41 17.59 19 19 17.59 13.41 12z"/>
            </svg>
          </button>
        </div>
        <div class="chat-messages" id="chatMessages"></div>
        <div class="chat-agent-tab" id="chatAgentTab">
          <button class="chat-agent-btn" id="chatAgentBtn">
            <svg viewBox="0 0 24 24" fill="currentColor" width="14" height="14"><path d="M12 2C6.48 2 2 6.48 2 12s4.48 10 10 10 10-4.48 10-10S17.52 2 12 2zm-2 15l-5-5 1.41-1.41L10 14.17l7.59-7.59L19 8l-9 9z"/></svg>
            상담사 직접 연결 요청
          </button>
        </div>
        <div class="chat-input-area">
          <textarea class="chat-input-field" id="chatInput" placeholder="메시지를 입력하세요..." rows="1"></textarea>
          <button class="chat-input-send" id="chatSend" tabindex="-1" aria-label="전송">
            <svg viewBox="0 0 24 24" fill="currentColor" width="18" height="18">
              <path d="M2.01 21L23 12 2.01 3 2 10l15 2-15 2z"/>
            </svg>
          </button>
        </div>
      </div>
    `);

    // ── 요소 참조 ──
    const widget    = document.getElementById('chatWidget');
    const fabGroup  = document.getElementById('fabGroup');
    const overlay   = document.getElementById('chatOverlay');
    const fabChat   = document.getElementById('fabChat');
    const msgArea   = document.getElementById('chatMessages');
    const input     = document.getElementById('chatInput');
    const sendBtn   = document.getElementById('chatSend');
    const agentBtn  = document.getElementById('chatAgentBtn');
    const onlineText = widget.querySelector('.chat-online-text');
    const statusDot  = widget.querySelector('.chat-status-dot');

    // ── 영업시간에 따라 UI 초기 상태 설정 ──
    if (!isBizHours()) {
      onlineText.textContent = '영업시간 외 (AI 상담)';
      statusDot.style.background = '#fbbf24';
      statusDot.style.boxShadow = '0 0 0 3px rgba(251,191,36,0.25)';
      agentBtn.disabled = true;
      agentBtn.innerHTML = `<svg viewBox="0 0 24 24" fill="currentColor" width="14" height="14"><path d="M12 2C6.48 2 2 6.48 2 12s4.48 10 10 10 10-4.48 10-10S17.52 2 12 2zm1 15h-2v-2h2v2zm0-4h-2V7h2v6z"/></svg> 영업시간 외 — 상담사 연결 불가`;
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

    // ── 상담사 연결 탭 ──
    agentBtn.addEventListener('mousedown', e => e.preventDefault());
    agentBtn.addEventListener('click', () => {
      if (!isBizHours()) return;
      addMsg('user', '상담사 연결을 요청합니다.');
      showTyping();
      setTimeout(() => {
        hideTyping();
        addMsg('assistant', '상담사 연결 요청이 접수되었습니다!\n\n담당자가 빠른 시간 내에 연락드리겠습니다.\n\n📞 즉시 연결: 02-3142-4051\n📧 이메일: op@ttt3.co.kr\n⏰ 영업시간: 평일 09:00 ~ 18:00');
      }, 800);
    });

    let _closeMobileTimer = null;

    // ── 위젯 위치 초기화 ──
    function resetWidgetPos() {
      widget.style.position      = '';
      widget.style.top           = '';
      widget.style.left          = '';
      widget.style.right         = '';
      widget.style.bottom        = '';
      widget.style.width         = '';
      widget.style.height        = '';
      widget.style.maxHeight     = '';
      widget.style.paddingBottom = '';
      widget.style.boxSizing     = '';
      widget.style.borderRadius  = '';
      widget.classList.remove('kb-open');
      fabGroup.style.opacity = '';
      fabGroup.style.pointerEvents = '';
    }

    // ── 모바일: 시각적 뷰포트(visual viewport)에 정확히 맞춰 전체화면 ──
    // iOS Safari에서 키보드가 올라오면 vvp.offsetTop이 양수가 되며
    // 헤더가 화면 위로 밀려나는 버그를 top: vvp.offsetTop으로 방지
    function setMobileLayout() {
      const vvp = window.visualViewport;
      const top = vvp ? Math.round(vvp.offsetTop) : 0;
      const h   = vvp ? Math.round(vvp.height)    : window.innerHeight;

      widget.style.position      = 'fixed';
      widget.style.top           = top + 'px';
      widget.style.left          = '0';
      widget.style.right         = '0';
      widget.style.bottom        = '';
      widget.style.width         = '100%';
      widget.style.height        = h + 'px';
      widget.style.maxHeight     = 'none';
      widget.style.paddingBottom = '';
      widget.style.boxSizing     = 'border-box';
      widget.style.borderRadius  = (top > 0 || h < window.innerHeight) ? '0' : '20px';
      // transform / opacity / pointerEvents → CSS가 담당
      widget.classList.add('kb-open');
      fabGroup.style.opacity = '0';
      fabGroup.style.pointerEvents = 'none';
    }

    // ── 키보드/뷰포트 변화 시 레이아웃 갱신 ──
    function adjustForKeyboard() {
      if (!widget.classList.contains('open') || window.innerWidth > 600) return;
      const vvp = window.visualViewport;
      setMobileLayout();
      if (vvp && vvp.height < window.innerHeight) msgArea.scrollTop = msgArea.scrollHeight;
    }

    if (window.visualViewport) {
      window.visualViewport.addEventListener('resize', adjustForKeyboard);
      window.visualViewport.addEventListener('scroll', adjustForKeyboard);
    }
    input.addEventListener('focus', () => setTimeout(adjustForKeyboard, 80));
    input.addEventListener('focus', () => setTimeout(adjustForKeyboard, 300));
    input.addEventListener('blur',  () => {
      setTimeout(() => {
        if (widget.classList.contains('open') && window.innerWidth <= 600) setMobileLayout();
      }, 100);
    });

    // ── 열기/닫기 ──
    const openChat = () => {
      if (_closeMobileTimer) { clearTimeout(_closeMobileTimer); _closeMobileTimer = null; }
      overlay.classList.add('active');
      if (window.innerWidth <= 600) {
        resetWidgetPos();
        setMobileLayout();
      }
      widget.classList.add('open');
      fabChat.classList.add('active');
      if (!msgArea.children.length) {
        if (isBizHours()) {
          addMsg('assistant', '안녕하세요! 태인종합물류 AI 상담입니다 😊\n무엇을 도와드릴까요?');
        } else {
          addMsg('assistant', '안녕하세요! 태인종합물류 AI 상담입니다 😊\n⚠️ 현재 영업시간 외입니다. AI가 기본 정보를 안내해드립니다.');
        }
        addQuickBtns();
        msgArea.scrollTop = 0;
      }
      setTimeout(() => input.focus(), 300);
    };
    const closeChat = () => {
      overlay.classList.remove('active');
      widget.classList.remove('open');
      fabChat.classList.remove('active');
      if (window.innerWidth <= 600) {
        _closeMobileTimer = setTimeout(() => { _closeMobileTimer = null; resetWidgetPos(); }, 350);
      } else {
        resetWidgetPos();
      }
    };

    fabChat.addEventListener('click', () => widget.classList.contains('open') ? closeChat() : openChat());
    document.getElementById('chatClose').addEventListener('mousedown', e => e.preventDefault());
    document.getElementById('chatClose').addEventListener('click', closeChat);
    overlay.addEventListener('click', closeChat);

    // ── 채팅창 터치 시 뒤 페이지 스크롤 방지 ──
    overlay.addEventListener('touchmove', e => e.preventDefault(), { passive: false });
    widget.addEventListener('touchmove', e => e.stopPropagation(), { passive: true });

    // ── 빠른 답변 버튼 ──
    function addQuickBtns() {
      const wrap = document.createElement('div');
      wrap.className = 'chat-quick-btns';
      ['해상운송', '항공운송', '견적문의'].forEach(label => {
        const btn = document.createElement('button');
        btn.className = 'chat-quick-btn';
        btn.textContent = label;
        btn.addEventListener('mousedown', e => e.preventDefault());
        btn.addEventListener('click', () => { wrap.remove(); send(label); });
        wrap.appendChild(btn);
      });
      msgArea.appendChild(wrap);
      msgArea.scrollTop = msgArea.scrollHeight;
    }

    // ── 메시지 전송 ──
    async function send(preset) {
      const msg = preset || input.value.trim();
      if (!msg || busy) return;
      busy = true;
      if (!preset) { input.value = ''; input.style.height = 'auto'; }
      input.focus();
      sendBtn.disabled = true;
      addMsg('user', msg);
      showTyping();
      await new Promise(r => setTimeout(r, 700 + Math.random() * 600));
      hideTyping();
      addMsg('assistant', getAutoReply(msg));
      busy = false;
      sendBtn.disabled = false;
    }

    // mousedown preventDefault → 버튼 탭 시 input 포커스(키보드) 유지
    sendBtn.addEventListener('mousedown', e => e.preventDefault());
    sendBtn.addEventListener('touchstart', e => e.preventDefault(), { passive: false });
    sendBtn.addEventListener('touchend', (e) => { e.preventDefault(); send(); });
    sendBtn.addEventListener('click', send);

    input.addEventListener('keydown', (e) => {
      if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); send(); }
    });
    input.addEventListener('input', () => {
      input.style.height = 'auto';
      input.style.height = Math.min(input.scrollHeight, 80) + 'px';
    });

  })();

  /* ── LANGUAGE TOGGLE ── */
  (function initLang() {
    const LANGS = {
      ko: {
        'nav.company': '회사소개', 'nav.services': '사업영역',
        'nav.network': '글로벌 네트워크', 'nav.notice': '공지사항',
        'nav.support': '고객센터', 'nav.estimate': '빠른 견적', 'nav.consult': '상담 문의',
        'hero1.h1': '신뢰와 열정으로<br/>세계를 연결합니다',
        'hero1.desc': 'TAEIN TOTAL TRANSPORTATION CO.,LTD<br/>해상·항공 수출입, 통관, 운송의 글로벌 종합물류 기업',
        'hero1.btn': '서비스 알아보기', 'hero.consult': '상담 문의',
        'hero2.h1': '글로벌 물류 네트워크로<br/>세계를 연결합니다',
        'hero2.desc': '해운·항공·육로의 복합운송 서비스로<br/>전 세계 어디든 안전하게 운송합니다.',
        'hero2.btn': '네트워크 보기',
        'hero3.h1': '고객 맞춤<br/>원스톱 물류 서비스',
        'hero3.desc': 'WCA(World Cargo Association) 회원사로서<br/>40여 개국 120여 해외 파트너와 함께합니다',
        'hero3.btn': '더 알아보기',
        'about.title': '(주)태인종합물류를<br/>소개합니다',
        'about.desc': '2010년 설립 이래, 해상·항공 수출입, 통관, 운송을 아우르는 종합 물류 서비스를 제공합니다. WCA 정식 회원사로 40여 개국 120여 해외파트너와 협력하며 고객의 성공적인 비즈니스를 지원합니다.',
        'about.btn': '회사 소개 더보기',
        'stat1.label': '년 설립', 'stat2.label': '개국 네트워크',
        'stat3.label': '해외 파트너', 'stat4.label': '원 화물보험',
        'svc.title': '수출입 기업을 위한<br/>올인원 물류 솔루션',
        'svc.desc': '복잡한 국제 운송, 태인종합물류로<br/>하나로 간편하게 해결하세요',
        'svc.more': '자세히 보기 ↗',
        'svc.card1.title': '다양한 운송 수단', 'svc.card1.desc': '해운 FCL/LCL, 항공, 철도를 통해 전 세계 연결',
        'svc.card2.title': '다양한 화물 타입', 'svc.card2.desc': '일반 화물부터 위험물 및 냉동화물까지 안전한 운송',
        'svc.card3.title': '출도착지 내륙 운송', 'svc.card3.desc': '출발지 픽업 및 최종 도착지까지의 운송 서비스 제공',
        'svc.card4.title': '부가 서비스', 'svc.card4.desc': '통관, 보험, 포장 등 국제 운송에 필요한 모든 서비스',
        'contact.title': '언제든지 문의하세요',
        'contact.desc': '물류 관련 궁금한 사항이나 견적 문의는 전화 또는 온라인으로 남겨주시면 빠르게 연락드리겠습니다.',
        'form.title': '견적 및 상담 문의', 'form.subtitle': '아래 양식을 작성해 주시면 담당자가 빠르게 연락드리겠습니다.',
        'form.name': '이름/회사명 *', 'form.phone': '연락처 *', 'form.email': '이메일 *',
        'form.service': '문의 서비스', 'form.message': '문의 내용 *', 'form.submit': '문의 보내기',
      },
      en: {
        'nav.company': 'About Us', 'nav.services': 'Services',
        'nav.network': 'Global Network', 'nav.notice': 'Notice',
        'nav.support': 'Support', 'nav.estimate': 'Quick Quote', 'nav.consult': 'Contact Us',
        'hero1.h1': 'Connecting the World<br/>with Trust & Passion',
        'hero1.desc': 'TAEIN TOTAL TRANSPORTATION CO.,LTD<br/>Your Global Partner for Sea, Air & Customs',
        'hero1.btn': 'Our Services', 'hero.consult': 'Contact Us',
        'hero2.h1': 'Global Logistics Network<br/>Connecting the World',
        'hero2.desc': 'Multi-modal transport via sea, air & land—<br/>safe delivery anywhere in the world.',
        'hero2.btn': 'View Network',
        'hero3.h1': 'Customer-Tailored<br/>One-Stop Logistics',
        'hero3.desc': 'As a WCA (World Cargo Alliance) member,<br/>partnering with 120+ agents in 40+ countries',
        'hero3.btn': 'Learn More',
        'about.title': 'About TAEIN<br/>Total Logistics',
        'about.desc': 'Since 2010, we have provided comprehensive logistics services covering sea/air import-export, customs clearance, and transportation. As an official WCA member, we collaborate with 120+ partners across 40+ countries to support your business success.',
        'about.btn': 'Learn More',
        'stat1.label': 'Year Founded', 'stat2.label': 'Countries',
        'stat3.label': 'Partners', 'stat4.label': 'Cargo Insurance',
        'svc.title': 'All-in-One Logistics<br/>for Import/Export Companies',
        'svc.desc': 'Simplify complex international shipping<br/>with TAEIN Total Logistics',
        'svc.more': 'Learn More ↗',
        'svc.card1.title': 'Multiple Transport Modes', 'svc.card1.desc': 'Global connectivity via FCL/LCL, air, and rail',
        'svc.card2.title': 'All Cargo Types', 'svc.card2.desc': 'From general freight to hazmat and refrigerated goods',
        'svc.card3.title': 'Inland Transport', 'svc.card3.desc': 'Door-to-door pickup and final delivery services',
        'svc.card4.title': 'Value-Added Services', 'svc.card4.desc': 'Customs, insurance, packaging — everything you need',
        'contact.title': 'Contact Us Anytime',
        'contact.desc': 'For logistics inquiries or quotation requests, contact us by phone or online and we will respond promptly.',
        'form.title': 'Inquiry & Consultation', 'form.subtitle': 'Fill in the form below and our team will get back to you quickly.',
        'form.name': 'Name / Company *', 'form.phone': 'Phone *', 'form.email': 'Email *',
        'form.service': 'Service Type', 'form.message': 'Message *', 'form.submit': 'Send Inquiry',
      }
    };

    const toggleBtn = document.getElementById('langToggle');
    if (!toggleBtn) return;
    let lang = localStorage.getItem('lang') || 'ko';

    function applyLang(l) {
      lang = l;
      localStorage.setItem('lang', l);
      toggleBtn.textContent = l === 'ko' ? 'EN' : 'KO';
      document.querySelectorAll('[data-i18n]').forEach(el => {
        const v = LANGS[l][el.dataset.i18n];
        if (v !== undefined) el.textContent = v;
      });
      document.querySelectorAll('[data-i18n-html]').forEach(el => {
        const v = LANGS[l][el.dataset.i18nHtml];
        if (v !== undefined) el.innerHTML = v;
      });
    }

    toggleBtn.addEventListener('click', () => applyLang(lang === 'ko' ? 'en' : 'ko'));
    if (lang !== 'ko') applyLang(lang);
  })();

});
