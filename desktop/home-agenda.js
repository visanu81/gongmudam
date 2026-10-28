(() => {
  'use strict';
  const routes = new Map([['/travel.html', 'travel'], ['/adhoc.html', 'collection'], ['/folders.html', 'folders'], ['/index.html', 'chat']]);
  function date(value) {
    return typeof value === 'string' && /^\d{4}-\d{2}-\d{2}$/.test(value) &&
      Number.isFinite(Date.parse(value + 'T00:00:00Z')) && new Date(value + 'T00:00:00Z').toISOString().slice(0, 10) === value;
  }
  function select(snapshot) {
    if (!snapshot || !date(snapshot.today) || !date(snapshot.week_start) || !date(snapshot.week_end) ||
        snapshot.today < snapshot.week_start || snapshot.today > snapshot.week_end || !Array.isArray(snapshot.tasks)) {
      throw new Error('업무 날짜와 목록을 확인하지 못했습니다.');
    }
    const active = snapshot.tasks.filter(row => row && row.is_task === true && row.status !== 'done' && date(row.due));
    const sorted = [...active].sort((a, b) => a.due.localeCompare(b.due) || String(a.id).localeCompare(String(b.id)));
    return {
      today: sorted.filter(row => row.due === snapshot.today),
      week: sorted.filter(row => row.is_deadline === true && row.due >= snapshot.week_start && row.due <= snapshot.week_end),
      next: sorted.find(row => row.is_deadline === true && row.due > snapshot.week_end) || null,
    };
  }
  function calendarHref(day, view = 'dayGridMonth') {
    const query = new URLSearchParams();
    if (date(day)) query.set('date', day);
    if (['dayGridMonth', 'timeGridWeek', 'timeGridDay'].includes(view)) query.set('view', view);
    return '/calendar.html?' + query;
  }
  function destination(row, origin) {
    const action = row?.action || {};
    const fallback = { id: 'calendar', href: calendarHref(row?.due) };
    const key = value => typeof value === 'string' && value.trim() && value.length <= 200;
    if (action.type === 'education' && key(action.job_id) && key(action.step_id)) {
      return { id: 'collection', href: '/adhoc.html?step=' + encodeURIComponent(action.step_id) + '#job-' + encodeURIComponent(action.job_id) };
    }
    if (action.type === 'link' && typeof action.href === 'string') {
      try {
        const url = new URL(action.href, origin);
        if (url.origin === origin && routes.has(url.pathname)) return { id: routes.get(url.pathname), href: url.pathname + url.search + url.hash };
      } catch { /* Unknown destinations stay in the calendar. */ }
    }
    return fallback;
  }
  function mount({ root, open, fetcher = window.fetch.bind(window), origin = window.location.origin }) {
    if (!root) return null;
    let snapshot = null, model = null, error = '', loading = false, controller = null, sequence = 0, disposed = false;
    let signature = '', statusNode = null, refreshControl = null;
    const el = (tag, className, text) => {
      const node = document.createElement(tag);
      if (className) node.className = className;
      if (text !== undefined) node.textContent = text;
      return node;
    };
    function button(text, className, focusKey, action) {
      const node = el('button', className, text); node.type = 'button';
      node.setAttribute('data-home-focus', focusKey); node.addEventListener('click', action); return node;
    }
    const shortDate = value => value.slice(5).replace('-', '/');
    const jump = target => open(target.id, target.href);
    function taskButton(row, prefix, next = false) {
      const node = button('', next ? 'home-agenda-next' : 'home-agenda-task', prefix + ':' + row.id, () => jump(destination(row, origin)));
      node.append(el('strong', '', (next ? '다음 마감 · ' : '') + (row.title || '제목 없는 업무')));
      if (row.work_title && row.work_title !== row.title) node.append(el('small', '', row.work_title));
      node.append(el('span', '', `${shortDate(row.due)} · ${row.overdue ? '기한 지남' : row.status_label || '미완료'}`));
      return node;
    }
    function group(label, rows, kind, day, view) {
      const section = el('section', 'home-agenda-group');
      section.append(el('h3', '', label + (rows ? ` ${rows.length}` : '')));
      const items = el('div', 'home-agenda-items');
      if (!rows) items.append(el('p', 'home-agenda-empty', error ? '목록을 확인하지 못했습니다.' : '확인 중입니다.'));
      else if (!rows.length) items.append(el('p', 'home-agenda-empty', kind === 'today' ? '오늘이 기한인 미완료 업무가 없습니다.' : '이번 주에 남은 마감이 없습니다.'));
      else rows.slice(0, 2).forEach(row => items.append(taskButton(row, kind)));
      section.append(items);
      if (rows?.length > 2) section.append(button(`${rows.length - 2}건 더 보기`, 'home-agenda-more', 'more:' + kind, () => jump({ id: 'calendar', href: calendarHref(day, view) })));
      return section;
    }
    function statusText() {
      return error ? (snapshot ? '최신 확인 실패 · 이전 결과입니다. 새로고침해 주세요.' : '업무를 불러오지 못했습니다. 새로고침해 주세요.') : loading ? '최신 업무를 확인하고 있습니다…' : '기한이 있는 미완료 업무를 표시합니다.';
    }
    function updateStatus() {
      if (statusNode) statusNode.textContent = statusText();
      if (refreshControl) refreshControl.disabled = loading;
    }
    function render() {
      const focused = root.contains(document.activeElement) ? document.activeElement.getAttribute('data-home-focus') : null;
      const header = el('div', 'home-agenda-header'), controls = el('div', 'home-agenda-controls');
      header.append(el('h2', '', '오늘과 이번 주'));
      const refreshButton = button('새로고침', '', 'refresh', refresh); refreshButton.disabled = loading;
      refreshControl = refreshButton;
      controls.append(button('달력', '', 'calendar', () => jump({ id: 'calendar', href: calendarHref(snapshot?.today) })), refreshButton);
      header.append(controls);
      const context = el('p', 'home-agenda-context', snapshot ? `${snapshot.today.replaceAll('-', '.')} · 이번 주 ${shortDate(snapshot.week_start)}–${shortDate(snapshot.week_end)} · 한국 시간` : '달력의 업무 정보를 확인합니다.');
      const nodes = [header, context,
        group('오늘 할 일', model?.today, 'today', snapshot?.today, 'timeGridDay'),
        group('이번 주 마감', model?.week, 'week', snapshot?.today, 'timeGridWeek')];
      if (model && !model.week.length && model.next) nodes.push(taskButton(model.next, 'next', true));
      const status = el('p', 'home-agenda-status', statusText()); statusNode = status;
      status.setAttribute('role', 'status'); status.setAttribute('aria-live', 'polite'); nodes.push(status);
      root.replaceChildren(...nodes);
      if (focused) {
        const candidates = [...root.querySelectorAll('[data-home-focus]')];
        const target = candidates.find(node => node.getAttribute('data-home-focus') === focused && !node.disabled) || candidates.find(node => node.getAttribute('data-home-focus') === 'refresh' && !node.disabled);
        target?.focus({ preventScroll: true });
      }
    }
    async function refresh() {
      if (disposed) return;
      const request = ++sequence;
      let needsRender = !snapshot;
      controller?.abort(); controller = new AbortController(); loading = true; error = '';
      if (!snapshot) render(); else updateStatus();
      try {
        const response = await fetcher('/api/calendar/agenda', { headers: { Accept: 'application/json' }, credentials: 'same-origin', cache: 'no-store', signal: controller.signal });
        if (!response.ok) throw new Error('HTTP ' + response.status);
        const data = await response.json();
        if (disposed || request !== sequence) return;
        const selected = select(data);
        const nextSignature = JSON.stringify([data.today, data.week_start, data.week_end, selected]);
        needsRender = needsRender || signature !== nextSignature;
        signature = nextSignature; snapshot = data; model = selected;
      } catch (failure) {
        if (disposed || request !== sequence || failure.name === 'AbortError') return;
        error = failure.message || '업무 확인 실패';
      } finally {
        if (!disposed && request === sequence) { loading = false; controller = null; if (needsRender) render(); else updateStatus(); }
      }
    }
    function onVisible() { if (!document.hidden) refresh(); }
    const timer = window.setInterval(onVisible, 60000);
    document.addEventListener('visibilitychange', onVisible); window.addEventListener('focus', onVisible);
    refresh();
    return { refresh, dispose() { disposed = true; sequence++; controller?.abort(); window.clearInterval(timer); document.removeEventListener('visibilitychange', onVisible); window.removeEventListener('focus', onVisible); } };
  }
  window.GongmudamHomeAgenda = { select, destination, mount };
})();
