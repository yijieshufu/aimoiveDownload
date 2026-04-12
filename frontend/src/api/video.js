import { API_BASE, throwIfNotOk } from './http.js';

export async function apiExtract(url) {
  const resp = await fetch(`${API_BASE}/api/extract`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    credentials: 'include',
    body: JSON.stringify({ url }),
  });
  await throwIfNotOk(resp, '解析失败');
  return await resp.json();
}

export async function apiDownload(url, formatId) {
  const resp = await fetch(
    `${API_BASE}/api/download?url=${encodeURIComponent(url)}&format_id=${encodeURIComponent(formatId)}`,
    { method: 'GET', credentials: 'include' }
  );
  await throwIfNotOk(resp, '下载失败');
  return await resp.json();
}

export function apiDownloadFileUrl(filePath) {
  return `${API_BASE}/api/download/file?file_path=${encodeURIComponent(filePath)}`;
}

export function apiAbsolute(path) {
  if (!path) return '';
  if (path.startsWith('http://') || path.startsWith('https://')) return path;
  return `${API_BASE}${path}`;
}
