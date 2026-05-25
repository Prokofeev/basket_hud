export class AnimationManager {
  constructor({ changedClass = 'changed', animateInitial = false } = {}) {
    this.changedClass = changedClass;
    this.animateInitial = animateInitial;
    this.previous = new Map();
    this.reduceMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  }

  setText(el, value, { fallback = '--', dimClass = 'dim', key = el && el.id } = {}) {
    if (!el) return;
    const empty = value == null || value === '';
    const next = empty ? fallback : String(value);
    const had = this.previous.has(key);
    const prev = this.previous.get(key);

    el.textContent = next;
    el.classList.toggle(dimClass, empty);

    if (!this.reduceMotion && (had || this.animateInitial) && prev !== next) {
      el.classList.remove(this.changedClass);
      requestAnimationFrame(() => el.classList.add(this.changedClass));
    }

    this.previous.set(key, next);
  }
}

