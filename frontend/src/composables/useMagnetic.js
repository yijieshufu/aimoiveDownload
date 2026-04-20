import { onMounted, onUnmounted } from 'vue';

function clamp(n, min, max) {
  return Math.max(min, Math.min(max, n));
}

function attachMagnetic(el, opts = {}) {
  if (!el) return () => {};
  const strength = Number(opts.strength ?? 10);
  const maxTranslate = Number(opts.maxTranslate ?? 10);
  const hasFinePointer = window.matchMedia && window.matchMedia('(pointer: fine)').matches;
  if (!hasFinePointer) return () => {};

  let raf = 0;
  let rect = null;

  const onEnter = () => {
    rect = el.getBoundingClientRect();
    el.style.willChange = 'transform';
    el.style.transition = 'transform 140ms ease-out';
  };

  const onMove = (e) => {
    if (!rect) rect = el.getBoundingClientRect();
    const cx = rect.left + rect.width / 2;
    const cy = rect.top + rect.height / 2;
    const dx = (e.clientX - cx) / strength;
    const dy = (e.clientY - cy) / strength;
    const tx = clamp(dx, -maxTranslate, maxTranslate);
    const ty = clamp(dy, -maxTranslate, maxTranslate);
    if (raf) cancelAnimationFrame(raf);
    raf = requestAnimationFrame(() => {
      el.style.transform = `translate3d(${tx}px, ${ty}px, 0)`;
    });
  };

  const onLeave = () => {
    rect = null;
    if (raf) cancelAnimationFrame(raf);
    raf = 0;
    el.style.transition = 'transform 220ms cubic-bezier(0.2, 1, 0.2, 1)';
    el.style.transform = 'translate3d(0,0,0)';
    setTimeout(() => {
      el.style.willChange = '';
    }, 260);
  };

  el.addEventListener('pointerenter', onEnter);
  el.addEventListener('pointermove', onMove);
  el.addEventListener('pointerleave', onLeave);

  return () => {
    if (raf) cancelAnimationFrame(raf);
    el.removeEventListener('pointerenter', onEnter);
    el.removeEventListener('pointermove', onMove);
    el.removeEventListener('pointerleave', onLeave);
  };
}

export function useMagnetic(selector = '[data-magnetic]', opts = {}) {
  const cleanups = [];
  onMounted(() => {
    document.querySelectorAll(selector).forEach((el) => {
      cleanups.push(attachMagnetic(el, opts));
    });
  });
  onUnmounted(() => {
    while (cleanups.length) cleanups.pop()?.();
  });
}

