export function createUrlResolver(base = window.location.href) {
  const page = new URL(base);

  function media(pathOrUrl) {
    const raw = String(pathOrUrl || '').trim();
    if (!raw) return '';
    if (/^(https?:|data:|blob:)/i.test(raw)) return raw;
    return new URL(raw.replace(/^\/+/, ''), page.origin + '/').href;
  }

  function json(path) {
    const url = new URL(String(path || '').replace(/^\/+/, ''), page.origin + '/');
    url.searchParams.set('_', String(Date.now()));
    return url.href;
  }

  return { json, media };
}

