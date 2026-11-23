import React, { Component, Suspense, lazy, useEffect, useState, type ReactNode } from 'react';
import { createRoot } from 'react-dom/client';
import { BrowserRouter, Link, NavLink, Navigate, Route, Routes, useLocation, useNavigate } from 'react-router-dom';
import { QueryClient, QueryClientProvider, useQuery } from '@tanstack/react-query';
import { BarChart3, BookOpen, Boxes, ChevronDown, CircleHelp, FileText, LayoutDashboard, LogOut, Menu, Search, Settings as SettingsIcon, ShoppingBag, Sparkles, Users, WifiOff, X } from 'lucide-react';
import { api, send, ApiError, type Me } from './api';
import { AppProvider, useApp } from './context';
import { Button, ErrorNotice, Field, Loading } from './components';
import { Overview } from './overview';
import './style.css';

const Transactions = lazy(() => import('./transactions'));
const Contacts = lazy(() => import('./contacts'));
const Inventory = lazy(() => import('./inventory'));
const Accounting = lazy(() => import('./accounting'));
const Reports = lazy(() => import('./reports'));
const InsightsPage = lazy(() => import('./insights'));
const SettingsPage = lazy(() => import('./settings'));
const SearchPage = lazy(() => import('./search'));
const client = new QueryClient({ defaultOptions: { queries: { staleTime: 20_000, retry: (count, error) => !(error instanceof ApiError && [401, 403, 404].includes(error.status)) && count < 2, refetchOnWindowFocus: false }, mutations: { retry: false } } });

function Brand({ light = false }: { light?: boolean }) { return <Link to="/" className={`brand ${light ? 'on-dark' : ''}`} aria-label="Hisaab home"><img src="/hisaab.svg" alt="" width="35" height="35"/><span>hisaab<span className="brand-period">.</span></span></Link>; }

function SignIn({ expired }: { expired: boolean }) {
  const [register, setRegister] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);
  async function submit(e: React.FormEvent<HTMLFormElement>) {
    e.preventDefault(); setBusy(true); setError(null);
    const form = new FormData(e.currentTarget);
    try {
      const data = Object.fromEntries(form.entries());
      const me = await send<Me>(register ? '/auth/register' : '/auth/login', data);
      client.removeQueries({ predicate: query => query.queryKey[0] !== 'me' });
      client.setQueryData(['me'], me);
      window.dispatchEvent(new Event('hisaab:signed-in'));
    } catch (error) { setError(error); } finally { setBusy(false); }
  }
  return <main className="auth-page"><section className="auth-story"><Brand light/><div><div className="ledger-mark" aria-hidden="true"><span/><span/><span/></div><h1>Your business,<br/>in balance.</h1><p>From the first purchase to the final payment.<br/>A clearer view of the business you’re building.</p><p lang="ne" className="auth-ne">हरेक कारोबारको हिसाब।<br/>हरेक निर्णयमा स्पष्टता।</p></div><footer>Made for the way Nepal does business.</footer></section><section className="auth-form"><div className="auth-form-inner"><p className="muted">Accounting for Nepal’s wholesalers</p><h2>{register ? 'Start your business workspace' : 'Welcome to Hisaab'}</h2><p>{register ? 'Create an independent workspace for your company.' : 'Sign in to see how your business is doing.'}</p>{expired && <div className="notice warning">Your session ended. Sign in again to recover your drafts.</div>}<form onSubmit={submit}>{register && <><Field label="Company name" name="company" required minLength={2}/><Field label="Your name" name="name" required minLength={2}/></>}<Field label="Email address" name="email" type="email" autoComplete="username" required/><Field label="Password" name="password" type="password" autoComplete={register ? 'new-password' : 'current-password'} required minLength={register ? 12 : undefined} hint={register ? 'Use at least 12 characters.' : undefined}/><ErrorNotice error={error}/><Button type="submit" busy={busy}>{register ? 'Create workspace' : 'Sign in'}</Button></form><p className="auth-switch">{register ? 'Already have a workspace?' : 'New to Hisaab?'} <button className="text-button" onClick={() => { setRegister(!register); setError(null); }}>{register ? 'Sign in' : 'Create a workspace'}</button></p>{!register && <details className="demo-credentials" open><summary>Explore the sample business</summary><p>This workspace uses sample transactions. Tax billing is disabled.</p><dl><dt>Email</dt><dd>owner@hisaab.demo</dd><dt>Password</dt><dd>Hisaab-demo-2026!</dd></dl></details>}</div></section></main>;
}

const nav = [
  ['/', 'Overview', 'अवलोकन', LayoutDashboard], ['/sales', 'Sales', 'बिक्री', FileText], ['/purchases', 'Purchases', 'खरिद', ShoppingBag], ['/contacts', 'Contacts', 'सम्पर्क', Users], ['/inventory', 'Inventory', 'मौज्दात', Boxes], ['/accounting', 'Accounting', 'लेखा', BookOpen], ['/reports', 'Reports', 'प्रतिवेदन', BarChart3], ['/insights', 'Insights', 'अन्तर्दृष्टि', Sparkles],
] as const;

function Shell() {
  const { me, t, language, setLanguage, calendar, setCalendar } = useApp();
  const [mobile, setMobile] = useState(false);
  const [online, setOnline] = useState(navigator.onLine);
  const [search, setSearch] = useState('');
  const location = useLocation(); const navigate = useNavigate();
  useEffect(() => { setMobile(false); window.scrollTo(0, 0); }, [location.pathname]);
  useEffect(() => { const update = () => setOnline(navigator.onLine); window.addEventListener('online', update); window.addEventListener('offline', update); return () => { window.removeEventListener('online', update); window.removeEventListener('offline', update); }; }, []);
  const finance = ['Owner', 'Accountant', 'Viewer'].includes(me.role);
  const allowed = nav.filter(([path]) => finance || !['/', '/accounting', '/reports', '/insights', ...(me.role === 'Warehouse' ? ['/sales', '/contacts'] : ['/purchases'])].includes(path));
  return <div className="app-shell"><a className="skip-link" href="#main">{t('Skip to content', 'मुख्य सामग्रीमा जानुहोस्')}</a><aside className={`sidebar ${mobile ? 'mobile-open' : ''}`}><div className="sidebar-brand"><Brand/><button className="icon-button mobile-only" aria-label="Close navigation" onClick={() => setMobile(false)}><X size={20}/></button></div><div className="workspace"><div className="workspace-avatar">HT</div><div><strong>{me.company.name}</strong><span>{t('Business workspace', 'व्यवसाय कार्यक्षेत्र')}</span></div><ChevronDown size={15}/></div><nav aria-label="Main navigation">{allowed.map(([path, en, ne, Icon]) => <NavLink key={path} to={path} end={path === '/'}><Icon size={19} strokeWidth={1.7}/><span>{t(en, ne)}</span>{path === '/insights' && <span className="nav-label">AI</span>}</NavLink>)}</nav><div className="sidebar-bottom"><Link to="/settings"><SettingsIcon size={19}/>{t('Settings', 'सेटिङ')}</Link><Link to="/settings?tab=help"><CircleHelp size={19}/>{t('Help & getting started', 'सहयोग र सुरुवात')}</Link><div className="user-profile"><span className="avatar">{me.name.split(' ').map(x => x[0]).slice(0, 2).join('')}</span><div><strong>{me.name}</strong><small>{me.role}</small></div><button className="icon-button" aria-label="Sign out" onClick={async () => { await send('/auth/logout'); client.clear(); window.location.assign('/'); }}><LogOut size={17}/></button></div></div></aside>{mobile && <button className="mobile-backdrop" aria-label="Close menu" onClick={() => setMobile(false)}/>}<div className="main-shell"><header className="topbar"><button className="icon-button mobile-only" aria-label="Open navigation" onClick={() => setMobile(true)}><Menu size={22}/></button><form className="global-search" onSubmit={e => { e.preventDefault(); if (search.trim()) navigate(`/search?q=${encodeURIComponent(search)}`); }}><Search size={18}/><input aria-label="Search customers, products, invoices" placeholder={t('Search customers, products, invoices…', 'ग्राहक, वस्तु वा बीजक खोज्नुहोस्…')} value={search} onChange={e => setSearch(e.target.value)}/></form><div className="topbar-tools"><span className="fiscal-label">{t('FY', 'आ.व.')} {me.calendar.fiscal_year}</span><button className="small-button" onClick={() => setCalendar(calendar === 'ad' ? 'bs' : 'ad')} aria-label="Switch calendar">{calendar.toUpperCase()} <ChevronDown size={12}/></button><button className="language-button" onClick={() => setLanguage(language === 'en' ? 'ne' : 'en')}>{language === 'en' ? 'नेपाली' : 'English'}</button><span className="avatar small">{me.name[0]}</span></div></header>{!online && <div className="connection-banner" role="status"><WifiOff size={16}/>{t('You are offline. Drafts are preserved; reconnect to post transactions. Cached figures may be outdated.', 'इन्टरनेट छैन। मस्यौदा सुरक्षित छ; कारोबार प्रविष्ट गर्न पुनः जडान गर्नुहोस्। तथ्याङ्क पुरानो हुन सक्छ।')}</div>}{me.company.demo && <div className="demo-banner"><span>{t('Sample business', 'नमुना व्यवसाय')}</span>{t('Explore with demo transactions. Internal records only; tax billing is disabled.', 'नमुना कारोबार प्रयोग गर्नुहोस्। आन्तरिक लेखा मात्र; कर बीजक बन्द छ।')}</div>}<main id="main" className="main-content"><Suspense fallback={<Loading/>}><Routes><Route path="/" element={finance ? <Overview/> : <Navigate to={me.role === 'Warehouse' ? '/inventory' : '/sales'} replace/>}/><Route path="/sales" element={<Transactions area="sales"/>}/><Route path="/purchases" element={<Transactions area="purchases"/>}/><Route path="/new/:kind" element={<Transactions area="editor"/>}/><Route path="/documents/:id" element={<Transactions area="detail"/>}/><Route path="/contacts/*" element={<Contacts/>}/><Route path="/inventory" element={<Inventory/>}/><Route path="/accounting" element={<Accounting/>}/><Route path="/reports" element={<Reports/>}/><Route path="/insights" element={<InsightsPage/>}/><Route path="/settings" element={<SettingsPage/>}/><Route path="/search" element={<SearchPage/>}/><Route path="*" element={<div className="empty"><h1>Page not found</h1><Link to="/">Return to your overview</Link></div>}/></Routes></Suspense><footer className="app-footer"><span>Hisaab <span className="footer-divider">/</span> {t('Your business, in balance.', 'व्यवसायको स्पष्ट हिसाब।')}</span><span>{t('Nepal time', 'नेपाल समय')} (UTC+05:45)</span></footer></main></div></div>;
}

class Boundary extends Component<{ children: ReactNode }, { error: boolean }> {
  state = { error: false };
  static getDerivedStateFromError() { return { error: true }; }
  render() { return this.state.error ? <div className="empty"><h1>This view couldn’t be loaded</h1><p>Your saved records are preserved.</p><button className="button" onClick={() => window.location.reload()}>Reload view</button></div> : this.props.children; }
}

function App() {
  const [expired, setExpired] = useState(false);
  const session = useQuery({ queryKey: ['me'], queryFn: () => api<Me>('/me'), retry: false, staleTime: Infinity });
  useEffect(() => { const onExpire = () => { if (client.getQueryData(['me'])) { setExpired(true); client.removeQueries({ predicate: query => query.queryKey[0] !== 'me' }); } }; const signedIn = () => setExpired(false); window.addEventListener('hisaab:session-expired', onExpire); window.addEventListener('hisaab:signed-in', signedIn); return () => { window.removeEventListener('hisaab:session-expired', onExpire); window.removeEventListener('hisaab:signed-in', signedIn); }; }, []);
  if (expired) return <SignIn expired/>;
  if (session.isPending) return <div className="startup"><img src="/hisaab.svg" width="52" height="52" alt="Hisaab"/><p>Opening your workspace…</p></div>;
  if (session.isError) {
    if (session.error instanceof ApiError && session.error.status === 401) return <SignIn expired={expired}/>;
    return <div className="startup"><h1>Couldn’t connect to Hisaab</h1><p>Check your connection and make sure the API is running.</p><Button onClick={() => session.refetch()}>Try again</Button></div>;
  }
  return <AppProvider me={session.data}><Boundary><Shell/></Boundary></AppProvider>;
}

createRoot(document.getElementById('root')!).render(<QueryClientProvider client={client}><BrowserRouter><App/></BrowserRouter></QueryClientProvider>);
