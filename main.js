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

});
