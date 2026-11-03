(() => {
  'use strict';
  const entryParams = new URLSearchParams(location.search);
  if(entryParams.has('file') || entryParams.has('source') || entryParams.get('view') === 'references') { location.replace('folders-advanced.html' + location.search + location.hash); return; }
  const $ = (s, r = document) => r.querySelector(s);
  const el = (tag, cls, text) => { const n = document.createElement(tag); if (cls) n.className = cls; if (text !== undefined) n.textContent = text; return n; };
  const listView = $('#project-list-view'), projectView = $('#project-view'), projectList = $('#project-list');
  const question = $('#question-input'), conversation = $('#conversation'), fileList = $('#file-list');
  let projects = [], project = null, localAccess = false, publicDemo = false, selectedFiles = new Set(), explicitSelection = false, draftMode = false;
  let currentId = '', generation = 0, timer = null, requestVersion = 0, lastMessagesSignature = '', libraryProject = '', seenProject = '', fileLimit = 100, pickerBusy = false;
  const draftValues = new Map();
  const storageKey = id => `folder-project-question:${id}`;
  const setMessage = (target, text, error = false) => { target.textContent = text || ''; target.classList.toggle('is-error', error); };
  function materialAdded() { $('#add-menu').open = false; question.focus({preventScroll:true}); }
  async function api(path, method = 'GET', body) {
    const response = await fetch(`/api/folder-projects${path}`, { method, headers: body === undefined ? {} : { 'Content-Type': 'application/json' }, body: body === undefined ? undefined : JSON.stringify(body) });
    const data = await response.json().catch(() => ({}));
    if (!response.ok) { const error = new Error(typeof data.detail === 'string' ? data.detail : `요청을 처리하지 못했습니다 (${response.status}).`); error.status = response.status; throw error; }
    return data;
  }
  function safeId(value) { return encodeURIComponent(value); }
  // The open project no longer exists (the shared demo removes visitor projects after an hour and resets on a new version;
  // on the personal app another window removed it). Leave the stale view instead of retrying it.
  async function projectGone() {
    showList(); await loadProjects();
    setMessage($('#list-message'), publicDemo
      ? '열려 있던 프로젝트가 없어졌습니다. 공유 시연 사이트에 만든 프로젝트와 올린 자료는 1시간이 지나거나 새 버전이 올라가면 지워집니다. 프로젝트를 다시 만들어 주세요.'
      : '열려 있던 프로젝트를 찾지 못했습니다. 다른 창에서 삭제됐을 수 있습니다.', true);
  }
  function projectUrl(id) { return `folders.html#project=${encodeURIComponent(id)}`; }
  function showList() { resetCreateForm(); currentId = ''; generation++; requestVersion++; project = null; selectedFiles.clear(); explicitSelection = false; seenProject = ''; libraryProject = ''; lastMessagesSignature = ''; clearTimeout(timer); timer = null; listView.hidden = false; projectView.hidden = true; $('#back-projects').hidden = true; history.replaceState(null, '', 'folders.html'); question.value = ''; }
  function showProject(id) { currentId = id; generation++; requestVersion++; project = null; selectedFiles.clear(); explicitSelection = false; draftMode = false; $('#draft-toggle').setAttribute('aria-pressed','false'); $('#draft-toggle').textContent='초안 작성'; seenProject = id; libraryProject = ''; lastMessagesSignature = ''; clearTimeout(timer); timer = null; listView.hidden = true; projectView.hidden = false; $('#add-menu').open = false; $('#back-projects').hidden = false; history.replaceState(null, '', projectUrl(id)); question.value = localStorage.getItem(storageKey(id)) || ''; setMessage($('#project-message'), ''); refreshProject(); }
  function renderProjects() {
    projectList.replaceChildren();
    if (!projects.length) { projectList.append(el('p', 'fp-empty', '아직 프로젝트가 없습니다. 이름을 입력해 프로젝트를 만들어 보세요.')); return; }
    projects.forEach(item => {
      const a = el('a', 'fp-project-row'); a.href = projectUrl(item.id);
      const heading = el('strong', '', item.name); a.append(heading); projectList.append(a);
    });
  }
  async function loadProjects() {
    try { const data = await api(''); projects = data.projects || []; localAccess = !!data.local_access; publicDemo = !!data.public_demo; renderProjects(); if(project) renderSources(project.sources || []); }
    catch (e) { setMessage($('#list-message'), e.message, true); }
  }
  function isBusy(data) { return (data.jobs || []).some(j => ['queued', 'waiting', 'running'].includes(j.status)) || (data.messages || []).some(m => ['queued', 'waiting', 'running'].includes(m.status)); }
  function schedulePoll(id, gen, data) {
    clearTimeout(timer); timer = null;
    if (id !== currentId || gen !== generation) return;
    timer = setTimeout(() => refreshProject(id, gen), isBusy(data) ? 1000 : 15000);
  }
  async function refreshProject(id = currentId, gen = generation) {
    if (!id) return;
    const version = ++requestVersion;
    try {
      const data = await api(`/${safeId(id)}`);
      if (id !== currentId || gen !== generation || version !== requestVersion) return;
      $('#retry-project').hidden = true; project = data; renderProject(data); schedulePoll(id, gen, data);
    } catch (e) { if (id === currentId && gen === generation && version === requestVersion) { if (e.status === 404) { projectGone(); return; } setMessage($('#project-message'), e.message, true); $('#retry-project').hidden = false; } }
  }
  function renderFiles(files) {
    const focused = document.activeElement?.closest('.fp-file')?.querySelector('input')?.value;
    const previous = selectedFiles; fileList.replaceChildren(); const available = new Set(files.map(f => f.id)); selectedFiles = new Set([...previous].filter(id => available.has(id)));
    $('.fp-source-tools').hidden = !files.length;
    if (!files.length) { fileList.append(el('p', 'fp-empty', '+ 자료 추가를 눌러 파일이나 폴더를 넣어 주세요.')); return; }
    files.slice(0,fileLimit).forEach(file => {
      const label = el('label', 'fp-file'); const input = document.createElement('input'); input.type = 'checkbox'; input.value = file.id;
      input.checked = explicitSelection ? selectedFiles.has(file.id) : true;
      input.addEventListener('change', () => { if(!explicitSelection) selectedFiles = new Set(files.map(f => f.id)); explicitSelection = true; input.checked ? selectedFiles.add(file.id) : selectedFiles.delete(file.id); updateSelectionSummary(files); });
      const body = el('span', 'fp-file-body'); body.append(el('strong', '', file.name), el('small', `fp-status status-${file.status || 'unknown'}`, statusLabel(file.status)));
      if (file.detail && file.status !== 'ready') body.append(el('small', 'fp-muted', file.detail));
      if(file.stale) body.append(el('small','fp-stale','원본 변경 · 다시 읽기 대기'));
      label.append(input, body);
      const row = el('div', 'fp-file-row'); const remove = el('button', 'fp-remove', '빼기'); remove.type = 'button';
      remove.setAttribute('aria-label', `${file.name} 프로젝트에서 빼기`); remove.title = '이 프로젝트에서만 뺍니다. 원본 파일은 그대로입니다.';
      remove.addEventListener('click', () => removeItem(`/files/${safeId(file.id)}`, `‘${file.name}’ 파일을 이 프로젝트에서 뺐습니다. 원본 파일은 그대로입니다.`));
      row.append(label, remove); fileList.append(row);
    });
    if(files.length > fileLimit) { const more=el('button','secondary',`자료 더 보기 (${fileLimit}/${files.length})`); more.type='button';more.onclick=()=>{fileLimit+=100;renderFiles(project.files);};fileList.append(more); }
    if(focused) fileList.querySelector(`input[value="${CSS.escape(focused)}"]`)?.focus({preventScroll:true});
  }
  function statusLabel(status) { return ({ ready: '읽을 수 있음', partial: '일부 읽음', error: '읽기 오류', unsupported: '본문 미지원', unread: '아직 읽지 않음', queued: '대기 중', waiting: '대기 중', running: '읽는 중' })[status] || '상태 확인 중'; }
  function updateSelectionSummary(files = project?.files || []) {
    const count = explicitSelection ? selectedFiles.size : files.length;
    $('#selection-summary').textContent = explicitSelection ? (count ? `${count}개 파일 선택됨` : '선택한 파일 없음 · 질문할 자료를 선택하거나 전체 자료로 질문하세요.') : '전체 자료를 질문에 사용합니다.';
  }
  function renderSources(sources) {
    const list = el('div', 'fp-source-list');
    if (!sources.length) list.append(el('p', 'fp-empty', '연결된 자료가 없습니다.'));
    sources.forEach(source => {
      const row = el('div', 'fp-source-row'); const text = el('div', 'fp-source-text');
      text.append(el('strong', '', source.label), el('span', 'fp-muted', `${source.kind === 'folder' ? '폴더' : '파일'} · ${statusLabel(source.status)}`));
      const remove = el('button', 'fp-remove', '빼기'); remove.type = 'button'; remove.setAttribute('aria-label', `${source.label} 연결 빼기`);
      remove.addEventListener('click', () => { if (source.kind === 'folder' && !window.confirm(`${source.label} 폴더의 파일을 모두 이 프로젝트에서 뺄까요? 원본 폴더는 그대로입니다.`)) return; removeItem(`/sources/${safeId(source.id)}`, `${source.label} 연결을 뺐습니다. 원본은 그대로입니다.`); });
      row.append(text, remove); list.append(row);
    });
    $('#source-count').textContent = sources.length ? `${sources.length}개` : '';
    if (localAccess) {
      $('#add-folder').hidden = false; $('#add-file').hidden = false; $('#add-folder').disabled = pickerBusy; $('#add-file').disabled = pickerBusy;
    } else { $('#add-folder').hidden = true; $('#add-file').hidden = true; }
    if (localAccess) {
      $('#add-folder').onclick = () => chooseLocal('folder', currentId, generation); $('#add-file').onclick = () => chooseLocal('file', currentId, generation);
    }
    $('#demo-source').hidden = !publicDemo;
    if (publicDemo) $('#demo-source').onclick = async () => { const id = currentId, gen = generation; try { await api(`/${safeId(id)}/demo-source`, 'POST', {}); if (id === currentId && gen === generation) { await refreshProject(id, gen); materialAdded(); } } catch (e) { if (id === currentId && gen === generation) setMessage($('#project-message'), e.message, true); } };
    $('#source-controls').replaceChildren(list);
    $('#add-note').textContent = localAccess ? '연결한 PC 원본은 바뀌면 자동으로 다시 읽습니다. 사본은 올린 시점의 내용입니다.' : (publicDemo ? '공개 시연에서는 다른 방문자도 자료를 볼 수 있습니다. 공개·합성 자료만 올리세요.' : 'PC 원본 연결은 이 PC의 공무담 화면에서만 할 수 있습니다.');
  }
  function renderExcluded(items) {
    const box = $('#excluded-list'); box.replaceChildren(); $('#excluded-details').hidden = !items.length; $('#excluded-count').textContent = items.length ? `${items.length}개` : '';
    items.forEach(item => {
      const row = el('div', 'fp-source-row'); const back = el('button', 'fp-text-button', '다시 넣기'); back.type = 'button';
      back.addEventListener('click', async () => { const id = currentId, gen = generation; try { await api(`/${safeId(id)}/excluded/restore`, 'POST', { id: item.id }); if (id === currentId && gen === generation) { setMessage($('#project-message'), `‘${item.name}’ 파일을 다시 넣었습니다. 읽기가 끝나면 질문에 사용됩니다.`); await refreshProject(id, gen); } } catch (e) { if (id === currentId && gen === generation) setMessage($('#project-message'), e.message, true); } });
      row.append(el('strong', '', item.name), back); box.append(row);
    });
  }
  async function removeItem(path, done) {
    const id = currentId, gen = generation; if (!id) return;
    try { await api(`/${safeId(id)}${path}`, 'DELETE'); if (id === currentId && gen === generation) { setMessage($('#project-message'), done); await refreshProject(id, gen); } }
    catch (e) { if (id === currentId && gen === generation) setMessage($('#project-message'), e.message, true); }
  }
  async function loadLibrariesForProject(id = currentId, gen = generation) {
    if (!id || libraryProject === id) return;
    libraryProject = id;
    const container = $('#library-controls'); container.replaceChildren();
    try {
      const response = await fetch('/api/folders/libraries'); const libraries = await readJson(response);
      if (id !== currentId || gen !== generation) return;
      const items = Array.isArray(libraries) ? libraries : (libraries.libraries || []);
      if (!items.length) { container.append(el('p', 'fp-muted', '연결할 기존 자료함이 없습니다.')); return; }
      const label = el('label', '', '기존 자료함 연결'); const select = document.createElement('select'); select.setAttribute('aria-label', '연결할 기존 자료함');
      select.append(new Option('자료함 선택', ''));
      items.forEach(lib => { const option = new Option(lib.name || lib.id, lib.id); option.dataset.projectId = lib.id; select.append(option); });
      const add = el('button', 'secondary', '자료함 연결'); add.type = 'button'; add.addEventListener('click', async () => { if (!select.value) return; const target = id; try { await api(`/${safeId(target)}/libraries`, 'POST', { library_id: select.value }); if (target === currentId && gen === generation) await refreshProject(target, gen); } catch (e) { if (target === currentId && gen === generation) setMessage($('#project-message'), e.message, true); } });
      label.append(select); const all = el('a', 'fp-library-link', '기존 자료함 전체 보기 →'); all.href = 'folders-advanced.html'; container.append(label, add, all);
    } catch (e) { if (id === currentId && gen === generation) { libraryProject = ''; container.append(el('p', 'fp-muted', `기존 자료함 목록을 불러오지 못했습니다: ${e.message}`)); } }
  }
  async function chooseLocal(kind, id = currentId, gen = generation) {
    if (pickerBusy) return;
    pickerBusy = true;
    setMessage($('#project-message'), kind === 'folder' ? '폴더 선택 창을 열었습니다. 탐색기에서 폴더를 선택해 주세요.' : '파일 선택 창을 열었습니다. 탐색기에서 파일을 선택해 주세요.');
    if (project) renderSources(project.sources || []);
    try {
      const picked = kind === 'folder' ? await fetch('/api/folders/choose-local', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: '{}' }).then(readJson) : await fetch('/api/folder-projects/choose-files', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: '{}' }).then(readJson);
      if (id !== currentId || gen !== generation) return;
      const paths = picked.paths || (picked.path ? [picked.path] : []);
      if (picked.cancelled || !paths.length) { setMessage($('#project-message'), '자료 선택을 취소했습니다.'); return; }
      await api(`/${safeId(id)}/sources`, 'POST', { kind, paths }); if (id === currentId && gen === generation) { await refreshProject(id, gen); setMessage($('#project-message'), '선택한 자료를 연결했습니다. 읽기 상태를 확인한 뒤 질문하세요.'); materialAdded(); }
    } catch (e) { if (id === currentId && gen === generation) setMessage($('#project-message'), e.message, true); }
    finally {
      pickerBusy = false;
      if (currentId && project) renderSources(project.sources || []);
    }
  }
  async function readJson(r) { const data = await r.json().catch(() => ({})); if (!r.ok) throw new Error(data.detail || `요청을 처리하지 못했습니다 (${r.status}).`); return data; }
  async function addUploads(id, gen, folder = false) {
    const input = document.createElement('input'); input.type = 'file'; input.multiple = true; if(folder) input.setAttribute('webkitdirectory', ''); input.accept='.txt,.md,.csv,.pdf,.xlsx,.docx,.hwpx'; input.setAttribute('aria-label', folder ? '업로드할 폴더 선택' : '업로드할 파일 선택');
    input.addEventListener('change', async () => {
      const files = [...input.files]; if (!files.length || id !== currentId || gen !== generation) return;
      if (files.length > 100 || files.some(f => f.size > 5 * 1024 * 1024) || files.reduce((n, f) => n + f.size, 0) > 10 * 1024 * 1024) { setMessage($('#project-message'), '파일 최대 100개·파일당 5MB·전체 10MB까지 업로드할 수 있습니다.', true); return; }
      let name = project?.name || '새 프로젝트'; if(name.trim().length < 2) name += ' 자료';
      const publicConsent = publicDemo && window.confirm('공개 시연 사이트에서는 다른 방문자도 업로드 자료와 분석 결과를 볼 수 있습니다(1시간 뒤 자동 삭제). 공개 또는 합성 자료만 업로드하시겠습니까?');
      if (publicDemo && !publicConsent) return;
      const form = new FormData(); form.append('name', name); form.append('paths', JSON.stringify(files.map(f => f.webkitRelativePath || f.name))); form.append('situation', ''); form.append('public_consent', String(!publicDemo || publicConsent));
      files.forEach(file => form.append('files', file, file.webkitRelativePath || file.name));
      try {
        setMessage($('#project-message'), '선택한 파일 사본을 업로드하고 있습니다…');
        const created = await readJson(await fetch('/api/folders/uploads', { method: 'POST', body: form }));
        if (id !== currentId || gen !== generation) return;
        await api(`/${safeId(id)}/libraries`, 'POST', { library_id: created.id });
        if (id === currentId && gen === generation) { setMessage($('#project-message'), '올린 사본을 프로젝트에 넣었습니다. 원본과 자동 동기화되지 않습니다.'); await refreshProject(id, gen); materialAdded(); }
      } catch (e) { if (id === currentId && gen === generation) setMessage($('#project-message'), e.message, true); }
    });
    input.click();
  }
  function evidenceBlock(ev) {
    const details = el('details', 'fp-evidence'); const summary = el('summary', '', `${ev.name} · ${ev.loc || `단위 ${ev.unit}`}${ev.stale ? ' · 원문 변경됨' : ''}`);
    const text = el('p', '', ev.text || ''); const links = el('div', 'fp-evidence-links');
    const unit = document.createElement('a'); unit.href = `/api/folder-projects/${safeId(currentId)}/files/${safeId(ev.file_id)}/units/${encodeURIComponent(ev.unit)}?sha256=${encodeURIComponent(ev.sha256)}`; unit.textContent = '근거 단위'; unit.target = '_blank'; unit.rel = 'noopener';
    const original = document.createElement('a'); original.href = `/api/folder-projects/${safeId(currentId)}/files/${safeId(ev.file_id)}/original?sha256=${encodeURIComponent(ev.sha256)}`; original.textContent = '전체 원문'; original.target = '_blank'; original.rel = 'noopener'; links.append(unit, original);
    if (ev.stale) details.append(el('span', 'fp-stale', '자료가 변경되어 근거가 오래되었습니다.'));
    details.append(summary, text, links); return details;
  }
  function renderMessage(message) {
    const article = el('article', `fp-message-row ${message.role === 'user' ? 'is-user' : 'is-assistant'}`); article.dataset.messageId = message.id;
    article.append(el('div', 'fp-message-meta', message.role === 'user' ? '질문' : (message.draft ? '보고서 초안' : '답변')));
    if(message.role === 'user') { article.append(el('div', 'fp-answer', message.content || '')); return article; }
    if (message.role === 'assistant' && message.status === 'completed') {
      const content = el('div', 'fp-answer'); content.textContent = (message.content || '').replace(/\n{3,}/g, '\n\n'); article.append(content);
      if (message.notice || message.coverage) {
        const info = el('details', 'fp-answer-info');
        const coverage = message.coverage;
        const mode = ({offline:'AI 없이 원문 검색',local_ai:'로컬 AI 보조',upstage_ai:'업스테이지 AI 보조',fallback:'AI 연결 대신 원문 검색'})[message.mode] || '답변 방식·확인 범위';
        const summaryText = coverage ? `${mode} · 범위 ${coverage.total ?? 0}개 파일${coverage.partial ? ` · 일부 읽음 ${coverage.partial}` : ''}${coverage.unread ? ` · 미확인 ${coverage.unread}` : ''}` : mode;
        info.append(el('summary', '', summaryText));
        if (message.notice) info.append(el('p', 'fp-notice', message.notice));
        if (coverage) info.append(el('p', 'fp-coverage', `자료 확인 범위: 전체 ${coverage.total ?? 0} · 읽음 ${coverage.ready ?? 0} · 일부 ${coverage.partial ?? 0} · 미확인 ${coverage.unread ?? 0}`));
        article.append(info);
      }
      const keep = el('button', 'fp-text-button fp-keep', isOutput(message) ? '결과물에 저장됨 ✓' : '결과물로 저장'); keep.type = 'button'; keep.setAttribute('aria-pressed', String(isOutput(message)));
      keep.addEventListener('click', () => setOutput(message, !isOutput(message))); article.append(keep);
      if (message.evidence?.length) { const group = el('details', 'fp-citations'); group.append(el('summary', '', `근거 ${message.evidence.length}개`)); message.evidence.forEach(ev => group.append(evidenceBlock(ev))); article.append(group); }
      if (message.draft) {
        const edit = el('details', 'fp-edit-draft'); const summary = el('summary', '', '초안 수정'); const area = document.createElement('textarea'); area.rows = 8; area.value = draftValues.get(message.id) ?? (message.content || ''); area.setAttribute('aria-label', '보고서 초안 수정'); area.addEventListener('input', () => draftValues.set(message.id, area.value));
        const save = el('button', 'secondary', '수정 저장'); save.type = 'button'; save.addEventListener('click', async () => { const id = currentId, gen = generation; try { await api(`/${safeId(id)}/messages/${safeId(message.id)}`, 'PATCH', { content: area.value }); if (id === currentId && gen === generation) { draftValues.delete(message.id); await refreshProject(id, gen); } } catch (e) { if (id === currentId && gen === generation) setMessage($('#project-message'), e.message, true); } });
        const copy = el('button', 'secondary', '복사'); copy.type = 'button'; copy.addEventListener('click', async () => { try { await navigator.clipboard.writeText(area.value); setMessage($('#project-message'), '초안을 복사했습니다.'); } catch { setMessage($('#project-message'), '복사하지 못했습니다. 초안을 선택해 복사해 주세요.', true); } });
        const download = el('button', 'secondary', 'TXT로 저장'); download.type = 'button'; download.addEventListener('click', () => { const url = URL.createObjectURL(new Blob([area.value], { type: 'text/plain;charset=utf-8' })); const a = document.createElement('a'); a.href = url; a.download = `${project?.name || '업무'}-초안.txt`; a.click(); setTimeout(() => URL.revokeObjectURL(url), 1000); });
        edit.append(summary, area, save, copy, download); article.append(edit);
      }
    } else {
      article.append(el('p', 'fp-answer', message.content || ({ queued: '대기 중', waiting: '자료를 기다리는 중', running: '답변을 작성하고 있습니다', failed: '답변을 만들지 못했습니다' })[message.status] || '처리 중'));
      if (message.notice) article.append(el('p', 'fp-notice', message.notice));
    }
    if (message.role === 'user') { const content = el('div', 'fp-answer'); content.textContent = message.content || ''; article.append(content); }
    return article;
  }
  function renderJobs(jobs, files) {
    const area = $('#job-area'); area.replaceChildren();
    const active = jobs.filter(job => ['queued', 'waiting', 'running'].includes(job.status));
    const history = jobs.filter(job => !['queued', 'waiting', 'running'].includes(job.status));
    const reading = active[0];
    $('#reading-progress').hidden = !reading;
    $('#reading-progress').textContent = reading ? `자료 읽는 중 · 전체 ${reading.total ?? '확인 중'}개 중 ${reading.processed || 0}개 읽음 · 질문을 미리 입력해도 됩니다.` : '';
    $('#job-history').open = active.length > 0;
    active.forEach(job => {
      const box = el('div', 'fp-job'); const title = el('strong', '', job.kind === 'refresh' ? '자료 다시 읽기' : '자료 읽기');
      const progress = document.createElement('progress'); progress.max = Math.max(1, job.total || 1); progress.value = job.processed || 0; progress.setAttribute('aria-label', '자료 읽기 진행 상태');
      const meta = el('p', 'fp-muted', `${job.processed || 0} / ${job.total || 0}개 처리${job.current_file ? ` · ${job.current_file}` : ''}${job.error ? ` · ${job.error}` : ''}`);
      const id = currentId, gen = generation;
      const cancel = el('button', 'secondary', '작업 취소'); cancel.type = 'button'; cancel.disabled = !['queued', 'waiting', 'running'].includes(job.status); cancel.addEventListener('click', async () => { try { await api(`/${safeId(id)}/jobs/${safeId(job.id)}/cancel`, 'POST', {}); if (id === currentId && gen === generation) await refreshProject(id, gen); } catch (e) { if (id === currentId && gen === generation) setMessage($('#project-message'), e.message, true); } });
      box.append(title, progress, meta, cancel); area.append(box);
    });
    history.slice(-1).forEach(job => area.append(el('p', 'fp-muted', `${job.status === 'completed' ? '마지막 작업 완료' : job.status === 'failed' ? '마지막 작업 오류' : '마지막 작업 취소'}${job.error ? ` · ${job.error}` : ''}`)));
    const summary = files.reduce((acc, f) => (acc[f.status] = (acc[f.status] || 0) + 1, acc), {});
    const existing = area.querySelector('.fp-file-summary'); if (existing) existing.remove();
    if (files.length) area.append(el('p', 'fp-file-summary fp-muted', `자료 상태 · 읽을 수 있음 ${summary.ready || 0} · 일부 ${summary.partial || 0} · 오류 ${summary.error || 0} · 미지원 ${summary.unsupported || 0}`));
  }
  function renderProject(data) {
    $('#project-title').textContent = data.name || '프로젝트';
    const files = data.files || [], messages = data.messages || [];
    $('#project-summary').textContent = files.length ? `${files.length}개 파일이 담겨 있습니다.` : (publicDemo ? '시연 자료를 추가해 시작하세요.' : '폴더나 파일을 추가해 시작하세요.');
    $('#file-count').textContent = `${files.length}개 파일`;
    renderSources(data.sources || []); renderFiles(files); renderExcluded(data.excluded || []); renderJobs(data.jobs || [], files); renderOutputs(messages);
    updateSelectionSummary(files);
    const signature = JSON.stringify(messages.map(m => [m.id, m.status, m.content, m.draft, m.output, m.evidence?.map(e => [e.file_id,e.stale])]));
    if (signature !== lastMessagesSignature) {
      const focused = document.activeElement; const focusMessage = focused?.closest('.fp-message-row')?.dataset.messageId; const selection = focused?.selectionStart;
      const openDetails = new Set([...conversation.querySelectorAll('details[open]')].map(d => `${d.closest('[data-message-id]')?.dataset.messageId}:${d.querySelector('summary')?.textContent}`));
      const scroll = conversation.scrollTop, nearBottom = conversation.scrollHeight - scroll - conversation.clientHeight < 70;
      conversation.replaceChildren();
      if (!messages.length) conversation.append(el('p', 'fp-empty fp-conversation-empty', '안녕하세요. 프로젝트 자료를 추가하고 궁금한 점을 물어보세요.'));
      messages.forEach(m => { const node = renderMessage(m); node.dataset.messageId = m.id; conversation.append(node); });
      conversation.querySelectorAll('details').forEach(d => { if(openDetails.has(`${d.closest('[data-message-id]')?.dataset.messageId}:${d.querySelector('summary')?.textContent}`)) d.open=true; });
      conversation.scrollTop = nearBottom ? conversation.scrollHeight : scroll;
      lastMessagesSignature = signature;
      if (focusMessage) { const row = conversation.querySelector(`[data-message-id="${CSS.escape(focusMessage)}"]`); const area = row?.querySelector('textarea'); if (area) { area.focus(); if (selection !== undefined) area.setSelectionRange(selection, selection); } }
    }
    if (seenProject !== currentId) { seenProject = currentId; libraryProject = ''; }
    if ($('#add-menu').open && libraryProject !== currentId) loadLibrariesForProject(currentId, generation);
  }
  // Outputs: answers made from the outputs panel, drafts, and answers the user kept.
  function isOutput(message) { return message.role === 'assistant' && (message.output === true || (message.output == null && !!message.draft)); }
  async function setOutput(message, saved) {
    const id = currentId, gen = generation;
    try { await api(`/${safeId(id)}/messages/${safeId(message.id)}/output`, 'POST', { saved }); if (id === currentId && gen === generation) await refreshProject(id, gen); }
    catch (e) { if (id === currentId && gen === generation) setMessage($('#project-message'), e.message, true); }
  }
  const outputLabels = new Map([...document.querySelectorAll('[data-output]')].map(b => [b.dataset.output, b.textContent.trim()]));
  function outputTitle(message, messages) { const asked = messages.find(m => m.id === message.user_id)?.content || message.question || ''; if (outputLabels.has(asked)) return outputLabels.get(asked); return asked.length > 40 ? asked.slice(0, 40) + '…' : asked || '결과물'; }
  function localTime(value) { const at = new Date(value || ''); return isNaN(at) ? '' : at.toLocaleString('ko-KR', { month: 'numeric', day: 'numeric', hour: '2-digit', minute: '2-digit' }); }
  function renderOutputs(messages) {
    const list = $('#output-list'); const items = messages.filter(isOutput).reverse();
    const open = new Set([...list.querySelectorAll('details[open]')].map(d => d.dataset.messageId));
    list.replaceChildren();
    if (!items.length) { list.append(el('p', 'fp-empty', '아직 결과물이 없습니다. 위 버튼으로 만들거나 대화 답변을 저장하세요.')); return; }
    items.forEach(message => {
      const card = el('details', 'fp-output'); card.dataset.messageId = message.id; card.open = open.has(message.id);
      const done = message.status === 'completed';
      const summary = el('summary'); summary.append(el('strong', '', outputTitle(message, messages)), el('small', 'fp-muted', done ? `${message.draft ? '초안' : '정리'} · ${localTime(message.edited_at || message.created_at)}` : '만드는 중…'));
      card.append(summary);
      if (done) {
        const text = draftValues.get(message.id) ?? (message.content || '');
        card.append(el('div', 'fp-output-text', text.replace(/\n{3,}/g, '\n\n')));
        const actions = el('div', 'fp-output-actions');
        const copy = el('button', 'fp-text-button', '복사'); copy.type = 'button'; copy.addEventListener('click', async () => { try { await navigator.clipboard.writeText(text); setMessage($('#project-message'), '결과물을 복사했습니다.'); } catch { setMessage($('#project-message'), '복사하지 못했습니다. 내용을 선택해 복사해 주세요.', true); } });
        const save = el('button', 'fp-text-button', 'TXT로 저장'); save.type = 'button'; save.addEventListener('click', () => { const url = URL.createObjectURL(new Blob([text], { type: 'text/plain;charset=utf-8' })); const a = document.createElement('a'); a.href = url; a.download = `${project?.name || '업무'}-${outputTitle(message, messages).replace(/[\\/:*?"<>|]/g, '')}.txt`; a.click(); setTimeout(() => URL.revokeObjectURL(url), 1000); });
        const go = el('button', 'fp-text-button', '대화에서 보기'); go.type = 'button'; go.addEventListener('click', () => { const row = conversation.querySelector(`[data-message-id="${CSS.escape(message.id)}"]`); if (row) { row.scrollIntoView({ block: 'center', behavior: 'smooth' }); row.classList.add('is-highlight'); setTimeout(() => row.classList.remove('is-highlight'), 1600); } });
        const drop = el('button', 'fp-text-button', '결과물에서 빼기'); drop.type = 'button'; drop.addEventListener('click', () => setOutput(message, false));
        actions.append(copy, save, go, drop); card.append(actions);
      }
      list.append(card);
    });
  }
  $('#new-project-form').addEventListener('submit', async e => {
    e.preventDefault(); const input = $('#new-project-name'); const name = input.value.trim(); if (!name) return;
    try { const data = await api('', 'POST', { name }); const item = data.project || data; projects = [item, ...projects.filter(p => p.id !== item.id)]; input.value = ''; resetCreateForm(); if(pendingHandoff) localStorage.setItem(storageKey(item.id), pendingHandoff); pendingHandoff=''; showProject(item.id); }
    catch (err) { setMessage($('#list-message'), err.message, true); }
  });
  function resetCreateForm() { $('#new-project-form').hidden = true; $('#toggle-new-project').hidden = false; $('#toggle-new-project').setAttribute('aria-expanded','false'); }
  $('#toggle-new-project').addEventListener('click', e => { const form = $('#new-project-form'); form.hidden = false; e.currentTarget.hidden = true; e.currentTarget.setAttribute('aria-expanded','true'); $('#new-project-name').focus(); });
  $('#cancel-new-project').addEventListener('click', () => { $('#new-project-form').hidden = true; $('#toggle-new-project').hidden = false; $('#toggle-new-project').setAttribute('aria-expanded','false'); $('#toggle-new-project').focus(); });
  $('#question-form').addEventListener('submit', async e => {
    e.preventDefault(); const content = question.value.trim(); if (!content) return;
    const id = currentId, gen = generation; if (!id) return;
    if(explicitSelection && !selectedFiles.size) { setMessage($('#project-message'), '자료를 선택하거나 전체 자료로 질문을 눌러주세요.', true); return; }
    const file_ids = explicitSelection ? [...selectedFiles] : []; const body = { content, file_ids, draft: draftMode };
    setMessage($('#project-message'), '질문을 보내고 있습니다…');
    try { question.value = ''; localStorage.removeItem(storageKey(id)); draftMode = false; $('#draft-toggle').setAttribute('aria-pressed', 'false'); $('#draft-toggle').textContent='초안 작성'; const sent = await api(`/${safeId(id)}/messages`, 'POST', body); if (id === currentId && gen === generation) { setMessage($('#project-message'),''); await refreshProject(id, gen); } }
    catch (err) { if (id === currentId && gen === generation) { question.value = content; localStorage.setItem(storageKey(id), content); if (err.status === 404) { projectGone(); return; } setMessage($('#project-message'), err.message, true); } }
  });
  question.addEventListener('input', () => { if (currentId) localStorage.setItem(storageKey(currentId), question.value); });
  document.querySelectorAll('[data-prompt]').forEach(b => b.addEventListener('click', () => { question.value = b.dataset.prompt; question.focus(); question.dispatchEvent(new Event('input')); }));
  $('#draft-toggle').addEventListener('click', e => { draftMode = !draftMode; e.currentTarget.setAttribute('aria-pressed', String(draftMode)); e.currentTarget.textContent = draftMode ? '초안 작성 켬' : '초안 작성'; });
  $('#select-all-files').addEventListener('click', () => { explicitSelection = true; selectedFiles = new Set((project?.files || []).map(f => f.id)); fileList.querySelectorAll('input[type=checkbox]').forEach(c => c.checked = true); updateSelectionSummary(); });
  $('#clear-file-selection').addEventListener('click', () => { explicitSelection = false; selectedFiles.clear(); fileList.querySelectorAll('input[type=checkbox]').forEach(c => c.checked = true); updateSelectionSummary(); });
  $('#refresh-project').addEventListener('click', async () => { const id = currentId, gen = generation; if (!id) return; try { await api(`/${safeId(id)}/refresh`, 'POST', {}); if (id === currentId && gen === generation) await refreshProject(id, gen); } catch (e) { if (id === currentId && gen === generation) setMessage($('#project-message'), e.message, true); } });
  $('#retry-project').addEventListener('click', () => refreshProject());
  $('#add-menu').addEventListener('toggle', e => { if (e.currentTarget.open) loadLibrariesForProject(currentId, generation); });
  $('#upload-files').addEventListener('click', () => addUploads(currentId, generation, false));
  $('#upload-folder').addEventListener('click', () => addUploads(currentId, generation, true));
  document.querySelectorAll('[data-output]').forEach(b => b.addEventListener('click', async () => {
    const id = currentId, gen = generation; if (!id) return;
    if (!(project?.files || []).length) { setMessage($('#project-message'), '먼저 + 자료 추가로 자료를 넣어 주세요.', true); return; }
    if (explicitSelection && !selectedFiles.size) { setMessage($('#project-message'), '자료를 선택하거나 전체 자료로 질문을 눌러주세요.', true); return; }
    const body = { content: b.dataset.output, file_ids: explicitSelection ? [...selectedFiles] : [], draft: !!b.dataset.draft, output: true };
    try { await api(`/${safeId(id)}/messages`, 'POST', body); if (id === currentId && gen === generation) { setMessage($('#project-message'), `‘${b.textContent}’ 만드는 중입니다. 다 되면 결과물 칸에 표시됩니다.`); await refreshProject(id, gen); } }
    catch (e) { if (id === currentId && gen === generation) setMessage($('#project-message'), e.message, true); }
  }));
  $('#back-projects').addEventListener('click', e => { e.preventDefault(); showList(); loadProjects(); });
  window.addEventListener('hashchange', route);
  let importing = '';
  let pendingHandoff = '';
  function route() { const m = location.hash.match(/^#project=(.*)$/); if (m) { const id = decodeURIComponent(m[1]); if (id !== currentId) showProject(id); } else if(location.hash === '#from-guidance') { pendingHandoff = window.SeomuFlow?.take('folder')?.text || ''; setMessage($('#list-message'), pendingHandoff ? '대화에서 질문을 가져왔습니다. 프로젝트를 만들면 질문 입력란에 이어집니다.' : '프로젝트를 만들고 자료를 추가해 질문하세요.'); } else if(location.hash.length > 1) { const library = decodeURIComponent(location.hash.slice(1)); if(importing === library) return; importing = library; const hash = location.hash; api('/import-library','POST',{library_id:library}).then(p=>{if(location.hash===hash)showProject(p.id);}).catch(e=>setMessage($('#list-message'),e.message,true)).finally(()=>{importing='';}); } else if (currentId) showList(); }
  async function loadProviderNotice() {
    const notice = $('#upstage-notice');
    try {
      const response = await fetch('/api/settings');
      if (!response.ok) return;
      const settings = await response.json();
      const llm = settings.llm || {};
      const profile = llm.profiles?.[llm.active];
      if (llm.active !== 'upstage' && !String(profile?.base_url || '').startsWith('https://api.upstage.ai/v1')) return;
      notice.hidden = false;
    } catch {}
  }
  route(); loadProjects(); loadProviderNotice();
})();
