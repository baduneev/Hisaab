import type { components } from './generated/api';
export type Doc = components['schemas']['DocumentOut'];
export type DocInput = components['schemas']['DocumentIn'];
export type Kind = DocInput['kind'];
export type Contact = components['schemas']['ContactIn'] & { id: string; balance?: string };
export type Product = Omit<components['schemas']['ProductIn'], 'sale_price' | 'reorder_level' | 'pack_size'> & { id: string; sale_price: string; reorder_level: string; pack_size: string };
export type Warehouse = { id: string; name: string; branch: string };
export type Me = { id: string; name: string; email: string; role: string; tenant_id: string; company: { id: string; name: string; pan: string; address: string; vat_registered: boolean; demo: boolean; locked_through: string | null }; tax_billing_enabled: boolean; today: string; calendar: { ad: string; bs: string; fiscal_year: string } };
export type Aging = { id: string; number: string; contact_id: string; contact_name: string; date: string; due_date: string; amount: string; days_overdue: number; bucket: string; href: string };
export type Stock = { id: string; product_id: string; name: string; sku: string; category: string; unit: string; warehouse_id: string; warehouse: string; branch: string; quantity: string; reorder_level: string; low_stock: boolean; sale_price: string; value?: string; average_cost?: string };
export type Summary = { period: { start: string; end: string }; as_of: string; last_posted_at: string | null; cash: string; cash_in_hand: string; bank: string; sales: string; cost_of_goods_sold: string; gross_profit: string; expenses: string; net_profit: string; receivables: string; payables: string; inventory_value: string; overdue: string; upcoming_dues: string; collections: Aging[]; supplier_dues: Aging[]; stock_alerts: { id: string; name: string; quantity: string; reorder_level: string; unit: string; href: string }[]; history: { date: string; sales: string; cost: string; cash_in: string; cash_out: string }[]; checks: { journal_balanced: boolean; inventory_reconciled: boolean } };
export type Evidence = { label: string; href: string; amount: string };
export type InsightCard = { id: string; title: string; title_ne: string; description: string; description_ne: string; amount: string; metric: string; severity: string; href: string; evidence: Evidence[] };
export type Insights = { as_of: string; period: { start: string; end: string }; cards: InsightCard[]; provider_status: string; limitations: string[]; metrics: Record<string, string> };
export class ApiError extends Error { constructor(public status: number, message: string) { super(message); } }
export async function api<T>(path: string, options: RequestInit = {}): Promise<T> {
  const response = await fetch('/api/v1' + path, { ...options, credentials: 'same-origin', headers: { ...(options.body ? { 'Content-Type': 'application/json' } : {}), ...options.headers } });
  if (!response.ok) {
    const body = await response.json().catch(() => ({}));
    const detail = body.detail;
    const message = typeof detail === 'string' ? detail : Array.isArray(detail) ? detail.map((x: { loc: string[]; msg: string }) => `${x.loc.slice(1).join(' ')}: ${x.msg}`).join('; ') : `Request failed (${response.status})`;
    if (response.status === 401 && !path.startsWith('/auth/')) window.dispatchEvent(new Event('hisaab:session-expired'));
    throw new ApiError(response.status, message);
  }
  return response.json();
}
export function send<T>(path: string, data?: unknown, headers?: Record<string, string>) { return api<T>(path, { method: 'POST', body: data === undefined ? undefined : JSON.stringify(data), headers }); }
export function npr(value: string | number | undefined) { return value === undefined ? '—' : new Intl.NumberFormat('en-IN', { style: 'currency', currency: 'NPR', currencyDisplay: 'code', maximumFractionDigits: 2 }).format(Number(value)).replace('NPR', 'Rs.'); }
export function num(value: string | number) { return new Intl.NumberFormat('en-IN', { maximumFractionDigits: 2 }).format(Number(value)); }
