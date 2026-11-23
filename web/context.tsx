import { createContext, useContext, useEffect, useState, type ReactNode } from 'react';
import { useQuery } from '@tanstack/react-query';
import type { Me } from './api';
import { api } from './api';

type AppContext = { me: Me; language: 'en' | 'ne'; setLanguage: (value: 'en' | 'ne') => void; calendar: 'ad' | 'bs'; setCalendar: (value: 'ad' | 'bs') => void; t: (english: string, nepali?: string) => string };
const Context = createContext<AppContext | null>(null);
export function AppProvider({ me, children }: { me: Me; children: ReactNode }) {
  const [language, setLanguage] = useState<'en' | 'ne'>(() => localStorage.getItem('hisaab.language') === 'ne' ? 'ne' : 'en');
  const [calendar, setCalendar] = useState<'ad' | 'bs'>(() => localStorage.getItem('hisaab.calendar') === 'bs' ? 'bs' : 'ad');
  useEffect(() => { localStorage.setItem('hisaab.language', language); document.documentElement.lang = language; }, [language]);
  useEffect(() => { localStorage.setItem('hisaab.calendar', calendar); }, [calendar]);
  return <Context.Provider value={{ me, language, setLanguage, calendar, setCalendar, t: (en, ne) => language === 'ne' && ne ? ne : en }}>{children}</Context.Provider>;
}
export function useApp() { const value = useContext(Context); if (!value) throw new Error('Missing application session'); return value; }
export function useData<T>(path: string, enabled = true) { const { me } = useApp(); return useQuery({ queryKey: [me.tenant_id, path], queryFn: () => api<T>(path), enabled }); }
export function DateText({ value }: { value: string | null | undefined }) {
  const { calendar } = useApp();
  const { data } = useData<{ bs: string }>(`/calendar?date=${value?.slice(0, 10)}`, calendar === 'bs' && !!value);
  if (!value) return <span aria-label="No date">-</span>;
  return <time dateTime={value}>{calendar === 'bs' ? data ? `${data.bs} BS` : '…' : new Intl.DateTimeFormat('en-GB', { day: '2-digit', month: 'short', year: 'numeric', timeZone: 'Asia/Kathmandu' }).format(new Date(value.slice(0, 10) + 'T12:00:00+05:45'))}</time>;
}
