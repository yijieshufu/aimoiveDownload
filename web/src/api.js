const API_BASE = 'http://localhost:8001';

async function readError(resp) {
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

export async function apiExtract(url) {
  const resp = await fetch(`${API_BASE}/api/extract`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ url }),
  });
  if (!resp.ok) throw new Error((await readError(resp)) || '解析失败');
  return await resp.json();
}

export async function apiDownload(url, formatId) {
  const resp = await fetch(
    `${API_BASE}/api/download?url=${encodeURIComponent(url)}&format_id=${encodeURIComponent(formatId)}`,
    { method: 'GET' }
  );
  if (!resp.ok) throw new Error((await readError(resp)) || '下载失败');
  return await resp.json();
}

export async function apiSummarize(url) {
  const resp = await fetch(`${API_BASE}/api/summarize`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ url }),
  });
  if (!resp.ok) throw new Error((await readError(resp)) || '创建总结任务失败');
  return await resp.json();
}

export async function apiSummarizeStatus(taskId) {
  const resp = await fetch(`${API_BASE}/api/summarize/${encodeURIComponent(taskId)}`, {
    method: 'GET',
  });
  if (!resp.ok) throw new Error((await readError(resp)) || '查询总结任务失败');
  return await resp.json();
}

export async function apiSummarizeQa(taskId, question) {
  const resp = await fetch(`${API_BASE}/api/summarize/${encodeURIComponent(taskId)}/qa`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ question }),
  });
  if (!resp.ok) throw new Error((await readError(resp)) || '问答失败');
  return await resp.json();
}

export async function apiGetTabs() {
  const resp = await fetch(`${API_BASE}/api/ui/tabs`, { method: 'GET' });
  if (!resp.ok) throw new Error((await readError(resp)) || 'load tabs failed');
  return await resp.json();
}

export async function apiSaveTabs(tabs) {
  const resp = await fetch(`${API_BASE}/api/ui/tabs`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ tabs }),
  });
  if (!resp.ok) throw new Error((await readError(resp)) || 'save tabs failed');
  return await resp.json();
}

export async function apiGetMindmap(taskId) {
  const resp = await fetch(`${API_BASE}/api/summarize/${encodeURIComponent(taskId)}/mindmap`, {
    method: 'GET',
  });
  if (!resp.ok) throw new Error((await readError(resp)) || 'load mindmap failed');
  return await resp.json();
}

export async function apiSaveMindmap(taskId, mindmap) {
  const resp = await fetch(`${API_BASE}/api/summarize/${encodeURIComponent(taskId)}/mindmap`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ mindmap }),
  });
  if (!resp.ok) throw new Error((await readError(resp)) || 'save mindmap failed');
  return await resp.json();
}

export async function apiTranslateSummary(taskId, targetLanguage = 'zh') {
  const resp = await fetch(`${API_BASE}/api/summarize/${encodeURIComponent(taskId)}/translate`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ target_language: targetLanguage }),
  });
  if (!resp.ok) throw new Error((await readError(resp)) || 'translate failed');
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

