import { useEffect, useId, useRef, type ReactNode, type InputHTMLAttributes, type SelectHTMLAttributes } from 'react';
import { AlertCircle, Check, FileText, LoaderCircle, Plus, RefreshCw, Search, X } from 'lucide-react';
import { Link } from 'react-router-dom';
import type { UseQueryResult } from '@tanstack/react-query';
import { useApp, DateText } from './context';
import { npr, type Doc } from './api';

export function Field({ label, hint, ...props }: InputHTMLAttributes<HTMLInputElement> & { label: string; hint?: string }) {
  const id = useId();
  return <div className="field"><label htmlFor={id}>{label}</label><input id={id} aria-describedby={hint ? `${id}-hint` : undefined} {...props} />{hint && <small id={`${id}-hint`}>{hint}</small>}</div>;
}
export function Select({ label, children, ...props }: SelectHTMLAttributes<HTMLSelectElement> & { label: string; children: ReactNode }) {
  const id = useId();
  return <div className="field"><label htmlFor={id}>{label}</label><select id={id} {...props}>{children}</select></div>;
}
export function ErrorNotice({ error }: { error: unknown }) { return error ? <div className="notice error" role="alert"><AlertCircle size={18} /><span>{error instanceof Error ? error.message : String(error)}</span></div> : null; }
export function Success({ children }: { children: ReactNode }) { return <div className="notice success" role="status"><Check size={18}/><span>{children}</span></div>; }
export function Empty({ title, description, action }: { title: string; description: string; action?: ReactNode }) { return <div className="empty"><FileText size={30} strokeWidth={1.3} /><h3>{title}</h3><p>{description}</p>{action}</div>; }
export function Loading() { return <div className="skeleton" role="status" aria-label="Loading records"><div/><div/><div/><span className="sr-only">Loading records</span></div>; }
export function QueryState<T>({ query, children }: { query: UseQueryResult<T, Error>; children: (data: T) => ReactNode }) {
  const { t } = useApp();
  if (query.isPending) return <Loading/>;
  if (query.isError) return <div className="error-region"><ErrorNotice error={query.error}/><button className="button quiet" onClick={() => query.refetch()}><RefreshCw size={16}/>{t('Retry', 'पुनः प्रयास')}</button></div>;
  return <>{children(query.data)}</>;
}
export function PageHeading({ title, description, action }: { title: string; description?: string; action?: ReactNode }) { return <div className="page-heading"><div><h1>{title}</h1>{description && <p>{description}</p>}</div>{action}</div>; }
export function SearchInput({ value, onChange, placeholder = 'Search records' }: { value: string; onChange: (value: string) => void; placeholder?: string }) { return <label className="search"><Search size={17}/><span className="sr-only">{placeholder}</span><input value={value} onChange={e => onChange(e.target.value)} placeholder={placeholder}/>{value && <button aria-label="Clear search" onClick={() => onChange('')}><X size={15}/></button>}</label>; }
export function Status({ status }: { status: string }) { const { t } = useApp(); return <span className={`status ${status}`}>{status === 'posted' ? t('Posted', 'प्रविष्ट') : status === 'draft' ? t('Draft', 'मस्यौदा') : status === 'paid' ? t('Paid', 'भुक्तानी भयो') : status === 'overdue' ? t('Overdue', 'भाका नाघेको') : status}</span>; }
export function Modal({ title, onClose, children }: { title: string; onClose: () => void; children: ReactNode }) {
  const ref = useRef<HTMLDialogElement>(null);
  useEffect(() => { ref.current?.showModal(); return () => ref.current?.close(); }, []);
  return <dialog ref={ref} className="modal" onCancel={onClose} onClick={e => { if (e.target === e.currentTarget) onClose(); }}><div className="modal-heading"><h2>{title}</h2><button className="icon-button" aria-label="Close dialog" onClick={onClose}><X size={20}/></button></div>{children}</dialog>;
}
export function Button({ children, busy, ...props }: React.ButtonHTMLAttributes<HTMLButtonElement> & { busy?: boolean }) { return <button {...props} className={props.className ?? 'button'} disabled={busy || props.disabled} aria-busy={busy}>{busy && <LoaderCircle size={16} className="spin"/>}{children}</button>; }
export const kindLabel: Record<string, [string, string]> = { sale: ['Sales invoice', 'बिक्री बीजक'], quotation: ['Quotation', 'मूल्य प्रस्ताव'], purchase_order: ['Purchase order', 'खरिद आदेश'], goods_receipt: ['Goods receipt', 'सामान प्राप्ति'], purchase_bill: ['Supplier bill', 'आपूर्तिकर्ता बीजक'], sale_return: ['Sales return', 'बिक्री फिर्ता'], purchase_return: ['Purchase return', 'खरिद फिर्ता'], receipt: ['Customer receipt', 'ग्राहकबाट प्राप्ति'], payment: ['Supplier payment', 'आपूर्तिकर्तालाई भुक्तानी'], expense: ['Expense', 'खर्च'], journal: ['Journal entry', 'जर्नल प्रविष्टि'], opening_balance: ['Opening balances', 'सुरु मौज्दात'], opening_stock: ['Opening stock', 'सुरु सामान'], stock_adjustment: ['Stock adjustment', 'मौज्दात समायोजन'], transfer: ['Stock transfer', 'मौज्दात स्थानान्तरण'] };
export function DocumentsTable({ docs, showContact = true }: { docs: Doc[]; showContact?: boolean }) {
  const { t } = useApp();
  if (!docs.length) return <Empty title={t('No transactions yet', 'कारोबार छैन')} description={t('Create a draft to start tracking your business.', 'कारोबार सुरु गर्न मस्यौदा बनाउनुहोस्।')}/>;
  return <div className="table-scroll" tabIndex={0} aria-label="Transactions"><table><thead><tr><th>{t('Document', 'कागजात')}</th>{showContact && <th>{t('Customer / supplier', 'ग्राहक / आपूर्तिकर्ता')}</th>}<th>{t('Date', 'मिति')}</th><th>{t('Status', 'अवस्था')}</th><th className="numeric">{t('Amount', 'रकम')}</th><th className="numeric">{t('Outstanding', 'बाँकी')}</th></tr></thead><tbody>{docs.map(doc => <tr key={doc.id}><td><Link className="record-link" to={`/documents/${doc.id}`}>{doc.number || t('Draft', 'मस्यौदा')}</Link><small>{t(...(kindLabel[doc.kind] || [doc.kind, doc.kind]))}</small></td>{showContact && <td>{doc.contact_id ? <Link to={`/contacts/${doc.contact_id}`}>{doc.contact_name}</Link> : '—'}</td>}<td><DateText value={doc.date}/></td><td><Status status={doc.status === 'posted' && ['sale', 'purchase_bill'].includes(doc.kind) && Number(doc.outstanding) === 0 ? 'paid' : doc.status}/></td><td className="numeric">{npr(doc.total)}</td><td className="numeric">{['sale', 'purchase_bill'].includes(doc.kind) ? npr(doc.outstanding) : '—'}</td></tr>)}</tbody></table></div>;
}
