import { API_BASE, readError } from './http.js';

export async function apiBillingCreateWeChatpay(amount = 1999, title = '升级 Pro（月度）') {
  const resp = await fetch(
    `${API_BASE}/api/billing/wechatpay/create?amount=${encodeURIComponent(amount)}&title=${encodeURIComponent(title)}`,
    { method: 'POST', credentials: 'include' }
  );
  if (!resp.ok) throw new Error((await readError(resp)) || 'wechatpay create failed');
  return await resp.json();
}

export async function apiBillingCreateAlipay(amount = 1999, title = '升级 Pro（月度）') {
  const resp = await fetch(
    `${API_BASE}/api/billing/alipay/create?amount=${encodeURIComponent(amount)}&title=${encodeURIComponent(title)}`,
    { method: 'POST', credentials: 'include' }
  );
  if (!resp.ok) throw new Error((await readError(resp)) || 'alipay create failed');
  return await resp.json();
}

export async function apiBillingOrder(orderId) {
  const resp = await fetch(`${API_BASE}/api/billing/orders/${encodeURIComponent(orderId)}`, {
    method: 'GET',
    credentials: 'include',
  });
  if (!resp.ok) throw new Error((await readError(resp)) || 'order status failed');
  return await resp.json();
}

export async function apiBillingMockMarkPaid(orderId) {
  const resp = await fetch(`${API_BASE}/api/billing/mock/mark-paid/${encodeURIComponent(orderId)}`, {
    method: 'POST',
    credentials: 'include',
  });
  if (!resp.ok) throw new Error((await readError(resp)) || 'mock pay failed');
  return await resp.json();
}
