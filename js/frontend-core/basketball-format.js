export function valueOrDash(value) {
  return value == null || String(value).trim() === '' ? '--' : String(value).trim();
}

export function statusText(result) {
  const status = String(result && result.status || '').toLowerCase();
  if (status === 'over') return 'Финальный счет';
  if (status === 'live') return 'Матч идет';
  return 'Матч';
}

export function clockText(result) {
  const q = String(result && result.quarter || '').trim();
  const t = String(result && result.time || '').trim();
  if (q && t) return `${q} · ${t}`;
  return q || t || 'Матч';
}

