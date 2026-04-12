export const API_BASE = '';

export async function readError(resp) {
  try {
    const ct = resp.headers.get('content-type') || '';
    if (ct.includes('application/json')) {
      const j = await resp.json();
      return j.detail || JSON.stringify(j);
    }
    return await resp.text();
  } catch {
    return '';
  }
}

/** @param {Response} resp */
export async function throwIfNotOk(resp, fallbackMessage) {
  if (resp.ok) return;
  const detail = await readError(resp);
  const err = new Error(String(detail || fallbackMessage));
  err.status = resp.status;
  throw err;
}
