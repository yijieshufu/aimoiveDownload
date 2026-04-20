import { API_BASE, readError } from './http.js';

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

export async function apiGetNotesEdit(taskId) {
  const resp = await fetch(`${API_BASE}/api/summarize/${encodeURIComponent(taskId)}/notes-edit`, {
    method: 'GET',
  });
  if (!resp.ok) throw new Error((await readError(resp)) || 'load notes edit failed');
  return await resp.json();
}

export async function apiSaveNotesEdit(taskId, noteSections) {
  const resp = await fetch(`${API_BASE}/api/summarize/${encodeURIComponent(taskId)}/notes-edit`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ note_sections: noteSections }),
  });
  if (!resp.ok) throw new Error((await readError(resp)) || 'save notes edit failed');
  return await resp.json();
}

export async function apiDeleteNotesEdit(taskId) {
  const resp = await fetch(`${API_BASE}/api/summarize/${encodeURIComponent(taskId)}/notes-edit`, {
    method: 'DELETE',
  });
  if (!resp.ok) throw new Error((await readError(resp)) || 'delete notes edit failed');
  return await resp.json();
}
