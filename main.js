/* ============================================================
   (주)태엔종합물류 — Main JavaScript
   ============================================================ */

document.addEventListener('DOMContentLoaded', () => {

  /* ── HERO PARTICLES ── */
  const particleContainer = document.getElementById('heroParticles');
  if (particleContainer) {
    const rand = (min, max) => Math.random() * (max - min) + min;

    // Floating dots
    for (let i = 0; i < 22; i++) {
      const dot = document.createElement('span');
      dot.className = 'p-dot';
      const size = rand(3, 9);
      dot.style.cssText = `
        width:${size}px; height:${size}px;
        left:${rand(2,98)}%; top:${rand(5,90)}%;
        animation-duration:${rand(4,9)}s;
        animation-delay:${rand(0,6)}s;
        opacity:${rand(0.25,0.65)};
      `;
      particleContainer.appendChild(dot);
    }

    // Pulsing rings
    for (let i = 0; i < 8; i++) {
      const ring = document.createElement('span');
      ring.className = 'p-ring';
      const size = rand(20, 60);
      ring.style.cssText = `
        width:${size}px; height:${size}px;
        left:${rand(5,90)}%; top:${rand(10,85)}%;
        animation-duration:${rand(3,7)}s;
        animation-delay:${rand(0,5)}s;
      `;
      particleContainer.appendChild(ring);
    }

    // Logistics icon SVGs (ship, plane, truck)
    const icons = [
      `<svg viewBox="0 0 48 48" width="48" height="48" fill="none" stroke="white" stroke-width="1.5"><path d="M4 34l4-12h32l4 12H4z"/><path d="M10 22V14h28v8"/><path d="M4 34c0 4 8 6 20 6s20-2 20-6"/><line x1="24" y1="14" x2="24" y2="22"/></svg>`,
      `<svg viewBox="0 0 48 48" width="48" height="48" fill="none" stroke="white" stroke-width="1.5"><path d="M36 38l-4-14 6-6a4 4 0 0 0-6-6l-14 7-6-3a2 2 0 0 0-2 .5L6 19l13 7-2 7-4 1v3l5-2 2 5 4-3 7-2 8 4 2-3a2 2 0 0 0 .4-2z"/></svg>`,
      `<svg viewBox="0 0 48 48" width="48" height="48" fill="none" stroke="white" stroke-width="1.5"><rect x="2" y="8" width="28" height="24" rx="2"/><path d="M30 16h8l6 8v8H30V16z"/><circle cx="11" cy="36" r="5"/><circle cx="37" cy="36" r="5"/></svg>`
    ];
    icons.forEach((svg, i) => {
      const el = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
      const wrapper = document.createElement('div');
      wrapper.className = 'p-svg';
      wrapper.innerHTML = svg;
      const w = wrapper.firstChild;
      w.style.cssText = `
        position:absolute;
        left:${[15, 55, 75][i]}%; top:${[20, 65, 35][i]}%;
        animation:particleFloat ease-in-out infinite;
        animation-duration:${rand(7,12)}s;
        animation-delay:${i * 2}s;
        opacity:0.15;
        pointer-events:none;
      `;
      particleContainer.appendChild(w);
    });
  }

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

});
