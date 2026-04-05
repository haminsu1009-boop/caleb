/* ============================================================
   (주)태엔종합물류 — Main JavaScript
   ============================================================ */

document.addEventListener('DOMContentLoaded', () => {

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

  /* ── HERO SLIDER ── */
  const slides  = document.querySelectorAll('.slide');
  const dots    = document.querySelectorAll('.dot');
  let current   = 0;
  let autoPlay;

  const goTo = (idx) => {
    slides[current].classList.remove('active');
    dots[current].classList.remove('active');
    current = (idx + slides.length) % slides.length;
    slides[current].classList.add('active');
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
