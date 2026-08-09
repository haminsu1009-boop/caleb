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

    const routes = [
      [0, 3], [0, 4], [1, 4], [2, 3],
      [8, 5], [6, 3], [0, 6], [7, 3],
      [1, 5], [3, 11],[2, 6], [4, 10],
      [0, 8], [3, 9],
    ];

    const particles = routes.map((r, i) => ({
      route: r,
      t: (i / routes.length),
      speed: 0.0008 + Math.random() * 0.0012,
    }));
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
      const bg = ctx.createLinearGradient(0, 0, W, H);
      bg.addColorStop(0,   '#030c20');
      bg.addColorStop(0.5, '#071833');
      bg.addColorStop(1,   '#030c20');
      ctx.fillStyle = bg;
      ctx.fillRect(0, 0, W, H);

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

      particles.forEach(p => {
        p.t = (p.t + p.speed) % 1;
        const [a, b] = p.route;
        const [ax,ay] = [nodes[a][0]*W, nodes[a][1]*H];
        const [bx,by] = [nodes[b][0]*W, nodes[b][1]*H];
        const [px,py] = bezierPt(ax,ay,bx,by,p.t);
        const alpha = p.t < 0.1 ? p.t/0.1 : p.t > 0.9 ? (1-p.t)/0.1 : 1;
        ctx.fillStyle = `rgba(255,190,60,${0.85*alpha})`;
        ctx.beginPath(); ctx.arc(px,py,2.2,0,Math.PI*2); ctx.fill();
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

  /* ── HEADER: scroll effect (항상 표시, 숨김 없음) ── */
  const header = document.getElementById('header');
  const isHomePage = location.pathname === '/' || location.pathname.endsWith('index.html') || location.pathname === '';
  if (!isHomePage) header.classList.add('scrolled');

  let scrollTicking = false;

  const onScroll = () => {
    if (scrollTicking) return;
    scrollTicking = true;
    requestAnimationFrame(() => {
      const cur = window.scrollY;

      if (isHomePage) {
        header.classList.toggle('scrolled', cur > 60);
      }
      // 서브페이지는 항상 scrolled (흰색) 유지 — 숨기지 않음

      scrollTopBtn.classList.toggle('visible', cur > 400);
      scrollTicking = false;
    });
  };
  window.addEventListener('scroll', onScroll, { passive: true });

  /* ── FADE-IN on scroll (IntersectionObserver) ── */
  (function initFadeIn() {
    const io = new IntersectionObserver((entries) => {
      entries.forEach(e => {
        if (e.isIntersecting) {
          e.target.classList.add('fade-visible');
          io.unobserve(e.target);
        }
      });
    }, { threshold: 0.12 });

    // 자동으로 fade-in 적용할 선택자
    const SEL = [
      '.sub-page-content section',
      '.section-header',
      '.stat-item',
      '.svc-card',
      '.strength-card',
      '.service-type-card',
      '.timeline-item',
      '.info-box',
      '.dir-card',
      '.faq-item',
      '.notice-item',
      '.network-region',
      '.biz-slide',
      '.about-text',
      '.ceo-greeting > *',
      '.philosophy-block',
    ].join(',');

    document.querySelectorAll(SEL).forEach((el, i) => {
      el.classList.add('fade-in');
      el.style.transitionDelay = Math.min(i % 4 * 0.08, 0.24) + 's';
      io.observe(el);
    });
  })();

  /* ── HAMBURGER MENU ── */
  const hamburger  = document.getElementById('hamburger');
  const mobileMenu = document.getElementById('mobileMenu');
  hamburger.addEventListener('click', () => {
    mobileMenu.classList.toggle('open');
  });
  mobileMenu.querySelectorAll('a').forEach(link => {
    link.addEventListener('click', () => mobileMenu.classList.remove('open'));
  });

  mobileMenu.querySelectorAll('.mobile-acc-title').forEach(btn => {
    btn.addEventListener('click', () => {
      const item = btn.closest('.mobile-accordion');
      const isOpen = item.classList.contains('open');
      mobileMenu.querySelectorAll('.mobile-accordion.open').forEach(el => el.classList.remove('open'));
      if (!isOpen) item.classList.add('open');
    });
  });

  /* ── HERO SLIDER ── */
  const slides     = document.querySelectorAll('.slide');
  const slideTexts = document.querySelectorAll('.slide-text');
  const dots       = document.querySelectorAll('.dot');
  let current = 0;

  const goTo = (idx) => {
    slides[current].classList.remove('active');
    if (slideTexts.length) slideTexts[current].classList.remove('active');
    if (dots.length) dots[current].classList.remove('active');
    current = (idx + slides.length) % slides.length;
    slides[current].classList.add('active');
    if (slideTexts.length) slideTexts[current].classList.add('active');
    if (dots.length) dots[current].classList.add('active');
  };

  document.getElementById('slideNext').addEventListener('click', () => goTo(current + 1));
  document.getElementById('slidePrev').addEventListener('click', () => goTo(current - 1));
  dots.forEach(dot => {
    dot.addEventListener('click', () => goTo(Number(dot.dataset.idx)));
  });

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
        const offset = 72;
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
  }, { threshold: 0.08, rootMargin: '0px 0px -5% 0px' });

  fadeEls.forEach(el => fadeObserver.observe(el));

  /* ── STATS COUNTER ANIMATION ── */
  const statNums = document.querySelectorAll('.stat-num-value[data-target]');
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

    function isBizHours() {
      const now = new Date();
      const day = now.getDay();
      const h = now.getHours();
      return day >= 1 && day <= 5 && h >= 9 && h < 18;
    }

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

    document.body.insertAdjacentHTML('beforeend', `
      <div class="chat-overlay" id="chatOverlay"></div>
      <div class="phone-popup" id="phonePopup" aria-hidden="true">
        <button class="phone-popup-close" id="phonePopupClose" aria-label="닫기">✕</button>
        <p class="phone-popup-label">대표전화</p>
        <a href="tel:02-3142-4051" class="phone-popup-number">02-3142-4051</a>
        <p class="phone-popup-sub">📧 op@ttt3.co.kr</p>
        <p class="phone-popup-hours">영업시간: 평일 09:00 ~ 18:00</p>
      </div>
      <div class="fab-group" id="fabGroup">
        <button class="fab-btn fab-phone" id="fabPhone" aria-label="전화 문의">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" width="20" height="20">
            <path d="M22 16.92v3a2 2 0 0 1-2.18 2 19.79 19.79 0 0 1-8.63-3.07A19.5 19.5 0 0 1 4.49 12a19.79 19.79 0 0 1-3.07-8.67A2 2 0 0 1 3.4 1.27h3a2 2 0 0 1 2 1.72 12.84 12.84 0 0 0 .7 2.81 2 2 0 0 1-.45 2.11L7.91 9a16 16 0 0 0 6.29 6.29l1.09-1.76a2 2 0 0 1 2.11-.45 12.84 12.84 0 0 0 2.81.7A2 2 0 0 1 22 15.92z"/>
          </svg>
          <span class="fab-btn-label">전화 문의</span>
        </button>
        <button class="fab-btn fab-chat" id="fabChat" aria-label="실시간 상담">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" width="20" height="20">
            <path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/>
          </svg>
          <span class="fab-btn-label">상담 문의</span>
        </button>
      </div>

      <div class="chat-choice-panel" id="chatChoicePanel" aria-hidden="true">
        <button class="chat-choice-item" id="choiceAI">
          <span class="chat-choice-icon">💬</span>
          <span class="chat-choice-text">
            <strong>AI 상담</strong>
            <small>24시간 자동 응답</small>
          </span>
        </button>
        <div class="chat-choice-divider"></div>
        <a href="https://pf.kakao.com/_taeinlogistics" target="_blank" rel="noopener" class="chat-choice-item" id="choiceKakao">
          <span class="chat-choice-icon chat-choice-kakao-icon">
            <svg viewBox="0 0 24 24" fill="currentColor" width="20" height="20"><path d="M12 2C6.48 2 2 5.86 2 10.6c0 3.04 1.87 5.72 4.72 7.29L5.6 22l5.02-2.64c.45.06.9.09 1.38.09 5.52 0 10-3.86 10-8.6S17.52 2 12 2z"/></svg>
          </span>
          <span class="chat-choice-text">
            <strong>카카오톡 상담</strong>
            <small>전문 상담사 연결</small>
          </span>
        </a>
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

    if (!isBizHours()) {
      onlineText.textContent = '영업시간 외 (AI 상담)';
      statusDot.style.background = '#fbbf24';
      statusDot.style.boxShadow = '0 0 0 3px rgba(251,191,36,0.25)';
      agentBtn.disabled = true;
      agentBtn.innerHTML = `<svg viewBox="0 0 24 24" fill="currentColor" width="14" height="14"><path d="M12 2C6.48 2 2 6.48 2 12s4.48 10 10 10 10-4.48 10-10S17.52 2 12 2zm1 15h-2v-2h2v2zm0-4h-2V7h2v6z"/></svg> 영업시간 외 — 상담사 연결 불가`;
    }

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
      widget.classList.add('kb-open');
      fabGroup.style.opacity = '0';
      fabGroup.style.pointerEvents = 'none';
    }

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

    const choicePanel = document.getElementById('chatChoicePanel');
    const phonePopup  = document.getElementById('phonePopup');
    const openChoice = () => {
      choicePanel.classList.add('open');
      fabChat.classList.add('active');
    };
    const closeChoice = () => {
      choicePanel.classList.remove('open');
      if (!widget.classList.contains('open')) fabChat.classList.remove('active');
    };

    document.getElementById('fabPhone').addEventListener('click', () => {
      const wasOpen = phonePopup.classList.contains('open');
      if (!wasOpen && choicePanel.classList.contains('open')) closeChoice();
      if (!wasOpen && widget.classList.contains('open')) closeChat();
      phonePopup.classList.toggle('open', !wasOpen);
      overlay.classList.toggle('active', !wasOpen);
    });
    document.getElementById('phonePopupClose').addEventListener('mousedown', e => e.preventDefault());
    document.getElementById('phonePopupClose').addEventListener('click', () => {
      phonePopup.classList.remove('open');
      overlay.classList.remove('active');
    });

    fabChat.addEventListener('click', () => {
      if (widget.classList.contains('open')) { closeChat(); return; }
      if (choicePanel.classList.contains('open')) { closeChoice(); return; }
      openChoice();
    });

    document.getElementById('choiceAI').addEventListener('click', () => {
      closeChoice();
      openChat();
    });

    overlay.addEventListener('click', () => { closeChat(); closeChoice(); phonePopup.classList.remove('open'); });

    document.getElementById('chatClose').addEventListener('mousedown', e => e.preventDefault());
    document.getElementById('chatClose').addEventListener('click', closeChat);

    overlay.addEventListener('touchmove', e => e.preventDefault(), { passive: false });
    widget.addEventListener('touchmove', e => e.stopPropagation(), { passive: true });

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

  /* ── BUSINESS SLIDER ── */
  (function initBizSlider() {
    const slider = document.getElementById('bizSlider');
    const bar    = document.getElementById('bizProgressBar');
    if (!slider || !bar) return;
    slider.addEventListener('scroll', () => {
      const max = slider.scrollWidth - slider.clientWidth;
      if (max <= 0) return;
      bar.style.width = (25 + (slider.scrollLeft / max) * 75) + '%';
    }, { passive: true });
    let isDown = false, startX, scrollLeft;
    slider.addEventListener('mousedown', e => {
      isDown = true; slider.classList.add('grabbing');
      startX = e.pageX - slider.offsetLeft; scrollLeft = slider.scrollLeft;
    });
    ['mouseleave','mouseup'].forEach(ev => slider.addEventListener(ev, () => {
      isDown = false; slider.classList.remove('grabbing');
    }));
    slider.addEventListener('mousemove', e => {
      if (!isDown) return;
      e.preventDefault();
      slider.scrollLeft = scrollLeft - (e.pageX - slider.offsetLeft - startX);
    });
  })();

  /* ── LANGUAGE TOGGLE ── */
  (function initLang() {
    const LANGS = {
      ko: {
        /* ── 내비게이션 ── */
        'nav.company':'회사소개','nav.services':'사업영역','nav.network':'글로벌 네트워크',
        'nav.notice':'공지사항','nav.support':'고객센터','nav.estimate':'빠른 견적','nav.consult':'상담 문의',
        /* ── 히어로 ── */
        'hero1.h1':'신뢰와 열정으로<br/>세계를 연결합니다',
        'hero1.desc':'TAEIN TOTAL TRANSPORTATION CO.,LTD<br/>해상·항공 수출입, 통관, 운송의 글로벌 종합물류 기업',
        'hero1.btn':'서비스 알아보기','hero.consult':'상담 문의',
        'hero2.h1':'글로벌 물류 네트워크로<br/>세계를 연결합니다',
        'hero2.desc':'해운·항공·육로의 복합운송 서비스로<br/>전 세계 어디든 안전하게 운송합니다.',
        'hero2.btn':'네트워크 보기',
        'hero3.h1':'고객 맞춤<br/>원스톱 물류 서비스',
        'hero3.desc':'WCA(World Cargo Association) 회원사로서<br/>40여 개국 120여 해외 파트너와 함께합니다',
        'hero3.btn':'더 알아보기',
        /* ── 회사소개 (인덱스) ── */
        'about.title':'(주)태인종합물류를<br/>소개합니다',
        'about.desc':'2010년 설립 이래, 해상·항공 수출입, 통관, 운송을 아우르는 종합 물류 서비스를 제공합니다. WCA 정식 회원사로 40여 개국 120여 해외파트너와 협력하며 고객의 성공적인 비즈니스를 지원합니다.',
        'about.btn':'회사 소개 더보기',
        'stat1.label':'년 설립','stat2.label':'개국 네트워크','stat3.label':'해외 파트너','stat4.label':'원 화물보험',
        /* ── 서비스 (인덱스) ── */
        'svc.title':'수출입 기업을 위한<br/>올인원 물류 솔루션',
        'svc.desc':'복잡한 국제 운송, 태인종합물류로<br/>하나로 간편하게 해결하세요','svc.more':'자세히 보기 ↗',
        'svc.card1.title':'다양한 운송 수단','svc.card1.desc':'해운 FCL/LCL, 항공, 철도를 통해 전 세계 연결',
        'svc.card2.title':'다양한 화물 타입','svc.card2.desc':'일반 화물부터 위험물 및 냉동화물까지 안전한 운송',
        'svc.card3.title':'출도착지 내륙 운송','svc.card3.desc':'출발지 픽업 및 최종 도착지까지의 운송 서비스 제공',
        'svc.card4.title':'부가 서비스','svc.card4.desc':'통관, 보험, 포장 등 국제 운송에 필요한 모든 서비스',
        /* ── 문의 (인덱스) ── */
        'contact.title':'언제든지 문의하세요',
        'contact.desc':'물류 관련 궁금한 사항이나 견적 문의는 전화 또는 온라인으로 남겨주시면 빠르게 연락드리겠습니다.',
        'form.title':'견적 및 상담 문의','form.subtitle':'아래 양식을 작성해 주시면 담당자가 빠르게 연락드리겠습니다.',
        'form.name':'이름/회사명 *','form.phone':'연락처 *','form.email':'이메일 *',
        'form.service':'문의 서비스','form.message':'문의 내용 *','form.submit':'문의 보내기',
        'estimate.title':'빠른 견적 문의','estimate.desc':'출발지·도착지·화물 정보를 입력하시면 담당자가 빠르게 안내해 드립니다.',
        /* ── 페이지 헤더 레이블 ── */
        'page.ceo.label':'CEO GREETING','page.ceo.h1':'대표 인사말',
        'page.phil.label':'MANAGEMENT PHILOSOPHY','page.phil.h1':'경영이념',
        'page.hist.label':'COMPANY HISTORY','page.hist.h1':'연혁',
        'page.dir.label':'DIRECTIONS','page.dir.h1':'오시는길',
        'page.svc.label':'SERVICES','page.svc.h1':'국제 물류 서비스',
        'page.sea.label':'OCEAN FREIGHT','page.sea.h1':'해상운송',
        'page.air.label':'AIR FREIGHT','page.air.h1':'항공운송',
        'page.land.label':'LAND TRANSPORT','page.land.h1':'육상운송',
        'page.customs.label':'CUSTOMS & FORWARDING','page.customs.h1':'통관 및 포워딩',
        'page.sol.label':'LOGISTICS SOLUTIONS','page.sol.h1':'물류 솔루션',
        'page.net.label':'GLOBAL NETWORK','page.net.h1':'글로벌 네트워크',
        'page.notice.label':'NOTICE','page.notice.h1':'공지사항',
        'page.faq.label':'FAQ','page.faq.h1':'자주 묻는 질문',
        'page.cs.label':'CUSTOMER SERVICE','page.cs.h1':'고객센터',
        /* ── 브레드크럼 ── */
        'breadcrumb.home':'홈','breadcrumb.services':'사업영역','breadcrumb.sea':'해상운송','breadcrumb.air':'항공운송',
        /* ── CEO ── */
        'ceo.section.title':'대표 인사말',
        'ceo.msg.p1':'안녕하십니까.<br/>(주)태인종합물류 대표이사 <strong>하형탁</strong>입니다.',
        'ceo.msg.p2':'저희 태인종합물류를 방문해 주신 고객 여러분께 진심으로 감사드립니다.',
        'ceo.msg.p3':'(주)태인종합물류는 2010년 5월 설립 이래, 해상·항공 수출입, 통관, 내륙 운송에 이르는 종합 물류 서비스를 제공하며 고객 여러분과 함께 성장해 왔습니다. 설립 이래 축적된 현장 경험과 국내외 파트너 네트워크를 바탕으로 최적의 물류 솔루션을 제공하기 위해 끊임없이 노력하고 있습니다.',
        'ceo.msg.p4':'오늘날 글로벌 물류 환경은 빠르게 변화하고 있습니다. 공급망 불안정, 운임 변동, 규제 강화 등 다양한 도전 속에서도 저희 태인종합물류는 전문성과 열정을 바탕으로 고객의 화물을 안전하고 신속하게 목적지까지 운송하는 데 최선을 다하고 있습니다.',
        'ceo.msg.p5':'<strong>「고객의 만족은 태인의 보람입니다」</strong><br/>이 한 문장이 저희 모든 임직원의 마음속에 새겨진 경영 철학입니다. 고객 한 분 한 분의 요구에 귀 기울이고, 최적의 물류 솔루션으로 응답하겠습니다.',
        'ceo.msg.p6':'앞으로도 변함없는 신뢰와 성원을 부탁드리며, 태인종합물류는 고객 여러분의 성공적인 비즈니스를 위한 가장 믿을 수 있는 물류 파트너가 되겠습니다.',
        'ceo.msg.p7':'감사합니다.',
        'ceo.sig.company':'(주)태인종합물류','ceo.sig.name':'<strong>하형탁</strong> &nbsp;대표이사','ceo.btn.estimate':'견적 문의하기',
        /* ── 경영이념 ── */
        'phil.vision.quote':'"고객의 만족은 태인의 보람입니다"',
        'phil.vision.desc':'태인종합물류는 고객과의 신뢰를 최우선 가치로 삼고, 물류 산업의 변화 속에서도 흔들리지 않는 전문성과 열정으로 최고의 서비스를 제공합니다.',
        'phil.vision.cite':'— (주)태인종합물류 경영방침',
        'phil.values.title':'태인의 핵심 역량','phil.values.sub':'숫자로 증명하는 태인종합물류의 신뢰와 전문성',
        'phil.val1.label':'정식 회원사','phil.val1.desc':'세계화물협회(WCA) 정식 회원사로서 글로벌 표준의 물류 서비스와 광범위한 국제 파트너 네트워크를 제공합니다.',
        'phil.val2.label':'화물배상 책임보험','phil.val2.desc':'10억원 규모의 화물배상 책임보험 가입으로 고객의 화물을 책임감 있게 보호하며 만일의 사고에도 철저히 대비합니다.',
        'phil.val3.label':'물류 전문기업','phil.val3.desc':'2010년 설립 이래 16년 이상의 물류 전문 경험과 현장 노하우로 다양한 산업군의 물류 니즈에 최적의 솔루션을 제공합니다.',
        'phil.val4.label':'파트너 네트워크','phil.val4.desc':'아시아, 유럽, 미주, 중동, 아프리카 등 40여 개국 120개 이상의 해외 파트너와 긴밀한 협력 네트워크를 구축하고 있습니다.',
        'phil.cards.title':'핵심 경영이념','phil.cards.sub':'태인종합물류가 추구하는 네 가지 핵심 가치가 고객 만족을 이끕니다.',
        'phil.card1.title':'신뢰','phil.card1.desc':'실력을 기반으로 고객과 신뢰를 구축하며, 고객과 회사의 존재가치가 분명히 설명되는 회사를 지향합니다.',
        'phil.card2.title':'성장','phil.card2.desc':'끊임없이 변화하는 물류 문화를 읽고, 늘 최고의 서비스를 제공하기 위해 성장하는 회사입니다.',
        'phil.card3.title':'열정','phil.card3.desc':'고객의 발전이 곧 우리의 발전임을 상기하고, 가장 효율적인 서비스를 찾아 제공하는 회사입니다.',
        'phil.card4.title':'원스톱 서비스','phil.card4.desc':'업체별 전담 영업사원 배정, 다양한 노하우의 프로정신, 국내외 네트워크망을 통한 최고의 솔루션을 한 번에 제공합니다.',
        'phil.stat.quote':'신뢰 · 성장 · 열정<br/>세 가지 가치로<br/>고객과 함께 성장합니다.',
        'phil.stat.founded':'설립 연도','phil.stat.partners':'해외 파트너사','phil.stat.capital':'창립 자본금','phil.stat.clients':'주요 거래처',
        'phil.mission.title':'태인과 함께하면 다릅니다',
        'phil.mission.desc':'태인종합물류는 단순한 운송 대행사가 아닙니다. 고객의 사업 파트너로서 물류의 시작부터 끝까지 함께합니다.',
        'phil.mission.li1':'고객 맞춤형 물류 솔루션 설계 및 제공','phil.mission.li2':'전담 영업사원을 통한 1:1 밀착 관리 서비스',
        'phil.mission.li3':'실시간 화물 현황 추적 및 신속한 보고','phil.mission.li4':'신속하고 정확한 통관 처리',
        'phil.mission.li5':'합리적이고 투명한 운임 구조','phil.mission.li6':'긴급 화물 대응 24시간 지원 체계',
        'phil.mission.btn':'견적 문의하기',
        'phil.cta.title':'태인과 함께 더 넓은 세계로','phil.cta.desc':'16년의 전문성과 40개국 글로벌 네트워크로 고객의 물류 파트너가 되겠습니다.',
        'phil.cta.btn1':'견적 문의하기','phil.cta.btn2':'연혁 보기',
        /* ── 연혁 ── */
        'hist.section.title':'태인의 발자취','hist.section.sub':'2010년 창립 이래, 신뢰와 혁신으로 대한민국 대표 종합물류 기업을 향해 나아갑니다.',
        'hist.tag.founding':'창립','hist.tag.present':'진행 중',
        'hist.stat1.label':'물류 전문 역사','hist.stat1.unit':'년+','hist.stat2.label':'글로벌 파트너십','hist.stat2.unit':'개국+',
        'hist.stat3.label':'해외 파트너','hist.stat3.unit':'개사+','hist.stat4.label':'주요 거래처','hist.stat4.unit':'개사+',
        'hist.founding.title':'(주)태인종합물류 설립',
        'hist.founding.li1':'(주)태인종합물류 법인 설립','hist.founding.li2':'자본금 3억원으로 출발',
        'hist.founding.li3':'서울 마포구 본사 개설','hist.founding.li4':'물류 전문 인력 채용 및 조직 구성',
        'hist.year6.title':'사업 본격 개시 및 WCA 글로벌 회원 가입',
        'hist.year6.li1':'해상·항공 수출입 포워딩 사업 본격 개시','hist.year6.li2':'WCA(World Cargo Association) 정식 회원사 가입',
        'hist.year6.li3':'인천공항 항공 화물 취급 서비스 시작','hist.year6.li4':'주요 해운사 대리점 계약 체결','hist.year6.li5':'국내 육상운송 네트워크 구축',
        'hist.year5.title':'글로벌 네트워크 본격 확장',
        'hist.year5.li1':'아시아, 유럽, 미주 글로벌 네트워크 본격 확장','hist.year5.li2':'해외 파트너 50개사 돌파',
        'hist.year5.li3':'중국, 일본, 동남아 핵심 노선 서비스 강화','hist.year5.li4':'FCL/LCL 해상운송 서비스 다변화','hist.year5.li5':'고객 맞춤형 물류 컨설팅 서비스 론칭',
        'hist.year4.title':'부산 지사 개설 및 통관 전문 서비스 강화',
        'hist.year4.li1':'부산 지사 개설 — 전국 물류 서비스 체계 확립','hist.year4.li2':'관세사 협력 통관 전문 서비스 강화',
        'hist.year4.li3':'해외 파트너 100개사 돌파 (아시아·유럽·미주)','hist.year4.li4':'항만 물류 특화 서비스 개시 (부산항, 인천항)','hist.year4.li5':'대기업 전속 물류 대행 계약 체결',
        'hist.year3.title':'화물 보험 강화 및 물류 솔루션 사업 확장',
        'hist.year3.li1':'화물배상 책임보험 10억원 가입 — 고객 화물 안전 강화','hist.year3.li2':'3PL(제3자 물류) 및 SCM 컨설팅 사업 본격 확장',
        'hist.year3.li3':'코로나19 대응 긴급 항공 화물 서비스 운영','hist.year3.li4':'비대면 온라인 견적 시스템 도입','hist.year3.li5':'주요 거래처 200개사 돌파',
        'hist.year2.title':'스마트 물류 시스템 도입 및 인증 획득',
        'hist.year2.li1':'스마트 물류 시스템(TMS/WMS) 도입으로 운영 효율화','hist.year2.li2':'ISO 9001:2015 품질경영시스템 인증 획득',
        'hist.year2.li3':'글로벌 파트너 40개국 120개사 돌파','hist.year2.li4':'AI 기반 화물 추적 시스템 개발 및 서비스 개시','hist.year2.li5':'물류 빅데이터 분석 인프라 구축',
        'hist.year1.title':'지속 성장 — 글로벌 물류 전문기업으로 도약','hist.year1.badge':'2025 ~ 현재',
        'hist.year1.li1':'글로벌 물류 전문기업으로의 지속적 도약 추진','hist.year1.li2':'스마트 물류 플랫폼 고도화 및 디지털 전환 가속화',
        'hist.year1.li3':'친환경 그린 물류 솔루션 개발 착수','hist.year1.li4':'신규 해외 파트너십 확대 (동남아, 중동 중심)','hist.year1.li5':'ESG 경영 체계 도입 및 지속가능성 보고서 발간',
        'hist.cta.title':'태인의 16년 전문성을 경험해보세요','hist.cta.desc':'축적된 노하우와 글로벌 네트워크로 최적의 물류 솔루션을 제공합니다.',
        'hist.cta.btn1':'견적 문의하기','hist.cta.btn2':'경영이념 보기',
        /* ── 오시는길 ── */
        'dir.section.title':'사무소 안내','dir.section.sub':'서울 본사와 부산 지사에서 전국 물류 서비스를 제공하고 있습니다.',
        'dir.hq.badge':'본사 HQ','dir.hq.name':'서울 본사',
        'dir.label.tel':'대표전화','dir.label.fax':'팩스','dir.label.email':'이메일','dir.label.address':'주소','dir.label.hours':'업무시간',
        'dir.hq.hours':'평일 09:00 ~ 18:00 &nbsp;<span class="closed">토·일·공휴일 휴무</span>',
        'dir.map.naver':'네이버지도로 보기','dir.map.kakao':'카카오맵으로 보기',
        'dir.transport.hq.title':'교통안내 (서울 본사)','dir.transport.subway':'지하철 이용 시','dir.transport.bus':'버스 이용 시','dir.transport.car':'자가용 이용 시',
        'dir.hq.subway.li1':'<span class="line-badge line2">2호선</span> 합정역 7번 출구 — 도보 5분','dir.hq.subway.li2':'<span class="line-badge line6">6호선</span> 합정역 3번 출구 — 도보 5분','dir.hq.subway.li3':'<span class="line-badge line6">6호선</span> 망원역 2번 출구 — 도보 10분',
        'dir.hq.bus.li1':'<span class="bus-badge bus-blue">간선버스</span> 271, 571, 672','dir.hq.bus.li2':'<span class="bus-badge bus-green">지선버스</span> 7713, 7726','dir.hq.bus.li3':'<span class="bus-badge bus-red">광역버스</span> 9701',
        'dir.hq.car.li1':'내부순환로 마포IC 방면 → 월드컵로 방향 우회전 후 직진','dir.hq.car.li2':'강변북로 합정IC 방면 → 월드컵로 직진 약 5분','dir.hq.car.li3':'건물 내 주차 가능 (유료, 방문 시 주차권 제공)',
        'dir.branch.badge':'지사 Branch','dir.branch.name':'부산 지사',
        'dir.branch.hours':'평일 09:00 ~ 18:00 &nbsp;<span class="closed">토·일·공휴일 휴무</span>',
        'dir.transport.branch.title':'교통안내 (부산 지사)',
        'dir.branch.subway.li1':'<span class="line-badge line1">1호선</span> 중앙역 8번 출구 — 도보 5분','dir.branch.subway.li2':'<span class="line-badge line1">1호선</span> 부산역 6번 출구 — 도보 10분',
        'dir.branch.bus.li1':'<span class="bus-badge bus-blue">일반버스</span> 81, 85, 88, 190','dir.branch.bus.li2':'<span class="bus-badge bus-green">마을버스</span> 중구-1, 중구-2',
        'dir.branch.car.li1':'충장대로 방향 진입 → 코리아빌딩 표지판 확인 후 좌회전','dir.branch.car.li2':'부산항 국제여객터미널에서 차량으로 약 5분','dir.branch.car.li3':'인근 공영주차장 또는 건물 주차장 이용 가능',
        'dir.cta.title':'방문 전 사전 문의를 권장합니다','dir.cta.desc':'원활한 상담을 위해 방문 전 전화 또는 이메일로 사전 예약을 해 주시면 담당자가 준비하여 맞이하겠습니다.',
        'dir.cta.btn1':'본사 전화하기','dir.cta.btn2':'온라인 견적 문의',
        /* ── 사업영역 페이지 ── */
        'svc.section.title':'국제 물류 서비스','svc.section.sub':'태인종합물류는 해운부터 항공, 내륙 운송까지 전방위 물류 서비스로<br/>고객의 화물을 전 세계 어디든 안전하게 연결합니다.',
        'svc.fcl.title':'해상 FCL','svc.fcl.desc':'전 세계 주요 항구를 연결하는 컨테이너 단위의 해상 운송 서비스입니다.',
        'svc.fcl.li1':'20GP / 40GP / 40HC / FR / OT / RF 등 다양한 컨테이너 제공','svc.fcl.li2':'전세계 주요 항구 커버 — 아시아, 유럽, 미주, 중동, 아프리카','svc.fcl.li3':'출항 전 선적 서류 (B/L, 포킹 리스트, Invoice) 검토 지원','svc.fcl.li4':'위험물(DG Cargo) 및 냉동화물(RF) 전문 처리',
        'svc.lcl.title':'해상 LCL','svc.lcl.desc':'소량 화물도 경쟁력 있는 가격과 전문 관리로 이용하세요.',
        'svc.lcl.li1':'소량·소화물 전용 혼재 서비스 (CFS → CFS / CFS → CY)','svc.lcl.li2':'주간 정기 선적 스케줄로 빠른 리드타임 확보','svc.lcl.li3':'창고 보관 및 픽업·배달 서비스 연계',
        'svc.tag.sea':'해상운송','svc.air.title':'항공','svc.air.desc':'긴급 화물 및 고가 화물 운송에 최적화된 서비스입니다.',
        'svc.air.li1':'일반항공(Commercial Air) · 전세기(Charter) · 특급화물(Express) 모두 가능','svc.air.li2':'위험물(IATA 규정 준수), 의약품, 생동물, 냉동화물 등 특수화물 처리','svc.air.li3':'Door-to-Door 픽업·배달 서비스 연계','svc.air.li4':'인천, 김포, 김해 공항 출발 전 세계 주요 공항 연결',
        'svc.tag.air':'항공운송','svc.land.title':'출도착지 내륙 운송','svc.land.desc':'출발지 픽업부터 최종 목적지까지 일괄 운송합니다.',
        'svc.land.li1':'전국 배송망 — 서울·경기·인천·부산·대구·광주 외 전국','svc.land.li2':'일반화물 / 대형화물 / 냉동냉장 / 위험물 운송 가능','svc.land.li3':'항만·공항 → 공장·물류센터 Door-to-Door 운송','svc.land.li4':'컨테이너 내륙 운송 (ICD 연계)',
        'svc.tag.land':'육상운송','svc.addon.title':'부가서비스','svc.addon.sub':'통관, 보험, 포장 등 국제 운송에 필요한 모든 서비스를 선택하실 수 있습니다.',
        'svc.addon1.title':'수출통관 서비스','svc.addon1.desc':'수출입 통관 서류 작성 및 세관 신고 대행',
        'svc.addon2.title':'낙화 서비스','svc.addon2.desc':'화물 도착 후 수입 통관 및 배달까지 일괄 처리',
        'svc.addon3.title':'공컨테이너 지입 서비스','svc.addon3.desc':'공컨테이너 수급 및 내륙 운송 연계',
        'svc.addon4.title':'도착지 배달 서비스','svc.addon4.desc':'현지 파트너를 통한 최종 목적지까지 Door-to-Door',
        'svc.addon5.title':'포장 서비스','svc.addon5.desc':'화물 특성에 맞는 전문 포장 및 라벨링 서비스',
        'svc.addon6.title':'CFS 서비스','svc.addon6.desc':'컨테이너 화물 집배 및 분류 창고 서비스',
        'svc.addon7.title':'ISF 신고 서비스','svc.addon7.desc':'미국 수출 화물 ISF(10+2) 신고 대행',
        'svc.addon8.title':'화물 보험','svc.addon8.desc':'10억원 화물배상 책임보험 — 만일의 사고에도 안심',
        'svc.link.detail':'자세히 보기 →','svc.link.more':'자세히 →','svc.link.inquire':'문의하기 →','svc.desc2':'해상·항공·육상·통관·물류솔루션까지 원스톱으로 제공합니다',
        'svc.cta.title':'최적의 물류 솔루션을 찾고 계신가요?','svc.cta.desc':'전담 상담원이 귀사의 화물 특성에 맞는 최적 운송 방법과 운임을 빠르게 안내해드립니다.','svc.cta.btn1':'온라인 견적 문의',
        /* ── 해상운송 ── */
        'sea.overview.title':'해상운송 서비스 소개','sea.overview.desc':'태인종합물류는 FCL(Full Container Load)과 LCL(Less than Container Load) 서비스를 모두 제공합니다.',
        'sea.types.title':'서비스 유형','sea.fcl.desc':'전용 컨테이너를 활용한 대량화물 운송 서비스입니다.',
        'sea.fcl.li1':'20ft / 40ft / 40ft HC 컨테이너','sea.fcl.li2':'단독 컨테이너 사용으로 보안성 강화','sea.fcl.li3':'대량화물 비용 효율 최적화',
        'sea.lcl.desc':'소량화물에 최적화된 합적(혼재) 서비스입니다.',
        'sea.lcl.li1':'소량화물 경제적 운임 제공','sea.lcl.li2':'정기적인 혼재 스케줄 운영','sea.lcl.li3':'안전한 화물 관리 및 포장',
        'sea.special.title':'특수화물 운송','sea.special.desc':'위험물, 냉동화물, 초대형·중량화물 등 특수 취급이 필요한 화물 전문 해상운송 서비스입니다.',
        'sea.special.li1':'IMDG Code 준수 위험물 운송','sea.special.li2':'리퍼 컨테이너를 이용한 냉동·냉장 화물','sea.special.li3':'FR(Flat Rack)·OT(Open Top) 활용 초대형·중량화물',
        'sea.features.title':'서비스 특징','sea.feat1.title':'글로벌 해운사 네트워크','sea.feat1.desc':'세계 주요 선사들과의 긴밀한 파트너십을 통해 안정적인 선복 확보와 경쟁력 있는 운임을 제공합니다.',
        'sea.feat2.title':'실시간 화물 추적 시스템','sea.feat2.desc':'선적부터 도착까지 화물의 위치와 상태를 실시간으로 추적할 수 있습니다.',
        'sea.feat3.title':'원스톱 통관 연계 서비스','sea.feat3.desc':'해상운송과 통관 업무를 연계한 원스톱 서비스로 절차를 간소화합니다.',
        'sea.feat4.title':'경쟁력 있는 운임 제안','sea.feat4.desc':'항로별·화물 특성별 맞춤형 운임 분석을 통해 최저가 운임을 제안합니다.',
        'sea.cta.title':'해상운송 서비스가 필요하신가요?','sea.cta.desc':'전문 물류 컨설턴트가 최적의 해상운송 솔루션을 제안해 드립니다.<br/>지금 바로 문의하시면 맞춤형 견적을 신속하게 받아보실 수 있습니다.','sea.cta.btn':'해상운송 견적 문의하기',
        /* ── 항공운송 ── */
        'air.cta.title':'항공운송 서비스가 필요하신가요?','air.cta.desc':'긴급화물부터 특수화물까지 전문 항공 물류 컨설턴트가 최적의 솔루션을 제안합니다.<br/>지금 바로 문의하시면 신속하게 맞춤형 견적을 받아보실 수 있습니다.','air.cta.btn':'항공운송 견적 문의하기',
        /* ── 육상운송 ── */
        'land.overview.title':'육상운송 서비스 소개','land.overview.desc':'태인종합물류는 전국 광역 네트워크를 활용한 육상 운송 서비스를 제공합니다.',
        'land.types.title':'서비스 유형','land.type1.name':'일반화물 운송','land.type1.desc':'전국 당일·익일 배송이 가능한 일반화물 운송 서비스입니다.',
        'land.type1.li1':'1톤 ~ 25톤 다양한 차종 보유','land.type1.li2':'전국 당일·익일 배송 서비스','land.type1.li3':'온도 관리 냉동·냉장 차량 운영',
        'land.type2.name':'대형·중량물 운송','land.type2.desc':'일반 운송으로 불가능한 초대형 중량물 전문 운송 서비스입니다.',
        'land.type2.li1':'로우베드·트레일러 특수차량 운영','land.type2.li2':'중량물 운송 허가 취득 대행','land.type2.li3':'산업 기계류·플랜트 장비 전문',
        'land.type3.name':'항만·공항 연계 운송','land.type3.desc':'항만 및 공항과 연계한 픽업·배송 서비스입니다.',
        'land.type3.li1':'부두 직통 컨테이너 픽업·반납','land.type3.li2':'공항 화물 터미널 연계 딜리버리','land.type3.li3':'통관 완료 화물 즉시 배송 서비스',
        'land.features.title':'서비스 특징','land.feat1.name':'전국 차량 네트워크','land.feat1.desc':'전국 주요 거점에 차량 및 협력사 네트워크를 구축하고 있습니다.',
        'land.feat2.name':'GPS 실시간 화물 추적','land.feat2.desc':'모든 운송 차량에 GPS를 장착하여 화물 위치를 실시간으로 추적합니다.',
        'land.feat3.name':'항만·공항 연계 원스톱 운송','land.feat3.desc':'해상·항공 운송과 연계한 원스톱 운송 서비스를 제공합니다.',
        'land.feat4.name':'전용 차량 계약 서비스','land.feat4.desc':'정기적인 물류 수요가 있는 기업을 위해 전용 차량 계약 서비스를 제공합니다.',
        'land.area.title':'전국 서비스 권역','land.area.desc':'태인종합물류는 대한민국 전역을 커버하는 광역 운송 네트워크를 운영합니다.',
        'land.area.tag1':'🏙️ 서울·경기 (수도권 당일 배송)','land.area.tag2':'⚓ 인천 (인천항·인천공항 연계)',
        'land.area.tag3':'🚢 부산·경남 (부산항 연계 특화)','land.area.tag4':'🌊 광주·전라 (서해안 물류 거점)',
        'land.area.tag5':'🏔️ 대구·경북 (내륙 산업단지 연계)','land.area.tag6':'🌿 대전·충청 (중부권 허브)',
        'land.area.tag7':'🏝️ 제주 (제주도 특수 운송)','land.area.tag8':'🚀 전국 익일 배송 서비스',
        'land.cta.title':'육상운송 서비스가 필요하신가요?','land.cta.desc':'전국 어디든 신속하고 안전하게 화물을 운반해 드립니다.<br/>지금 문의하시면 전담 담당자가 최적의 운송 방법을 안내해 드립니다.','land.cta.btn':'육상운송 견적 문의하기',
        /* ── 통관 ── */
        'customs.overview.title':'통관 및 포워딩 서비스 소개','customs.overview.desc':'복잡하고 까다로운 수출입 통관 절차를 태인종합물류가 원스톱으로 처리합니다.',
        'customs.overview.box':'수출입 통관은 잘못된 HS 코드 분류, 서류 누락, 규정 미준수 등으로 인해 화물이 세관에서 지연되거나 추가 비용이 발생할 수 있습니다.',
        'customs.types.title':'서비스 유형','customs.type1.name':'수출통관','customs.type1.desc':'수출 화물의 세관 신고부터 수출 허가까지 전 과정을 대행합니다.',
        'customs.type1.li1':'HS 코드 정확 분류 및 검토','customs.type1.li2':'수출신고서 작성 및 제출 대행','customs.type1.li3':'원산지 증명서 발급 지원','customs.type1.li4':'전략물자 수출 허가 대행',
        'customs.type2.name':'수입통관','customs.type2.desc':'수입 화물의 입항부터 보세창고 반입·반출, 수입신고, 관세 납부, 통관 완료까지 신속하게 처리합니다.',
        'customs.type2.li1':'FTA 협정세율 적용 관세 절감','customs.type2.li2':'세관 검사·검역 대응 지원','customs.type2.li3':'수입요건 확인 및 허가 취득 대행','customs.type2.li4':'신속 통관으로 보세료 절감',
        'customs.type3.name':'국제 포워딩','customs.type3.desc':'해상·항공·육상을 복합 활용한 국제 포워딩 서비스를 제공합니다.',
        'customs.type3.li1':'복합운송 경로 최적화 기획','customs.type3.li2':'선박·항공기 스페이스 확보 및 예약','customs.type3.li3':'B/L·AWB 등 운송 서류 발행','customs.type3.li4':'목적지 현지 파트너 연계 배송',
        'customs.process.title':'통관 처리 프로세스','customs.process.desc':'태인종합물류의 체계적인 6단계 통관 프로세스로 신속하고 정확한 통관을 실현합니다.',
        'customs.step1.label':'화물 접수','customs.step1.desc':'운송 의뢰 및<br/>화물 정보 확인',
        'customs.step2.label':'서류 검토','customs.step2.desc':'인보이스·P/L<br/>HS 코드 분류',
        'customs.step3.label':'통관 신고','customs.step3.desc':'세관 전산 신고<br/>서류 제출',
        'customs.step4.label':'세관 심사','customs.step4.desc':'서류 심사 및<br/>검사 대응',
        'customs.step5.label':'통관 완료','customs.step5.desc':'관세 납부 및<br/>수리 확인',
        'customs.step6.label':'배송','customs.step6.desc':'화물 출고 및<br/>목적지 배송',
        'customs.features.title':'서비스 특징','customs.feat1.name':'전문 관세사 협력 네트워크','customs.feat1.desc':'다년간의 현장 경험을 보유한 전문 관세사들과 긴밀히 협력합니다.',
        'customs.feat2.name':'빠른 통관 처리 및 즉시 대응','customs.feat2.desc':'전산 신고 시스템과 세관과의 긴밀한 커뮤니케이션을 통해 신속한 통관을 실현합니다.',
        'customs.feat3.name':'세금 최적화 컨설팅','customs.feat3.desc':'FTA 협정세율 적용, 관세 분류 최적화 등 합법적인 방법으로 관세 부담을 최소화합니다.',
        'customs.feat4.name':'수출입 서류 일괄 대행','customs.feat4.desc':'인보이스, 패킹 리스트, B/L, AWB, 원산지 증명서 등 수출입에 필요한 모든 서류를 일괄 처리합니다.',
        'customs.cta.title':'통관·포워딩 문의가 있으신가요?','customs.cta.desc':'복잡한 수출입 절차를 태인종합물류가 원스톱으로 해결해 드립니다.<br/>전문 담당자에게 지금 바로 문의하시면 최적의 통관 방법을 안내해 드립니다.','customs.cta.btn':'통관 문의하기',
        /* ── 물류솔루션 ── */
        'sol.overview.title':'물류 솔루션 서비스 소개','sol.overview.desc':'태인종합물류는 기업 맞춤형 3PL·4PL 물류 아웃소싱 서비스를 제공합니다.',
        'sol.overview.box':'물류는 기업 경쟁력의 핵심 요소입니다. 그러나 자체 물류 인프라를 구축하고 운영하려면 막대한 초기 투자와 지속적인 운영 비용이 발생합니다.',
        'sol.types.title':'서비스 유형','sol.type1.name':'3PL 아웃소싱','sol.type1.desc':'운송, 보관, 유통 등 물류 전반을 통합 관리하는 제3자 물류(3PL) 서비스입니다.',
        'sol.type1.li1':'수배송·보관·유통 통합 관리','sol.type1.li2':'전국 물류 네트워크 활용','sol.type1.li3':'재고 관리 및 입출고 서비스','sol.type1.li4':'물류 정보 시스템(WMS/TMS) 연동',
        'sol.type2.name':'4PL 컨설팅','sol.type2.desc':'공급망(Supply Chain) 전체를 최적화하는 제4자 물류(4PL) 컨설팅 서비스입니다.',
        'sol.type2.li1':'공급망 현황 분석 및 개선 컨설팅','sol.type2.li2':'복수 물류 파트너 통합 조율','sol.type2.li3':'KPI 기반 성과 관리 및 보고','sol.type2.li4':'물류 전략 수립 및 실행 지원',
        'sol.features.title':'서비스 특징','sol.feat1.name':'기업 맞춤형 물류 설계','sol.feat1.desc':'고객사의 업종, 화물 특성, 물동량, 배송 권역 등을 종합 분석하여 최적화된 맞춤형 물류 솔루션을 설계합니다.',
        'sol.feat2.name':'통합 물류 정보 시스템','sol.feat2.desc':'WMS(창고관리시스템), TMS(운송관리시스템)를 연동한 실시간 물류 가시성을 제공합니다.',
        'sol.feat3.name':'해상·항공·육상 통합 운영','sol.feat3.desc':'해상운송, 항공운송, 육상운송, 통관 서비스를 하나의 파트너로 통합 운영합니다.',
        'sol.feat4.name':'성과 기반 SLA 관리','sol.feat4.desc':'명확한 SLA(서비스 수준 협약)를 기반으로 납기 준수율, 오배송률 등 주요 KPI를 정기적으로 측정하고 보고합니다.',
        'sol.benefits.title':'도입 효과','sol.benefit1.name':'물류 비용 절감','sol.benefit1.desc':'전문 물류 인프라와 규모의 경제를 활용해 물류 운영 비용을 평균 15~30% 절감합니다.',
        'sol.benefit2.name':'핵심 사업 집중','sol.benefit2.desc':'물류 운영에 소요되는 인력·시간·비용을 핵심 사업에 집중할 수 있습니다.',
        'sol.benefit3.name':'전문 인력 활용','sol.benefit3.desc':'물류 각 분야의 전문 인력과 축적된 노하우를 즉시 활용할 수 있습니다.',
        'sol.benefit4.name':'유연한 확장성','sol.benefit4.desc':'사업 성장에 따른 물류 규모 확장이 즉각 가능합니다.',
        'sol.customers.title':'주요 고객군','sol.customers.desc':'태인종합물류의 물류 솔루션은 다양한 산업 분야의 기업에 최적화된 서비스를 제공합니다.',
        'sol.customer.tag1':'🏭 제조업체 (생산·부품 조달 물류)','sol.customer.tag2':'🛒 유통업체 (도소매 배송 물류)',
        'sol.customer.tag3':'💻 이커머스 (온라인 풀필먼트)','sol.customer.tag4':'🌏 수출입 기업 (국제 물류 일관화)',
        'sol.customer.tag5':'🏥 의약·바이오 (콜드체인 물류)','sol.customer.tag6':'👗 패션·소비재 (시즌 물량 대응)',
        'sol.customer.tag7':'🔧 중공업·플랜트 (대형 장비 물류)','sol.customer.tag8':'🛒 스타트업·중소기업 (물류 인프라 확보)',
        'sol.cta.title':'맞춤형 물류 솔루션을 찾고 계신가요?','sol.cta.desc':'귀사의 물류 현황을 분석하고 최적의 3PL·4PL 솔루션을 제안해 드립니다.<br/>전문 물류 컨설턴트와 무료 상담을 시작해 보세요.','sol.cta.btn':'물류 솔루션 상담하기',
        /* ── 글로벌 네트워크 ── */
        'net.overview.title':'40여 개국, 120여 개 해외파트너','net.overview.desc':'미주/유럽/동남아/중국 등 현지 지사 및 파트너사를 통한 전세계 네트워킹',
        'net.region1.title':'아시아',
        'net.region1.li1':'🇨🇳 중국 (상하이·칭다오·선전·홍콩)','net.region1.li2':'🇯🇵 일본','net.region1.li3':'🇸🇬 싱가포르','net.region1.li4':'🇲🇾 말레이시아',
        'net.region1.li5':'🇹🇭 태국','net.region1.li6':'🇻🇳 베트남','net.region1.li7':'🇮🇩 인도네시아','net.region1.li8':'🇵🇭 필리핀',
        'net.region1.li9':'🇹🇼 대만','net.region1.li10':'🇧🇩 방글라데시','net.region1.li11':'🇮🇳 인도','net.region1.li12':'🇵🇰 파키스탄',
        'net.region1.li13':'🇱🇰 스리랑카','net.region1.li14':'🇰🇭 캄보디아',
        'net.region2.title':'유럽 / 중동 / 아프리카',
        'net.region2.li1':'🇬🇧 영국','net.region2.li2':'🇩🇪 독일','net.region2.li3':'🇫🇷 프랑스','net.region2.li4':'🇮🇹 이탈리아',
        'net.region2.li5':'🇳🇱 네덜란드','net.region2.li6':'🇧🇪 벨기에','net.region2.li7':'🇪🇸 스페인','net.region2.li8':'🇵🇱 폴란드',
        'net.region2.li9':'🇹🇷 튀르키예','net.region2.li10':'🇸🇦 사우디아라비아','net.region2.li11':'🇮🇷 이란','net.region2.li12':'🇰🇼 쿠웨이트',
        'net.region2.li13':'🇿🇦 남아프리카공화국','net.region2.li14':'🇳🇬 나이지리아 외 다수',
        'net.region3.title':'미주 / 호주·오세아니아',
        'net.region3.li1':'🇺🇸 미국 (LA·시카고·뉴욕·휴스턴·애틀랜타)','net.region3.li2':'🇨🇦 캐나다 (토론토)','net.region3.li3':'🇲🇽 멕시코',
        'net.region3.li4':'🇨🇴 콜롬비아','net.region3.li5':'🇧🇷 브라질','net.region3.li6':'🇦🇷 아르헨티나','net.region3.li7':'🇨🇱 칠레',
        'net.region3.li8':'🇵🇪 페루','net.region3.li9':'🇵🇦 파나마','net.region3.li10':'🇬🇹 과테말라 외 중미 다수','net.region3.li11':'🇦🇺 호주','net.region3.li12':'🇳🇿 뉴질랜드',
        'net.cta.btn':'글로벌 네트워크 문의하기 →',
        /* ── FAQ ── */
        'faq.q1':'해상 운임 견적은 어떻게 받을 수 있나요?','faq.a1':'홈페이지 견적 문의 양식 또는 대표전화(02-3142-4051)를 통해 견적을 요청하실 수 있습니다.',
        'faq.q2':'FCL과 LCL의 차이점은 무엇인가요?','faq.a2':'FCL(Full Container Load)은 컨테이너 1개를 독점 사용하는 방식으로, 대량 화물에 적합합니다. LCL(Less than Container Load)은 여러 화주가 컨테이너를 공유하는 혼재 방식으로, 소량 화물에 적합합니다.',
        'faq.q3':'항공 긴급화물은 얼마나 빨리 처리되나요?','faq.a3':'항공 긴급화물은 접수 후 당일 또는 익일 출발이 가능합니다. 화물 종류, 목적지, 항공편 스케줄에 따라 달라집니다.',
        'faq.q4':'수입 통관 시 필요한 서류는 무엇인가요?','faq.a4':'기본적으로 상업송장(Commercial Invoice), 패킹리스트(Packing List), 선하증권(B/L) 또는 항공화물운송장(AWB)이 필요합니다.',
        'faq.q5':'화물 보험은 어떻게 되나요?','faq.a5':'태인종합물류는 화물배상 책임보험 10억원에 가입되어 있어 운송 중 발생하는 손해에 대비하고 있습니다.',
        'faq.q6':'서비스 가능 국가는 어디인가요?','faq.a6':'WCA(World Cargo Association) 회원사로서 40여 개국, 120여 개 해외 파트너와 협력하고 있습니다.',
        'faq.q7':'부산 지사에서도 동일한 서비스를 받을 수 있나요?','faq.a7':'네, 부산 지사(051-464-7056)에서 서울 본사와 동일한 물류 서비스를 제공합니다.',
        'faq.q8':'3PL 서비스란 무엇인가요?','faq.a8':'3PL(Third Party Logistics, 제3자 물류)은 기업의 물류 업무(운송, 보관, 유통 등)를 전문 물류 기업에 위탁하는 서비스입니다.',
        'faq.q9':'위험물 운송도 가능한가요?','faq.a9':'네, IMDG Code(해상), IATA(항공) 등 국제 위험물 규정에 따라 위험물 운송이 가능합니다.',
        'faq.q10':'운송 중 화물 현황을 확인할 수 있나요?','faq.a10':'네, 선사 및 항공사의 추적 시스템을 통해 화물 현황을 실시간으로 확인하실 수 있도록 안내해 드립니다.',
        'faq.cta.title':'찾으시는 답변이 없으신가요?','faq.cta.desc':'전문 상담원이 직접 도와드립니다.','faq.cta.btn':'1:1 문의하기',
        /* ── 고객센터 ── */
        'cs.hq.tag':'본사 · SEOUL','cs.hq.addr':'서울 마포구 월드컵로 112, 효성 B/D 4층',
        'cs.busan.tag':'지사 · BUSAN','cs.busan.addr':'부산광역시 중구 충장대로 5번길 12-1, 코리아 B/D 3층',
        'cs.label.phone':'대표전화','cs.label.fax':'팩스','cs.label.email':'이메일','cs.label.addr':'주소',
        'cs.hours':'평일 09:00 ~ 18:00','cs.faq.btn':'자주 묻는 질문 보기',
        'cs.form.title':'온라인 견적 문의','cs.form.desc':'아래 양식을 작성해 주시면 담당자가 빠르게 연락드리겠습니다.',
        'cs.form.name':'이름/회사명 *','cs.form.phone':'연락처 *','cs.form.email':'이메일',
        'cs.form.service':'문의 서비스','cs.form.service.placeholder':'서비스를 선택하세요',
        'cs.form.svc.fcl':'해상운송 (FCL)','cs.form.svc.lcl':'해상운송 (LCL)','cs.form.svc.air':'항공운송',
        'cs.form.svc.land':'육상운송','cs.form.svc.customs':'통관/포워딩','cs.form.svc.sol':'물류 솔루션','cs.form.svc.other':'기타',
        'cs.form.message':'문의 내용 *','cs.form.agree':'개인정보 수집·이용에 동의합니다. <a href="#">[내용보기]</a>','cs.form.submit':'문의 보내기',
        /* ── 공지사항 ── */
        'notice.col.num':'번호','notice.col.title':'제목','notice.col.category':'구분','notice.col.date':'등록일','notice.col.views':'조회',
        'notice.tag.notice':'공지','notice.tag.general':'일반','notice.pagination.prev':'이전','notice.pagination.next':'다음',
        'notice.total':'총 <strong>30</strong>건',
        'notice.title1':'2026년 설 연휴 물류 운영 안내 <span class="new-badge">NEW</span>','notice.title2':'인천 물류센터 확장 이전 안내',
        'notice.title3':'화물 운임 요율 조정 안내 (2026년 1월)','notice.title4':'태인물류 ISO 9001:2015 재인증 완료',
        'notice.title5':'스마트 물류 시스템 업그레이드 완료','notice.title6':'추석 연휴 물류 운영 안내',
        'notice.title7':'WCA 연례 총회 참가 안내','notice.title8':'중국 노선 운임 조정 안내',
        'notice.title9':'부산 지사 이전 완료 안내','notice.title10':'2025년 하반기 신입사원 채용 안내',
      },
      en: {
        /* ── Navigation ── */
        'nav.company':'About Us','nav.services':'Services','nav.network':'Global Network',
        'nav.notice':'Notice','nav.support':'Customer Support','nav.estimate':'Quick Quote','nav.consult':'Contact Us',
        /* ── Hero ── */
        'hero1.h1':'Connecting the World<br/>with Trust & Passion',
        'hero1.desc':'TAEIN TOTAL TRANSPORTATION CO.,LTD<br/>Your Global Partner for Sea, Air & Customs',
        'hero1.btn':'Our Services','hero.consult':'Contact Us',
        'hero2.h1':'Global Logistics Network<br/>Connecting the World',
        'hero2.desc':'Multi-modal transport via sea, air & land—<br/>safe delivery anywhere in the world.',
        'hero2.btn':'View Network',
        'hero3.h1':'Customer-Tailored<br/>One-Stop Logistics',
        'hero3.desc':'As a WCA (World Cargo Alliance) member,<br/>partnering with 120+ agents in 40+ countries',
        'hero3.btn':'Learn More',
        /* ── About ── */
        'about.title':'About TAEIN<br/>Total Logistics',
        'about.desc':'Since 2010, we have provided comprehensive logistics services covering sea/air import-export, customs clearance, and transportation. As an official WCA member, we collaborate with 120+ partners across 40+ countries to support your business success.',
        'about.btn':'Learn More',
        'stat1.label':'Year Founded','stat2.label':'Countries','stat3.label':'Partners','stat4.label':'Cargo Insurance',
        /* ── Services (index) ── */
        'svc.title':'All-in-One Logistics<br/>for Import/Export Companies',
        'svc.desc':'Simplify complex international shipping<br/>with TAEIN Total Logistics','svc.more':'View All Services ↗',
        'svc.card1.title':'Multiple Transport Modes','svc.card1.desc':'Global connectivity via FCL/LCL, air, and rail',
        'svc.card2.title':'All Cargo Types','svc.card2.desc':'From general freight to hazmat and refrigerated goods',
        'svc.card3.title':'Inland Transport','svc.card3.desc':'Door-to-door pickup and final delivery services',
        'svc.card4.title':'Value-Added Services','svc.card4.desc':'Customs, insurance, packaging — everything you need',
        /* ── Contact ── */
        'contact.title':'Contact Us Anytime',
        'contact.desc':'For logistics inquiries or quotation requests, contact us by phone or online and we will respond promptly.',
        'form.title':'Inquiry & Consultation','form.subtitle':'Fill in the form below and our team will get back to you quickly.',
        'form.name':'Name / Company *','form.phone':'Phone *','form.email':'Email *',
        'form.service':'Service Type','form.message':'Message *','form.submit':'Send Inquiry',
        'estimate.title':'Quick Quote','estimate.desc':'Enter origin, destination and cargo details — our team will respond promptly.',
        /* ── Page headers ── */
        'page.ceo.label':'CEO GREETING','page.ceo.h1':"CEO's Message",
        'page.phil.label':'MANAGEMENT PHILOSOPHY','page.phil.h1':'Our Philosophy',
        'page.hist.label':'COMPANY HISTORY','page.hist.h1':'History',
        'page.dir.label':'DIRECTIONS','page.dir.h1':'How to Find Us',
        'page.svc.label':'SERVICES','page.svc.h1':'International Logistics Services',
        'page.sea.label':'OCEAN FREIGHT','page.sea.h1':'Ocean Freight',
        'page.air.label':'AIR FREIGHT','page.air.h1':'Air Freight',
        'page.land.label':'LAND TRANSPORT','page.land.h1':'Land Transport',
        'page.customs.label':'CUSTOMS & FORWARDING','page.customs.h1':'Customs & Forwarding',
        'page.sol.label':'LOGISTICS SOLUTIONS','page.sol.h1':'Logistics Solutions',
        'page.net.label':'GLOBAL NETWORK','page.net.h1':'Global Network',
        'page.notice.label':'NOTICE','page.notice.h1':'Notice',
        'page.faq.label':'FAQ','page.faq.h1':'Frequently Asked Questions',
        'page.cs.label':'CUSTOMER SERVICE','page.cs.h1':'Customer Service',
        /* ── Breadcrumb ── */
        'breadcrumb.home':'Home','breadcrumb.services':'Services','breadcrumb.sea':'Ocean Freight','breadcrumb.air':'Air Freight',
        /* ── CEO ── */
        'ceo.section.title':"CEO's Message",
        'ceo.msg.p1':'Hello.<br/>I am <strong>Ha Hyeong-tak</strong>, CEO of Taein General Logistics Co., Ltd.',
        'ceo.msg.p2':'We sincerely thank all customers who have visited Taein General Logistics.',
        'ceo.msg.p3':'Since its founding in May 2010, Taein General Logistics has provided comprehensive logistics services encompassing sea and air import-export, customs clearance, and inland transport, growing together with our valued customers. Built on years of field experience and a domestic and international partner network, we continuously strive to deliver the best logistics solutions.',
        'ceo.msg.p4':'Today, the global logistics environment is changing rapidly. Amid challenges such as supply chain instability, freight rate fluctuations, and tightening regulations, Taein General Logistics does its utmost — grounded in expertise and passion — to transport your cargo safely and swiftly to its destination.',
        'ceo.msg.p5':'<strong>"Customer satisfaction is Taein\'s greatest reward."</strong><br/>This single sentence is the management philosophy engraved in the hearts of all our employees. We listen carefully to each customer\'s needs and respond with the best logistics solutions.',
        'ceo.msg.p6':'We ask for your continued trust and support. Taein General Logistics will be your most reliable logistics partner for your successful business.',
        'ceo.msg.p7':'Thank you.',
        'ceo.sig.company':'Taein General Logistics Co., Ltd.','ceo.sig.name':'<strong>Ha Hyeong-tak</strong> &nbsp;CEO','ceo.btn.estimate':'Request a Quote',
        /* ── Philosophy ── */
        'phil.vision.quote':'"Customer satisfaction is Taein\'s greatest reward."',
        'phil.vision.desc':'Taein General Logistics places trust with customers as its top priority, providing the finest service with unwavering expertise and passion amid changes in the logistics industry.',
        'phil.vision.cite':'— Taein General Logistics Management Policy',
        'phil.values.title':'Core Competencies of Taein','phil.values.sub':'The trust and expertise of Taein General Logistics, proven in numbers',
        'phil.val1.label':'WCA Member','phil.val1.desc':'As an official member of the World Cargo Alliance (WCA), we provide global-standard logistics services and an extensive international partner network.',
        'phil.val2.label':'Cargo Liability Insurance','phil.val2.desc':'With KRW 1 billion in cargo liability insurance, we protect your cargo responsibly and are fully prepared for any unexpected incidents.',
        'phil.val3.label':'Logistics Specialist','phil.val3.desc':'With 16+ years of logistics expertise and field know-how since our founding in 2010, we deliver optimal solutions for various industry logistics needs.',
        'phil.val4.label':'Partner Network','phil.val4.desc':'We have built close cooperation networks with 120+ overseas partners in 40+ countries across Asia, Europe, the Americas, the Middle East, and Africa.',
        'phil.cards.title':'Core Management Philosophy','phil.cards.sub':'Four core values pursued by Taein General Logistics drive customer satisfaction.',
        'phil.card1.title':'Trust','phil.card1.desc':'We build trust with customers through competence, aiming to be a company whose value to customers and to itself is clearly demonstrated.',
        'phil.card2.title':'Growth','phil.card2.desc':'We are a company that reads the constantly changing logistics culture and grows to always provide the best service.',
        'phil.card3.title':'Passion','phil.card3.desc':'We are a company that remembers customer growth is our growth, and finds and provides the most efficient service.',
        'phil.card4.title':'One-Stop Service','phil.card4.desc':'We provide the best solutions all at once through dedicated sales staff per company, professional expertise from diverse know-how, and our networks.',
        'phil.stat.quote':'Trust · Growth · Passion<br/>Growing together with customers<br/>through these three values.',
        'phil.stat.founded':'Year Founded','phil.stat.partners':'Overseas Partners','phil.stat.capital':'Initial Capital','phil.stat.clients':'Key Clients',
        'phil.mission.title':"It's Different with Taein",
        'phil.mission.desc':'Taein General Logistics is not just a freight forwarder. As your business partner, we accompany you from the start to the finish of logistics.',
        'phil.mission.li1':'Design and provision of customized logistics solutions','phil.mission.li2':'1-on-1 dedicated management service through assigned sales staff',
        'phil.mission.li3':'Real-time cargo status tracking and prompt reporting','phil.mission.li4':'Fast and accurate customs clearance processing',
        'phil.mission.li5':'Reasonable and transparent freight rate structure','phil.mission.li6':'24-hour emergency cargo response system',
        'phil.mission.btn':'Request a Quote',
        'phil.cta.title':'A Wider World with Taein','phil.cta.desc':'We will be your logistics partner with 16 years of expertise and a global network spanning 40+ countries.',
        'phil.cta.btn1':'Request a Quote','phil.cta.btn2':'View History',
        /* ── History ── */
        'hist.section.title':"Taein's Footsteps",'hist.section.sub':'Since our founding in 2010, we advance toward becoming Korea\'s leading comprehensive logistics company with trust and innovation.',
        'hist.tag.founding':'Founded','hist.tag.present':'Ongoing',
        'hist.stat1.label':'Logistics Expertise','hist.stat1.unit':'yrs+','hist.stat2.label':'Global Partnerships','hist.stat2.unit':'countries+',
        'hist.stat3.label':'Overseas Partners','hist.stat3.unit':'companies+','hist.stat4.label':'Key Clients','hist.stat4.unit':'companies+',
        'hist.founding.title':'Founding of Taein General Logistics Co., Ltd.',
        'hist.founding.li1':'Incorporated as Taein General Logistics Co., Ltd.','hist.founding.li2':'Started with KRW 300 million in capital',
        'hist.founding.li3':'Established headquarters in Mapo-gu, Seoul','hist.founding.li4':'Hired logistics professionals and built organizational structure',
        'hist.year6.title':'Full Business Launch & WCA Global Membership',
        'hist.year6.li1':'Launched sea and air import/export forwarding business','hist.year6.li2':'Became an official member of WCA (World Cargo Association)',
        'hist.year6.li3':'Started air cargo handling service at Incheon Airport','hist.year6.li4':'Signed agency contracts with major shipping lines','hist.year6.li5':'Built domestic inland transport network',
        'hist.year5.title':'Full Expansion of Global Network',
        'hist.year5.li1':'Full-scale expansion of Asia, Europe, Americas global network','hist.year5.li2':'Surpassed 50 overseas partner companies',
        'hist.year5.li3':'Strengthened key routes in China, Japan, and Southeast Asia','hist.year5.li4':'Diversified FCL/LCL ocean freight services','hist.year5.li5':'Launched customized logistics consulting service',
        'hist.year4.title':'Busan Branch Opening & Customs Service Strengthening',
        'hist.year4.li1':'Opened Busan branch — established nationwide logistics service system','hist.year4.li2':'Strengthened specialized customs clearance service with customs brokers',
        'hist.year4.li3':'Surpassed 100 overseas partner companies (Asia, Europe, Americas)','hist.year4.li4':'Launched port logistics service (Busan Port, Incheon Port)','hist.year4.li5':'Signed exclusive logistics agency contracts with major corporations',
        'hist.year3.title':'Cargo Insurance Enhancement & Logistics Solutions Expansion',
        'hist.year3.li1':'Enrolled in KRW 1 billion cargo liability insurance','hist.year3.li2':'Full-scale expansion of 3PL and SCM consulting business',
        'hist.year3.li3':'Operated emergency air freight services in response to COVID-19','hist.year3.li4':'Introduced non-contact online quotation system','hist.year3.li5':'Surpassed 200 key clients',
        'hist.year2.title':'Smart Logistics System Introduction & Certification',
        'hist.year2.li1':'Improved operational efficiency by introducing Smart Logistics System (TMS/WMS)','hist.year2.li2':'Obtained ISO 9001:2015 Quality Management System certification',
        'hist.year2.li3':'Surpassed 40 countries and 120 global partners','hist.year2.li4':'Developed and launched AI-based cargo tracking system','hist.year2.li5':'Built logistics big data analytics infrastructure',
        'hist.year1.title':'Continued Growth — Leap to Global Logistics Specialist','hist.year1.badge':'2025 ~ Present',
        'hist.year1.li1':'Continuing pursuit of growth as a global logistics specialist','hist.year1.li2':'Upgrading smart logistics platform and accelerating digital transformation',
        'hist.year1.li3':'Started developing eco-friendly green logistics solutions','hist.year1.li4':'Expanded new overseas partnerships (focused on Southeast Asia & Middle East)','hist.year1.li5':'Introduced ESG management system and published sustainability report',
        'hist.cta.title':"Experience Taein's 16 Years of Expertise",'hist.cta.desc':'We provide optimal logistics solutions backed by accumulated know-how and a global network.',
        'hist.cta.btn1':'Request a Quote','hist.cta.btn2':'View Philosophy',
        /* ── Directions ── */
        'dir.section.title':'Office Locations','dir.section.sub':'We provide nationwide logistics services from our Seoul headquarters and Busan branch.',
        'dir.hq.badge':'HQ','dir.hq.name':'Seoul Headquarters',
        'dir.label.tel':'Phone','dir.label.fax':'Fax','dir.label.email':'Email','dir.label.address':'Address','dir.label.hours':'Business Hours',
        'dir.hq.hours':'Weekdays 09:00–18:00 &nbsp;<span class="closed">Closed Sat/Sun/Holidays</span>',
        'dir.map.naver':'View on Naver Map','dir.map.kakao':'View on Kakao Map',
        'dir.transport.hq.title':'Directions (Seoul HQ)','dir.transport.subway':'By Subway','dir.transport.bus':'By Bus','dir.transport.car':'By Car',
        'dir.hq.subway.li1':'<span class="line-badge line2">Line 2</span> Hapjeong Station Exit 7 — 5 min walk',
        'dir.hq.subway.li2':'<span class="line-badge line6">Line 6</span> Hapjeong Station Exit 3 — 5 min walk',
        'dir.hq.subway.li3':'<span class="line-badge line6">Line 6</span> Mangwon Station Exit 2 — 10 min walk',
        'dir.hq.bus.li1':'<span class="bus-badge bus-blue">Trunk Bus</span> 271, 571, 672',
        'dir.hq.bus.li2':'<span class="bus-badge bus-green">Branch Bus</span> 7713, 7726',
        'dir.hq.bus.li3':'<span class="bus-badge bus-red">Express Bus</span> 9701',
        'dir.hq.car.li1':'Inner Ring Road toward Mapo IC → Turn right onto Worldcup-ro and go straight',
        'dir.hq.car.li2':'Riverside Road toward Hapjeong IC → Go straight on Worldcup-ro for about 5 min',
        'dir.hq.car.li3':'Parking available in building (paid; parking ticket provided on visit)',
        'dir.branch.badge':'Branch','dir.branch.name':'Busan Branch',
        'dir.branch.hours':'Weekdays 09:00–18:00 &nbsp;<span class="closed">Closed Sat/Sun/Holidays</span>',
        'dir.transport.branch.title':'Directions (Busan Branch)',
        'dir.branch.subway.li1':'<span class="line-badge line1">Line 1</span> Jungang Station Exit 8 — 5 min walk',
        'dir.branch.subway.li2':'<span class="line-badge line1">Line 1</span> Busan Station Exit 6 — 10 min walk',
        'dir.branch.bus.li1':'<span class="bus-badge bus-blue">Regular Bus</span> 81, 85, 88, 190',
        'dir.branch.bus.li2':'<span class="bus-badge bus-green">Neighborhood Bus</span> Jungu-1, Jungu-2',
        'dir.branch.car.li1':'Enter via Chungjang-daero → Turn left after seeing Korea Building sign',
        'dir.branch.car.li2':'About 5 min by car from Busan International Passenger Terminal',
        'dir.branch.car.li3':'Use nearby public parking or building parking lot',
        'dir.cta.title':'We Recommend Contacting Us Before Your Visit',
        'dir.cta.desc':'For a smooth consultation, please make a reservation by phone or email before visiting, and our staff will be ready to greet you.',
        'dir.cta.btn1':'Call Headquarters','dir.cta.btn2':'Online Quote Inquiry',
        /* ── Services page ── */
        'svc.section.title':'International Logistics Services',
        'svc.section.sub':'From sea freight to air, inland transport and beyond — TAEIN connects<br/>your cargo safely to anywhere in the world.',
        'svc.fcl.title':'Ocean FCL','svc.fcl.desc':'Container-load ocean freight service connecting major ports worldwide.',
        'svc.fcl.li1':'20GP / 40GP / 40HC / FR / OT / RF and more container types',
        'svc.fcl.li2':'Coverage of major world ports — Asia, Europe, Americas, Middle East, Africa',
        'svc.fcl.li3':'Pre-departure shipping document review (B/L, Packing List, Invoice)',
        'svc.fcl.li4':'Specialized handling of hazardous (DG) and refrigerated (RF) cargo',
        'svc.lcl.title':'Ocean LCL','svc.lcl.desc':'Competitive pricing and professional management even for small shipments.',
        'svc.lcl.li1':'Dedicated consolidation service for small cargo (CFS→CFS / CFS→CY)',
        'svc.lcl.li2':'Fast lead times with weekly fixed sailing schedules',
        'svc.lcl.li3':'Integrated warehouse storage, pickup, and delivery service',
        'svc.tag.sea':'Ocean Freight',
        'svc.air.title':'Air Freight','svc.air.desc':'Service optimized for urgent and high-value cargo.',
        'svc.air.li1':'Commercial Air, Charter, and Express all available',
        'svc.air.li2':'Hazardous goods (IATA compliant), pharmaceuticals, live animals, perishables handled',
        'svc.air.li3':'Door-to-Door pickup and delivery service',
        'svc.air.li4':'Departures from Incheon, Gimpo, Gimhae airports to major airports worldwide',
        'svc.tag.air':'Air Freight',
        'svc.land.title':'Inland Transport','svc.land.desc':'All-in-one transport from origin pickup to final destination.',
        'svc.land.li1':'Nationwide delivery — Seoul, Gyeonggi, Incheon, Busan, Daegu, Gwangju and all regions',
        'svc.land.li2':'General / Oversized / Refrigerated / Hazardous cargo all available',
        'svc.land.li3':'Port/Airport → Factory/Logistics Center Door-to-Door transport',
        'svc.land.li4':'Container inland transport (ICD connection)',
        'svc.tag.land':'Land Transport',
        'svc.addon.title':'Value-Added Services','svc.addon.sub':'Choose from all services needed for international shipping: customs, insurance, packaging, and more.',
        'svc.addon1.title':'Export Customs Clearance','svc.addon1.desc':'Customs document preparation and customs declaration for export/import',
        'svc.addon2.title':'Import Delivery Service','svc.addon2.desc':'All-in-one import customs clearance and delivery after cargo arrival',
        'svc.addon3.title':'Empty Container Trucking','svc.addon3.desc':'Empty container sourcing and inland transport connection',
        'svc.addon4.title':'Destination Delivery','svc.addon4.desc':'Door-to-Door to final destination via local partners',
        'svc.addon5.title':'Packaging Service','svc.addon5.desc':'Professional packaging and labeling tailored to cargo characteristics',
        'svc.addon6.title':'CFS Service','svc.addon6.desc':'Container cargo collection/distribution warehouse service',
        'svc.addon7.title':'ISF Filing Service','svc.addon7.desc':'ISF (10+2) filing service for US-bound export cargo',
        'svc.addon8.title':'Cargo Insurance','svc.addon8.desc':'KRW 1 billion cargo liability insurance — peace of mind for any incident',
        'svc.link.detail':'Learn More →','svc.link.more':'Details →','svc.link.inquire':'Inquire →','svc.desc2':'One-stop: sea, air, land, customs and logistics solutions',
        'svc.cta.title':'Looking for the Best Logistics Solution?','svc.cta.desc':'Our dedicated consultants will quickly guide you on the best shipping method and rates for your cargo.','svc.cta.btn1':'Online Quote Inquiry',
        /* ── Ocean Freight ── */
        'sea.overview.title':'Ocean Freight Service Overview','sea.overview.desc':'Taein General Logistics provides both FCL and LCL services connecting major ports in Asia, Europe, the Americas, the Middle East, and Africa.',
        'sea.types.title':'Service Types','sea.fcl.desc':'Full-container ocean freight service for bulk cargo — dedicated container without mixing.',
        'sea.fcl.li1':'20ft / 40ft / 40ft HC containers','sea.fcl.li2':'Enhanced security with dedicated container use','sea.fcl.li3':'Optimized cost efficiency for bulk cargo',
        'sea.lcl.desc':'Consolidation service optimized for small shipments — share a container to reduce freight costs.',
        'sea.lcl.li1':'Economical rates for small cargo','sea.lcl.li2':'Regular consolidation schedule operation','sea.lcl.li3':'Safe cargo management and packaging',
        'sea.special.title':'Special Cargo Transport','sea.special.desc':'Specialized ocean transport for hazardous materials, refrigerated cargo, oversized/heavy cargo, and other items requiring special handling.',
        'sea.special.li1':'Hazardous goods compliant with IMDG Code','sea.special.li2':'Refrigerated/frozen cargo using reefer containers','sea.special.li3':'Oversized/heavy cargo using FR (Flat Rack) and OT (Open Top) containers',
        'sea.features.title':'Service Features','sea.feat1.title':'Global Shipping Network','sea.feat1.desc':'Stable space allocation and competitive rates through close partnerships with major global shipping lines including MSC, COSCO, and Evergreen.',
        'sea.feat2.title':'Real-Time Cargo Tracking','sea.feat2.desc':'Track the location and status of your cargo in real time from loading to arrival via our online portal and mobile.',
        'sea.feat3.title':'One-Stop Customs Clearance','sea.feat3.desc':'Simplify procedures with a one-stop service linking ocean freight and customs clearance — from document prep to customs declaration.',
        'sea.feat4.title':'Competitive Rate Proposals','sea.feat4.desc':'We propose the lowest rates through route-specific and cargo-specific rate analysis with regular market monitoring.',
        'sea.cta.title':'Need Ocean Freight Service?','sea.cta.desc':'Our expert logistics consultants will propose the optimal ocean freight solution.<br/>Contact us now to receive a customized quote quickly.','sea.cta.btn':'Request Ocean Freight Quote',
        /* ── Air Freight ── */
        'air.cta.title':'Need Air Freight Service?','air.cta.desc':'From urgent cargo to special cargo, our expert air logistics consultants will propose the best solution.<br/>Contact us now to receive a customized quote quickly.','air.cta.btn':'Request Air Freight Quote',
        /* ── Land Transport ── */
        'land.overview.title':'Land Transport Service Overview','land.overview.desc':'Taein General Logistics provides land transport services utilizing a nationwide network — from small parcels to super-heavy cargo.',
        'land.types.title':'Service Types','land.type1.name':'General Cargo Transport','land.type1.desc':'Same-day and next-day nationwide delivery general cargo transport service.',
        'land.type1.li1':'Fleet from 1-ton to 25-ton vehicles','land.type1.li2':'Same-day and next-day delivery nationwide','land.type1.li3':'Temperature-controlled refrigerated/chilled vehicles',
        'land.type2.name':'Oversized / Heavy Cargo','land.type2.desc':'Specialized transport service for super-heavy and oversized items not possible with standard vehicles.',
        'land.type2.li1':'Low-bed and trailer special vehicles','land.type2.li2':'Heavy cargo transport permit acquisition','land.type2.li3':'Industrial machinery and plant equipment specialists',
        'land.type3.name':'Port / Airport Linked Transport','land.type3.desc':'Pickup and delivery service linked to ports and airports — swift pickup on vessel arrival.',
        'land.type3.li1':'Direct container pickup/return at berth','land.type3.li2':'Airport cargo terminal-linked delivery','land.type3.li3':'Immediate delivery after customs clearance',
        'land.features.title':'Service Features','land.feat1.name':'Nationwide Vehicle Network','land.feat1.desc':'Vehicle and partner networks at major nationwide bases — rapid dispatch for urgent logistics needs.',
        'land.feat2.name':'GPS Real-Time Cargo Tracking','land.feat2.desc':'All transport vehicles equipped with GPS for real-time cargo location tracking via web or mobile.',
        'land.feat3.name':'Port/Airport One-Stop Transport','land.feat3.desc':'One-stop transport service linked with sea and air transport — immediate delivery after customs clearance.',
        'land.feat4.name':'Dedicated Vehicle Contract','land.feat4.desc':'Dedicated vehicle contract service for companies with regular logistics needs — stable availability and cost reduction.',
        'land.area.title':'Nationwide Service Areas','land.area.desc':'Taein General Logistics operates a wide transport network covering all of South Korea.',
        'land.area.tag1':'🏙️ Seoul·Gyeonggi (Capital area same-day delivery)','land.area.tag2':'⚓ Incheon (Incheon Port & Airport connection)',
        'land.area.tag3':'🚢 Busan·Gyeongnam (Busan Port specialized)','land.area.tag4':'🌊 Gwangju·Jeolla (West coast logistics hub)',
        'land.area.tag5':'🏔️ Daegu·Gyeongbuk (Inland industrial complex)','land.area.tag6':'🌿 Daejeon·Chungcheong (Central hub)',
        'land.area.tag7':'🏝️ Jeju (Jeju Island special transport)','land.area.tag8':'🚀 Nationwide next-day delivery service',
        'land.cta.title':'Need Land Transport Service?','land.cta.desc':'We transport your cargo swiftly and safely anywhere nationwide.<br/>Contact us now and a dedicated representative will advise on the best transport method.','land.cta.btn':'Request Land Transport Quote',
        /* ── Customs ── */
        'customs.overview.title':'Customs Clearance & Forwarding Service Overview','customs.overview.desc':'Taein General Logistics handles complex import/export customs clearance in one-stop fashion based on rich experience and a professional customs broker network.',
        'customs.overview.box':'Import/export customs clearance can result in delays or additional costs due to incorrect HS code classification, missing documents, or non-compliance. Taein General Logistics works with professional customs brokers to strictly comply with customs laws.',
        'customs.types.title':'Service Types','customs.type1.name':'Export Customs Clearance','customs.type1.desc':'We handle the entire process from customs declaration to export license for export cargo — accurate HS code classification ensures timely shipment.',
        'customs.type1.li1':'Accurate HS code classification and review','customs.type1.li2':'Export declaration form preparation and submission',
        'customs.type1.li3':'Certificate of origin issuance support','customs.type1.li4':'Strategic goods export license acquisition',
        'customs.type2.name':'Import Customs Clearance','customs.type2.desc':'We handle everything from cargo arrival to import declaration, customs payment, and clearance — with FTA preferential tariff application and customs inspection support.',
        'customs.type2.li1':'FTA preferential tariff application for customs savings','customs.type2.li2':'Customs inspection/quarantine response support',
        'customs.type2.li3':'Import requirement verification and license acquisition','customs.type2.li4':'Bonded fee reduction through fast clearance',
        'customs.type3.name':'International Forwarding','customs.type3.desc':'We provide international forwarding services using a combination of sea, air, and land transport — planning the optimal route from origin to destination.',
        'customs.type3.li1':'Multi-modal route optimization planning','customs.type3.li2':'Vessel/aircraft space allocation and booking',
        'customs.type3.li3':'B/L, AWB and other transport document issuance','customs.type3.li4':'Destination local partner-linked delivery',
        'customs.process.title':'Customs Processing Procedure','customs.process.desc':"Fast and accurate customs clearance through Taein General Logistics' systematic 6-step customs process.",
        'customs.step1.label':'Cargo Receipt','customs.step1.desc':'Transport request &<br/>cargo information verification',
        'customs.step2.label':'Document Review','customs.step2.desc':'Invoice & P/L<br/>HS code classification',
        'customs.step3.label':'Customs Declaration','customs.step3.desc':'Electronic customs declaration<br/>& document submission',
        'customs.step4.label':'Customs Examination','customs.step4.desc':'Document review &<br/>inspection response',
        'customs.step5.label':'Clearance Complete','customs.step5.desc':'Customs payment &<br/>clearance confirmation',
        'customs.step6.label':'Delivery','customs.step6.desc':'Cargo release &<br/>destination delivery',
        'customs.features.title':'Service Features',
        'customs.feat1.name':'Professional Customs Broker Network','customs.feat1.desc':'We work closely with professional customs brokers with years of field experience, minimizing clearance risk even for complex matters.',
        'customs.feat2.name':'Fast Customs Processing & Immediate Response','customs.feat2.desc':'Fast customs clearance through our computer declaration system and close communication with customs authorities — real-time progress reporting.',
        'customs.feat3.name':'Tax Optimization Consulting','customs.feat3.desc':'We minimize tariff burden through FTA preferential tariff application, tariff classification optimization, and exemption/refund system utilization.',
        'customs.feat4.name':'Import/Export Document Bulk Service','customs.feat4.desc':'We prepare, compile, and submit all required documents in one batch: invoice, packing list, B/L, AWB, certificate of origin, quarantine certificate, and more.',
        'customs.cta.title':'Customs & Forwarding Inquiry?','customs.cta.desc':'Taein General Logistics resolves complex import/export procedures in one stop.<br/>Contact our expert representative now for guidance on the optimal customs method.','customs.cta.btn':'Customs Inquiry',
        /* ── Logistics Solutions ── */
        'sol.overview.title':'Logistics Solutions Service Overview','sol.overview.desc':'Taein General Logistics provides customized 3PL/4PL logistics outsourcing services — integrating transport, storage, distribution, and customs clearance.',
        'sol.overview.box':'Logistics is a key element of corporate competitiveness. Building your own logistics infrastructure requires enormous investment. Taein General Logistics handles all your logistics needs so you can focus on your core business.',
        'sol.types.title':'Service Types','sol.type1.name':'3PL Outsourcing','sol.type1.desc':'Third-party logistics (3PL) service integrating and managing transport, storage, and distribution — enabling you to focus on your core business.',
        'sol.type1.li1':'Integrated transport, storage, and distribution management','sol.type1.li2':'Nationwide logistics network utilization',
        'sol.type1.li3':'Inventory management and inbound/outbound services','sol.type1.li4':'Logistics information system (WMS/TMS) integration',
        'sol.type2.name':'4PL Consulting','sol.type2.desc':'Fourth-party logistics (4PL) consulting service optimizing the entire supply chain — deep analysis and multi-partner integration.',
        'sol.type2.li1':'Supply chain status analysis and improvement consulting','sol.type2.li2':'Multiple logistics partner integrated coordination',
        'sol.type2.li3':'KPI-based performance management and reporting','sol.type2.li4':'Logistics strategy development and execution support',
        'sol.features.title':'Service Features','sol.feat1.name':'Customized Logistics Design','sol.feat1.desc':'Optimized logistics solutions designed through comprehensive analysis of company type, cargo characteristics, volume, and delivery area.',
        'sol.feat2.name':'Integrated Logistics Information System','sol.feat2.desc':'Real-time logistics visibility through WMS and TMS integration — monitor inventory status, delivery progress, and cost analysis.',
        'sol.feat3.name':'Integrated Sea/Air/Land Operations','sol.feat3.desc':'Ocean freight, air freight, land transport, and customs services integrated with a single partner — single point of contact.',
        'sol.feat4.name':'SLA-Based Performance Management','sol.feat4.desc':'Regular measurement and reporting of key KPIs including on-time delivery rate, mis-delivery rate, and customer satisfaction based on clear SLA.',
        'sol.benefits.title':'Benefits of Adoption',
        'sol.benefit1.name':'Logistics Cost Reduction','sol.benefit1.desc':'Reduce logistics operating costs by an average of 15–30% through professional logistics infrastructure and economies of scale.',
        'sol.benefit2.name':'Focus on Core Business','sol.benefit2.desc':'Concentrate human resources, time, and costs spent on logistics operations on your core business.',
        'sol.benefit3.name':'Utilize Expert Staff','sol.benefit3.desc':'Immediately access specialized personnel and accumulated know-how — a verified team manages logistics without recruitment costs.',
        'sol.benefit4.name':'Flexible Scalability','sol.benefit4.desc':'Instant logistics scaling as your business grows — elastic response to volume changes during peak and off-peak seasons.',
        'sol.customers.title':'Key Customer Groups','sol.customers.desc':"Taein General Logistics' logistics solutions provide optimized services for companies in various industries.",
        'sol.customer.tag1':'🏭 Manufacturers (production & parts procurement)','sol.customer.tag2':'🛒 Distributors (wholesale/retail delivery)',
        'sol.customer.tag3':'💻 E-commerce (online fulfillment)','sol.customer.tag4':'🌏 Import/Export companies (international logistics integration)',
        'sol.customer.tag5':'🏥 Pharmaceutical/Biotech (cold chain logistics)','sol.customer.tag6':'👗 Fashion/Consumer goods (seasonal volume)',
        'sol.customer.tag7':'🔧 Heavy industry/Plant (large equipment logistics)','sol.customer.tag8':'🛒 Startups/SMEs (logistics infrastructure)',
        'sol.cta.title':'Looking for Customized Logistics Solutions?','sol.cta.desc':'We analyze your logistics status and propose the optimal 3PL/4PL solution.<br/>Start a free consultation with our expert logistics consultants.','sol.cta.btn':'Consult on Logistics Solutions',
        /* ── Global Network ── */
        'net.overview.title':'40+ Countries, 120+ Overseas Partners','net.overview.desc':'Global networking through local offices and partners in the Americas, Europe, Southeast Asia, China, and more',
        'net.region1.title':'Asia',
        'net.region1.li1':'🇨🇳 China (Shanghai · Qingdao · Shenzhen · Hong Kong)','net.region1.li2':'🇯🇵 Japan','net.region1.li3':'🇸🇬 Singapore','net.region1.li4':'🇲🇾 Malaysia',
        'net.region1.li5':'🇹🇭 Thailand','net.region1.li6':'🇻🇳 Vietnam','net.region1.li7':'🇮🇩 Indonesia','net.region1.li8':'🇵🇭 Philippines',
        'net.region1.li9':'🇹🇼 Taiwan','net.region1.li10':'🇧🇩 Bangladesh','net.region1.li11':'🇮🇳 India','net.region1.li12':'🇵🇰 Pakistan',
        'net.region1.li13':'🇱🇰 Sri Lanka','net.region1.li14':'🇰🇭 Cambodia',
        'net.region2.title':'Europe / Middle East / Africa',
        'net.region2.li1':'🇬🇧 United Kingdom','net.region2.li2':'🇩🇪 Germany','net.region2.li3':'🇫🇷 France','net.region2.li4':'🇮🇹 Italy',
        'net.region2.li5':'🇳🇱 Netherlands','net.region2.li6':'🇧🇪 Belgium','net.region2.li7':'🇪🇸 Spain','net.region2.li8':'🇵🇱 Poland',
        'net.region2.li9':'🇹🇷 Türkiye','net.region2.li10':'🇸🇦 Saudi Arabia','net.region2.li11':'🇮🇷 Iran','net.region2.li12':'🇰🇼 Kuwait',
        'net.region2.li13':'🇿🇦 South Africa','net.region2.li14':'🇳🇬 Nigeria & more',
        'net.region3.title':'Americas / Australia & Oceania',
        'net.region3.li1':'🇺🇸 USA (LA · Chicago · New York · Houston · Atlanta)','net.region3.li2':'🇨🇦 Canada (Toronto)','net.region3.li3':'🇲🇽 Mexico',
        'net.region3.li4':'🇨🇴 Colombia','net.region3.li5':'🇧🇷 Brazil','net.region3.li6':'🇦🇷 Argentina','net.region3.li7':'🇨🇱 Chile',
        'net.region3.li8':'🇵🇪 Peru','net.region3.li9':'🇵🇦 Panama','net.region3.li10':'🇬🇹 Guatemala & more Central America','net.region3.li11':'🇦🇺 Australia','net.region3.li12':'🇳🇿 New Zealand',
        'net.cta.btn':'Global Network Inquiry →',
        /* ── FAQ ── */
        'faq.q1':'How can I get a sea freight quote?','faq.a1':'You can request a quote via the website inquiry form or by calling us at <a href="tel:02-3142-4051" class="tel-link">02-3142-4051</a>. Provide cargo item, weight/volume, origin, and destination for a quick quote.',
        'faq.q2':'What is the difference between FCL and LCL?','faq.a2':'FCL (Full Container Load) uses a dedicated container — suitable for large shipments. LCL (Less than Container Load) shares a container with other shippers — ideal for small volumes. FCL offers higher security; LCL offers economical transport for small quantities.',
        'faq.q3':'How quickly is urgent air cargo processed?','faq.a3':'Urgent air cargo can depart on the same day or next day after receipt. This varies by cargo type, destination, and flight schedule.',
        'faq.q4':'What documents are required for import customs clearance?','faq.a4':'A Commercial Invoice, Packing List, B/L (Bill of Lading) or AWB (Air Waybill) are required. Depending on the cargo, a Certificate of Origin, quarantine certificate, and various permits may be additionally required.',
        'faq.q5':'What about cargo insurance?','faq.a5':'Taein General Logistics has KRW 1 billion in cargo liability insurance. For high-value cargo, we can also arrange separate cargo insurance (All Risk/WA).',
        'faq.q6':'Which countries do you service?','faq.a6':'As a WCA (World Cargo Association) member, we cooperate with 120+ overseas partners in 40+ countries including Asia, Europe, Americas, Middle East, and Africa.',
        'faq.q7':'Can I receive the same service at the Busan branch?','faq.a7':'Yes, our Busan branch (051-464-7056) provides the same logistics services as the Seoul headquarters with specialization in Busan Port-connected services.',
        'faq.q8':'What is 3PL service?','faq.a8':'3PL (Third Party Logistics) is a service where a professional company takes charge of a company\'s logistics operations. Companies can focus on their core business while utilizing professional logistics infrastructure.',
        'faq.q9':'Can you transport hazardous goods?','faq.a9':'Yes, we can transport hazardous goods in accordance with IMDG Code (sea) and IATA (air) international regulations. Transport methods and costs vary by classification — please consult in advance.',
        'faq.q10':'Can I check cargo status during transport?','faq.a10':'Yes, we guide you to check cargo status in real time through the shipping line\'s or airline\'s tracking system. Our representative also regularly reports progress.',
        'faq.cta.title':"Can't find the answer you're looking for?",'faq.cta.desc':'Our expert consultants will help you directly.','faq.cta.btn':'1-on-1 Inquiry',
        /* ── Customer Service ── */
        'cs.hq.tag':'HQ · SEOUL','cs.hq.addr':'Hyoseong B/D 4F, 112 Worldcup-ro, Mapo-gu, Seoul',
        'cs.busan.tag':'Branch · BUSAN','cs.busan.addr':'Korea B/D 3F, 12-1 Chungjang-daero 5-gil, Jung-gu, Busan',
        'cs.label.phone':'Phone','cs.label.fax':'Fax','cs.label.email':'Email','cs.label.addr':'Address',
        'cs.hours':'Weekdays 09:00 ~ 18:00','cs.faq.btn':'View FAQ',
        'cs.form.title':'Online Quote Inquiry','cs.form.desc':'Fill in the form below and our representative will get back to you quickly.',
        'cs.form.name':'Name / Company *','cs.form.phone':'Phone *','cs.form.email':'Email',
        'cs.form.service':'Service','cs.form.service.placeholder':'Select a service',
        'cs.form.svc.fcl':'Ocean Freight (FCL)','cs.form.svc.lcl':'Ocean Freight (LCL)','cs.form.svc.air':'Air Freight',
        'cs.form.svc.land':'Land Transport','cs.form.svc.customs':'Customs / Forwarding','cs.form.svc.sol':'Logistics Solutions','cs.form.svc.other':'Other',
        'cs.form.message':'Message *','cs.form.agree':'I agree to the collection and use of personal information. <a href="#">[View Details]</a>','cs.form.submit':'Send Inquiry',
        /* ── Notice ── */
        'notice.col.num':'No.','notice.col.title':'Title','notice.col.category':'Category','notice.col.date':'Date','notice.col.views':'Views',
        'notice.tag.notice':'Notice','notice.tag.general':'General','notice.pagination.prev':'Prev','notice.pagination.next':'Next',
        'notice.total':'Total <strong>30</strong> posts',
        'notice.title1':'Logistics Operations Guide for Lunar New Year 2026 <span class="new-badge">NEW</span>',
        'notice.title2':'Notice: Incheon Logistics Center Expansion Relocation',
        'notice.title3':'Freight Rate Adjustment Notice (January 2026)',
        'notice.title4':'Taein Logistics ISO 9001:2015 Re-certification Complete',
        'notice.title5':'Smart Logistics System Upgrade Complete',
        'notice.title6':'Logistics Operations Guide for Chuseok Holiday',
        'notice.title7':'WCA Annual General Meeting Participation Notice',
        'notice.title8':'China Route Rate Adjustment Notice',
        'notice.title9':'Busan Branch Relocation Complete',
        'notice.title10':'2025 Second-Half New Employee Recruitment Notice',
      }
    };

    const toggleBtn = document.getElementById('langToggle');
    const mobileToggleBtn = document.getElementById('mobileLangToggle');
    const mobLangHdr = document.getElementById('mobLangHdr');
    let lang = localStorage.getItem('lang') || 'ko';

    function applyLang(l) {
      lang = l;
      localStorage.setItem('lang', l);
      if (toggleBtn) toggleBtn.textContent = l === 'ko' ? 'EN' : 'KO';
      if (mobileToggleBtn) mobileToggleBtn.textContent = l === 'ko' ? '🌐 English' : '🌐 한국어';
      if (mobLangHdr) {
        const span = mobLangHdr.querySelector('.mob-lang-text');
        if (span) span.textContent = l === 'ko' ? 'EN' : 'KO';
      }
      document.querySelectorAll('[data-i18n]').forEach(el => {
        const v = LANGS[l][el.dataset.i18n];
        if (v !== undefined) el.textContent = v;
      });
      document.querySelectorAll('[data-i18n-html]').forEach(el => {
        const v = LANGS[l][el.dataset.i18nHtml];
        if (v !== undefined) el.innerHTML = v;
      });
    }

    if (toggleBtn) toggleBtn.addEventListener('click', () => applyLang(lang === 'ko' ? 'en' : 'ko'));
    if (mobileToggleBtn) mobileToggleBtn.addEventListener('click', () => applyLang(lang === 'ko' ? 'en' : 'ko'));
    if (mobLangHdr) mobLangHdr.addEventListener('click', () => applyLang(lang === 'ko' ? 'en' : 'ko'));
    applyLang(lang);
  })();

  /* ── 견적 인라인 연락처 전환 ── */
  window.openQuoteModal = function(type) {
    var labelMap = { fcl:'해운 FCL', lcl:'해운 LCL', air:'항공운송', land:'육상운송' };
    var from = '', to = '', detail = '', qty = '';

    if (type === 'fcl') {
      from   = (document.getElementById('fcl-from')||{}).value||'';
      to     = (document.getElementById('fcl-to')||{}).value||'';
      detail = (document.getElementById('fcl-container')||{}).value||'';
      qty    = (document.getElementById('fcl-qty')||{}).value||'1';
    } else if (type === 'lcl') {
      from   = (document.getElementById('lcl-from')||{}).value||'';
      to     = (document.getElementById('lcl-to')||{}).value||'';
      detail = (document.getElementById('lcl-weight')||{}).value||'';
      qty    = (document.getElementById('lcl-qty')||{}).value||'1';
    } else if (type === 'air') {
      from   = (document.getElementById('air-from')||{}).value||'';
      to     = (document.getElementById('air-to')||{}).value||'';
      detail = (document.getElementById('air-weight')||{}).value||'';
    } else if (type === 'land') {
      from   = (document.getElementById('land-from')||{}).value||'';
      to     = (document.getElementById('land-to')||{}).value||'';
      detail = (document.getElementById('land-cargo')||{}).value||'';
    }

    var parts = [labelMap[type]];
    if (from && to) parts.push(from + ' → ' + to);
    if (qty && (type==='fcl'||type==='lcl')) parts.push('수량: ' + qty);
    if (detail) parts.push(detail);
    var summary = parts.join(' | ');

    var summaryEl = document.getElementById('inline-contact-summary');
    var detailEl  = document.getElementById('ic-detail');
    if (summaryEl) summaryEl.textContent = summary;
    if (detailEl)  detailEl.value = summary;

    // 탭/pane 숨기고 인라인 패널 표시
    var panes = document.querySelector('.q-panes');
    var tabs  = document.querySelector('.q-tabs');
    var panel = document.getElementById('inline-contact-panel');
    if (panes) panes.style.display = 'none';
    if (tabs)  tabs.style.display  = 'none';
    if (panel) {
      panel.style.display = 'block';
      // 패널 상단이 화면 상단에 오도록 스크롤 (헤더 높이 70px 오프셋)
      setTimeout(function() {
        var card = document.querySelector('.quote-card');
        if (card) {
          var top = card.getBoundingClientRect().top + window.pageYOffset - 80;
          window.scrollTo({ top: top, behavior: 'smooth' });
        }
      }, 60);
    }
  };

  (function initInlineContact() {
    var panel   = document.getElementById('inline-contact-panel');
    var backBtn = document.getElementById('inlineContactBack');
    var form    = document.getElementById('inlineContactForm');
    if (!panel) return;

    if (backBtn) {
      backBtn.addEventListener('click', function() {
        panel.style.display = 'none';
        var panes = document.querySelector('.q-panes');
        var tabs  = document.querySelector('.q-tabs');
        if (panes) panes.style.display = '';
        if (tabs)  tabs.style.display  = '';
        if (form)  form.reset();
      });
    }

    /* 모두 동의하기 마스터 체크박스 */
    var agreeAll = document.getElementById('ic-agree-all');
    var subChecks = form ? form.querySelectorAll('.ic-agree-section input[type="checkbox"]:not(#ic-agree-all)') : [];
    if (agreeAll) {
      agreeAll.addEventListener('change', function() {
        subChecks.forEach(function(cb) { cb.checked = agreeAll.checked; });
      });
      subChecks.forEach(function(cb) {
        cb.addEventListener('change', function() {
          agreeAll.checked = Array.from(subChecks).every(function(c) { return c.checked; });
        });
      });
    }

    if (form) {
      form.addEventListener('submit', function(e) {
        e.preventDefault();
        var name    = (document.getElementById('ic-name')    || {}).value || '';
        var email   = (document.getElementById('ic-email')   || {}).value || '';
        var phone   = (document.getElementById('ic-phone')   || {}).value || '';
        var company = (document.getElementById('ic-company') || {}).value || '';
        var detail  = (document.getElementById('ic-detail')  || {}).value || '';

        var subject = '[태인종합물류 견적 문의] ' + (company || name);
        var body =
          '■ 이름: '   + name    + '\n' +
          '■ 이메일: ' + email   + '\n' +
          '■ 연락처: ' + phone   + '\n' +
          '■ 회사명: ' + company + '\n' +
          (detail ? '■ 문의 내용: ' + detail + '\n' : '');

        window.location.href =
          'mailto:caleb@ttt3.co.kr' +
          '?subject=' + encodeURIComponent(subject) +
          '&body='    + encodeURIComponent(body);
      });
    }
  })();

  /* ── 선박 영상 4개 끊김없이 순차 재생 ── */
  (function initSeaVideos() {
    var SRCS = [
      'assets/sea-video-1.mov',
      'assets/sea-video-2.mov',
      'assets/sea-video-3.mov',
      'assets/sea-video-4.mov'
    ];
    var ids  = ['seaVid1','seaVid2','seaVid3','seaVid4'];
    var vids = ids.map(function(id){ return document.getElementById(id); }).filter(Boolean);
    if (!vids.length) return;

    var cur = 0, switching = false;

    /* 영상별 시작 오프셋 (초) — 2·3·4번 영상 1초 스킵 */
    var SKIP = [0, 1.0, 1.0, 1.0];

    /* fetch() 로 Blob URL 생성 → 모바일 preload 한계 완전 우회 */
    SRCS.slice(1).forEach(function(src, i) {
      var idx = i + 1;
      fetch(src)
        .then(function(r){ return r.blob(); })
        .then(function(blob){
          var url = URL.createObjectURL(blob);
          vids[idx].src = url;
          vids[idx].load();
          /* canplaythrough 후 seek + play→pause 로 디코더 완전 워밍업 */
          vids[idx].addEventListener('canplaythrough', function(){
            vids[idx].currentTime = SKIP[idx];
            vids[idx].play().then(function(){
              vids[idx].pause();
            }).catch(function(){});
          }, { once: true });
        })
        .catch(function(){
          vids[idx].src = src;
          vids[idx].load();
        });
    });

    function doSwitch(nextIdx) {
      var prev = vids[cur], nxt = vids[nextIdx];
      nxt.currentTime = SKIP[nextIdx];
      nxt.play().catch(function(){});
      nxt.classList.add('sea-vid--active');
      setTimeout(function(){
        prev.classList.remove('sea-vid--active');
        prev.pause();
        prev.currentTime = SKIP[cur] || 0;
        cur = nextIdx; switching = false;
      }, 250);
    }

    function switchTo(nextIdx) {
      if (switching) return;
      switching = true;
      var nxt = vids[nextIdx];
      if (nxt.readyState >= 3) {
        doSwitch(nextIdx);
      } else {
        nxt.addEventListener('canplay', function(){ doSwitch(nextIdx); }, { once: true });
        if (!nxt.src) { nxt.src = SRCS[nextIdx]; nxt.load(); }
      }
    }

    vids.forEach(function(v, i) {
      v.addEventListener('timeupdate', function(){
        if (cur===i && !switching && v.duration && (v.duration - v.currentTime) < 1.0)
          switchTo((i+1) % vids.length);
      });
      v.addEventListener('ended', function(){
        if (cur===i && !switching) switchTo((i+1) % vids.length);
      });
    });
  })();

});
