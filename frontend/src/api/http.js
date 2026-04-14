function trimTrailingSlash(value) {
  return String(value || '').replace(/\/+$/, '');
}

function isLocalHostname(hostname) {
  return ['localhost', '127.0.0.1', '[::1]', '::1'].includes(String(hostname || '').toLowerCase());
}

function resolveApiBase() {
  const envBase = trimTrailingSlash(import.meta.env.VITE_API_BASE);
  if (envBase) return envBase;

  if (typeof window === 'undefined' || !window.location) return '';

  const { protocol, hostname, port, pathname } = window.location;

  if (protocol === 'file:') {
    return 'http://127.0.0.1:8003';
  }

  // 从任意本地后端直接托管 /frontend/... 时，优先走同源 /api。
  if (isLocalHostname(hostname) && port && String(pathname || '').startsWith('/frontend/')) {
    return '';
  }

  // Vite 开发服务器或同域代理场景优先走相对路径，避免跨域与 cookie 问题。
  if (port === '5173' || port === '4173' || port === '5174') {
    return '';
  }

  // 对本机其他静态服务兜底直连后端，避免页面能打开但 /api 不可达时直接 Failed to fetch。
  if (isLocalHostname(hostname)) {
    return 'http://127.0.0.1:8003';
  }

  return '';
}

export const API_BASE = resolveApiBase();

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
