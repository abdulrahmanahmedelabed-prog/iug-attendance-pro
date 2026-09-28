/* ZK Attendance Pro — UI core: API, i18n, grid, dialogs, forms. No external libraries. */
'use strict';

const App = { user: null, lang: 'ar', lookups: null, settings: {}, timers: [] };

// ------------------------------------------------------------------ i18n
function T(ar, en) { return App.lang === 'ar' ? ar : (en ?? ar); }
function setLang(lang) {
  App.lang = lang === 'en' ? 'en' : 'ar';
  try { localStorage.setItem('zk_lang', App.lang); } catch (e) { /* storage may be blocked */ }
  document.documentElement.lang = App.lang;
  document.documentElement.dir = App.lang === 'ar' ? 'rtl' : 'ltr';
}
try { setLang(localStorage.getItem('zk_lang') || 'ar'); } catch (e) { setLang('ar'); }

// ------------------------------------------------------------------ helpers
const $ = (sel, root = document) => root.querySelector(sel);
const $$ = (sel, root = document) => Array.from(root.querySelectorAll(sel));
function esc(v) {
  return String(v ?? '').replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
}
function h(html) { const t = document.createElement('template'); t.innerHTML = html.trim(); return t.content.firstElementChild; }
function hm(mins) { mins = +mins || 0; if (!mins) return ''; return `${Math.floor(mins / 60)}:${String(mins % 60).padStart(2, '0')}`; }
function today() { const d = new Date(); return iso(d); }
function iso(d) { return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`; }
function monthStart() { const d = new Date(); d.setDate(1); return iso(d); }
function addDays(s, n) { const d = new Date(s + 'T00:00:00'); d.setDate(d.getDate() + n); return iso(d); }
function debounce(fn, ms = 300) { let t; return (...a) => { clearTimeout(t); t = setTimeout(() => fn(...a), ms); }; }
function can(perm) { return App.user && (App.user.is_superuser || App.user.permissions.includes(perm)); }

// ------------------------------------------------------------------ API
async function api(method, url, body, opts = {}) {
  const init = { method, headers: {}, credentials: 'same-origin' };
  if (body instanceof FormData) init.body = body;
  else if (body !== undefined) { init.headers['Content-Type'] = 'application/json'; init.body = JSON.stringify(body); }
  const res = await fetch(url, init);
  if (res.status === 401 && !opts.noAuthRedirect) { showLogin(); throw new Error(T('انتهت الجلسة', 'Session expired')); }
  if (!res.ok) {
    let msg = res.statusText;
    try { const j = await res.json(); msg = typeof j.detail === 'string' ? j.detail : JSON.stringify(j.detail); } catch (e) { /* not JSON */ }
    throw new Error(msg);
  }
  const ct = res.headers.get('content-type') || '';
  return ct.includes('application/json') ? res.json() : res;
}
const GET = (u) => api('GET', u);
const POST = (u, b) => api('POST', u, b ?? {});
const PUT = (u, b) => api('PUT', u, b);
const DEL = (u) => api('DELETE', u);
function qs(o) { return Object.entries(o).filter(([, v]) => v !== undefined && v !== null && v !== '').map(([k, v]) => `${encodeURIComponent(k)}=${encodeURIComponent(v)}`).join('&'); }
async function lookups(force) { if (!App.lookups || force) App.lookups = await GET('/api/lookups'); return App.lookups; }
function download(url) { const a = document.createElement('a'); a.href = url; a.download = ''; document.body.appendChild(a); a.click(); a.remove(); }

// ------------------------------------------------------------------ toast / confirm
function toast(msg, kind = '') {
  let box = $('.toasts'); if (!box) { box = h('<div class="toasts"></div>'); document.body.appendChild(box); }
  const el = h(`<div class="toast ${kind}">${esc(msg)}</div>`); box.appendChild(el);
  setTimeout(() => el.remove(), kind === 'bad' ? 6000 : 3000);
}
async function guard(fn, okMsg) {
  try { const r = await fn(); if (okMsg) toast(okMsg, 'ok'); return r; } catch (e) { toast(e.message || String(e), 'bad'); throw e; }
}

// ------------------------------------------------------------------ icons (inline SVG)
const ICONS = {
  dashboard: '<path d="M3 13h8V3H3zm0 8h8v-6H3zm10 0h8V11h-8zm0-18v6h8V3z"/>',
  people: '<path d="M16 11c1.66 0 2.99-1.34 2.99-3S17.66 5 16 5s-3 1.34-3 3 1.34 3 3 3zm-8 0c1.66 0 2.99-1.34 2.99-3S9.66 5 8 5 5 6.34 5 8s1.34 3 3 3zm0 2c-2.33 0-7 1.17-7 3.5V19h14v-2.5C15 14.17 10.33 13 8 13zm8 0c-.29 0-.62.02-.97.05 1.16.84 1.97 1.97 1.97 3.45V19h6v-2.5c0-2.33-4.67-3.5-7-3.5z"/>',
  device: '<path d="M17 1H7c-1.1 0-2 .9-2 2v18c0 1.1.9 2 2 2h10c1.1 0 2-.9 2-2V3c0-1.1-.9-2-2-2zm-5 20a1.5 1.5 0 110-3 1.5 1.5 0 010 3zm5-5H7V4h10v12z"/>',
  clock: '<path d="M12 2a10 10 0 100 20 10 10 0 000-20zm0 18a8 8 0 110-16 8 8 0 010 16zm.5-13H11v6l5.2 3.2.8-1.3-4.5-2.7z"/>',
  report: '<path d="M19 3H5c-1.1 0-2 .9-2 2v14c0 1.1.9 2 2 2h14c1.1 0 2-.9 2-2V5c0-1.1-.9-2-2-2zM9 17H7v-7h2zm4 0h-2V7h2zm4 0h-2v-4h2z"/>',
  system: '<path d="M19.14 12.94c.04-.3.06-.61.06-.94s-.02-.64-.07-.94l2.03-1.58a.49.49 0 00.12-.61l-1.92-3.32a.49.49 0 00-.59-.22l-2.39.96a7.03 7.03 0 00-1.62-.94l-.36-2.54A.48.48 0 0013.92 2h-3.84c-.24 0-.43.17-.47.41l-.36 2.54c-.59.24-1.13.57-1.62.94l-2.39-.96a.49.49 0 00-.59.22L2.73 8.47a.49.49 0 00.12.61l2.03 1.58c-.05.3-.07.63-.07.94s.02.64.07.94l-2.03 1.58a.49.49 0 00-.12.61l1.92 3.32c.12.22.37.29.59.22l2.39-.96c.5.38 1.03.7 1.62.94l.36 2.54c.05.24.24.41.48.41h3.84c.24 0 .44-.17.47-.41l.36-2.54c.59-.24 1.13-.56 1.62-.94l2.39.96c.22.08.47 0 .59-.22l1.92-3.32a.49.49 0 00-.12-.61zM12 15.6A3.6 3.6 0 1112 8.4a3.6 3.6 0 010 7.2z"/>',
  add: '<path d="M19 13h-6v6h-2v-6H5v-2h6V5h2v6h6z"/>',
  edit: '<path d="M3 17.25V21h3.75L17.81 9.94l-3.75-3.75zM20.71 7.04a1 1 0 000-1.41l-2.34-2.34a1 1 0 00-1.41 0l-1.83 1.83 3.75 3.75z"/>',
  del: '<path d="M6 19c0 1.1.9 2 2 2h8c1.1 0 2-.9 2-2V7H6zM19 4h-3.5l-1-1h-5l-1 1H5v2h14z"/>',
  refresh: '<path d="M17.65 6.35A7.96 7.96 0 0012 4a8 8 0 108 8h-2a6 6 0 11-1.76-4.24L13 11h7V4z"/>',
  download: '<path d="M19 9h-4V3H9v6H5l7 7zM5 18v2h14v-2z"/>',
  upload: '<path d="M9 16h6v-6h4l-7-7-7 7h4zm-4 2h14v2H5z"/>',
  sync: '<path d="M12 4V1L8 5l4 4V6a6 6 0 016 6c0 1.01-.25 1.97-.7 2.8l1.46 1.46A7.93 7.93 0 0020 12a8 8 0 00-8-8zm0 14a6 6 0 01-6-6c0-1.01.25-1.97.7-2.8L5.24 7.74A7.93 7.93 0 004 12a8 8 0 008 8v3l4-4-4-4z"/>',
  more: '<path d="M12 8a2 2 0 100-4 2 2 0 000 4zm0 2a2 2 0 100 4 2 2 0 000-4zm0 6a2 2 0 100 4 2 2 0 000-4z"/>',
  list: '<path d="M3 13h2v-2H3zm0 4h2v-2H3zm0-8h2V7H3zm4 4h14v-2H7zm0 4h14v-2H7zM7 7v2h14V7z"/>',
  building: '<path d="M12 7V3H2v18h20V7zM6 19H4v-2h2zm0-4H4v-2h2zm0-4H4V9h2zm0-4H4V5h2zm4 12H8v-2h2zm0-4H8v-2h2zm0-4H8V9h2zm0-4H8V5h2zm10 12h-8v-2h2v-2h-2v-2h2v-2h-2V9h8z"/>',
  map: '<path d="M12 2C8.13 2 5 5.13 5 9c0 5.25 7 13 7 13s7-7.75 7-13c0-3.87-3.13-7-7-7zm0 9.5a2.5 2.5 0 110-5 2.5 2.5 0 010 5z"/>',
  badge: '<path d="M20 7h-5V4c0-1.1-.9-2-2-2h-2c-1.1 0-2 .9-2 2v3H4c-1.1 0-2 .9-2 2v11c0 1.1.9 2 2 2h16c1.1 0 2-.9 2-2V9c0-1.1-.9-2-2-2zM9 12a2 2 0 110 4 2 2 0 010-4zm4 7H5v-.57c0-.81.48-1.53 1.22-1.85A6.95 6.95 0 019 16c.98 0 1.91.2 2.78.58.74.32 1.22 1.04 1.22 1.85zM13 9h-2V4h2zm5 7.5h-4V15h4zm0-3h-4V12h4z"/>',
  exit: '<path d="M10.09 15.59L11.5 17l5-5-5-5-1.41 1.41L12.67 11H3v2h9.67zM19 3H5a2 2 0 00-2 2v4h2V5h14v14H5v-4H3v4a2 2 0 002 2h14c1.1 0 2-.9 2-2V5c0-1.1-.9-2-2-2z"/>',
  cal: '<path d="M19 4h-1V2h-2v2H8V2H6v2H5a2 2 0 00-2 2v14c0 1.1.9 2 2 2h14c1.1 0 2-.9 2-2V6c0-1.1-.9-2-2-2zm0 16H5V9h14zM7 11h5v5H7z"/>',
  leave: '<path d="M13.5 5.5c1.1 0 2-.9 2-2s-.9-2-2-2-2 .9-2 2 .9 2 2 2zM9.8 8.9L7 23h2.1l1.8-8 2.1 2v6h2v-7.5l-2.1-2 .6-3A7.3 7.3 0 0019 13v-2c-1.9 0-3.5-1-4.3-2.4l-1-1.6c-.4-.6-1-1-1.7-1-.3 0-.5.1-.8.1L6 8.3V13h2V9.6z"/>',
  hand: '<path d="M21 7c0-1.38-1.12-2.5-2.5-2.5-.17 0-.34.02-.5.05V4c0-1.38-1.12-2.5-2.5-2.5-.23 0-.46.03-.67.09C14.46.66 13.56 0 12.5 0c-1.23 0-2.25.89-2.46 2.06C9.87 2.02 9.69 2 9.5 2 8.12 2 7 3.12 7 4.5v5.89c-.34-.31-.76-.54-1.22-.66L5 9.52a2.5 2.5 0 00-3 3.08l1.58 5.81A7.49 7.49 0 0010.8 24H13c4.42 0 8-3.58 8-8z"/>',
  monitor: '<path d="M21 3H3c-1.1 0-2 .9-2 2v12c0 1.1.9 2 2 2h5v2h8v-2h5c1.1 0 1.99-.9 1.99-2L23 5c0-1.1-.9-2-2-2zm0 14H3V5h18z"/>',
  shield: '<path d="M12 1L3 5v6c0 5.55 3.84 10.74 9 12 5.16-1.26 9-6.45 9-12V5z"/>',
  db: '<path d="M12 3C7.58 3 4 4.79 4 7v10c0 2.21 3.59 4 8 4s8-1.79 8-4V7c0-2.21-3.58-4-8-4zm0 2c3.87 0 6 1.5 6 2s-2.13 2-6 2-6-1.5-6-2 2.13-2 6-2z"/>',
  print: '<path d="M19 8H5c-1.66 0-3 1.34-3 3v6h4v4h12v-4h4v-6c0-1.66-1.34-3-3-3zm-3 11H8v-5h8zm3-7a1 1 0 110-2 1 1 0 010 2zm-1-9H6v4h12z"/>',
  check: '<path d="M9 16.17L4.83 12l-1.42 1.41L9 19 21 7l-1.41-1.41z"/>',
  close: '<path d="M19 6.41L17.59 5 12 10.59 6.41 5 5 6.41 10.59 12 5 17.59 6.41 19 12 13.41 17.59 19 19 17.59 13.41 12z"/>',
  terminal: '<path d="M20 4H4a2 2 0 00-2 2v12a2 2 0 002 2h16a2 2 0 002-2V6a2 2 0 00-2-2zm0 14H4V8h16zM6 10l4 3-4 3zm6 5h6v1h-6z"/>',
  lang: '<path d="M12.87 15.07l-2.54-2.51.03-.03A17.52 17.52 0 0014.07 6H17V4h-7V2H8v2H1v2h11.17C11.5 7.92 10.44 9.75 9 11.35 8.07 10.32 7.3 9.19 6.69 8h-2c.73 1.63 1.73 3.17 2.98 4.56l-5.09 5.02L4 19l5-5 3.11 3.11zM18.5 10h-2L12 22h2l1.12-3h4.75L21 22h2zm-2.62 7l1.62-4.33L19.12 17z"/>',
};
function icon(name) { return `<svg viewBox="0 0 24 24" fill="currentColor" aria-hidden="true">${ICONS[name] || ''}</svg>`; }

// ------------------------------------------------------------------ dialogs
function dialog({ title, body, size = '', buttons = [], onClose }) {
  const ov = h(`<div class="overlay"><div class="dialog ${size}" role="dialog" aria-modal="true">
      <header><h3>${esc(title)}</h3><button class="x" aria-label="close">×</button></header>
      <div class="content"></div><footer></footer></div></div>`);
  const content = $('.content', ov);
  if (typeof body === 'string') content.innerHTML = body; else if (body) content.appendChild(body);
  const close = (v) => { ov.remove(); document.removeEventListener('keydown', onKey); onClose && onClose(v); };
  const onKey = (e) => { if (e.key === 'Escape') close(); };
  document.addEventListener('keydown', onKey);
  $('.x', ov).onclick = () => close();
  const foot = $('footer', ov);
  if (!buttons.length) foot.remove();
  for (const b of buttons) {
    const el = h(`<button class="btn ${b.cls || ''}">${b.icon ? icon(b.icon) : ''}${esc(b.label)}</button>`);
    el.onclick = async () => {
      if (!b.action) return close();
      el.disabled = true;
      try { const r = await b.action(); if (r !== false) close(r); } catch (e) { toast(e.message || e, 'bad'); } finally { el.disabled = false; }
    };
    foot.appendChild(el);
  }
  document.body.appendChild(ov);
  const first = $('input:not([type=checkbox]),select,textarea', content); if (first) setTimeout(() => first.focus(), 30);
  return { el: ov, content, close };
}
function confirmBox(msg, { danger = true, okLabel } = {}) {
  return new Promise(resolve => {
    dialog({ title: T('تأكيد', 'Confirm'), size: 'narrow', body: `<p>${esc(msg)}</p>`, onClose: v => resolve(v === true),
      buttons: [{ label: T('إلغاء', 'Cancel') }, { label: okLabel || T('موافق', 'OK'), cls: danger ? 'danger solid' : 'primary', action: () => true }] });
  });
}

// ------------------------------------------------------------------ forms
/* field: {key, label, type, options:[{value,label}] | fn, required, full, hint, placeholder, section, min, max, step} */
function formHtml(fields, data = {}, cls = '') {
  const parts = [];
  const isNew = data.id === undefined;  // defaults only for new records, never over a stored empty value
  for (const f of fields) {
    if (f.section) { parts.push(`<div class="section-title">${esc(f.section)}</div>`); continue; }
    const v = (isNew ? (data[f.key] ?? f.default) : data[f.key]) ?? '';
    const req = f.required ? ' <span class="req">*</span>' : '';
    const full = f.full || f.type === 'textarea' || f.type === 'multi' ? ' full' : '';
    let input;
    const common = `name="${f.key}" class="inp" ${f.required ? 'required' : ''} ${f.readonly ? 'readonly' : ''} placeholder="${esc(f.placeholder || '')}"`;
    switch (f.type) {
      case 'select':
        input = `<select ${common}>${f.blank !== false ? `<option value="">${esc(f.blankLabel || '—')}</option>` : ''}${(f.options || []).map(o =>
          `<option value="${esc(o.value)}" ${String(o.value) === String(v) ? 'selected' : ''}>${esc(o.label)}</option>`).join('')}</select>`;
        break;
      case 'multi': {
        const sel = new Set((v || []).map(String));
        input = `<div class="multi" data-multi="${f.key}">${(f.options || []).map(o =>
          `<label><input type="checkbox" value="${esc(o.value)}" ${sel.has(String(o.value)) ? 'checked' : ''}> ${esc(o.label)}</label>`).join('') || `<span class="muted">—</span>`}</div>`;
        break;
      }
      case 'checkbox':
        input = `<label class="check"><input type="checkbox" name="${f.key}" ${v === true || v === 1 || v === '1' ? 'checked' : ''}> ${esc(f.text || '')}</label>`;
        break;
      case 'textarea':
        input = `<textarea ${common} rows="${f.rows || 3}">${esc(v)}</textarea>`;
        break;
      case 'datetime':
        input = `<input type="datetime-local" ${common} value="${esc(String(v).replace(' ', 'T').slice(0, 16))}">`;
        break;
      default:
        input = `<input type="${f.type || 'text'}" ${common} value="${esc(v)}" ${f.min !== undefined ? `min="${f.min}"` : ''} ${f.max !== undefined ? `max="${f.max}"` : ''} ${f.step ? `step="${f.step}"` : ''}>`;
    }
    parts.push(`<div class="field${full}"><label>${esc(f.label)}${req}</label>${input}${f.hint ? `<span class="hint">${esc(f.hint)}</span>` : ''}</div>`);
  }
  return `<form class="form ${cls}" onsubmit="return false">${parts.join('')}</form>`;
}
function readForm(root, fields) {
  const out = {};
  for (const f of fields) {
    if (f.section || f.readonly) continue;
    if (f.type === 'multi') { out[f.key] = $$(`[data-multi="${f.key}"] input:checked`, root).map(i => isNaN(+i.value) ? i.value : +i.value); continue; }
    const el = $(`[name="${f.key}"]`, root); if (!el) continue;
    let v = f.type === 'checkbox' ? el.checked : el.value;
    if (f.type === 'datetime' && v) v = v.replace('T', ' ');
    if (f.type === 'number' && v !== '') v = +v;
    if (f.required && (v === '' || v === null)) throw new Error(T('الحقل مطلوب: ', 'Required: ') + f.label);
    out[f.key] = v;
  }
  return out;
}
function formDialog({ title, fields, data = {}, save, size = '', cls = '' }) {
  return new Promise(resolve => {
    const d = dialog({ title, size, body: formHtml(fields, data, cls), onClose: resolve,
      buttons: [{ label: T('إلغاء', 'Cancel') }, { label: T('حفظ', 'Save'), cls: 'primary', icon: 'check', action: async () => {
        const vals = readForm(d.content, fields); const r = await save(vals); toast(T('تم الحفظ', 'Saved'), 'ok'); return r ?? true; } }] });
  });
}

// ------------------------------------------------------------------ grid
/*
  grid(container, {
    columns: [{key, label, render(row), cls, sortable}],
    fetch: async ({offset, limit, q}) => ({total, rows}),
    toolbar: [{label, icon, cls, action(sel, grid), perm, needSel}] | extra HTML nodes,
    select: true, pageSize: 50, search: true, filters: [{key,label,type,options}], onRow(row)
  })
*/
function grid(container, cfg) {
  const st = { offset: 0, limit: cfg.pageSize || 50, q: '', total: 0, rows: [], sel: new Set(), filters: {} };
  const root = h(`<div class="panel"><div class="toolbar"></div><div class="grid-wrap"><table class="grid"><thead></thead><tbody></tbody></table></div><div class="pager"></div></div>`);
  container.appendChild(root);
  const tb = $('.toolbar', root), thead = $('thead', root), tbody = $('tbody', root), pager = $('.pager', root);
  const g = { root, reload: load, get selected() { return st.rows.filter(r => st.sel.has(r[cfg.idKey || 'id'])); }, state: st };

  for (const b of cfg.toolbar || []) {
    if (b instanceof Node) { tb.appendChild(b); continue; }
    if (b.perm && !can(b.perm)) continue;
    if (b.menu) {
      const dd = h(`<div class="dropdown"><button class="btn ${b.cls || ''}">${b.icon ? icon(b.icon) : ''}${esc(b.label)} ▾</button><div class="menu"></div></div>`);
      for (const it of b.menu) {
        if (it === '-') { $('.menu', dd).appendChild(h('<hr>')); continue; }
        if (it.perm && !can(it.perm)) continue;
        const mb = h(`<button>${it.icon ? icon(it.icon) : ''}${esc(it.label)}</button>`);
        mb.onclick = async () => { dd.classList.remove('open'); if (it.needSel && !g.selected.length) return toast(T('اختر سجلاً أولاً', 'Select a record first'), 'bad'); await it.action(g.selected, g); };
        $('.menu', dd).appendChild(mb);
      }
      $('button', dd).onclick = (e) => { e.stopPropagation(); $$('.dropdown.open').forEach(x => x !== dd && x.classList.remove('open')); dd.classList.toggle('open'); };
      tb.appendChild(dd); continue;
    }
    const el = h(`<button class="btn ${b.cls || ''}">${b.icon ? icon(b.icon) : ''}${esc(b.label)}</button>`);
    el.onclick = async () => {
      if (b.needSel && !g.selected.length) return toast(T('اختر سجلاً أولاً', 'Select a record first'), 'bad');
      await b.action(g.selected, g);
    };
    tb.appendChild(el);
  }
  tb.appendChild(h('<span class="grow"></span>'));
  for (const f of cfg.filters || []) {
    let el;
    if (f.type === 'select') el = h(`<select class="inp" title="${esc(f.label)}"><option value="">${esc(f.label)}</option>${f.options.map(o => `<option value="${esc(o.value)}">${esc(o.label)}</option>`).join('')}</select>`);
    else el = h(`<input class="inp" type="${f.type || 'text'}" title="${esc(f.label)}" placeholder="${esc(f.label)}">`);
    if (f.value !== undefined) { el.value = f.value; st.filters[f.key] = f.value; }
    el.onchange = () => { st.filters[f.key] = el.value; st.offset = 0; load(); };
    tb.appendChild(el);
  }
  if (cfg.search !== false) {
    const s = h(`<input class="inp search" type="search" placeholder="${esc(T('بحث...', 'Search...'))}">`);
    s.oninput = debounce(() => { st.q = s.value.trim(); st.offset = 0; load(); });
    tb.appendChild(s);
  }
  const rf = h(`<button class="btn" title="${esc(T('تحديث', 'Refresh'))}">${icon('refresh')}</button>`); rf.onclick = () => load(); tb.appendChild(rf);

  const cols = cfg.columns;
  thead.innerHTML = `<tr>${cfg.select !== false ? '<th class="chk"><input type="checkbox" class="all"></th>' : ''}${cols.map(c => `<th class="${c.cls || ''}">${esc(c.label)}</th>`).join('')}</tr>`;
  const all = $('.all', thead);
  if (all) all.onchange = () => { st.rows.forEach(r => all.checked ? st.sel.add(r[cfg.idKey || 'id']) : st.sel.delete(r[cfg.idKey || 'id'])); paint(); };

  function paint() {
    const idk = cfg.idKey || 'id';
    tbody.innerHTML = st.rows.length ? st.rows.map((r, i) => `<tr data-i="${i}" class="${st.sel.has(r[idk]) ? 'sel' : ''}">${cfg.select !== false ? `<td class="chk"><input type="checkbox" ${st.sel.has(r[idk]) ? 'checked' : ''}></td>` : ''}${cols.map(c => `<td class="${c.cls || ''}">${c.render ? c.render(r) : esc(r[c.key])}</td>`).join('')}</tr>`).join('')
      : `<tr><td class="empty" colspan="${cols.length + 1}">${esc(T('لا توجد بيانات', 'No data'))}</td></tr>`;
    $$('tr[data-i]', tbody).forEach(tr => {
      const r = st.rows[+tr.dataset.i];
      const cb = $('.chk input', tr);
      if (cb) cb.onclick = (e) => { e.stopPropagation(); cb.checked ? st.sel.add(r[idk]) : st.sel.delete(r[idk]); tr.classList.toggle('sel', cb.checked); };
      tr.ondblclick = () => cfg.onRow && cfg.onRow(r, g);
      $$('[data-act]', tr).forEach(a => a.onclick = (e) => { e.stopPropagation(); cfg.actions[a.dataset.act](r, g); });
    });
    const from = st.total ? st.offset + 1 : 0, to = Math.min(st.offset + st.limit, st.total);
    pager.innerHTML = `<span>${from}-${to} / ${st.total}${st.sel.size ? ` · ${T('المحدد', 'selected')}: ${st.sel.size}` : ''}</span>
      <span class="btns"><button class="btn small" data-p="prev" ${st.offset ? '' : 'disabled'}>‹</button>
      <select class="inp" data-p="size">${[20, 50, 100, 200, 500].map(n => `<option ${n === st.limit ? 'selected' : ''}>${n}</option>`).join('')}</select>
      <button class="btn small" data-p="next" ${to < st.total ? '' : 'disabled'}>›</button></span>`;
    $('[data-p=prev]', pager).onclick = () => { st.offset = Math.max(0, st.offset - st.limit); load(); };
    $('[data-p=next]', pager).onclick = () => { st.offset += st.limit; load(); };
    $('[data-p=size]', pager).onchange = (e) => { st.limit = +e.target.value; st.offset = 0; load(); };
  }
  async function load() {
    try {
      const r = await cfg.fetch({ offset: st.offset, limit: st.limit, q: st.q, ...st.filters });
      st.total = r.total ?? r.rows.length; st.rows = r.rows;
      const ids = new Set(st.rows.map(x => x[cfg.idKey || 'id'])); st.sel.forEach(id => { if (!ids.has(id)) st.sel.delete(id); });
      if (all) all.checked = false;
      paint();
    } catch (e) { tbody.innerHTML = `<tr><td class="empty" colspan="${cols.length + 1}">${esc(e.message)}</td></tr>`; }
  }
  load();
  return g;
}

/* Client-side list (for endpoints returning everything). */
function localFetch(url, filterKeys = []) {
  return async ({ offset, limit, q, ...f }) => {
    const r = await GET(url + (url.includes('?') ? '&' : '?') + qs(f));
    let rows = r.rows || r;
    if (q) { const s = q.toLowerCase(); rows = rows.filter(x => Object.values(x).some(v => String(v ?? '').toLowerCase().includes(s))); }
    return { total: rows.length, rows: rows.slice(offset, offset + limit) };
  };
}
function serverFetch(url) {
  return ({ offset, limit, q, ...f }) => GET(url + (url.includes('?') ? '&' : '?') + qs({ offset, limit, q, ...f }));
}

/* Standard CRUD page for a REST collection. */
function crudPage(container, { endpoint, columns, fields, title, perm, fetchUrl, dialogSize, beforeSave, extraToolbar = [], local, filters, pageSize, onRow, formCls }) {
  const openForm = async (row) => {
    const flds = typeof fields === 'function' ? await fields(row) : fields;
    await formDialog({ title: (row ? T('تعديل', 'Edit') : T('إضافة', 'Add')) + ' — ' + title, fields: flds, data: row || {}, size: dialogSize, cls: formCls,
      save: async (vals) => { if (beforeSave) vals = await beforeSave(vals, row) || vals; return row ? PUT(`${endpoint}/${row.id}`, vals) : POST(endpoint, vals); } });
    App.lookups = null; g.reload();
  };
  const g = grid(container, {
    columns, pageSize, filters,
    fetch: local ? localFetch(fetchUrl || endpoint) : serverFetch(fetchUrl || endpoint),
    onRow: onRow || (can(perm) ? (r) => openForm(r) : null),
    toolbar: [
      { label: T('إضافة', 'Add'), icon: 'add', cls: 'primary', perm, action: () => openForm(null) },
      { label: T('تعديل', 'Edit'), icon: 'edit', perm, needSel: true, action: (sel) => openForm(sel[0]) },
      { label: T('حذف', 'Delete'), icon: 'del', cls: 'danger', perm, needSel: true, action: async (sel) => {
        if (!await confirmBox(T(`حذف ${sel.length} سجل؟`, `Delete ${sel.length} record(s)?`))) return;
        for (const r of sel) await guard(() => DEL(`${endpoint}/${r.id}`));
        toast(T('تم الحذف', 'Deleted'), 'ok'); App.lookups = null; g.reload();
      } },
      ...extraToolbar,
    ],
  });
  g.openForm = openForm;
  return g;
}

// ------------------------------------------------------------------ employee picker
async function pickEmployees({ title, multiple = true, preselect = [] } = {}) {
  const lk = await lookups();
  return new Promise(resolve => {
    const chosen = new Map(preselect.map(e => [e.id, e]));
    const body = h(`<div>
      <div class="toolbar" style="margin:-16px -16px 10px;border-bottom:1px solid var(--line)">
        <select class="inp dep"><option value="">${esc(T('كل الأقسام', 'All departments'))}</option>${lk.departments.map(d => `<option value="${d.id}">${esc(d.name)}</option>`).join('')}</select>
        <input class="inp q" type="search" placeholder="${esc(T('رقم أو اسم الموظف', 'ID or name'))}">
        ${multiple ? `<button class="btn small all">${esc(T('تحديد الكل', 'Select all'))}</button>` : ''}
        <span class="grow"></span><span class="muted cnt"></span></div>
      <div class="grid-wrap" style="max-height:380px"><table class="grid"><thead><tr><th class="chk"></th><th>${esc(T('الرقم', 'ID'))}</th><th>${esc(T('الاسم', 'Name'))}</th><th>${esc(T('القسم', 'Department'))}</th></tr></thead><tbody></tbody></table></div></div>`);
    let rows = [];
    const paint = () => {
      $('tbody', body).innerHTML = rows.map(e => `<tr data-id="${e.id}"><td class="chk"><input type="${multiple ? 'checkbox' : 'radio'}" name="pick" ${chosen.has(e.id) ? 'checked' : ''}></td><td>${esc(e.emp_code)}</td><td>${esc(e.name)}</td><td>${esc(e.department)}</td></tr>`).join('');
      $$('tbody tr', body).forEach(tr => { tr.onclick = () => { const e = rows.find(x => x.id === +tr.dataset.id); const cb = $('input', tr);
        if (!multiple) { chosen.clear(); $$('tbody input', body).forEach(i => i.checked = false); }
        if (multiple && chosen.has(e.id)) { chosen.delete(e.id); cb.checked = false; } else { chosen.set(e.id, e); cb.checked = true; }
        $('.cnt', body).textContent = `${T('المحدد', 'Selected')}: ${chosen.size}`; }; });
      $('.cnt', body).textContent = `${T('المحدد', 'Selected')}: ${chosen.size}`;
    };
    const load = async () => { const r = await GET('/api/employees?' + qs({ q: $('.q', body).value, department_id: $('.dep', body).value, limit: 500 })); rows = r.rows; paint(); };
    $('.q', body).oninput = debounce(load); $('.dep', body).onchange = load;
    if (multiple) $('.all', body).onclick = () => { rows.forEach(e => chosen.set(e.id, e)); paint(); };
    load();
    dialog({ title: title || T('اختيار الموظفين', 'Select employees'), size: 'wide', body, onClose: v => resolve(v || null),
      buttons: [{ label: T('إلغاء', 'Cancel') }, { label: T('اختيار', 'Select'), cls: 'primary', action: () => [...chosen.values()] }] });
  });
}

/* Inline "choose employees" widget used in forms: returns {el, get()} */
function employeeChooser(initial = [], { multiple = true } = {}) {
  let list = [...initial];
  const el = h(`<div class="field full"><label>${esc(T('الموظفون', 'Employees'))} <span class="req">*</span></label>
      <div style="display:flex;gap:8px;align-items:center"><button type="button" class="btn">${icon('people')}${esc(T('اختيار...', 'Choose...'))}</button><span class="muted sum"></span></div></div>`);
  const sum = () => { $('.sum', el).textContent = list.length ? list.slice(0, 6).map(e => `${e.emp_code} ${e.name}`).join('، ') + (list.length > 6 ? ` +${list.length - 6}` : '') : T('لم يتم الاختيار', 'None selected'); };
  $('button', el).onclick = async () => { const r = await pickEmployees({ multiple, preselect: list }); if (r) { list = r; sum(); } };
  sum();
  return { el, get: () => list };
}
