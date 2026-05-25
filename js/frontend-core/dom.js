export function setText(id, value, fallback = '--') {
  const el = typeof id === 'string' ? document.getElementById(id) : id;
  if (!el) return;
  const empty = value == null || String(value).trim() === '';
  el.textContent = empty ? fallback : String(value).trim();
  el.classList.toggle('dim', empty);
}

export function setImageWithFallback(img, url, { fallback, visibleDisplay = 'block', hiddenDisplay = 'none' } = {}) {
  if (!img) return;

  function showFallback(show) {
    img.style.display = show ? hiddenDisplay : visibleDisplay;
    if (fallback) fallback.style.display = show ? '' : 'none';
  }

  if (!url) {
    img.removeAttribute('src');
    showFallback(true);
    return;
  }

  img.onerror = () => showFallback(true);
  img.onload = () => showFallback(false);
  if (img.src !== url) img.src = url;
}

