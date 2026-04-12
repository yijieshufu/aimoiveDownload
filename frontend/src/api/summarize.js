import { API_BASE, throwIfNotOk } from './http.js';

export async function apiSummarize(url) {
  const resp = await fetch(`${API_BASE}/api/summarize`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    credentials: 'include',
    body: JSON.stringify({ url }),
  });
  await throwIfNotOk(resp, '创建总结任务失败');
  return await resp.json();
}

export async function apiSummarizeStreamCreate(url) {
  const resp = await fetch(`${API_BASE}/api/summarize`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    credentials: 'include',
    body: JSON.stringify({ url, stream: true }),
  });
  await throwIfNotOk(resp, '创建流式总结任务失败');
  return await resp.json();
}

export function apiSummarizeStreamUrl(taskId) {
  return `${API_BASE}/api/summarize/${encodeURIComponent(taskId)}/stream`;
}

export async function apiSummarizeStatus(taskId) {
  const resp = await fetch(`${API_BASE}/api/summarize/${encodeURIComponent(taskId)}`, {
    method: 'GET',
    credentials: 'include',
  });
  await throwIfNotOk(resp, '查询总结任务失败');
  return await resp.json();
}

export async function apiSummarizeQa(taskId, question) {
  const resp = await fetch(`${API_BASE}/api/summarize/${encodeURIComponent(taskId)}/qa`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    credentials: 'include',
    body: JSON.stringify({ question }),
  });
  await throwIfNotOk(resp, '问答失败');
  return await resp.json();
}

export async function apiSummarizeChat(taskId, message) {
  const resp = await fetch(`${API_BASE}/api/summarize/${encodeURIComponent(taskId)}/chat`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    credentials: 'include',
    body: JSON.stringify({ message }),
  });
  await throwIfNotOk(resp, 'chat failed');
  return await resp.json();
}

export async function apiTranslateSummary(taskId, targetLanguage = 'zh') {
  const resp = await fetch(`${API_BASE}/api/summarize/${encodeURIComponent(taskId)}/translate`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    credentials: 'include',
    body: JSON.stringify({ target_language: targetLanguage }),
  });
  await throwIfNotOk(resp, 'translate failed');
  return await resp.json();
}

export async function apiGetSubtitles(taskId) {
  const resp = await fetch(`${API_BASE}/api/summarize/${encodeURIComponent(taskId)}/subtitles`, {
    method: 'GET',
    credentials: 'include',
  });
  await throwIfNotOk(resp, 'load subtitles failed');
  return await resp.json();
}

export function apiSubtitleDownloadUrl(taskId, format) {
  return `${API_BASE}/api/summarize/${encodeURIComponent(taskId)}/subtitles/download?format=${encodeURIComponent(format)}`;
}
