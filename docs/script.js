/* ═══════════════════════════════════════════════════
   Portfolio Monitor — GitHub Pages Interactions
   ═══════════════════════════════════════════════════ */

// ─── Sticky Nav Background ───
const nav = document.getElementById('nav');
const onScroll = () => {
  nav.classList.toggle('scrolled', window.scrollY > 32);
};
window.addEventListener('scroll', onScroll, { passive: true });
onScroll();

// ─── Scroll Reveal ───
const revealEls = document.querySelectorAll(
  '.feature-card, .pipeline-step, .report-item, .tech-item, .setup-step, .footer-cta'
);

const observer = new IntersectionObserver(
  (entries) => {
    entries.forEach((entry) => {
      if (entry.isIntersecting) {
        entry.target.setAttribute('data-reveal', '');
        entry.target.classList.add('visible');
        observer.unobserve(entry.target);
      }
    });
  },
  { threshold: 0.15, rootMargin: '0px 0px -40px 0px' }
);

revealEls.forEach((el) => {
  el.setAttribute('data-reveal', '');
  observer.observe(el);
});

// ─── Smooth anchor scroll (fallback for old browsers) ───
document.querySelectorAll('a[href^="#"]').forEach((anchor) => {
  anchor.addEventListener('click', function (e) {
    const target = document.querySelector(this.getAttribute('href'));
    if (target) {
      e.preventDefault();
      target.scrollIntoView({ behavior: 'smooth', block: 'start' });
    }
  });
});
