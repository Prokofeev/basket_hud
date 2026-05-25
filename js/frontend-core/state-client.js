export class OverlayStateClient {
  constructor({
    endpoints,
    intervalMs = 3000,
    staleAfterMs = 12000,
    timeoutMs = 2500,
    keepLastGood = true,
    fetcher = window.fetch.bind(window),
  }) {
    this.endpoints = endpoints;
    this.intervalMs = intervalMs;
    this.staleAfterMs = staleAfterMs;
    this.timeoutMs = timeoutMs;
    this.keepLastGood = keepLastGood;
    this.fetcher = fetcher;
    this.listeners = new Map();
    this.lastGood = {};
    this.lastOkAt = 0;
    this.timer = null;
    this.stopped = true;
  }

  on(type, fn) {
    const list = this.listeners.get(type) || [];
    list.push(fn);
    this.listeners.set(type, list);
    return () => this.listeners.set(type, list.filter(item => item !== fn));
  }

  emit(type, payload) {
    (this.listeners.get(type) || []).forEach(fn => fn(payload));
  }

  start() {
    this.stopped = false;
    this.emit('status', { phase: 'loading', stale: false });
    this.tick();
  }

  stop() {
    this.stopped = true;
    clearTimeout(this.timer);
  }

  async tick() {
    try {
      const data = await this.loadAll();
      this.lastGood = { ...this.lastGood, ...data };
      this.lastOkAt = Date.now();
      this.emit('data', { data: this.lastGood, phase: 'ready' });
      this.emit('status', { phase: 'ready', stale: false });
      this.schedule(this.intervalMs);
    } catch (error) {
      const age = Date.now() - this.lastOkAt;
      const stale = !this.lastOkAt || age >= this.staleAfterMs;
      this.emit('status', {
        phase: stale ? 'stale' : 'reconnecting',
        stale,
        error,
        lastGood: this.keepLastGood ? this.lastGood : null,
      });
      this.schedule(Math.min(this.intervalMs * 2, 10000));
    }
  }

  schedule(ms) {
    if (!this.stopped) this.timer = setTimeout(() => this.tick(), ms);
  }

  async loadAll() {
    const entries = await Promise.all(
      Object.entries(this.endpoints).map(async ([key, urlFactory]) => {
        const controller = new AbortController();
        const timeout = setTimeout(() => controller.abort(), this.timeoutMs);
        try {
          const response = await this.fetcher(urlFactory(), {
            signal: controller.signal,
            cache: 'no-store',
          });
          if (!response.ok) throw new Error(`${key}: HTTP ${response.status}`);
          return [key, await response.json()];
        } finally {
          clearTimeout(timeout);
        }
      })
    );
    return Object.fromEntries(entries);
  }
}

