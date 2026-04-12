import { API_BASE, readError } from './http.js';

export async function apiMe() {
  const resp = await fetch(`${API_BASE}/api/me`, { method: 'GET', credentials: 'include' });
  if (!resp.ok) throw new Error((await readError(resp)) || 'load me failed');
  return await resp.json();
}

export async function apiLogout() {
  const resp = await fetch(`${API_BASE}/api/auth/logout`, { method: 'POST', credentials: 'include' });
  if (!resp.ok) throw new Error((await readError(resp)) || 'logout failed');
  return await resp.json();
}
