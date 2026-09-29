/* ZK Attendance Pro — pages & navigation (BioTime 9.5 style). */
'use strict';

const STATUS = {
  present: ['حاضر', 'Present', 'ok'], late: ['متأخر', 'Late', 'warn'], early: ['خروج مبكر', 'Early leave', 'warn'],
  late_early: ['متأخر + مبكر', 'Late & early', 'warn'], absent: ['غائب', 'Absent', 'bad'], leave: ['إجازة', 'Leave', 'purple'],
  holiday: ['عطلة رسمية', 'Holiday', 'info'], off: ['راحة', 'Day off', ''], incomplete: ['بصمة ناقصة', 'Missed punch', 'warn'],
  unscheduled: ['بدون جدول', 'Unscheduled', ''], pending: ['لم يحضر بعد', 'Not yet', ''],
};
const statusBadge = (s) => s ? `<span class="badge ${STATUS[s]?.[2] || ''}">${esc(T(...(STATUS[s] || [s, s])))}</span>` : '';
const APPROVAL = { approved: ['معتمد', 'Approved', 'ok'], pending: ['بانتظار الموافقة', 'Pending', 'warn'], rejected: ['مرفوض', 'Rejected', 'bad'] };
const approvalBadge = (s) => `<span class="badge ${APPROVAL[s]?.[2] || ''}">${esc(T(...(APPROVAL[s] || [s, s])))}</span>`;
const STATES = () => [[0, T('دخول', 'Check-In')], [1, T('خروج', 'Check-Out')], [2, T('خروج استراحة', 'Break-Out')], [3, T('عودة من استراحة', 'Break-In')], [4, T('دخول إضافي', 'OT-In')], [5, T('خروج إضافي', 'OT-Out')]];
const stateName = (v) => (STATES().find(s => s[0] === +v) || [v, v === 255 ? '-' : v])[1];
const VERIFY = { password: ['كلمة مرور', 'Password'], fingerprint: ['بصمة إصبع', 'Fingerprint'], card: ['بطاقة', 'Card'], face: ['وجه', 'Face'], palm: ['كف', 'Palm'], finger_vein: ['وريد', 'Finger vein'], other: ['أخرى', 'Other'] };
const verifyName = (v) => T(...(VERIFY[v] || [v.replace(/_/g, ' + '), v.replace(/_/g, ' + ')]));
const WEEKDAYS = () => App.lang === 'ar' ? ['الإثنين', 'الثلاثاء', 'الأربعاء', 'الخميس', 'الجمعة', 'السبت', 'الأحد'] : ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'];
const BIO_NAMES = { 1: ['بصمة إصبع', 'Fingerprint'], 2: ['وجه (IR)', 'Face (IR)'], 7: ['وريد الإصبع', 'Finger vein'], 8: ['كف اليد', 'Palm'], 6: ['راحة اليد', 'Palmprint'], 9: ['وجه مرئي', 'Visible face'] };
const opts = (list, key = 'id', label = 'name') => (list || []).map(x => ({ value: x[key], label: x[label] }));

// ============================================================== navigation
function modules() {
  return [
    { key: 'dashboard', label: T('الرئيسية', 'Dashboard'), icon: 'dashboard', items: [
      { r: 'dashboard', label: T('لوحة التحكم', 'Dashboard'), icon: 'dashboard', page: pageDashboard },
      { r: 'monitor', label: T('المراقبة الحية', 'Real-time monitor'), icon: 'monitor', perm: 'attendance.view', page: pageMonitor },
    ] },
    { key: 'personnel', label: T('الملف الشخصي', 'Personnel'), icon: 'people', items: [
      { r: 'personnel/employees', label: T('الموظفون', 'Employees'), icon: 'people', perm: 'personnel.view', page: pageEmployees },
      { r: 'personnel/departments', label: T('الأقسام', 'Departments'), icon: 'building', perm: 'personnel.view', page: pageDepartments },
      { r: 'personnel/positions', label: T('المسميات الوظيفية', 'Positions'), icon: 'badge', perm: 'personnel.view', page: pagePositions },
      { r: 'personnel/areas', label: T('المناطق', 'Areas'), icon: 'map', perm: 'personnel.view', page: pageAreas },
      { r: 'personnel/resigned', label: T('المستقيلون', 'Resigned'), icon: 'exit', perm: 'personnel.view', page: pageResigned },
    ] },
    { key: 'device', label: T('الأجهزة', 'Device'), icon: 'device', items: [
      { r: 'device/terminals', label: T('الجهاز', 'Device'), icon: 'device', perm: 'device.view', page: pageDevices },
      { r: 'device/transactions', label: T('سجل الحركات', 'Transactions'), icon: 'list', perm: 'attendance.view', page: pageTransactions },
      { r: 'device/commands', label: T('أوامر الأجهزة', 'Device commands'), icon: 'terminal', perm: 'device.view', page: pageCommands },
      { r: 'device/traffic', label: T('مراقبة الاتصال', 'Communication'), icon: 'sync', perm: 'device.view', page: pageTraffic },
      { r: 'device/oplogs', label: T('سجل عمليات الجهاز', 'Operation log'), icon: 'list', perm: 'device.view', page: pageOplogs },
      { r: 'device/errors', label: T('سجل الأخطاء', 'Error log'), icon: 'list', perm: 'device.view', page: pageErrors },
    ] },
    { key: 'attendance', label: T('الحضور والإنصراف', 'Attendance'), icon: 'clock', items: [
      { r: 'att/timetables', label: T('أوقات الدوام', 'Timetables'), icon: 'clock', perm: 'attendance.view', page: pageTimetables },
      { r: 'att/shifts', label: T('الورديات', 'Shifts'), icon: 'cal', perm: 'attendance.view', page: pageShifts },
      { r: 'att/schedules', label: T('جدولة الموظفين', 'Employee schedule'), icon: 'people', perm: 'attendance.view', page: pageSchedules },
      { r: 'att/dept-schedules', label: T('جدولة الأقسام', 'Department schedule'), icon: 'building', perm: 'attendance.view', page: pageDeptSchedules },
      { r: 'att/temp', label: T('الجدول المؤقت', 'Temporary schedule'), icon: 'cal', perm: 'attendance.view', page: pageTemp },
      { r: 'att/holidays', label: T('العطل الرسمية', 'Holidays'), icon: 'cal', perm: 'attendance.view', page: pageHolidays },
      { r: 'att/leave-types', label: T('أنواع الإجازات', 'Leave types'), icon: 'leave', perm: 'attendance.view', page: pageLeaveTypes },
      { r: 'att/leaves', label: T('الإجازات', 'Leave'), icon: 'leave', perm: 'attendance.view', page: pageLeaves },
      { r: 'att/manual', label: T('البصمات اليدوية', 'Manual punch'), icon: 'hand', perm: 'attendance.view', page: pageManual },
      { r: 'att/overtime', label: T('العمل الإضافي', 'Overtime'), icon: 'clock', perm: 'attendance.view', page: pageOvertime },
      { r: 'att/calc', label: T('نتائج الحضور', 'Attendance results'), icon: 'check', perm: 'attendance.view', page: pageCalc },
      { r: 'att/calendar', label: T('تقويم الموظف', 'Employee calendar'), icon: 'cal', perm: 'attendance.view', page: pageCalendar },
      { r: 'att/rules', label: T('قواعد الحضور', 'Attendance rules'), icon: 'system', perm: 'system.admin', page: pageRules },
    ] },
    { key: 'reports', label: T('التقارير', 'Reports'), icon: 'report', items: [
      { r: 'reports', label: T('كل التقارير', 'All reports'), icon: 'report', perm: 'reports.view', page: pageReports },
      { r: 'reports/daily', label: T('الحضور اليومي', 'Daily attendance'), icon: 'list', perm: 'reports.view', page: (c) => pageReport(c, 'daily') },
      { r: 'reports/summary', label: T('الملخص الشهري', 'Monthly summary'), icon: 'list', perm: 'reports.view', page: (c) => pageReport(c, 'summary') },
      { r: 'reports/monthly_status', label: T('كشف الحضور الشهري', 'Monthly status'), icon: 'cal', perm: 'reports.view', page: (c) => pageReport(c, 'monthly_status') },
      { r: 'reports/late', label: T('التأخير', 'Late'), icon: 'clock', perm: 'reports.view', page: (c) => pageReport(c, 'late') },
      { r: 'reports/absent', label: T('الغياب', 'Absence'), icon: 'exit', perm: 'reports.view', page: (c) => pageReport(c, 'absent') },
    ] },
    { key: 'system', label: T('النظام', 'System'), icon: 'system', items: [
      { r: 'system/settings', label: T('إعدادات النظام', 'Settings'), icon: 'system', perm: 'system.admin', page: pageSettings },
      { r: 'system/users', label: T('المستخدمون', 'Users'), icon: 'people', perm: 'system.admin', page: pageUsers },
      { r: 'system/roles', label: T('الأدوار والصلاحيات', 'Roles'), icon: 'shield', perm: 'system.admin', page: pageRoles },
      { r: 'system/backup', label: T('النسخ الاحتياطي', 'Backup'), icon: 'db', perm: 'system.admin', page: pageBackup },
      { r: 'system/audit', label: T('سجل التدقيق', 'Audit log'), icon: 'list', perm: 'system.admin', page: pageAudit },
      { r: 'system/about', label: T('حول البرنامج', 'About'), icon: 'badge', page: pageAbout },
    ] },
  ];
}
const REPORT_ROUTE = /^reports\/(\w+)$/;

function renderShell() {
  document.body.innerHTML = `
    <header class="topbar">
      <div class="logo"><button class="btn link menu-toggle" style="color:#fff">☰</button><div class="mark">ZK</div><span>ZK Attendance Pro<small>${esc(T('نظام الحضور والانصراف', 'Time & Attendance'))}</small></span></div>
      <nav class="modules"></nav>
      <div class="top-right">
        <button class="chip" id="langBtn">${icon('lang').replace('<svg', '<svg style="width:14px;height:14px;vertical-align:-2px"')} ${App.lang === 'ar' ? 'English' : 'العربية'}</button>
        <div class="dropdown" id="userMenu"><button class="chip">👤 ${esc(App.user.full_name || App.user.username)} ▾</button>
          <div class="menu" style="inset-inline-start:auto;inset-inline-end:0">
            <button data-u="pw">${icon('shield')}${esc(T('تغيير كلمة المرور', 'Change password'))}</button>
            <button data-u="out">${icon('exit')}${esc(T('تسجيل الخروج', 'Log out'))}</button></div></div>
      </div>
    </header>
    <aside class="sidebar"></aside>
    <main class="main"><div class="crumbs"></div><div id="page"></div></main>`;
  const nav = $('.modules');
  for (const m of modules()) {
    const visible = m.items.filter(i => !i.perm || can(i.perm));
    if (!visible.length) continue;
    const a = h(`<a href="#/${visible[0].r}" data-mod="${m.key}">${icon(m.icon)}<span>${esc(m.label)}</span></a>`);
    nav.appendChild(a);
  }
  $('#langBtn').onclick = async () => { setLang(App.lang === 'ar' ? 'en' : 'ar'); try { await POST('/api/auth/language', { language: App.lang }); } catch (e) { /* offline */ } renderShell(); route(); };
  const um = $('#userMenu');
  $('button', um).onclick = (e) => { e.stopPropagation(); um.classList.toggle('open'); };
  $('[data-u=pw]', um).onclick = () => { um.classList.remove('open'); changePassword(); };
  $('[data-u=out]', um).onclick = async () => { await POST('/api/auth/logout'); App.user = null; showLogin(); };
  $('.menu-toggle').onclick = () => document.body.classList.toggle('menu-open');
}
document.addEventListener('click', () => $$('.dropdown.open').forEach(d => d.classList.remove('open')));

function route() {
  App.timers.forEach(t => clearInterval(t)); App.timers = [];
  document.body.classList.remove('menu-open');
  const path = (location.hash.replace(/^#\/?/, '') || 'dashboard').split('?')[0];
  const mods = modules();
  let mod = null, item = null;
  for (const m of mods) for (const i of m.items) if (i.r === path) { mod = m; item = i; }
  const rm = path.match(REPORT_ROUTE);
  if (!item && rm) { mod = mods.find(m => m.key === 'reports'); item = { r: path, label: T('تقرير', 'Report'), page: (c) => pageReport(c, rm[1]) }; }
  if (!item) { mod = mods[0]; item = mod.items[0]; }
  $$('.modules a').forEach(a => a.classList.toggle('active', a.dataset.mod === mod.key));
  const side = $('.sidebar');
  side.innerHTML = `<h4>${esc(mod.label)}</h4>` + mod.items.filter(i => !i.perm || can(i.perm)).map(i =>
    `<a href="#/${i.r}" class="${i.r === item.r ? 'active' : ''}">${icon(i.icon)}<span>${esc(i.label)}</span></a>`).join('');
  $('.crumbs').textContent = `${mod.label} / ${item.label}`;
  const page = $('#page'); page.innerHTML = '';
  if (item.perm && !can(item.perm)) { page.innerHTML = `<div class="alert">${esc(T('ليست لديك صلاحية لهذه الصفحة', 'You do not have permission for this page'))}</div>`; return; }
  Promise.resolve(item.page(page, item)).catch(e => { page.innerHTML = `<div class="alert">${esc(e.message)}</div>`; });
}
window.addEventListener('hashchange', () => App.user && route());

function title(c, text, right = '') { c.appendChild(h(`<div class="page-title"><h1>${esc(text)}</h1><div>${right}</div></div>`)); }

// ============================================================== login
function showLogin(msg) {
  App.timers.forEach(t => clearInterval(t)); App.timers = [];
  document.body.innerHTML = `<div class="login-wrap"><form class="login" method="post" action="#">
    <div class="logo" style="width:auto;padding:0;margin-bottom:14px;color:var(--brand-dark)"><div class="mark" style="color:#fff">ZK</div><b>ZK Attendance Pro</b></div>
    <h2>${esc(T('تسجيل الدخول', 'Sign in'))}</h2><p>${esc(T('نظام الحضور والانصراف لأجهزة ZKTeco', 'Time & attendance for ZKTeco terminals'))}</p>
    <div class="field"><label>${esc(T('اسم المستخدم', 'Username'))}</label><input class="inp" name="u" autocomplete="username" required></div>
    <div class="field"><label>${esc(T('كلمة المرور', 'Password'))}</label><input class="inp" name="p" type="password" autocomplete="current-password" required></div>
    <div class="alert hidden" id="lerr"></div>
    <button class="btn primary" type="submit">${esc(T('دخول', 'Sign in'))}</button>
    <div class="lang"><a href="#" id="lsw">${App.lang === 'ar' ? 'English' : 'العربية'}</a></div></form></div>`;
  if (msg) { $('#lerr').textContent = msg; $('#lerr').classList.remove('hidden'); }
  $('#lsw').onclick = (e) => { e.preventDefault(); setLang(App.lang === 'ar' ? 'en' : 'ar'); showLogin(); };
  $('.login').onsubmit = async (ev) => {
    ev.preventDefault();
    try {
      const r = await api('POST', '/api/auth/login', { username: $('[name=u]').value, password: $('[name=p]').value }, { noAuthRedirect: true });
      await startApp(r.user);
    } catch (e) { $('#lerr').textContent = e.message; $('#lerr').classList.remove('hidden'); }
  };
  setTimeout(() => $('[name=u]').focus(), 20);
}
async function startApp(user) {
  App.user = user;
  if (user.language && user.language !== App.lang && !localStorage.getItem('zk_lang')) setLang(user.language);
  App.lookups = null;
  renderShell();
  if (!location.hash || location.hash === '#login') location.hash = '#/dashboard'; else route();
  if (user.must_change_password) changePassword(true);
}
function changePassword(forced) {
  const fields = [
    { key: 'old_password', label: T('كلمة المرور الحالية', 'Current password'), type: 'password', required: true },
    { key: 'new_password', label: T('كلمة المرور الجديدة (6 أحرف على الأقل)', 'New password (min 6)'), type: 'password', required: true },
    { key: 'confirm', label: T('تأكيد كلمة المرور', 'Confirm password'), type: 'password', required: true },
  ];
  const d = dialog({ title: forced ? T('يرجى تغيير كلمة المرور الافتراضية', 'Please change the default password') : T('تغيير كلمة المرور', 'Change password'),
    size: 'narrow', body: formHtml(fields, {}, 'one'), buttons: [{ label: T('إلغاء', 'Cancel') }, { label: T('حفظ', 'Save'), cls: 'primary', action: async () => {
      const v = readForm(d.content, fields);
      if (v.new_password !== v.confirm) throw new Error(T('كلمتا المرور غير متطابقتين', 'Passwords do not match'));
      await POST('/api/auth/password', v); App.user.must_change_password = false; toast(T('تم تغيير كلمة المرور', 'Password changed'), 'ok');
    } }] });
}

// ============================================================== dashboard
async function pageDashboard(c) {
  title(c, T('لوحة التحكم', 'Dashboard'), `<span class="muted">${esc(new Date().toLocaleDateString(App.lang === 'ar' ? 'ar' : 'en-GB', { weekday: 'long', year: 'numeric', month: 'long', day: 'numeric' }))}</span>`);
  const box = h('<div></div>'); c.appendChild(box);
  const draw = async () => {
    const d = await GET('/api/dashboard');
    const card = (v, l, color, ic, href) => `<a class="card" ${href ? `href="#/${href}"` : ''} style="color:inherit"><div class="ic" style="background:${color}">${icon(ic)}</div><div><div class="v">${v}</div><div class="l">${esc(l)}</div></div></a>`;
    const maxT = Math.max(1, ...d.trend.map(t => t.present + t.absent));
    const W = 560, H = 200, bw = W / 7;
    const bars = d.trend.map((t, i) => {
      const x = i * bw + 12, ph = (t.present / maxT) * (H - 40), ah = (t.absent / maxT) * (H - 40), lh = (t.late / maxT) * (H - 40);
      const lbl = WEEKDAYS()[(new Date(t.date + 'T00:00:00').getDay() + 6) % 7];
      return `<rect x="${x}" y="${H - 22 - ph}" width="${bw / 3 - 2}" height="${ph}" fill="#6cb33f" rx="2"><title>${T('حضور', 'Present')}: ${t.present}</title></rect>
        <rect x="${x + bw / 3}" y="${H - 22 - lh}" width="${bw / 3 - 2}" height="${lh}" fill="#e08a00" rx="2"><title>${T('تأخير', 'Late')}: ${t.late}</title></rect>
        <rect x="${x + 2 * bw / 3 - 2}" y="${H - 22 - ah}" width="${bw / 3 - 2}" height="${ah}" fill="#d64040" rx="2"><title>${T('غياب', 'Absent')}: ${t.absent}</title></rect>
        <text x="${x + bw / 2 - 12}" y="${H - 6}" font-size="11" fill="#6b7a8c" text-anchor="middle">${esc(lbl)}</text>`;
    }).join('');
    box.innerHTML = `
      ${App.user.must_change_password ? `<div class="alert">${esc(T('ما زلت تستخدم كلمة المرور الافتراضية admin — غيّرها من قائمة المستخدم.', 'You are still using the default password — change it from the user menu.'))}</div>` : ''}
      <div class="cards">
        ${card(d.employees, T('الموظفون', 'Employees'), '#0b6fb8', 'people', 'personnel/employees')}
        ${card(`${d.online}/${d.devices}`, T('أجهزة متصلة', 'Devices online'), d.offline ? '#e08a00' : '#2e9b4b', 'device', 'device/terminals')}
        ${card(d.present, T('حاضرون اليوم', 'Present today'), '#2e9b4b', 'check', 'att/calc')}
        ${card(d.late, T('متأخرون', 'Late'), '#e08a00', 'clock', 'att/calc')}
        ${card(d.absent, T('غائبون', 'Absent'), '#d64040', 'exit', 'att/calc')}
        ${card(d.leave, T('في إجازة', 'On leave'), '#7b3fb0', 'leave', 'att/leaves')}
        ${card(d.not_yet, T('لم يحضروا بعد', 'Not yet in'), '#6b7a8c', 'clock', 'att/calc')}
        ${card(d.punches_today, T('حركات اليوم', 'Punches today'), '#1e88e5', 'hand', 'device/transactions')}
      </div>
      ${d.pending.leaves + d.pending.manual + d.pending.overtime ? `<div class="alert info">${esc(T('طلبات بانتظار الموافقة', 'Pending approvals'))}: ${esc(T('إجازات', 'leave'))} ${d.pending.leaves} · ${esc(T('بصمات يدوية', 'manual punches'))} ${d.pending.manual} · ${esc(T('عمل إضافي', 'overtime'))} ${d.pending.overtime}</div>` : ''}
      <div class="dash-grid">
        <div>
          <div class="panel"><div class="panel-head"><h3>${esc(T('الحضور خلال آخر 7 أيام', 'Attendance — last 7 days'))}</h3>
            <span class="muted"><span class="dot" style="background:#6cb33f"></span>${esc(T('حضور', 'Present'))} <span class="dot" style="background:#e08a00"></span>${esc(T('تأخير', 'Late'))} <span class="dot" style="background:#d64040"></span>${esc(T('غياب', 'Absent'))}</span></div>
            <div class="panel-body"><svg class="chart" viewBox="0 0 ${W} ${H}" preserveAspectRatio="none">${bars}</svg></div></div>
          <div class="panel"><div class="panel-head"><h3>${esc(T('حالة الأجهزة', 'Device status'))}</h3><a href="#/device/terminals">${esc(T('الكل', 'All'))}</a></div>
            <div class="grid-wrap"><table class="grid"><thead><tr><th>${esc(T('الجهاز', 'Device'))}</th><th>${esc(T('الرقم التسلسلي', 'Serial'))}</th><th>IP</th><th>${esc(T('الحالة', 'State'))}</th><th>${esc(T('المستخدمون', 'Users'))}</th><th>${esc(T('آخر اتصال', 'Last activity'))}</th></tr></thead>
            <tbody>${d.device_list.map(x => `<tr><td>${esc(x.alias)}</td><td class="ltr">${esc(x.sn)}</td><td class="ltr">${esc(x.ip)}</td><td>${stateIcon(x)} ${esc(stateLabel(x.state))}</td><td>${x.users}</td><td class="ltr">${esc(x.last_activity)}</td></tr>`).join('') || `<tr><td class="empty" colspan="6">${esc(T('لا توجد أجهزة بعد — وجّه جهاز البصمة إلى عنوان هذا الخادم (انظر الإعدادات)', 'No devices yet — point a terminal at this server (see Settings)'))}</td></tr>`}</tbody></table></div></div>
        </div>
        <div>
          <div class="panel"><div class="panel-head"><h3>${esc(T('آخر الحركات', 'Latest punches'))}</h3><a href="#/monitor">${esc(T('المراقبة الحية', 'Live monitor'))}</a></div><div class="feed" id="feed"></div></div>
          <div class="panel"><div class="panel-head"><h3>${esc(T('الحضور حسب القسم (اليوم)', 'Attendance by department (today)'))}</h3></div><div class="panel-body">
            ${d.departments.map(x => `<div class="bar-row"><span class="name">${esc(x.department)}</span><span class="bar"><i style="width:${x.total ? Math.round(100 * x.present / x.total) : 0}%"></i></span><span class="n">${x.present}/${x.total}</span></div>`).join('') || `<span class="muted">—</span>`}
          </div></div>
        </div>
      </div>`;
    await feed($('#feed', box), 12);
  };
  await draw();
  App.timers.push(setInterval(() => { if (document.visibilityState === 'visible') draw().catch(() => {}); }, 30000));
}
function stateLabel(s) { return { online: T('متصل', 'Online'), offline: T('غير متصل', 'Offline'), disabled: T('معطل', 'Disabled') }[s] || s; }
function avatar(r) {
  return r.employee_id && r.employee_has_photo ? `<span class="avatar"><img src="/api/employees/${r.employee_id}/photo" alt="" loading="lazy"></span>` : `<span class="avatar">${esc((r.name || r.emp_code || '?').trim().charAt(0))}</span>`;
}
async function feed(el, n) {
  const r = await GET('/api/monitor');
  const rows = r.rows.slice(-n).reverse();
  el.innerHTML = rows.map(x => `<div class="feed-item">${avatar(x)}<div class="meta"><b>${esc(x.name || x.emp_code)}</b><small>${esc(x.emp_code)} · ${esc(x.department || '')} · ${esc(x.device || '')}</small></div>
     <div class="t"><b class="ltr">${esc(x.punch_time.slice(11, 16))}</b>${esc(verifyName(x.verify))}</div></div>`).join('') || `<div class="empty">${esc(T('لا توجد حركات بعد', 'No punches yet'))}</div>`;
}

// ============================================================== real-time monitor
async function pageMonitor(c) {
  title(c, T('المراقبة الحية للحركات', 'Real-time monitor'), `<span class="muted" id="live">● ${esc(T('مباشر', 'Live'))}</span>`);
  const p = h(`<div class="panel"><div class="monitor"></div></div>`); c.appendChild(p);
  const box = $('.monitor', p);
  let last = 0;
  const add = (rows, isNew) => {
    for (const x of rows) {
      const photo = x.has_photo ? `<img src="/api/transactions/${x.id}/photo" alt="" loading="lazy">` : (x.employee_has_photo ? `<img src="/api/employees/${x.employee_id}/photo" alt="">` : `<span style="font-size:40px">👤</span>`);
      const el = h(`<div class="mcard ${isNew ? 'new' : ''}"><div class="ph">${photo}</div><div class="body"><b>${esc(x.name || x.emp_code)}</b>
        <small>${esc(x.emp_code)} · ${esc(x.department || '')}</small><small class="ltr">${esc(x.punch_time)}</small>
        <small>${esc(stateName(x.punch_state))} · ${esc(verifyName(x.verify))}${x.temperature ? ` · ${x.temperature}°` : ''}</small><small>${esc(x.device || '')}</small></div></div>`);
      box.prepend(el);
    }
    while (box.children.length > 60) box.lastChild.remove();
  };
  const r = await GET('/api/monitor'); add(r.rows, false); last = r.last_id;
  App.timers.push(setInterval(async () => {
    try { const n = await GET('/api/monitor?after_id=' + last); if (n.rows.length) { add(n.rows, true); last = n.last_id; } $('#live').style.color = '#2e9b4b'; }
    catch (e) { const l = $('#live'); if (l) l.style.color = '#d64040'; }
  }, 3000));
}

// ============================================================== personnel
async function employeeFields(row) {
  const lk = await lookups();
  return [
    { section: T('البيانات الأساسية', 'Basic information') },
    { key: 'emp_code', label: T('رقم الموظف (رقم البصمة)', 'Employee ID (device PIN)'), required: true, readonly: !!row },
    { key: 'first_name', label: T('الاسم الأول', 'First name'), required: true },
    { key: 'last_name', label: T('اسم العائلة', 'Last name') },
    { key: 'gender', label: T('الجنس', 'Gender'), type: 'select', options: [{ value: 'M', label: T('ذكر', 'Male') }, { value: 'F', label: T('أنثى', 'Female') }] },
    { key: 'department_id', label: T('القسم', 'Department'), type: 'select', options: opts(lk.departments), required: true, default: lk.departments[0]?.id },
    { key: 'position_id', label: T('المسمى الوظيفي', 'Position'), type: 'select', options: opts(lk.positions) },
    { key: 'hire_date', label: T('تاريخ التعيين', 'Hire date'), type: 'date', default: today() },
    { key: 'emp_type', label: T('نوع التوظيف', 'Employment type'), type: 'select', blank: false, options: [{ value: 'permanent', label: T('دائم', 'Permanent') }, { value: 'contract', label: T('عقد', 'Contract') }, { value: 'temporary', label: T('مؤقت', 'Temporary') }, { value: 'probation', label: T('تحت التجربة', 'Probation') }] },
    { key: 'birthday', label: T('تاريخ الميلاد', 'Birthday'), type: 'date' },
    { key: 'national_id', label: T('رقم الهوية', 'National ID') },
    { key: 'mobile', label: T('الجوال', 'Mobile') },
    { key: 'email', label: T('البريد الإلكتروني', 'Email'), type: 'email' },
    { key: 'address', label: T('العنوان', 'Address'), full: true },
    { section: T('إعدادات الجهاز', 'Device settings') },
    { key: 'card_no', label: T('رقم البطاقة', 'Card number') },
    { key: 'dev_password', label: T('كلمة مرور الجهاز', 'Device password') },
    { key: 'dev_privilege', label: T('الصلاحية على الجهاز', 'Device privilege'), type: 'select', blank: false, options: [{ value: 0, label: T('مستخدم عادي', 'User') }, { value: 2, label: T('مسجّل', 'Enroller') }, { value: 6, label: T('مدير', 'Administrator') }, { value: 14, label: T('مدير عام', 'Super administrator') }] },
    { key: 'verify_mode', label: T('طريقة التحقق', 'Verification mode'), type: 'select', blank: false, options: [{ value: -1, label: T('حسب إعداد الجهاز', 'Device default') }, { value: 15, label: T('وجه', 'Face') }, { value: 1, label: T('بصمة إصبع', 'Fingerprint') }, { value: 25, label: T('كف', 'Palm') }, { value: 4, label: T('بطاقة', 'Card') }, { value: 3, label: T('كلمة مرور', 'Password') }, { value: 0, label: T('أي طريقة', 'Any') }] },
    { key: 'enable_att', label: T('الحضور', 'Attendance'), type: 'checkbox', text: T('يُحتسب حضوره', 'Counts for attendance'), default: true },
    { key: 'area_ids', label: T('المناطق (يُرسل الموظف لكل أجهزة المنطقة)', 'Areas (the employee is sent to every device in them)'), type: 'multi', options: opts(lk.areas), default: lk.areas.length ? [lk.areas[0].id] : [] },
  ];
}
function bioCell(r) {
  const parts = [];
  if (r.face_count) parts.push(`<span title="${esc(T('وجه', 'Face'))}">😊 ${r.face_count}</span>`);
  if (r.fp_count) parts.push(`<span title="${esc(T('بصمة إصبع', 'Fingerprint'))}">☝ ${r.fp_count}</span>`);
  if (r.palm_count) parts.push(`<span title="${esc(T('كف', 'Palm'))}">✋ ${r.palm_count}</span>`);
  if (r.card_no) parts.push(`<span title="${esc(T('بطاقة', 'Card'))}">💳</span>`);
  return `<span class="bio">${parts.join('')}</span>`;
}
async function pageEmployees(c, _i, resigned = false) {
  title(c, resigned ? T('الموظفون المستقيلون', 'Resigned employees') : T('الموظفون', 'Employees'));
  const lk = await lookups();
  let g;
  const edit = async (row) => {
    const full = row ? await GET(`/api/employees/${row.id}`) : null;
    const flds = await employeeFields(full);
    const body = h(`<div><div class="tabs"><button class="active" data-t="info">${esc(T('البيانات', 'Details'))}</button>${full ? `<button data-t="bio">${esc(T('القياسات الحيوية', 'Biometrics'))}</button><button data-t="att">${esc(T('الحضور', 'Attendance'))}</button>` : ''}</div>
      <div data-p="info">${full ? `<div style="display:flex;gap:14px;align-items:center;margin-bottom:12px">${full.has_photo ? `<img src="/api/employees/${full.id}/photo?${Date.now()}" style="width:72px;height:72px;border-radius:8px;object-fit:cover">` : '<span class="avatar" style="width:72px;height:72px;border-radius:8px">👤</span>'}
        <label class="btn small">${icon('upload')}${esc(T('رفع صورة', 'Upload photo'))}<input type="file" accept="image/jpeg" hidden id="photoIn"></label></div>` : ''}${formHtml(flds, full || {})}</div>
      <div data-p="bio" class="hidden"></div><div data-p="att" class="hidden"></div></div>`);
    const d = dialog({ title: (full ? T('تعديل موظف', 'Edit employee') + ' — ' + full.emp_code : T('إضافة موظف', 'New employee')), size: 'wide', body,
      buttons: [{ label: T('إلغاء', 'Cancel') }, ...(can('personnel.edit') ? [{ label: T('حفظ', 'Save'), cls: 'primary', icon: 'check', action: async () => {
        const v = readForm($('[data-p=info]', body), flds);
        if (full) await PUT(`/api/employees/${full.id}`, v); else await POST('/api/employees', v);
        toast(T('تم الحفظ — ستُرسل التغييرات للأجهزة تلقائياً', 'Saved — changes are sent to the devices automatically'), 'ok'); g.reload();
      } }] : [])] });
    $$('.tabs button', body).forEach(b => b.onclick = () => {
      $$('.tabs button', body).forEach(x => x.classList.toggle('active', x === b));
      $$('[data-p]', body).forEach(p => p.classList.toggle('hidden', p.dataset.p !== b.dataset.t));
      if (b.dataset.t === 'bio') renderBio($('[data-p=bio]', body), full);
      if (b.dataset.t === 'att') renderEmpCalendar($('[data-p=att]', body), full.id, today().slice(0, 7));
    });
    const pin = $('#photoIn', body);
    if (pin) pin.onchange = async () => { const fd = new FormData(); fd.append('file', pin.files[0]); await guard(() => api('POST', `/api/employees/${full.id}/photo`, fd), T('تم رفع الصورة', 'Photo uploaded')); d.close(); g.reload(); };
  };
  g = grid(c, {
    columns: [
      { key: 'emp_code', label: T('الرقم', 'ID') },
      { key: 'name', label: T('الاسم', 'Name'), render: r => `${r.has_photo ? '📷 ' : ''}${esc(r.name)}` },
      { key: 'department', label: T('القسم', 'Department') },
      { key: 'position', label: T('الوظيفة', 'Position') },
      { key: 'areas', label: T('المناطق', 'Areas') },
      { key: 'bio', label: T('التحقق', 'Verification'), render: bioCell },
      { key: 'card_no', label: T('البطاقة', 'Card') },
      { key: 'hire_date', label: resigned ? T('تاريخ الاستقالة', 'Resign date') : T('تاريخ التعيين', 'Hire date'), render: r => esc(resigned ? r.resign_date : r.hire_date) },
      { key: 'mobile', label: T('الجوال', 'Mobile') },
    ],
    fetch: serverFetch(`/api/employees?status=${resigned ? 'resigned' : 'active'}`),
    filters: [{ key: 'department_id', label: T('كل الأقسام', 'All departments'), type: 'select', options: opts(lk.departments) },
      { key: 'area_id', label: T('كل المناطق', 'All areas'), type: 'select', options: opts(lk.areas) }],
    onRow: (r) => edit(r),
    toolbar: resigned ? [
      { label: T('إعادة للعمل', 'Reinstate'), icon: 'sync', cls: 'primary', perm: 'personnel.edit', needSel: true, action: async (sel) => { await guard(() => POST('/api/employees/batch', { ids: sel.map(r => r.id), action: 'reinstate' }), T('تمت الإعادة', 'Reinstated')); g.reload(); } },
      { label: T('حذف نهائي', 'Delete'), icon: 'del', cls: 'danger', perm: 'personnel.edit', needSel: true, action: async (sel) => { if (await confirmBox(T('حذف الموظفين نهائياً مع سجلاتهم؟', 'Permanently delete the employees and their records?'))) { await guard(() => POST('/api/employees/batch', { ids: sel.map(r => r.id), action: 'delete' }), T('تم الحذف', 'Deleted')); g.reload(); } } },
    ] : [
      { label: T('إضافة', 'Add'), icon: 'add', cls: 'primary', perm: 'personnel.edit', action: () => edit(null) },
      { label: T('تعديل', 'Edit'), icon: 'edit', perm: 'personnel.edit', needSel: true, action: (sel) => edit(sel[0]) },
      { label: T('إجراءات', 'Actions'), icon: 'more', perm: 'personnel.edit', menu: [
        { label: T('نقل إلى قسم', 'Change department'), icon: 'building', needSel: true, action: (sel) => batchSelect(sel, 'set_department', 'department_id', T('القسم', 'Department'), opts(lk.departments), g) },
        { label: T('تغيير المسمى الوظيفي', 'Change position'), icon: 'badge', needSel: true, action: (sel) => batchSelect(sel, 'set_position', 'position_id', T('المسمى', 'Position'), opts(lk.positions), g) },
        { label: T('تحديد المناطق', 'Set areas'), icon: 'map', needSel: true, action: (sel) => batchAreas(sel, 'set_areas', g) },
        { label: T('إضافة إلى مناطق', 'Add to areas'), icon: 'map', needSel: true, action: (sel) => batchAreas(sel, 'add_areas', g) },
        '-',
        { label: T('مزامنة مع الأجهزة', 'Synchronize to devices'), icon: 'sync', needSel: true, action: async (sel) => { const r = await guard(() => POST('/api/employees/batch', { ids: sel.map(x => x.id), action: 'sync' })); toast(T(`أُضيف ${r.commands} أمر للأجهزة`, `${r.commands} commands queued`), 'ok'); } },
        { label: T('استقالة', 'Resign'), icon: 'exit', needSel: true, action: (sel) => resignDialog(sel, g) },
        { label: T('حذف', 'Delete'), icon: 'del', needSel: true, action: async (sel) => { if (await confirmBox(T(`حذف ${sel.length} موظف؟ سيُحذفون من الأجهزة أيضاً.`, `Delete ${sel.length} employee(s)? They are removed from the devices too.`))) { await guard(() => POST('/api/employees/batch', { ids: sel.map(r => r.id), action: 'delete' }), T('تم الحذف', 'Deleted')); g.reload(); } } },
      ] },
      { label: T('استيراد', 'Import'), icon: 'upload', perm: 'personnel.edit', action: () => importEmployees(g) },
      { label: T('تصدير', 'Export'), icon: 'download', menu: [
        { label: 'Excel', action: () => download(`/api/employees-export?fmt=xlsx`) },
        { label: 'CSV', action: () => download(`/api/employees-export?fmt=csv`) }] },
    ],
  });
}
const pageResigned = (c, i) => pageEmployees(c, i, true);
function batchSelect(sel, action, key, label, options, g) {
  const f = [{ key, label, type: 'select', options, required: true }];
  formDialog({ title: label, size: 'narrow', cls: 'one', fields: f, save: (v) => POST('/api/employees/batch', { ids: sel.map(r => r.id), action, [key]: v[key] }) }).then(() => g.reload());
}
async function batchAreas(sel, action, g) {
  const lk = await lookups();
  const f = [{ key: 'area_ids', label: T('المناطق', 'Areas'), type: 'multi', options: opts(lk.areas) }];
  await formDialog({ title: action === 'set_areas' ? T('تحديد المناطق', 'Set areas') : T('إضافة إلى مناطق', 'Add to areas'), size: 'narrow', cls: 'one', fields: f,
    save: (v) => POST('/api/employees/batch', { ids: sel.map(r => r.id), action, area_ids: v.area_ids }) });
  g.reload();
}
async function resignDialog(sel, g) {
  const f = [
    { key: 'resign_date', label: T('تاريخ الاستقالة', 'Resign date'), type: 'date', default: today(), required: true },
    { key: 'resign_type', label: T('النوع', 'Type'), type: 'select', blank: false, options: [{ value: 'resign', label: T('استقالة', 'Resignation') }, { value: 'terminate', label: T('إنهاء خدمة', 'Termination') }, { value: 'other', label: T('أخرى', 'Other') }] },
    { key: 'resign_reason', label: T('السبب', 'Reason'), type: 'textarea' },
  ];
  await formDialog({ title: T('استقالة الموظفين', 'Resign employees') + ` (${sel.length})`, fields: f, cls: 'one', size: 'narrow',
    save: (v) => POST('/api/employees/batch', { ids: sel.map(r => r.id), action: 'resign', ...v }) });
  g.reload();
}
function importEmployees(g) {
  const body = h(`<div><p>${esc(T('ملف Excel أو CSV. الأعمدة المقبولة:', 'Excel or CSV file. Accepted columns:'))}</p>
    <pre class="code">emp_code, first_name, last_name, department, position, card_no, gender, hire_date, mobile, email, national_id</pre>
    <p class="muted">${esc(T('يمكن استخدام العناوين العربية: الرقم، الاسم، القسم، الوظيفة، البطاقة. الموظف الموجود يُحدَّث، والأقسام الجديدة تُنشأ تلقائياً.', 'Existing employees are updated; new departments are created automatically.'))}</p>
    <input type="file" accept=".xlsx,.csv" class="inp"><div class="res"></div></div>`);
  dialog({ title: T('استيراد الموظفين', 'Import employees'), body, buttons: [{ label: T('إغلاق', 'Close') }, { label: T('استيراد', 'Import'), cls: 'primary', action: async () => {
    const f = $('input', body).files[0]; if (!f) throw new Error(T('اختر ملفاً', 'Choose a file'));
    const fd = new FormData(); fd.append('file', f);
    const r = await api('POST', '/api/employees/import', fd);
    $('.res', body).innerHTML = `<div class="alert info">${esc(T('جديد', 'New'))}: ${r.created} · ${esc(T('محدّث', 'Updated'))}: ${r.updated}${r.errors.length ? '<br>' + r.errors.map(esc).join('<br>') : ''}</div>`;
    g.reload(); return false;
  } }] });
}
async function renderBio(el, emp) {
  const e = await GET(`/api/employees/${emp.id}`);
  const lk = await lookups();
  el.innerHTML = `<div class="alert info">${esc(T('القوالب تُسجَّل على أي جهاز ثم تُوزَّع تلقائياً على باقي أجهزة مناطق الموظف (إذا كانت خوارزمية الجهاز متوافقة؛ وإلا تُرسل صورة الوجه ليستخرج الجهاز قالبه).', 'Templates enrolled on any terminal are distributed to the other devices of the employee\'s areas (if the algorithm matches; otherwise the face photo is sent so the device builds its own template).'))}</div>
    <table class="grid"><thead><tr><th>${esc(T('النوع', 'Type'))}</th><th>${esc(T('الرقم', 'No.'))}</th><th>${esc(T('الإصدار', 'Version'))}</th><th>${esc(T('المصدر', 'Source'))}</th><th>${esc(T('آخر تحديث', 'Updated'))}</th><th></th></tr></thead><tbody>
    ${e.templates.map(t => `<tr><td>${esc(T(...(BIO_NAMES[t.bio_type] || [t.type, t.type])))}</td><td>${t.no}</td><td class="ltr">${esc(t.version)}</td><td class="ltr">${esc(t.source)}</td><td class="ltr">${esc(t.updated_at)}</td><td>${can('personnel.edit') ? `<button class="btn small danger" data-del="${t.id}">${icon('del')}</button>` : ''}</td></tr>`).join('') || `<tr><td class="empty" colspan="6">${esc(T('لا توجد قوالب — سجّل الوجه أو البصمة على الجهاز أو استخدم التسجيل عن بعد', 'No templates — enroll on a terminal or use remote enrollment'))}</td></tr>`}
    </tbody></table>
    ${e.bio_photos.length ? `<p class="muted">${esc(T('صورة تسجيل الوجه محفوظة', 'Face enrollment photo stored'))} ✓</p>` : ''}
    ${can('device.control') ? `<div style="margin-top:12px;display:flex;gap:8px;align-items:center;flex-wrap:wrap"><b>${esc(T('تسجيل عن بعد', 'Remote enrollment'))}:</b>
      <select class="inp dev">${lk.devices.map(d => `<option value="${esc(d.sn)}">${esc(d.name)}</option>`).join('')}</select>
      <select class="inp typ"><option value="9">${esc(T('وجه', 'Face'))}</option><option value="1">${esc(T('بصمة إصبع', 'Fingerprint'))}</option><option value="8">${esc(T('كف', 'Palm'))}</option></select>
      <button class="btn enroll">${esc(T('ابدأ التسجيل على الجهاز', 'Start on device'))}</button></div>` : ''}`;
  $$('[data-del]', el).forEach(b => b.onclick = async () => { if (await confirmBox(T('حذف القالب من البرنامج ومن الأجهزة؟', 'Delete the template from the server and devices?'))) { await guard(() => DEL(`/api/employees/${emp.id}/templates/${b.dataset.del}`), T('تم الحذف', 'Deleted')); renderBio(el, emp); } });
  const en = $('.enroll', el);
  if (en) en.onclick = async () => {
    const devs = (await GET('/api/devices')).rows; const d = devs.find(x => x.sn === $('.dev', el).value);
    if (!d) return toast(T('لا يوجد جهاز', 'No device'), 'bad');
    await guard(() => POST(`/api/devices/${d.id}/action`, { action: 'enroll', emp_code: emp.emp_code, bio_type: +$('.typ', el).value }), T('أُرسل الأمر — اطلب من الموظف الوقوف أمام الجهاز', 'Sent — ask the employee to stand at the device'));
  };
}

function simplePage(c, heading, endpoint, perm, columns, fields, extra = {}) {
  title(c, heading);
  return crudPage(c, { endpoint, columns, fields, title: heading, perm, ...extra });
}
async function pageDepartments(c) {
  const lk = await lookups();
  simplePage(c, T('الأقسام', 'Departments'), '/api/departments', 'personnel.edit',
    [{ key: 'code', label: T('الرمز', 'Code') }, { key: 'name', label: T('الاسم', 'Name') },
      { key: 'parent_id', label: T('القسم الرئيسي', 'Parent'), render: r => esc(lk.departments.find(d => d.id === r.parent_id)?.name || '') },
      { key: 'employees', label: T('عدد الموظفين', 'Employees'), cls: 'num' }],
    async () => { const l = await lookups(true); return [{ key: 'code', label: T('الرمز', 'Code'), required: true }, { key: 'name', label: T('الاسم', 'Name'), required: true }, { key: 'parent_id', label: T('القسم الرئيسي', 'Parent'), type: 'select', options: opts(l.departments) }]; });
}
function pagePositions(c) {
  simplePage(c, T('المسميات الوظيفية', 'Positions'), '/api/positions', 'personnel.edit',
    [{ key: 'code', label: T('الرمز', 'Code') }, { key: 'name', label: T('الاسم', 'Name') }],
    [{ key: 'code', label: T('الرمز', 'Code'), required: true }, { key: 'name', label: T('الاسم', 'Name'), required: true }]);
}
function pageAreas(c) {
  c.appendChild(h(`<div class="alert info">${esc(T('المنطقة = مجموعة أجهزة. كل موظف في منطقة يُرسل تلقائياً (بياناته وبصماته ووجهه) إلى جميع أجهزة تلك المنطقة، تماماً كما في BioTime.', 'An area is a group of devices. Every employee of an area is automatically sent (with templates) to all of its devices, as in BioTime.'))}</div>`));
  simplePage(c, T('المناطق', 'Areas'), '/api/areas', 'personnel.edit',
    [{ key: 'code', label: T('الرمز', 'Code') }, { key: 'name', label: T('الاسم', 'Name') }, { key: 'devices', label: T('الأجهزة', 'Devices'), cls: 'num' }, { key: 'employees', label: T('الموظفون', 'Employees'), cls: 'num' }],
    [{ key: 'code', label: T('الرمز', 'Code'), required: true }, { key: 'name', label: T('الاسم', 'Name'), required: true }]);
}

// ============================================================== devices
function stateIcon(r) {
  if (r.managed_by === 'biotime') return `${stateIconCore(r)} <span class="badge info" title="${esc(T('يُقرأ عبر واجهة BioTime؛ الجهاز ما زال متصلاً بـ BioTime', 'Read through the BioTime API; the terminal still talks to BioTime'))}">BioTime</span>`;
  return stateIconCore(r);
}
function stateIconCore(r) {
  if (r.state === 'online' && r.transferring) return `<span class="st-icon transferring" title="${esc(T('جارٍ نقل البيانات', 'Transferring data'))}">⇈</span>`;
  if (r.state === 'online') return `<span class="st-icon online" title="${esc(T('متصل', 'Online'))}">✓</span>`;
  return `<span class="st-icon ${r.state}" title="${esc(stateLabel(r.state))}"></span>`;
}
async function pageDevices(c) {
  title(c, T('الجهاز', 'Device'));
  const [s, first] = await Promise.all([GET('/api/settings'), GET('/api/devices')]);
  if (!first.rows.length) {
    c.appendChild(h(`<div class="alert">${esc(T('أجهزتك متصلة بـ ZKBioTime على المنفذ 90؟ لعرضها هنا فوراً بدون أي تغيير: النظام ← إعدادات النظام ← «القراءة من ZKBioTime عبر واجهته».', 'Terminals connected to ZKBioTime on port 90? To show them here right away without changing anything: System → Settings → "Read from ZKBioTime through its API".'))} <a href="#/system/settings">${esc(T('فتح الإعدادات', 'Open settings'))}</a></div>`));
    const ports = (s._server.adms_ports || []).join(' / ');
    c.appendChild(h(`<div class="alert info">${esc(T('لربط جهاز (مثل SpeedFace-V5L): من قائمة الجهاز ← الاتصال ← إعدادات الخادم السحابي (Cloud Server / ADMS): فعّل ADMS، ضع عنوان IP لهذا الحاسوب، والمنفذ', 'To connect a terminal (e.g. SpeedFace-V5L): device menu → Comm. → Cloud Server Setting (ADMS): enable it, enter this PC\'s IP address and port'))} <b class="ltr">${esc(ports)}</b>${esc(T('، وألغِ تفعيل HTTPS والـ Proxy. سيظهر الجهاز هنا تلقائياً خلال ثوانٍ.', ', with HTTPS and proxy off. The device appears here automatically within seconds.'))}</div>`));
  }
  const lk = await lookups(true);
  const act = async (sel, action, confirmMsg, extra = {}) => {
    if (confirmMsg && !await confirmBox(confirmMsg)) return;
    let n = 0; for (const d of sel) n += (await guard(() => POST(`/api/devices/${d.id}/action`, { action, ...extra }))).queued;
    toast(T(`أُضيف ${n} أمر — يُنفذ عند اتصال الجهاز التالي`, `${n} command(s) queued — executed at the next heartbeat`), 'ok'); g.reload();
  };
  const num = (k, label) => ({ key: k, label, cls: 'num' });
  // Same columns and order as ZKBioTime 9 > Device > Device
  const g = grid(c, {
    columns: [
      { key: 'alias', label: T('إسم الجهاز', 'Device name'), render: r => `<a href="#" data-act="detail">${esc(r.alias || r.sn)}</a>` },
      { key: 'sn', label: T('الرقم التسلسلي', 'Serial number'), cls: 'ltr' },
      { key: 'area', label: T('المنطقة', 'Area') },
      { key: 'ip', label: T('IP عنوان الجهاز', 'Device IP'), cls: 'ltr' },
      { key: 'state', label: T('الحالة', 'State'), cls: 'num', render: stateIcon },
      { key: 'last_activity', label: T('النشاط الأخير', 'Last activity'), cls: 'ltr' },
      num('user_count', T('المستخدم', 'User')),
      num('fp_count', T('بصمة الإصبع', 'Fingerprint')),
      num('face_count', T('الوجه', 'Face')),
      num('palm_count', T('كف اليد', 'Palm')),
      num('att_count', T('سجلات الحضور', 'Transactions')),
      { key: 'last_sync', label: T('آخر مزامنة', 'Last sync'), cls: 'ltr' },
      { key: 'pending', label: T('أوامر منتظرة', 'Pending cmds'), cls: 'num', render: r => r.pending ? `<span class="badge warn">${r.pending}</span>` : '0' },
      { key: 'model', label: T('الطراز', 'Model') },
      { key: 'firmware', label: T('إصدار البرنامج', 'Firmware'), cls: 'ltr' },
    ],
    fetch: localFetch('/api/devices'),
    actions: { detail: (r) => deviceDetail(r, g) },
    onRow: (r) => deviceDetail(r, g),
    toolbar: [
      { label: T('إضافة', 'Add'), icon: 'add', perm: 'device.control', action: () => deviceForm(null, lk, g) },
      { label: T('تعديل', 'Edit'), icon: 'edit', perm: 'device.control', needSel: true, action: (sel) => deviceForm(sel[0], lk, g) },
      { label: T('حذف', 'Delete'), icon: 'del', perm: 'device.control', needSel: true, action: async (sel) => { if (await confirmBox(T('حذف الجهاز من البرنامج؟ (لا يُمسح شيء من الجهاز نفسه)', 'Remove the device from the server? (nothing is erased on the device)'))) { for (const d of sel) await DEL(`/api/devices/${d.id}`); g.reload(); } } },
      { label: T('منطقة جديدة', 'New area'), icon: 'map', perm: 'device.control', needSel: true, action: (sel) => setDeviceArea(sel, lk, g) },
      { label: T('حذف الأوامر غير المنفذة', 'Clear pending commands'), icon: 'close', perm: 'device.control', needSel: true, action: async (sel) => {
        if (!await confirmBox(T('حذف كل الأوامر التي لم ينفذها الجهاز بعد؟', 'Delete all commands the device has not executed yet?'))) return;
        let n = 0; for (const d of sel) n += (await guard(() => POST('/api/device-commands/clear', { sn: d.sn, status: ['pending', 'sent'] }))).deleted;
        toast(T(`حُذف ${n} أمر`, `${n} command(s) deleted`), 'ok'); g.reload();
      } },
      { label: T('حذف البيانات', 'Clear data'), icon: 'del', perm: 'device.control', menu: [
        { label: T('حذف سجلات الحضور من الجهاز', 'Clear attendance records'), icon: 'del', needSel: true, action: (sel) => act(sel, 'clear_log', T('سيتم حذف سجلات الحضور من ذاكرة الجهاز (تبقى محفوظة في البرنامج). متابعة؟', 'Attendance records are erased from the device memory (they stay on the server). Continue?')) },
        { label: T('حذف صور الحضور', 'Clear attendance photos'), icon: 'del', needSel: true, action: (sel) => act(sel, 'clear_photo', T('متابعة؟', 'Continue?')) },
        { label: T('حذف كل بيانات الجهاز', 'Clear all device data'), icon: 'del', needSel: true, action: (sel) => act(sel, 'clear_data', T('سيُمسح كل المستخدمين والبصمات والسجلات من الجهاز! هل أنت متأكد؟', 'ALL users, templates and records will be erased from the device! Are you sure?')) },
      ] },
      { label: T('إرسال البيانات', 'Data transfer'), icon: 'sync', perm: 'device.control', menu: [
        { label: T('مزامنة البيانات إلى الجهاز', 'Synchronize data to device'), icon: 'upload', needSel: true, action: (sel) => act(sel, 'sync_all') },
        { label: T('رفع المستخدمين والقوالب من الجهاز', 'Upload user data from device'), icon: 'download', needSel: true, action: (sel) => act(sel, 'upload_users') },
        { label: T('رفع سجلات الحضور (فترة)', 'Upload transactions (period)'), icon: 'download', needSel: true, action: (sel) => uploadAtt(sel, act) },
        { label: T('إعادة تحميل البيانات', 'Reload data'), icon: 'refresh', needSel: true, action: (sel) => act(sel, 'reupload_all', T('سيعيد الجهاز إرسال كل السجلات (المكرر يُتجاهل تلقائياً). متابعة؟', 'The device will re-send all records (duplicates are ignored). Continue?')) },
        '-',
        { label: T('سحب الحركات عبر TCP 4370 (للأجهزة بدون ADMS)', 'Pull records over TCP 4370 (non-ADMS)'), icon: 'download', needSel: true, action: async (sel) => { for (const d of sel) { const r = await guard(() => POST(`/api/devices/${d.id}/pull`)); toast(`${d.alias}: ${r.read} / ${T('جديد', 'new')} ${r.new}`, 'ok'); } } },
      ] },
      { label: T('قائمة الجهاز', 'Device menu'), icon: 'system', perm: 'device.control', menu: [
        { label: T('إعادة تشغيل', 'Reboot'), icon: 'sync', needSel: true, action: (sel) => act(sel, 'reboot', T('إعادة تشغيل الأجهزة المحددة؟', 'Reboot the selected devices?')) },
        { label: T('مزامنة الوقت', 'Synchronize time'), icon: 'clock', needSel: true, action: (sel) => act(sel, 'sync_time') },
        { label: T('قراءة معلومات الجهاز', 'Get device info'), icon: 'device', needSel: true, action: (sel) => act(sel, 'info') },
        { label: T('إعادة تحميل الإعدادات', 'Reload options'), icon: 'refresh', needSel: true, action: (sel) => act(sel, 'check') },
        '-',
        { label: T('إرسال أمر مخصص', 'Send custom command'), icon: 'terminal', needSel: true, action: (sel) => customCmd(sel, act) },
      ] },
    ],
  });
  App.timers.push(setInterval(() => document.visibilityState === 'visible' && g.reload(), 15000));
}
function setDeviceArea(sel, lk, g) {
  const f = [{ key: 'area_id', label: T('المنطقة', 'Area'), type: 'select', options: opts(lk.areas), required: true }];
  formDialog({ title: T('منطقة جديدة', 'New area'), size: 'narrow', cls: 'one', fields: f,
    save: async (v) => { for (const d of sel) await PUT(`/api/devices/${d.id}`, { area_id: v.area_id }); } })
    .then(() => { toast(T('ستُرسل بيانات موظفي المنطقة الجديدة إلى الأجهزة', 'Employees of the new area will be sent to the devices'), 'ok'); g.reload(); });
}
function uploadAtt(sel, act) {
  const f = [{ key: 'start', label: T('من', 'From'), type: 'date', default: addDays(today(), -30), required: true }, { key: 'end', label: T('إلى', 'To'), type: 'date', default: today(), required: true }];
  formDialog({ title: T('سحب الحركات من الجهاز', 'Upload transactions'), size: 'narrow', fields: f, save: (v) => act(sel, 'upload_att', null, { start: v.start + ' 00:00:00', end: v.end + ' 23:59:59' }) });
}
function customCmd(sel, act) {
  const f = [{ key: 'command', label: T('الأمر (بدون C:ID:)', 'Command (without C:ID:)'), required: true, placeholder: 'DATA QUERY USERINFO PIN=1', full: true }];
  formDialog({ title: T('أمر مخصص', 'Custom command'), size: 'narrow', cls: 'one', fields: f, save: (v) => act(sel, 'custom', null, v) });
}
function deviceForm(row, lk, g) {
  const f = [
    { key: 'sn', label: T('الرقم التسلسلي', 'Serial number'), required: true, readonly: !!row },
    { key: 'alias', label: T('اسم الجهاز', 'Device name'), required: true },
    { key: 'area_id', label: T('المنطقة', 'Area'), type: 'select', options: opts(lk.areas), required: true },
    { key: 'ip', label: T('عنوان IP (لسحب TCP فقط)', 'IP address (TCP pull only)') },
    { key: 'time_zone', label: T('المنطقة الزمنية (ساعات، فارغ = حسب النظام)', 'Time zone (hours, empty = system)'), type: 'number', min: -12, max: 14 },
    { key: 'heartbeat', label: T('فترة الاتصال (ثانية)', 'Heartbeat (seconds)'), type: 'number', min: 5, default: 10 },
    { key: 'trans_interval', label: T('فترة رفع البيانات (دقيقة)', 'Upload interval (minutes)'), type: 'number', min: 1, default: 1 },
    { key: 'trans_times', label: T('أوقات الرفع المجدولة', 'Scheduled upload times'), default: '00:00;14:05' },
    { key: 'comm_key', label: T('مفتاح الاتصال (TCP)', 'Comm key (TCP)'), default: '0' },
    { key: 'tcp_port', label: T('منفذ TCP', 'TCP port'), type: 'number', default: 4370 },
    { key: 'realtime', label: T('الرفع الفوري', 'Real-time upload'), type: 'checkbox', text: T('إرسال كل بصمة فوراً', 'Send each punch immediately'), default: true },
    { key: 'is_attendance', label: T('جهاز حضور', 'Attendance device'), type: 'checkbox', text: T('بصماته تُحتسب في الحضور', 'Punches count for attendance'), default: true },
    { key: 'is_registration', label: T('جهاز تسجيل', 'Registration device'), type: 'checkbox', text: T('يُستخدم لتسجيل البصمات', 'Used for enrollment') },
    { key: 'enabled', label: T('مفعّل', 'Enabled'), type: 'checkbox', text: T('السماح للجهاز بالاتصال', 'Allow the device to connect'), default: true },
  ];
  formDialog({ title: row ? T('تعديل جهاز', 'Edit device') : T('إضافة جهاز', 'Add device'), fields: f, data: row || {},
    save: (v) => row ? PUT(`/api/devices/${row.id}`, v) : POST('/api/devices', v) }).then(() => { App.lookups = null; g.reload(); });
}
async function deviceDetail(r, g) {
  const d = await GET(`/api/devices/${r.id}`);
  const bio = Object.entries(d.bio_support).map(([t, v]) => `<span class="badge info">${esc(T(...(BIO_NAMES[t] || [t, t])))}${v ? ' v' + esc(v) : ''}</span>`).join(' ') || '<span class="muted">—</span>';
  const kv = [[T('الرقم التسلسلي', 'Serial'), d.sn], [T('الطراز', 'Model'), d.model], [T('البرنامج الثابت', 'Firmware'), d.firmware], [T('إصدار البروتوكول', 'Push version'), d.push_ver],
    ['IP', d.ip], ['MAC', d.mac], [T('المنصة', 'Platform'), d.platform], [T('الحالة', 'State'), stateLabel(d.state)], [T('آخر اتصال', 'Last activity'), d.last_activity], [T('آخر تهيئة', 'Last init'), d.last_init],
    [T('المستخدمون', 'Users'), d.user_count], [T('الوجوه', 'Faces'), d.face_count], [T('البصمات', 'Fingerprints'), d.fp_count], [T('الكف', 'Palms'), d.palm_count], [T('الحركات', 'Records'), d.att_count],
    [T('خوارزمية البصمة', 'FP algorithm'), d.fp_alg], [T('خوارزمية الوجه', 'Face algorithm'), d.face_alg], ['ATTLOG Stamp', d.att_stamp], ['OPERLOG Stamp', d.op_stamp]];
  const body = h(`<div><div class="tabs"><button class="active" data-t="i">${esc(T('المعلومات', 'Info'))}</button><button data-t="c">${esc(T('الأوامر', 'Commands'))}</button><button data-t="t">${esc(T('الاتصال', 'Traffic'))}</button><button data-t="o">${esc(T('خيارات الجهاز', 'Options'))}</button></div>
    <div data-p="i"><div class="kv">${kv.map(([k, v]) => `<div>${esc(k)}</div><div><bdi>${esc(v ?? '')}</bdi></div>`).join('')}<div>${esc(T('أنواع التحقق المدعومة', 'Supported biometrics'))}</div><div>${bio}</div></div></div>
    <div data-p="c" class="hidden"></div><div data-p="t" class="hidden"></div>
    <div data-p="o" class="hidden"><pre class="code">${esc(JSON.stringify(d.options, null, 2))}</pre></div></div>`);
  dialog({ title: `${d.alias} (${d.sn})`, size: 'wide', body, buttons: [{ label: T('إغلاق', 'Close') }] });
  $$('.tabs button', body).forEach(b => b.onclick = async () => {
    $$('.tabs button', body).forEach(x => x.classList.toggle('active', x === b));
    $$('[data-p]', body).forEach(p => p.classList.toggle('hidden', p.dataset.p !== b.dataset.t));
    if (b.dataset.t === 'c') { const p = $('[data-p=c]', body); p.innerHTML = ''; commandsGrid(p, d.sn); }
    if (b.dataset.t === 't') { const t = await GET('/api/device-traffic?sn=' + encodeURIComponent(d.sn)); $('[data-p=t]', body).innerHTML = trafficTable(t.rows); }
  });
}
function cmdBadge(s) { return `<span class="badge ${{ done: 'ok', failed: 'bad', sent: 'info', pending: 'warn' }[s] || ''}">${esc({ done: T('نُفذ', 'Done'), failed: T('فشل', 'Failed'), sent: T('أُرسل', 'Sent'), pending: T('بالانتظار', 'Pending') }[s] || s)}</span>`; }
function commandsGrid(c, sn) {
  const g = grid(c, {
    columns: [{ key: 'id', label: 'ID', cls: 'num' }, { key: 'device_sn', label: T('الجهاز', 'Device'), cls: 'ltr' }, { key: 'title', label: T('الأمر', 'Command') },
      { key: 'status', label: T('الحالة', 'Status'), render: r => cmdBadge(r.status) }, { key: 'return_code', label: T('النتيجة', 'Return'), cls: 'ltr' },
      { key: 'created_at', label: T('وقت الإنشاء', 'Created'), cls: 'ltr' }, { key: 'returned_at', label: T('وقت التنفيذ', 'Returned'), cls: 'ltr' },
      { key: 'content', label: T('المحتوى', 'Content'), render: r => `<span class="ltr muted" title="${esc(r.content)}">${esc(r.content.slice(0, 70))}</span>` }],
    fetch: serverFetch('/api/device-commands' + (sn ? '?sn=' + encodeURIComponent(sn) : '')), select: false,
    filters: [{ key: 'status', label: T('كل الحالات', 'All states'), type: 'select', options: [{ value: 'pending', label: T('بالانتظار', 'Pending') }, { value: 'sent', label: T('أُرسل', 'Sent') }, { value: 'done', label: T('نُفذ', 'Done') }, { value: 'failed', label: T('فشل', 'Failed') }] }],
    toolbar: [{ label: T('حذف المنفذة والفاشلة', 'Clear done/failed'), icon: 'del', perm: 'device.control', action: async () => { await guard(() => POST('/api/device-commands/clear', { sn })); g.reload(); } },
      { label: T('إلغاء المعلقة', 'Cancel pending'), icon: 'close', perm: 'device.control', action: async () => { if (await confirmBox(T('إلغاء كل الأوامر التي لم تُنفذ بعد؟', 'Cancel all commands not yet executed?'))) { await guard(() => POST('/api/device-commands/clear', { sn, status: ['pending', 'sent'] })); g.reload(); } } }],
  });
  return g;
}
function pageCommands(c) { title(c, T('أوامر الأجهزة', 'Device commands')); const g = commandsGrid(c); App.timers.push(setInterval(() => document.visibilityState === 'visible' && g.reload(), 10000)); }
function trafficTable(rows) {
  return `<div class="grid-wrap" style="max-height:60vh"><table class="grid"><thead><tr><th>${esc(T('الوقت', 'Time'))}</th><th>SN</th><th>${esc(T('الطلب', 'Request'))}</th><th>${esc(T('الحجم', 'Bytes'))}</th><th>${esc(T('الرد', 'Reply'))}</th></tr></thead><tbody>
    ${rows.map(t => `<tr><td class="ltr">${esc(t.time.slice(11))}</td><td class="ltr">${esc(t.sn)}</td><td class="ltr wrap">${esc(t.method)} ${esc(t.path)}?${esc(t.query)}</td><td class="num">${t.bytes}</td><td class="ltr wrap"><pre style="margin:0;white-space:pre-wrap;font-size:11px">${esc(t.reply)}</pre></td></tr>`).join('') || `<tr><td class="empty" colspan="5">${esc(T('لم يتصل أي جهاز منذ تشغيل الخادم', 'No device has contacted the server since it started'))}</td></tr>`}</tbody></table></div>`;
}
async function pageTraffic(c) {
  title(c, T('مراقبة اتصال الأجهزة (ADMS)', 'Device communication (ADMS)'));
  c.appendChild(h(`<div class="alert info">${esc(T('آخر 500 طلب من الأجهزة إلى الخادم. مفيد لتشخيص مشاكل الربط: إن لم يظهر الجهاز هنا فالمشكلة في الشبكة أو الجدار الناري أو إعداد الخادم على الجهاز.', 'The last 500 device requests. Useful for troubleshooting: if a device never shows up here, check the network, firewall or the server setting on the device.'))}</div>`));
  const rs = h('<div></div>'); c.appendChild(rs);
  const p = h('<div class="panel"></div>'); c.appendChild(p);
  const draw = async () => {
    const [t, r] = await Promise.all([GET('/api/device-traffic'), GET('/api/relay')]);
    rs.innerHTML = r.enabled ? `<div class="alert ${r.last_error && r.last_error_at > r.last_ok ? '' : 'info'}">${esc(T('التمرير إلى BioTime مفعّل', 'Relaying to BioTime'))}: <b class="ltr">${esc(r.url)}</b> · ${esc(T('ناجح', 'ok'))} ${r.ok} · ${esc(T('فاشل', 'failed'))} ${r.failed}${r.last_error ? ` · ${esc(T('آخر خطأ', 'last error'))}: <span class="ltr">${esc(r.last_error_at)} ${esc(r.last_error)}</span>` : ''}</div>` : '';
    p.innerHTML = trafficTable(t.rows);
  };
  await draw(); App.timers.push(setInterval(() => document.visibilityState === 'visible' && draw(), 5000));
}
async function pageTransactions(c) {
  title(c, T('سجل الحركات', 'Transactions'));
  const lk = await lookups();
  grid(c, {
    columns: [
      { key: 'emp_code', label: T('الرقم', 'ID') }, { key: 'name', label: T('الاسم', 'Name') }, { key: 'department', label: T('القسم', 'Department') },
      { key: 'punch_time', label: T('وقت البصمة', 'Punch time'), cls: 'ltr' },
      { key: 'punch_state', label: T('الحالة', 'State'), render: r => esc(stateName(r.punch_state)) },
      { key: 'verify', label: T('التحقق', 'Verify'), render: r => esc(verifyName(r.verify)) },
      { key: 'device', label: T('الجهاز', 'Device') },
      { key: 'temperature', label: T('الحرارة', 'Temp.'), render: r => r.temperature ? esc(r.temperature) + '°' : '' },
      { key: 'photo', label: T('صورة', 'Photo'), render: r => r.has_photo ? `<a href="/api/transactions/${r.id}/photo" target="_blank">📷</a>` : '' },
      { key: 'source', label: T('المصدر', 'Source') },
      { key: 'upload_time', label: T('وقت الرفع', 'Uploaded'), cls: 'ltr' },
    ],
    fetch: serverFetch('/api/transactions'), select: false,
    filters: [{ key: 'start', label: T('من', 'From'), type: 'date', value: addDays(today(), -7) }, { key: 'end', label: T('إلى', 'To'), type: 'date', value: today() },
      { key: 'department_id', label: T('كل الأقسام', 'All departments'), type: 'select', options: opts(lk.departments) },
      { key: 'sn', label: T('كل الأجهزة', 'All devices'), type: 'select', options: opts(lk.devices, 'sn', 'name') }],
    toolbar: [{ label: T('تصدير', 'Export'), icon: 'download', menu: [
      { label: 'Excel', action: (s, g) => download(`/api/reports/transactions?${qs({ start: g.state.filters.start, end: g.state.filters.end, department_ids: g.state.filters.department_id, device: g.state.filters.sn, lang: App.lang, fmt: 'xlsx' })}`) },
      { label: 'CSV', action: (s, g) => download(`/api/reports/transactions?${qs({ start: g.state.filters.start, end: g.state.filters.end, department_ids: g.state.filters.department_id, device: g.state.filters.sn, lang: App.lang, fmt: 'csv' })}`) }] }],
  });
}
function pageOplogs(c) {
  title(c, T('سجل عمليات الجهاز', 'Device operation log'));
  grid(c, { columns: [{ key: 'device_sn', label: T('الجهاز', 'Device'), cls: 'ltr' }, { key: 'op_code', label: T('رمز العملية', 'Operation'), cls: 'num' }, { key: 'admin', label: T('المدير', 'Admin') },
    { key: 'op_time', label: T('الوقت', 'Time'), cls: 'ltr' }, { key: 'obj1', label: T('الهدف 1', 'Object 1') }, { key: 'obj2', label: T('الهدف 2', 'Object 2') }, { key: 'upload_time', label: T('وقت الرفع', 'Uploaded'), cls: 'ltr' }],
    fetch: serverFetch('/api/device-oplogs'), select: false, search: false });
}
function pageErrors(c) {
  title(c, T('سجل أخطاء الأجهزة', 'Device error log'));
  grid(c, { columns: [{ key: 'device_sn', label: T('الجهاز', 'Device'), cls: 'ltr' }, { key: 'err_code', label: T('الرمز', 'Code') }, { key: 'err_msg', label: T('الرسالة', 'Message'), cls: 'wrap' }, { key: 'upload_time', label: T('الوقت', 'Time'), cls: 'ltr' }],
    fetch: serverFetch('/api/device-errorlogs'), select: false, search: false });
}

// ============================================================== attendance setup
function ttFields() {
  return [
    { key: 'alias', label: T('الاسم', 'Name'), required: true },
    { key: 'kind', label: T('النوع', 'Type'), type: 'select', blank: false, options: [{ value: 'normal', label: T('ثابت', 'Normal') }, { value: 'flexible', label: T('مرن (عدد ساعات)', 'Flexible (hours)') }] },
    { key: 'check_in', label: T('وقت الدخول', 'Check-in'), type: 'time', required: true, default: '08:00' },
    { key: 'check_out', label: T('وقت الخروج', 'Check-out'), type: 'time', required: true, default: '16:00', hint: T('إذا كان أقل من وقت الدخول فالدوام ليلي ينتهي اليوم التالي', 'Earlier than check-in = overnight shift') },
    { key: 'late_grace', label: T('السماح بالتأخير (دقيقة)', 'Late allowance (min)'), type: 'number', min: 0, default: 0 },
    { key: 'early_grace', label: T('السماح بالخروج المبكر (دقيقة)', 'Early-leave allowance (min)'), type: 'number', min: 0, default: 0 },
    { section: T('نوافذ البصمة (بالدقائق)', 'Punch windows (minutes)') },
    { key: 'in_ahead', label: T('بداية نافذة الدخول قبل الموعد', 'Check-in window starts before'), type: 'number', min: 0, default: 120 },
    { key: 'in_above', label: T('نهاية نافذة الدخول بعد الموعد', 'Check-in window ends after'), type: 'number', min: 0, default: 240 },
    { key: 'out_ahead', label: T('بداية نافذة الخروج قبل الموعد', 'Check-out window starts before'), type: 'number', min: 0, default: 240 },
    { key: 'out_above', label: T('نهاية نافذة الخروج بعد الموعد', 'Check-out window ends after'), type: 'number', min: 0, default: 240 },
    { key: 'must_check_in', label: T('بصمة الدخول', 'Check-in punch'), type: 'checkbox', text: T('إلزامية', 'Required'), default: true },
    { key: 'must_check_out', label: T('بصمة الخروج', 'Check-out punch'), type: 'checkbox', text: T('إلزامية', 'Required'), default: true },
    { section: T('الاستراحة والمدة', 'Break & duration') },
    { key: 'break_start', label: T('بداية الاستراحة (تُخصم)', 'Break start (deducted)'), type: 'time' },
    { key: 'break_end', label: T('نهاية الاستراحة', 'Break end'), type: 'time' },
    { key: 'work_minutes', label: T('ساعات الدوام المرن (دقيقة)', 'Flexible work minutes'), type: 'number', default: 480 },
    { key: 'workday', label: T('يُحسب كأيام عمل', 'Counts as work days'), type: 'number', step: '0.5', default: 1 },
    { key: 'color', label: T('اللون', 'Color'), type: 'color', default: '#1e88e5' },
  ];
}
function pageTimetables(c) {
  simplePage(c, T('أوقات الدوام', 'Timetables'), '/api/timetables', 'attendance.edit', [
    { key: 'alias', label: T('الاسم', 'Name'), render: r => `<span class="dot" style="background:${esc(r.color)}"></span>${esc(r.alias)}` },
    { key: 'kind', label: T('النوع', 'Type'), render: r => r.kind === 'flexible' ? T('مرن', 'Flexible') : T('ثابت', 'Normal') },
    { key: 'check_in', label: T('الدخول', 'Check-in'), cls: 'ltr' }, { key: 'check_out', label: T('الخروج', 'Check-out'), cls: 'ltr' },
    { key: 'late_grace', label: T('سماح التأخير', 'Late allow.'), cls: 'num' }, { key: 'early_grace', label: T('سماح الخروج', 'Early allow.'), cls: 'num' },
    { key: 'break', label: T('الاستراحة', 'Break'), render: r => r.break_start ? `${r.break_start}-${r.break_end}` : '' },
    { key: 'workday', label: T('أيام عمل', 'Work days'), cls: 'num' }], ttFields(), { dialogSize: 'wide', formCls: 'three' });
}
async function pageShifts(c) {
  title(c, T('الورديات', 'Shifts'));
  c.appendChild(h(`<div class="alert info">${esc(T('الوردية = دورة (أسبوع/أيام/شهر) يُحدد لكل يوم فيها وقت دوام أو أكثر. الأيام بدون وقت دوام تعتبر راحة.', 'A shift is a cycle (week/days/month) with one or more timetables per day; days without a timetable are days off.'))}</div>`));
  const g = grid(c, {
    columns: [{ key: 'alias', label: T('الاسم', 'Name') }, { key: 'cycle', label: T('الدورة', 'Cycle'), render: r => `${r.cycle} × ${esc({ day: T('يوم', 'day'), week: T('أسبوع', 'week'), month: T('شهر', 'month') }[r.cycle_unit])}` }, { key: 'summary', label: T('أوقات الدوام', 'Timetables') }, { key: 'days', label: T('أيام العمل', 'Work days'), render: r => new Set(r.details.map(d => d.day_index)).size }],
    fetch: localFetch('/api/shifts'),
    onRow: (r) => can('attendance.edit') && shiftEditor(r, g),
    toolbar: [{ label: T('إضافة', 'Add'), icon: 'add', cls: 'primary', perm: 'attendance.edit', action: () => shiftEditor(null, g) },
      { label: T('تعديل', 'Edit'), icon: 'edit', perm: 'attendance.edit', needSel: true, action: (s) => shiftEditor(s[0], g) },
      { label: T('حذف', 'Delete'), icon: 'del', cls: 'danger', perm: 'attendance.edit', needSel: true, action: async (s) => { if (await confirmBox(T('حذف الوردية وجداولها؟', 'Delete the shift and its schedules?'))) { for (const x of s) await DEL(`/api/shifts/${x.id}`); App.lookups = null; g.reload(); } } }],
  });
}
async function shiftEditor(row, g) {
  const lk = await lookups(true);
  const s = row || { alias: '', cycle_unit: 'week', cycle: 1, details: [] };
  const sel = new Set(s.details.map(d => `${d.day_index}:${d.timetable_id}`));
  const body = h(`<div>${formHtml([{ key: 'alias', label: T('الاسم', 'Name'), required: true }, { key: 'cycle_unit', label: T('وحدة الدورة', 'Cycle unit'), type: 'select', blank: false, options: [{ value: 'week', label: T('أسبوع', 'Week') }, { value: 'day', label: T('يوم', 'Day') }, { value: 'month', label: T('شهر', 'Month') }] }, { key: 'cycle', label: T('طول الدورة', 'Cycle length'), type: 'number', min: 1, max: 12 }], s, 'three')}
    <div style="margin-top:12px" class="grid-wrap"></div></div>`);
  const holder = $('.grid-wrap', body);
  const draw = () => {
    const unit = $('[name=cycle_unit]', body).value, cyc = Math.max(1, +$('[name=cycle]', body).value || 1);
    const span = cyc * ({ day: 1, week: 7, month: 31 }[unit]);
    const label = (i) => unit === 'week' ? `${cyc > 1 ? T('أ', 'W') + (Math.floor(i / 7) + 1) + ' ' : ''}${WEEKDAYS()[i % 7]}` : unit === 'month' ? `${cyc > 1 ? T('ش', 'M') + (Math.floor(i / 31) + 1) + ' ' : ''}${(i % 31) + 1}` : `${T('يوم', 'Day')} ${i + 1}`;
    holder.innerHTML = `<table class="shift-grid"><thead><tr><th>${esc(T('اليوم', 'Day'))}</th>${lk.timetables.map(t => `<th><span class="dot" style="background:${esc(t.color)}"></span>${esc(t.name)}<br><small class="ltr">${t.check_in}-${t.check_out}</small></th>`).join('')}</tr></thead><tbody>
      ${Array.from({ length: span }, (_, i) => `<tr><th>${esc(label(i))}</th>${lk.timetables.map(t => `<td><input type="checkbox" data-k="${i}:${t.id}" ${sel.has(`${i}:${t.id}`) ? 'checked' : ''}></td>`).join('')}</tr>`).join('')}</tbody></table>
      ${lk.timetables.length ? '' : `<div class="alert">${esc(T('أضف وقت دوام أولاً', 'Add a timetable first'))}</div>`}`;
    $$('input[data-k]', holder).forEach(i => i.onchange = () => i.checked ? sel.add(i.dataset.k) : sel.delete(i.dataset.k));
  };
  $('[name=cycle_unit]', body).onchange = draw; $('[name=cycle]', body).onchange = draw; draw();
  dialog({ title: row ? T('تعديل وردية', 'Edit shift') : T('وردية جديدة', 'New shift'), size: 'wide', body, buttons: [{ label: T('إلغاء', 'Cancel') }, { label: T('حفظ', 'Save'), cls: 'primary', action: async () => {
    const data = { alias: $('[name=alias]', body).value, cycle_unit: $('[name=cycle_unit]', body).value, cycle: +$('[name=cycle]', body).value || 1,
      details: [...sel].map(k => { const [d, t] = k.split(':'); return { day_index: +d, timetable_id: +t }; }) };
    if (row) await PUT(`/api/shifts/${row.id}`, data); else await POST('/api/shifts', data);
    toast(T('تم الحفظ', 'Saved'), 'ok'); App.lookups = null; g.reload();
  } }] });
}
async function pageSchedules(c) {
  title(c, T('جدولة الموظفين', 'Employee schedules'));
  const lk = await lookups(true);
  const g = grid(c, {
    columns: [{ key: 'emp_code', label: T('الرقم', 'ID') }, { key: 'name', label: T('الاسم', 'Name') }, { key: 'department', label: T('القسم', 'Department') }, { key: 'shift', label: T('الوردية', 'Shift') }, { key: 'start_date', label: T('من', 'From'), cls: 'ltr' }, { key: 'end_date', label: T('إلى', 'To'), cls: 'ltr' }],
    fetch: localFetch('/api/schedules'),
    toolbar: [{ label: T('جدولة', 'Assign shift'), icon: 'add', cls: 'primary', perm: 'attendance.edit', action: () => assignSchedule(lk, g) },
      { label: T('حذف', 'Delete'), icon: 'del', cls: 'danger', perm: 'attendance.edit', needSel: true, action: async (s) => { if (await confirmBox(T('حذف الجداول المحددة؟', 'Delete the selected schedules?'))) { for (const x of s) await DEL(`/api/schedules/${x.id}`); g.reload(); } } }],
  });
}
function assignSchedule(lk, g) {
  const chooser = employeeChooser();
  const f = [{ key: 'shift_id', label: T('الوردية', 'Shift'), type: 'select', options: opts(lk.shifts), required: true },
    { key: 'start_date', label: T('من تاريخ', 'From'), type: 'date', required: true, default: monthStart() },
    { key: 'end_date', label: T('إلى تاريخ', 'To'), type: 'date', required: true, default: `${new Date().getFullYear()}-12-31` },
    { key: 'department_ids', label: T('أو أقسام كاملة', 'Or whole departments'), type: 'multi', options: opts(lk.departments) }];
  const body = h(`<div>${formHtml(f)}</div>`); $('form', body).appendChild(chooser.el);
  dialog({ title: T('جدولة الموظفين', 'Assign shift'), body, buttons: [{ label: T('إلغاء', 'Cancel') }, { label: T('حفظ', 'Save'), cls: 'primary', action: async () => {
    const v = readForm(body, f); v.employee_ids = chooser.get().map(e => e.id);
    const r = await POST('/api/schedules', v); toast(T(`تمت جدولة ${r.employees} موظف`, `${r.employees} employee(s) scheduled`), 'ok'); g.reload();
  } }] });
}
async function pageDeptSchedules(c) {
  const lk = await lookups(true);
  c.appendChild(h(`<div class="alert info">${esc(T('جدول القسم يُطبق على موظفي القسم الذين ليس لهم جدول شخصي.', 'A department schedule applies to its employees who have no personal schedule.'))}</div>`));
  simplePage(c, T('جدولة الأقسام', 'Department schedules'), '/api/dept-schedules', 'attendance.edit',
    [{ key: 'department', label: T('القسم', 'Department') }, { key: 'shift', label: T('الوردية', 'Shift') }, { key: 'start_date', label: T('من', 'From'), cls: 'ltr' }, { key: 'end_date', label: T('إلى', 'To'), cls: 'ltr' }],
    [{ key: 'department_id', label: T('القسم', 'Department'), type: 'select', options: opts(lk.departments), required: true },
      { key: 'shift_id', label: T('الوردية', 'Shift'), type: 'select', options: opts(lk.shifts), required: true },
      { key: 'start_date', label: T('من', 'From'), type: 'date', required: true, default: monthStart() },
      { key: 'end_date', label: T('إلى', 'To'), type: 'date', required: true, default: `${new Date().getFullYear()}-12-31` }]);
}
async function pageTemp(c) {
  title(c, T('الجدول المؤقت (تبديل ورديات ليوم أو فترة)', 'Temporary schedule'));
  const lk = await lookups(true);
  const g = grid(c, {
    columns: [{ key: 'att_date', label: T('التاريخ', 'Date'), cls: 'ltr' }, { key: 'emp_code', label: T('الرقم', 'ID') }, { key: 'name', label: T('الاسم', 'Name') }, { key: 'timetable', label: T('وقت الدوام', 'Timetable') }],
    fetch: localFetch('/api/temp-schedules'),
    filters: [{ key: 'start', label: T('من', 'From'), type: 'date', value: monthStart() }, { key: 'end', label: T('إلى', 'To'), type: 'date' }],
    toolbar: [{ label: T('إضافة', 'Add'), icon: 'add', cls: 'primary', perm: 'attendance.edit', action: () => {
      const chooser = employeeChooser();
      const f = [{ key: 'start_date', label: T('من', 'From'), type: 'date', required: true, default: today() }, { key: 'end_date', label: T('إلى', 'To'), type: 'date', required: true, default: today() },
        { key: 'timetable_ids', label: T('أوقات الدوام (بدون اختيار = يوم راحة)', 'Timetables (none = day off)'), type: 'multi', options: opts(lk.timetables) }];
      const body = h(`<div>${formHtml(f)}</div>`); $('form', body).appendChild(chooser.el);
      dialog({ title: T('جدول مؤقت', 'Temporary schedule'), body, buttons: [{ label: T('إلغاء', 'Cancel') }, { label: T('حفظ', 'Save'), cls: 'primary', action: async () => {
        const v = readForm(body, f); v.employee_ids = chooser.get().map(e => e.id); await POST('/api/temp-schedules', v); toast(T('تم الحفظ', 'Saved'), 'ok'); g.reload(); } }] });
    } }, { label: T('حذف', 'Delete'), icon: 'del', cls: 'danger', perm: 'attendance.edit', needSel: true, action: async (s) => { for (const x of s) await DEL(`/api/temp-schedules/${x.id}`); g.reload(); } }],
  });
}
async function pageHolidays(c) {
  const lk = await lookups();
  simplePage(c, T('العطل الرسمية', 'Holidays'), '/api/holidays', 'attendance.edit',
    [{ key: 'alias', label: T('الاسم', 'Name') }, { key: 'start_date', label: T('تاريخ البداية', 'Start date'), cls: 'ltr' }, { key: 'days', label: T('عدد الأيام', 'Days'), cls: 'num' },
      { key: 'department_id', label: T('القسم', 'Department'), render: r => esc(lk.departments.find(d => d.id === r.department_id)?.name || T('الكل', 'All')) }],
    [{ key: 'alias', label: T('الاسم', 'Name'), required: true }, { key: 'start_date', label: T('تاريخ البداية', 'Start date'), type: 'date', required: true },
      { key: 'days', label: T('عدد الأيام', 'Days'), type: 'number', min: 1, default: 1 }, { key: 'department_id', label: T('القسم (فارغ = الكل)', 'Department (empty = all)'), type: 'select', options: opts(lk.departments) }]);
}
function pageLeaveTypes(c) {
  simplePage(c, T('أنواع الإجازات', 'Leave types'), '/api/leave-types', 'attendance.edit',
    [{ key: 'code', label: T('الرمز', 'Code') }, { key: 'name', label: T('الاسم', 'Name'), render: r => `<span class="dot" style="background:${esc(r.color)}"></span>${esc(r.name)}` }, { key: 'paid', label: T('مدفوعة', 'Paid'), render: r => r.paid ? '✓' : '—' }],
    [{ key: 'code', label: T('الرمز (يظهر في الكشف الشهري)', 'Code (shown in monthly sheet)'), required: true }, { key: 'name', label: T('الاسم', 'Name'), required: true },
      { key: 'paid', label: T('مدفوعة', 'Paid'), type: 'checkbox', text: T('إجازة مدفوعة', 'Paid leave'), default: true }, { key: 'color', label: T('اللون', 'Color'), type: 'color', default: '#8e24aa' }]);
}
async function requestPage(c, { heading, endpoint, kind, columns, fields }) {
  title(c, heading);
  const g = grid(c, {
    columns: [{ key: 'emp_code', label: T('الرقم', 'ID') }, { key: 'name', label: T('الاسم', 'Name') }, { key: 'department', label: T('القسم', 'Department') }, ...columns,
      { key: 'reason', label: T('السبب', 'Reason') }, { key: 'status', label: T('الحالة', 'Status'), render: r => approvalBadge(r.status) }, { key: 'approver', label: T('المعتمد', 'Approver') }],
    fetch: serverFetch(endpoint),
    filters: [{ key: 'status', label: T('كل الحالات', 'All states'), type: 'select', options: Object.keys(APPROVAL).map(k => ({ value: k, label: T(...APPROVAL[k]) })) }],
    toolbar: [
      { label: T('إضافة', 'Add'), icon: 'add', cls: 'primary', perm: 'attendance.edit', action: () => requestForm(null) },
      { label: T('تعديل', 'Edit'), icon: 'edit', perm: 'attendance.edit', needSel: true, action: (s) => requestForm(s[0]) },
      { label: T('حذف', 'Delete'), icon: 'del', cls: 'danger', perm: 'attendance.edit', needSel: true, action: async (s) => { if (await confirmBox(T('حذف المحدد؟', 'Delete selected?'))) { for (const x of s) await DEL(`${endpoint}/${x.id}`); g.reload(); } } },
      { label: T('اعتماد', 'Approve'), icon: 'check', cls: 'success', perm: 'attendance.approve', needSel: true, action: async (s) => { await guard(() => POST(`/api/approvals/${kind}`, { ids: s.map(x => x.id), status: 'approved' }), T('تم الاعتماد', 'Approved')); g.reload(); } },
      { label: T('رفض', 'Reject'), icon: 'close', perm: 'attendance.approve', needSel: true, action: async (s) => { await guard(() => POST(`/api/approvals/${kind}`, { ids: s.map(x => x.id), status: 'rejected' }), T('تم الرفض', 'Rejected')); g.reload(); } },
    ],
  });
  const requestForm = async (row) => {
    const flds = await fields();
    const chooser = row ? null : employeeChooser([], { multiple: true });
    const body = h(`<div>${row ? `<p><b>${esc(row.emp_code)} — ${esc(row.name)}</b></p>` : ''}${formHtml(flds, row || {})}</div>`);
    if (chooser) $('form', body).prepend(chooser.el);
    dialog({ title: heading, body, buttons: [{ label: T('إلغاء', 'Cancel') }, { label: T('حفظ', 'Save'), cls: 'primary', action: async () => {
      const v = readForm(body, flds);
      if (row) await PUT(`${endpoint}/${row.id}`, v);
      else { const emps = chooser.get(); if (!emps.length) throw new Error(T('اختر موظفاً', 'Choose an employee')); for (const e of emps) await POST(endpoint, { ...v, employee_id: e.id }); }
      toast(T('تم الحفظ', 'Saved'), 'ok'); g.reload();
    } }] });
  };
}
const statusField = () => ({ key: 'status', label: T('الحالة', 'Status'), type: 'select', blank: false, default: 'approved', options: Object.keys(APPROVAL).map(k => ({ value: k, label: T(...APPROVAL[k]) })) });
function pageLeaves(c) {
  requestPage(c, { heading: T('الإجازات', 'Leave'), endpoint: '/api/leaves', kind: 'leaves',
    columns: [{ key: 'leave_type', label: T('النوع', 'Type') }, { key: 'start_time', label: T('من', 'From'), cls: 'ltr' }, { key: 'end_time', label: T('إلى', 'To'), cls: 'ltr' }],
    fields: async () => { const lk = await lookups(); return [
      { key: 'leave_type_id', label: T('نوع الإجازة', 'Leave type'), type: 'select', options: opts(lk.leave_types), required: true },
      statusField(),
      { key: 'start_time', label: T('من', 'From'), type: 'datetime', required: true, default: today() + ' 00:00' },
      { key: 'end_time', label: T('إلى', 'To'), type: 'datetime', required: true, default: today() + ' 23:59' },
      { key: 'reason', label: T('السبب', 'Reason'), type: 'textarea' }]; } });
}
function pageManual(c) {
  requestPage(c, { heading: T('البصمات اليدوية (نسيان البصمة)', 'Manual punches'), endpoint: '/api/manual-logs', kind: 'manual-logs',
    columns: [{ key: 'punch_time', label: T('الوقت', 'Time'), cls: 'ltr' }, { key: 'punch_state', label: T('الحالة', 'State'), render: r => esc(stateName(r.punch_state)) }],
    fields: async () => [{ key: 'punch_time', label: T('وقت البصمة', 'Punch time'), type: 'datetime', required: true, default: today() + ' 08:00' },
      { key: 'punch_state', label: T('نوع البصمة', 'Punch state'), type: 'select', blank: false, options: STATES().map(([v, l]) => ({ value: v, label: l })) }, statusField(),
      { key: 'reason', label: T('السبب', 'Reason'), type: 'textarea' }] });
}
function pageOvertime(c) {
  requestPage(c, { heading: T('طلبات العمل الإضافي', 'Overtime'), endpoint: '/api/overtimes', kind: 'overtimes',
    columns: [{ key: 'start_time', label: T('من', 'From'), cls: 'ltr' }, { key: 'end_time', label: T('إلى', 'To'), cls: 'ltr' }],
    fields: async () => [{ key: 'start_time', label: T('من', 'From'), type: 'datetime', required: true, default: today() + ' 16:00' },
      { key: 'end_time', label: T('إلى', 'To'), type: 'datetime', required: true, default: today() + ' 18:00' }, statusField(),
      { key: 'reason', label: T('السبب', 'Reason'), type: 'textarea' }] });
}

// ============================================================== calculated attendance
async function pageCalc(c) {
  title(c, T('نتائج الحضور', 'Attendance results'));
  const lk = await lookups();
  grid(c, {
    columns: [
      { key: 'date', label: T('التاريخ', 'Date'), cls: 'ltr' }, { key: 'emp_code', label: T('الرقم', 'ID') }, { key: 'name', label: T('الاسم', 'Name') }, { key: 'department', label: T('القسم', 'Department') },
      { key: 'timetable', label: T('الدوام', 'Timetable') },
      { key: 'clock_in', label: T('الدخول', 'In'), cls: 'ltr', render: r => esc(r.clock_in.slice(11)) }, { key: 'clock_out', label: T('الخروج', 'Out'), cls: 'ltr', render: r => esc(r.clock_out.slice(11)) },
      { key: 'late', label: T('تأخير', 'Late'), cls: 'num', render: r => hm(r.late) }, { key: 'early', label: T('مبكر', 'Early'), cls: 'num', render: r => hm(r.early) },
      { key: 'worked', label: T('عمل', 'Worked'), cls: 'num', render: r => hm(r.worked) }, { key: 'ot', label: T('إضافي', 'OT'), cls: 'num', render: r => hm(r.ot) },
      { key: 'status', label: T('الحالة', 'Status'), render: r => statusBadge(r.status) + (r.holiday ? ` <small class="muted">${esc(r.holiday)}</small>` : '') + (r.leave_codes.length ? ` <small class="muted">${esc(r.leave_codes.join(','))}</small>` : '') },
      { key: 'punches', label: T('كل البصمات', 'Punches'), cls: 'ltr', render: r => esc(r.punches.join(' ')) },
    ],
    select: false, pageSize: 100,
    fetch: async ({ offset, limit, q, start, end, department_ids, status }) => {
      const r = await GET('/api/attendance/daily?' + qs({ start: start || today(), end: end || start || today(), department_ids, status }));
      let rows = r.rows; if (q) { const s = q.toLowerCase(); rows = rows.filter(x => (x.emp_code + ' ' + x.name).toLowerCase().includes(s)); }
      return { total: rows.length, rows: rows.slice(offset, offset + limit) };
    },
    filters: [{ key: 'start', label: T('من', 'From'), type: 'date', value: today() }, { key: 'end', label: T('إلى', 'To'), type: 'date', value: today() },
      { key: 'department_ids', label: T('كل الأقسام', 'All departments'), type: 'select', options: opts(lk.departments) },
      { key: 'status', label: T('كل الحالات', 'All states'), type: 'select', options: Object.keys(STATUS).map(k => ({ value: k, label: T(...STATUS[k]) })) }],
  });
}
async function renderEmpCalendar(el, empId, month) {
  const r = await GET(`/api/attendance/calendar/${empId}?month=${month}`);
  const first = new Date(r.month + '-01T00:00:00');
  const lead = (first.getDay() + 6) % 7;
  const s = r.summary || {};
  el.innerHTML = `<div style="display:flex;gap:8px;align-items:center;margin-bottom:10px"><button class="btn small prev">‹</button><b class="ltr">${esc(r.month)}</b><button class="btn small next">›</button>
    <span class="muted" style="margin-inline-start:12px">${esc(T('حضور', 'Present'))}: ${s.present_days ?? 0} · ${esc(T('غياب', 'Absent'))}: ${s.absent_days ?? 0} · ${esc(T('تأخير', 'Late'))}: ${s.late_count ?? 0} (${hm(s.late)}) · ${esc(T('إضافي', 'OT'))}: ${hm(s.ot)}</span></div>
    <div class="calendar">${WEEKDAYS().map(w => `<div class="h">${esc(w)}</div>`).join('')}${'<div></div>'.repeat(lead)}
    ${r.days.map(d => `<div class="d ${['off', 'holiday'].includes(d.status) ? 'off' : ''}"><div class="n">${+d.date.slice(8)}</div>
      <div class="st-${d.status}">${esc(STATUS[d.status] ? T(...STATUS[d.status]) : '')}</div>
      ${d.timetable ? `<div class="muted">${esc(d.timetable)}</div>` : ''}<div class="ltr">${esc(d.punches.join(' '))}</div>
      ${d.late ? `<div class="st-late">${esc(T('تأخير', 'Late'))} ${hm(d.late)}</div>` : ''}${d.ot ? `<div class="st-holiday">${esc(T('إضافي', 'OT'))} ${hm(d.ot)}</div>` : ''}</div>`).join('')}</div>`;
  const shift = (n) => { const d = new Date(first); d.setMonth(d.getMonth() + n); renderEmpCalendar(el, empId, iso(d).slice(0, 7)); };
  $('.prev', el).onclick = () => shift(-1); $('.next', el).onclick = () => shift(1);
}
function pageCalendar(c) {
  title(c, T('تقويم حضور الموظف', 'Employee attendance calendar'));
  const p = h(`<div class="panel"><div class="toolbar"><button class="btn primary">${icon('people')}${esc(T('اختر موظفاً', 'Choose employee'))}</button><b class="who"></b></div><div class="panel-body cal"><span class="muted">${esc(T('اختر موظفاً لعرض تقويمه الشهري', 'Choose an employee to see the month'))}</span></div></div>`);
  c.appendChild(p);
  $('button', p).onclick = async () => { const r = await pickEmployees({ multiple: false }); if (r && r[0]) { $('.who', p).textContent = `${r[0].emp_code} — ${r[0].name}`; renderEmpCalendar($('.cal', p), r[0].id, today().slice(0, 7)); } };
}
async function pageRules(c) {
  title(c, T('قواعد احتساب الحضور', 'Attendance rules'));
  const s = await GET('/api/settings');
  const f = [
    { section: T('البصمات', 'Punches') },
    { key: 'att.dup_punch_minutes', label: T('تجاهل البصمات المكررة خلال (دقيقة)', 'Ignore repeated punches within (min)'), type: 'number', min: 0 },
    { key: 'att.no_in', label: T('عند عدم وجود بصمة دخول', 'When there is no check-in'), type: 'select', blank: false, options: [{ value: 'incomplete', label: T('بصمة ناقصة (استثناء)', 'Missed punch (exception)') }, { value: 'absent', label: T('غياب', 'Absent') }, { value: 'late', label: T('تأخير بعدد دقائق', 'Late by N minutes') }] },
    { key: 'att.no_in_minutes', label: T('دقائق التأخير عند عدم وجود دخول', 'Late minutes for no check-in'), type: 'number', min: 0 },
    { key: 'att.no_out', label: T('عند عدم وجود بصمة خروج', 'When there is no check-out'), type: 'select', blank: false, options: [{ value: 'incomplete', label: T('بصمة ناقصة (استثناء)', 'Missed punch (exception)') }, { value: 'absent', label: T('غياب', 'Absent') }, { value: 'early', label: T('خروج مبكر بعدد دقائق', 'Early leave by N minutes') }] },
    { key: 'att.no_out_minutes', label: T('دقائق الخروج المبكر عند عدم وجود خروج', 'Early minutes for no check-out'), type: 'number', min: 0 },
    { key: 'att.late_full', label: T('بعد تجاوز فترة السماح', 'After the allowance is exceeded'), type: 'checkbox', text: T('احتساب كامل مدة التأخير (وليس ما زاد عن السماح فقط)', 'Count the full lateness (not only the excess)') },
    { section: T('العمل الإضافي', 'Overtime') },
    { key: 'att.ot_mode', label: T('طريقة احتساب الإضافي', 'Overtime mode'), type: 'select', blank: false, options: [{ value: 'auto', label: T('تلقائي من البصمات', 'Automatic from punches') }, { value: 'approval', label: T('بطلبات معتمدة فقط', 'Approved requests only') }, { value: 'both', label: T('الأكبر من الاثنين', 'Greater of both') }] },
    { key: 'att.ot_min_minutes', label: T('أقل مدة تُحتسب إضافي (دقيقة)', 'Minimum overtime (min)'), type: 'number', min: 0 },
    { key: 'att.ot_before_work', label: T('الحضور المبكر', 'Early arrival'), type: 'checkbox', text: T('يُحتسب عملاً إضافياً', 'Counts as overtime') },
    { key: 'att.dayoff_ot', label: T('العمل في الراحة والعطل', 'Work on days off / holidays'), type: 'checkbox', text: T('يُحتسب عملاً إضافياً', 'Counts as overtime') },
    { key: 'att.round_minutes', label: T('تقريب ساعات العمل والإضافي لأقل مضاعف لـ (دقيقة، 0 = بدون)', 'Round worked/OT down to (min, 0 = off)'), type: 'number', min: 0 },
    { section: T('الموظفون بدون جدول', 'Employees without a schedule') },
    { key: 'att.weekend', label: T('أيام الراحة', 'Days off'), type: 'multi', options: WEEKDAYS().map((w, i) => ({ value: i, label: w })) },
  ];
  const p = h(`<div class="panel"><div class="panel-body">${formHtml(f, s)}</div><div class="toolbar" style="border-top:1px solid var(--line);border-bottom:0"><button class="btn primary">${icon('check')}${esc(T('حفظ', 'Save'))}</button></div></div>`);
  c.appendChild(p);
  $('.btn.primary', p).onclick = () => guard(() => PUT('/api/settings', readForm(p, f)), T('تم الحفظ — النتائج تُحسب فوراً بالقواعد الجديدة', 'Saved — results use the new rules immediately'));
}

// ============================================================== reports
async function pageReports(c) {
  title(c, T('التقارير', 'Reports'));
  const list = await GET('/api/reports');
  c.appendChild(h(`<div class="report-cards">${list.map(r => `<a href="#/reports/${r.key}">${icon(r.kind === 'matrix' ? 'cal' : r.kind === 'summary' ? 'report' : 'list')}<div><b>${esc(App.lang === 'ar' ? r.title_ar : r.title_en)}</b></div></a>`).join('')}</div>`));
}
async function pageReport(c, key) {
  const list = await GET('/api/reports');
  const meta = list.find(r => r.key === key);
  if (!meta) { c.innerHTML = `<div class="alert">${esc(T('تقرير غير معروف', 'Unknown report'))}</div>`; return; }
  const lk = await lookups();
  title(c, App.lang === 'ar' ? meta.title_ar : meta.title_en);
  const p = h(`<div class="panel"><div class="filters">
    <div class="field"><label>${esc(T('من', 'From'))}</label><input class="inp" type="date" name="start" value="${meta.kind === 'punch' ? today() : monthStart()}"></div>
    <div class="field"><label>${esc(T('إلى', 'To'))}</label><input class="inp" type="date" name="end" value="${today()}"></div>
    <div class="field"><label>${esc(T('القسم', 'Department'))}</label><select class="inp" name="dep"><option value="">${esc(T('الكل', 'All'))}</option>${lk.departments.map(d => `<option value="${d.id}">${esc(d.name)}</option>`).join('')}</select></div>
    ${meta.kind === 'punch' ? `<div class="field"><label>${esc(T('الجهاز', 'Device'))}</label><select class="inp" name="dev"><option value="">${esc(T('الكل', 'All'))}</option>${lk.devices.map(d => `<option value="${esc(d.sn)}">${esc(d.name)}</option>`).join('')}</select></div>` : ''}
    <div class="field"><label>${esc(T('الموظفون', 'Employees'))}</label><button class="btn emp">${esc(T('الكل', 'All'))}</button></div>
    <button class="btn primary run">${icon('refresh')}${esc(T('عرض', 'Show'))}</button>
    <span style="flex:1"></span>
    <button class="btn xl">${icon('download')}Excel</button><button class="btn csv">${icon('download')}CSV</button><button class="btn prn">${icon('print')}${esc(T('طباعة', 'Print'))}</button>
  </div><div class="out"><div class="empty" style="padding:30px">${esc(T('اختر الفترة ثم اضغط عرض', 'Choose a period and press Show'))}</div></div></div>`);
  c.appendChild(p);
  let emps = [];
  $('.emp', p).onclick = async () => { const r = await pickEmployees({ preselect: emps }); if (r) { emps = r; $('.emp', p).textContent = emps.length ? `${emps.length} ${T('موظف', 'selected')}` : T('الكل', 'All'); } };
  const params = (fmt) => qs({ start: $('[name=start]', p).value, end: $('[name=end]', p).value, department_ids: $('[name=dep]', p).value, device: $('[name=dev]', p)?.value, employee_ids: emps.map(e => e.id).join(','), lang: App.lang, fmt });
  const run = async () => {
    const out = $('.out', p); out.innerHTML = `<div class="empty" style="padding:30px">${esc(T('جارٍ الحساب...', 'Calculating...'))}</div>`;
    try {
      const r = await GET(`/api/reports/${key}?${params('json')}`);
      const matrix = r.kind === 'matrix';
      out.innerHTML = `<div class="muted" style="padding:8px 12px">${esc(r.title)} · <span class="ltr">${esc(r.start)} → ${esc(r.end)}</span> · ${r.rows.length} ${esc(T('سجل', 'rows'))}</div>
        ${matrix ? `<div class="muted" style="padding:0 12px 8px">${Object.entries(r.legend).map(([s, l]) => `<b>${esc(s)}</b>=${esc(l)}`).join(' · ')}</div>` : ''}
        <div class="grid-wrap" style="max-height:calc(100vh - 300px)"><table class="grid ${matrix ? 'matrix' : ''}"><thead><tr>${r.columns.map(col => `<th>${esc(col.label)}</th>`).join('')}</tr></thead>
        <tbody>${r.rows.map(row => `<tr>${r.columns.map(col => { const v = row[col.key] ?? ''; return `<td class="${matrix ? 'm-' + esc(v) : ''}">${col.key === 'status_label' ? `<span class="badge ${STATUS[row.status]?.[2] || ''}">${esc(v)}</span>` : esc(Array.isArray(v) ? v.join(' ') : v)}</td>`; }).join('')}</tr>`).join('') || `<tr><td class="empty" colspan="${r.columns.length}">${esc(T('لا توجد بيانات', 'No data'))}</td></tr>`}</tbody></table></div>`;
    } catch (e) { out.innerHTML = `<div class="alert">${esc(e.message)}</div>`; }
  };
  $('.run', p).onclick = run;
  $('.xl', p).onclick = () => download(`/api/reports/${key}?${params('xlsx')}`);
  $('.csv', p).onclick = () => download(`/api/reports/${key}?${params('csv')}`);
  $('.prn', p).onclick = () => window.print();
  run();
}

// ============================================================== system
async function pageSettings(c) {
  title(c, T('إعدادات النظام', 'System settings'));
  const s = await GET('/api/settings');
  const lk = await lookups(true);
  const f = [
    { section: T('الشركة', 'Company') },
    { key: 'company.name_ar', label: T('اسم الشركة (عربي)', 'Company name (Arabic)') },
    { key: 'company.name', label: T('اسم الشركة (إنجليزي)', 'Company name (English)') },
    { section: T('اتصال الأجهزة (ADMS)', 'Device communication (ADMS)') },
    { key: 'adms.auto_add', label: T('الأجهزة الجديدة', 'New devices'), type: 'checkbox', text: T('إضافة أي جهاز يتصل تلقائياً', 'Automatically add any device that connects') },
    { key: 'adms.default_area', label: T('المنطقة الافتراضية للأجهزة الجديدة', 'Default area for new devices'), type: 'select', options: opts(lk.areas) },
    { key: 'adms.timezone', label: T('المنطقة الزمنية للأجهزة (ساعات، فارغ = توقيت هذا الحاسوب)', 'Device time zone (hours, empty = this PC)'), type: 'number', min: -12, max: 14 },
    { key: 'adms.sync_bio', label: T('توزيع القوالب', 'Template distribution'), type: 'checkbox', text: T('إرسال الوجه/البصمة المسجلة على جهاز إلى باقي أجهزة المنطقة', 'Send faces/fingerprints enrolled on one device to the other devices of the area') },
    { key: 'adms.upload_photos', label: T('صور الحضور', 'Attendance photos'), type: 'checkbox', text: T('طلب صور البصمة من الأجهزة', 'Ask devices to upload punch photos') },
    { section: T('القراءة من ZKBioTime عبر واجهته (بدون أي تغيير على الأجهزة)', 'Read from ZKBioTime through its API (no change to the terminals)') },
    { key: 'biotime.enabled', label: T('المزامنة التلقائية', 'Automatic sync'), type: 'checkbox', text: T('استيراد الأجهزة والموظفين والحركات من BioTime دورياً', 'Import terminals, employees and punches from BioTime periodically') },
    { key: 'biotime.url', label: T('عنوان BioTime', 'BioTime address'), placeholder: 'http://127.0.0.1:90' },
    { key: 'biotime.username', label: T('مستخدم BioTime (مدير)', 'BioTime user (admin)') },
    { key: 'biotime.password', label: T('كلمة مرور BioTime', 'BioTime password'), type: 'password' },
    { key: 'biotime.interval', label: T('كل (دقيقة)', 'Every (minutes)'), type: 'number', min: 1 },
    { key: 'biotime.history_days', label: T('أيام السجلات في أول مزامنة', 'Days of punches on first sync'), type: 'number', min: 1 },
    { section: T('العمل جنباً إلى جنب مع ZKBioTime', 'Side by side with ZKBioTime') },
    { key: 'adms.relay_url', label: T('عنوان BioTime (فارغ = إيقاف)', 'BioTime address (empty = off)'), placeholder: 'http://127.0.0.1:90',
      hint: T('وجّه الأجهزة إلى منفذ هذا البرنامج، وسيحفظ كل شيء ويمرّر كل طلب إلى BioTime كما هو فيبقى BioTime يعمل.', 'Point terminals at this program; it stores everything and passes every request on to BioTime unchanged.') },
    { key: 'adms.relay_primary', label: T('الجهاز يتبع ردود', 'Terminal follows'), type: 'select', blank: false, options: [
      { value: 'biotime', label: T('BioTime (فترة التجربة — لا يفقد BioTime أي سجل)', 'BioTime (trial period — BioTime never misses a record)') },
      { value: 'zkpro', label: T('هذا البرنامج (قبل إيقاف BioTime نهائياً)', 'This program (before retiring BioTime)') }] },
    { section: T('النسخ الاحتياطي التلقائي', 'Automatic backup') },
    { key: 'backup.hour', label: T('ساعة النسخ اليومي (0-23)', 'Daily backup hour (0-23)'), type: 'number', min: 0, max: 23 },
    { key: 'backup.keep', label: T('عدد النسخ المحفوظة', 'Backups to keep'), type: 'number', min: 1 },
  ];
  const srv = s._server;
  const p = h(`<div><div class="panel"><div class="panel-head"><h3>${esc(T('معلومات الخادم', 'Server'))}</h3></div><div class="panel-body"><div class="kv">
      <div>${esc(T('الإصدار', 'Version'))}</div><div>${esc(srv.app)} ${esc(srv.version)}</div>
      <div>${esc(T('منفذ الواجهة', 'Web port'))}</div><div><bdi>${srv.web_port}</bdi></div>
      <div>${esc(T('منفذ الأجهزة ADMS', 'ADMS port(s)'))}</div><div><bdi>${esc(srv.adms_ports.join(', '))}</bdi> ${esc(T('(الواجهة تقبل اتصال الأجهزة أيضاً على منفذها)', '(the web port accepts devices too)'))}</div>
      <div>${esc(T('مجلد البيانات', 'Data folder'))}</div><div><bdi>${esc(srv.data_dir)}</bdi></div></div>
      <p class="muted">${esc(T('لتغيير المنافذ: عدّل ملف zkpro.ini أو شغّل البرنامج بـ run.py --web 8090 --adms 90', 'To change ports edit zkpro.ini or start with run.py --web 8090 --adms 90'))}</p></div></div>
    <div class="panel"><div class="panel-body">${formHtml(f, s)}</div><div class="toolbar" style="border-top:1px solid var(--line);border-bottom:0"><button class="btn primary">${icon('check')}${esc(T('حفظ', 'Save'))}</button><button class="btn bt-test">${icon('check')}${esc(T('اختبار ربط BioTime', 'Test BioTime API'))}</button><button class="btn bt-sync">${icon('download')}${esc(T('مزامنة من BioTime الآن', 'Sync from BioTime now'))}</button><button class="btn relay-test">${icon('sync')}${esc(T('اختبار الاتصال بـ BioTime', 'Test BioTime connection'))}</button><span class="relay-res muted"></span></div></div></div>`);
  c.appendChild(p);
  const btResult = () => {
    let r = {}; try { r = JSON.parse(s['biotime.last_result'] || '{}'); } catch (e) { /* not JSON */ }
    if (!s['biotime.last_run']) return '';
    return r.error ? `✗ ${s['biotime.last_run']}: ${r.error}` : `✓ ${T('آخر مزامنة', 'Last sync')} ${s['biotime.last_run']}: ${T('أجهزة', 'terminals')} ${r.terminals} · ${T('موظفون', 'employees')} ${r.employees} · ${T('حركات جديدة', 'new punches')} ${r.punches}`;
  };
  $('.relay-res', p).textContent = btResult();
  const btForm = () => ({ url: $('[name="biotime.url"]', p).value.trim(), username: $('[name="biotime.username"]', p).value, password: $('[name="biotime.password"]', p).value });
  $('.bt-test', p).onclick = async () => {
    const r = await guard(() => POST('/api/biotime/test', btForm()));
    $('.relay-res', p).textContent = r.ok ? `✓ ${T('تم الدخول إلى BioTime', 'Logged in to BioTime')}: ${r.terminals.length} ${T('جهاز', 'terminals')} (${r.terminals.map(t => t.alias || t.sn).join('، ')}) · ${r.employees ?? '?'} ${T('موظف', 'employees')}` : `✗ ${r.error}`;
  };
  $('.bt-sync', p).onclick = async () => {
    await guard(() => { const v = readForm(p, f); if (v['adms.timezone'] === '') v['adms.timezone'] = null; if (v['adms.default_area'] !== '') v['adms.default_area'] = +v['adms.default_area']; return PUT('/api/settings', v); });
    $('.relay-res', p).textContent = T('جارٍ الاستيراد من BioTime... قد يستغرق دقائق في المرة الأولى', 'Importing from BioTime... the first time can take minutes');
    const r = await guard(() => POST('/api/biotime/sync'));
    $('.relay-res', p).textContent = `✓ ${T('أجهزة', 'terminals')} ${r.terminals} · ${T('موظفون', 'employees')} ${r.employees} · ${T('أقسام', 'departments')} ${r.departments} · ${T('حركات جديدة', 'new punches')} ${r.punches}`;
    App.lookups = null;
  };
  $('.relay-test', p).onclick = async () => {
    const url = $('[name="adms.relay_url"]', p).value.trim();
    if (!url) return toast(T('اكتب عنوان BioTime أولاً', 'Enter the BioTime address first'), 'bad');
    const r = await guard(() => POST('/api/relay/test', { url }));
    $('.relay-res', p).textContent = r.ok ? `✓ ${T('BioTime يرد', 'BioTime answers')} (HTTP ${r.status}: ${r.reply})` : `✗ ${r.error}`;
  };
  $('.btn.primary', p).onclick = () => guard(() => { const v = readForm(p, f); if (v['adms.timezone'] === '') v['adms.timezone'] = null; if (v['adms.default_area'] !== '') v['adms.default_area'] = +v['adms.default_area']; return PUT('/api/settings', v); }, T('تم الحفظ', 'Saved'));
}
async function pageUsers(c) {
  const lk = await lookups(true);
  simplePage(c, T('المستخدمون', 'Users'), '/api/users', 'system.admin',
    [{ key: 'username', label: T('اسم المستخدم', 'Username') }, { key: 'full_name', label: T('الاسم', 'Name') }, { key: 'role', label: T('الدور', 'Role'), render: r => r.is_superuser ? `<span class="badge info">${esc(T('مدير عام', 'Superuser'))}</span>` : esc(r.role) },
      { key: 'active', label: T('نشط', 'Active'), render: r => r.active ? '✓' : '—' }, { key: 'last_login', label: T('آخر دخول', 'Last login'), cls: 'ltr' }],
    [{ key: 'username', label: T('اسم المستخدم', 'Username'), required: true }, { key: 'full_name', label: T('الاسم', 'Name') },
      { key: 'password', label: T('كلمة المرور (اتركها فارغة لعدم التغيير)', 'Password (blank = unchanged)'), type: 'password' }, { key: 'email', label: T('البريد', 'Email') },
      { key: 'role_id', label: T('الدور', 'Role'), type: 'select', options: opts(lk.roles) }, { key: 'is_superuser', label: T('مدير عام', 'Superuser'), type: 'checkbox', text: T('كل الصلاحيات', 'All permissions') },
      { key: 'active', label: T('نشط', 'Active'), type: 'checkbox', text: T('يمكنه الدخول', 'Can sign in'), default: true }]);
}
async function pageRoles(c) {
  const perms = await GET('/api/permissions');
  const names = { 'personnel.view': T('عرض الموظفين', 'View personnel'), 'personnel.edit': T('تعديل الموظفين', 'Edit personnel'), 'device.view': T('عرض الأجهزة', 'View devices'), 'device.control': T('التحكم بالأجهزة', 'Control devices'), 'attendance.view': T('عرض الحضور', 'View attendance'), 'attendance.edit': T('تعديل الحضور والجداول', 'Edit attendance & schedules'), 'attendance.approve': T('اعتماد الطلبات', 'Approve requests'), 'reports.view': T('التقارير', 'Reports'), 'system.admin': T('إدارة النظام', 'System administration') };
  simplePage(c, T('الأدوار والصلاحيات', 'Roles'), '/api/roles', 'system.admin',
    [{ key: 'name', label: T('الاسم', 'Name') }, { key: 'permissions', label: T('الصلاحيات', 'Permissions'), cls: 'wrap', render: r => r.permissions.map(p => `<span class="badge">${esc(names[p] || p)}</span>`).join(' ') }],
    [{ key: 'name', label: T('الاسم', 'Name'), required: true }, { key: 'permissions', label: T('الصلاحيات', 'Permissions'), type: 'multi', options: perms.map(p => ({ value: p, label: names[p] || p })) }]);
}
function pageBackup(c) {
  title(c, T('النسخ الاحتياطي', 'Backup'));
  c.appendChild(h(`<div class="alert info">${esc(T('يُنشأ نسخة احتياطية تلقائية كل يوم. احفظ نسخة خارج الجهاز بانتظام (زر تنزيل).', 'A backup is made automatically every day. Keep a copy outside this PC (Download).'))}</div>`));
  const g = grid(c, {
    columns: [{ key: 'name', label: T('الملف', 'File'), cls: 'ltr' }, { key: 'time', label: T('الوقت', 'Time'), cls: 'ltr' }, { key: 'size', label: T('الحجم', 'Size'), render: r => (r.size / 1048576).toFixed(2) + ' MB' },
      { key: 'x', label: '', render: r => `<button class="btn small" data-act="dl">${icon('download')}${esc(T('تنزيل', 'Download'))}</button> <button class="btn small danger" data-act="restore">${esc(T('استعادة', 'Restore'))}</button>` }],
    idKey: 'name', select: false, search: false,
    fetch: localFetch('/api/backups'),
    actions: { dl: (r) => download(`/api/backups/${encodeURIComponent(r.name)}`), restore: async (r) => {
      if (!await confirmBox(T('استعادة هذه النسخة؟ ستُستبدل كل البيانات الحالية (تُحفظ نسخة منها أولاً).', 'Restore this backup? All current data is replaced (a copy is saved first).'))) return;
      await guard(() => POST(`/api/backups/${encodeURIComponent(r.name)}/restore`), T('تمت الاستعادة', 'Restored')); setTimeout(() => location.reload(), 800); } },
    toolbar: [{ label: T('نسخة احتياطية الآن', 'Back up now'), icon: 'db', cls: 'primary', action: async () => { await guard(() => POST('/api/backups'), T('تم إنشاء النسخة', 'Backup created')); g.reload(); } }],
  });
}
function pageAudit(c) {
  title(c, T('سجل التدقيق', 'Audit log'));
  grid(c, { columns: [{ key: 'created_at', label: T('الوقت', 'Time'), cls: 'ltr' }, { key: 'username', label: T('المستخدم', 'User') }, { key: 'action', label: T('العملية', 'Action') }, { key: 'target', label: T('الهدف', 'Target') }, { key: 'detail', label: T('التفاصيل', 'Detail'), cls: 'wrap' }, { key: 'ip', label: 'IP', cls: 'ltr' }],
    fetch: serverFetch('/api/audit'), select: false });
}
async function pageAbout(c) {
  const a = await GET('/api/about');
  title(c, T('حول البرنامج', 'About'));
  c.appendChild(h(`<div class="panel"><div class="panel-body"><h2 style="margin-top:0">${esc(a.app)} <span class="badge info">${esc(a.version)}</span></h2>
    <p>${esc(T('نظام حضور وانصراف بأسلوب BioTime لأجهزة ZKTeco (SpeedFace، ProFace، MB، UFace...) عبر بروتوكول ADMS/Push، مع دعم الوجه والبصمة والكف والبطاقة.', 'BioTime-style time & attendance for ZKTeco terminals (SpeedFace, ProFace, MB, UFace...) over ADMS/Push, with face, fingerprint, palm and card.'))}</p>
    <ul><li>${esc(T('الأجهزة، المناطق، توزيع القوالب تلقائياً', 'Devices, areas, automatic template distribution'))}</li><li>${esc(T('أوقات الدوام، الورديات الدورية، الجداول المؤقتة، الدوام الليلي والمرن', 'Timetables, cyclic shifts, temporary schedules, night & flexible shifts'))}</li>
    <li>${esc(T('الإجازات، البصمات اليدوية، العمل الإضافي مع الاعتماد', 'Leave, manual punches, overtime with approval'))}</li><li>${esc(T('13 تقريراً مع التصدير إلى Excel وCSV والطباعة', '13 reports with Excel/CSV export and printing'))}</li></ul>
    <p class="muted"><a href="/api/docs" target="_blank">API</a></p></div></div>`));
}

// ============================================================== boot
(async function boot() {
  try { const u = await api('GET', '/api/auth/me', undefined, { noAuthRedirect: true }); await startApp(u); }
  catch (e) { showLogin(); }
})();
