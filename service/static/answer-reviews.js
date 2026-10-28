"use strict";
(() => {
  const root = document.querySelector("#answer-review-root");
  if (!root) return;
  const esc = (v) => String(v ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const state = { items: [], selected: null, detail: null, sources: [], edits: {}, sourceQueries: {}, selectedOutsideFilter: false, dirty: false, busy: false, filter: "open", query: "", sourceQuery: "", sourcesOpen: false, listToken: 0, detailToken: 0, sourceToken: 0, publicReadOnly: false, notice: "", today: new Date().toISOString().slice(0, 10) };
  const ratingNames = { solved: "해결됨", wrong: "틀림", insufficient: "근거 부족" };
  const stateNames = { pending: "검토 대기", draft: "초안", applied: "적용됨", resolved: "해결", needs_review: "재검토 필요", disabled: "사용 중지" };
  const req = async (method, path, body) => {
    const r = await fetch("/api/answer-reviews" + path, { method, headers: body ? { "Content-Type": "application/json" } : {}, body: body ? JSON.stringify(body) : undefined });
    let data = {}; try { data = await r.json(); } catch (_) { /* empty response */ }
    if (!r.ok) { const detail = data.detail; const message = typeof detail === "string" ? detail : Array.isArray(detail) ? detail.map((issue) => { const field = (issue.loc || []).filter((part) => part !== "body").join(" · "); const names = { evidence: "근거", answer: "답변", reviewer: "검토자 이름", valid_from: "유효 시작일", valid_until: "유효 종료일", alternate_questions: "대체 질문", quote: "인용문", source_id: "자료", unit_index: "근거 위치", sha256: "자료 지문", note: "의견" }; const label = names[field.split(" · ").at(-1)] || "입력"; return `${label}: ${issue.msg === "Field required" ? "필수 항목입니다." : issue.msg === "String should have at least 1 character" ? "비워 둘 수 없습니다." : issue.msg === "String should have at most 20000 characters" ? "길이 제한을 초과했습니다." : "입력 형식을 확인하세요."}`; }).join(" ") : detail ? "입력 형식을 확인하고 다시 시도하세요." : r.statusText || "요청에 실패했습니다."; const e = new Error(message); e.status = r.status; e.data = data; throw e; }
    return data;
  };
  const say = (message, kind = "info") => {
    const el = root.querySelector("[data-review-status]");
    if (el) { el.textContent = message; el.className = "review-status " + kind; }
  };
  const confirmedKey = (d) => `${d?.id || ""}:${(d && (latestDraft(d) || latestActive(d)))?.id || ""}`;
  const isConfirmed = (value, d) => value === confirmedKey(d);
  const referenceKey = (e) => `${e.source_id}:${Number(e.unit_index)}`;
  function mergeEvidence(baseline, visible) {
    const visibleKeys = new Set(visible.map((x) => referenceKey(x.reference)));
    return [...baseline.filter((e) => !visibleKeys.has(referenceKey(e))), ...visible.filter((x) => x.checked).map((x) => x.reference)];
  }
  function compareBaseline(d, displayed, active) {
    if (active?.id && active.id !== displayed?.id) return { label: "현재 적용 답변", answer: active.answer || "", evidence: active.evidence || [] };
    return { label: "최초 답변", answer: d.original_answer || "", evidence: d.original_evidence || [] };
  }
  const setBusy = (value) => { state.busy = value; root.querySelectorAll("button").forEach((b) => { const draft = state.detail && latestDraft(state.detail); b.disabled = value || b.dataset.requiresWritable === "true" && (state.publicReadOnly || b.id === "review-apply" && (!draft?.id || !!state.edits[state.selected] || !isConfirmed(state.confirmed, state.detail))); }); };
  const detailUrl = (id) => `index.html?review=${encodeURIComponent(id)}#reviews`;
  function render() {
    const items = state.items;
    root.innerHTML = `<div class="review-layout">
      <section class="review-list" aria-label="검토 목록">
        <div class="review-controls"><label>상태<select id="review-filter"><option value="open">열린 항목</option><option value="applied">적용됨</option><option value="resolved">해결</option><option value="all">전체</option></select></label><label class="review-search">질문 검색<input id="review-query" type="search" value="${esc(state.query)}" placeholder="질문·소속 검색"></label><button type="button" class="secondary" id="review-refresh">새로고침</button></div>
        <p class="review-list-note">${items.length}개 항목${state.selectedOutsideFilter ? " · 현재 열어둔 항목 포함" : ""}${state.publicReadOnly ? " · 읽기 전용" : ""}</p>
        <ul>${items.map((item) => `<li><button type="button" class="review-row ${item.id === state.selected ? "selected" : ""}" data-review-id="${esc(item.id)}"><span class="review-row-top"><b>${esc(item.query || "질문 없음")}</b><span class="review-state">${esc(stateNames[item.state] || item.state || "검토 대기")}</span></span><span>${esc(ratingNames[item.rating] || item.rating || "평가 전")} · ${esc(item.reviewer || "검토자 미입력")}</span><span>${esc(item.updated_at || item.created_at || "")}${item.applied_version ? ` · 적용 버전 ${esc(item.applied_version)}` : ""}</span>${item.validation_issues?.length ? `<span class="review-issue">확인 필요: ${esc(item.validation_issues.join(" · "))}</span>` : ""}</button></li>`).join("") || `<li class="review-empty">표시할 검토 항목이 없습니다.</li>`}</ul>
      </section><section class="review-detail" aria-label="검토 내용">${state.detail ? detailHtml(state.detail) : `<p class="review-empty-detail">왼쪽에서 질문을 선택하세요.</p>`}</section></div>`;
    root.querySelector("#review-filter").value = state.filter;
    root.insertAdjacentHTML("afterbegin", `<p data-review-status class="review-status" role="status" aria-live="polite">${esc(state.notice || (state.dirty ? "저장하지 않은 편집이 있습니다. 다른 항목을 열어도 초안은 유지됩니다." : ""))}</p>`);
    root.querySelector("#review-filter").addEventListener("change", (e) => { state.filter = e.target.value; refreshList(); });
    root.querySelector("#review-query").addEventListener("input", (e) => { state.query = e.target.value; });
    root.querySelector("#review-query").addEventListener("change", refreshList);
    root.querySelector("#review-refresh").addEventListener("click", refreshList);
    root.querySelectorAll("[data-review-id]").forEach((b) => b.addEventListener("click", () => openItem(b.dataset.reviewId)));
    bindDetail();
  }
  function evidenceHtml(refs, prefix) {
    return (refs || []).map((e, i) => `<li><b>${esc(e.title || e.source_id || "근거 자료")}</b><span>${esc(e.loc || e.unit_index || "")}</span><p>${esc(e.quote || e.text || "")}</p><input type="hidden" name="${prefix}-source" value="${esc(e.source_id || e.id || "")}"><input type="hidden" name="${prefix}-sha" value="${esc(e.sha256 || "")}"><input type="hidden" name="${prefix}-unit" value="${esc(e.unit_index ?? "")}"></li>`).join("") || "<li>등록 근거 없음</li>";
  }
  function detailHtml(d) {
    const version = latestDraft(d) || latestActive(d);
    const edit = state.edits[d.id] || {};
    const answer = edit.answer ?? version?.answer ?? d.original_answer ?? "";
    const reviewer = edit.reviewer ?? version?.reviewer ?? "";
    const alternatives = edit.alternate_questions ?? (version?.alternate_questions || []).join("\n");
    const refs = version?.evidence || d.original_evidence || [];
    const current = latestActive(d);
    const baseline = compareBaseline(d, version, current);
    const confirmed = isConfirmed(state.confirmed, d);
    const canWrite = !state.publicReadOnly;
    const baselineEvidence = edit.evidence || (latestDraft(d)?.evidence || []);
    const candidateMap = new Map();
    for (const e of baselineEvidence) candidateMap.set(`${e.source_id}:${Number(e.unit_index)}`, { ...e, unit_index: Number(e.unit_index) });
    for (const s of state.sources) candidateMap.set(`${s.source_id}:${Number(s.unit_index)}`, s);
    const sourceList = [...candidateMap.values()].map((s) => { const key = `${s.source_id}:${Number(s.unit_index)}`; const selected = baselineEvidence.find((e) => e.source_id === s.source_id && Number(e.unit_index) === Number(s.unit_index)); const catalog = typeof knowledgeSourcesSnapshot !== "undefined" ? knowledgeSourcesSnapshot?.find((e) => (e.id || e.source_id) === s.source_id) : null; const fileUrl = catalog && typeof knowledgeFileUrl === "function" ? knowledgeFileUrl(catalog) : ""; const manualUrl = catalog?.reference_kind === "system_manual" && typeof knowledgeManualUrl === "function" ? knowledgeManualUrl({ ...catalog, page: catalog.page || 1 }) : ""; const officialUrl = catalog?.official?.source_url && typeof knowledgeHttpUrl === "function" ? knowledgeHttpUrl(catalog.official.source_url) : ""; const originalLinks = [fileUrl ? `<a href="${esc(fileUrl)}">자료함에서 원문 확인</a>` : "", manualUrl ? `<a href="${esc(manualUrl)}" target="_blank" rel="noopener noreferrer">등록 매뉴얼 원문 PDF 열기 ↗</a>` : "", officialUrl ? `<a href="${esc(officialUrl)}" target="_blank" rel="noopener noreferrer">공식 원문 열기 ↗</a>` : ""].filter(Boolean).join(" · "); const text = String(s.text || ""); const truncated = text.length >= 20000; return `<div class="review-source"><input type="checkbox" aria-label="근거 선택: ${esc(s.title || s.source_id)} ${esc(s.loc || "")}" data-source-id="${esc(s.source_id)}" data-sha="${esc(s.sha256)}" data-unit="${esc(s.unit_index)}" ${selected ? "checked" : ""}><div class="review-source-body"><b>${esc(s.title || s.source_id)}</b><small>${esc(s.loc || "")} · ${esc(s.institution || "공통")} · ${esc(s.effective_date || "")}</small><details><summary>등록 원문 보기${truncated ? " · 일부 생략" : ""}</summary>${truncated ? "<small>표시 길이 제한으로 뒤 문장이 생략되었습니다.</small>" : ""}<p class="review-source-text">${esc(text)}</p></details>${originalLinks ? `<span class="review-source-links">${originalLinks}</span>` : ""}<button type="button" class="secondary" data-fill-quote="${esc(key)}">원문 인용</button><textarea aria-label="${esc(s.title || s.source_id)} 근거 인용문" data-quote-for="${esc(key)}" rows="3" placeholder="자료 원문에서 정확한 인용문을 입력하세요.">${esc(selected?.quote || "")}</textarea></div></div>`; }).join("");
    const affiliation = d.context?.affiliation;
    const organization = typeof affiliation === "string" ? affiliation : affiliation?.organization || affiliation?.institution || "소속 미지정";
    return `<header class="review-detail-head"><div><h3>${esc(d.query || "검토 항목")}</h3><p>${esc(organization)} · ${esc(ratingNames[d.rating] || d.rating || "평가 전")} · ${esc(stateNames[d.state] || d.state || "검토 대기")}</p></div><a class="secondary" href="${detailUrl(d.id)}">이 항목 링크</a></header>
      ${state.publicReadOnly ? `<p class="review-readonly">${esc(state.notice || "현재 검토함은 읽기 전용입니다.")}</p>` : ""}
      ${d.state === "needs_review" || d.validation_issues?.length ? `<div class="review-warning" role="status"><b>근거 또는 적용 범위를 다시 확인해야 합니다.</b><p>${esc((d.validation_issues || []).join(" · ") || "기존 적용 버전은 이 질문의 답변으로 사용하지 않습니다.")}</p><p>검토 전에는 원문 답변이 안내됩니다.</p></div>` : ""}
      <div class="review-compare"><section tabindex="0" aria-label="${esc(baseline.label)}와 근거"><h4>${esc(baseline.label)}</h4><p>${esc(baseline.answer)}</p><h5>기존 근거</h5><ul>${evidenceHtml(baseline.evidence, "before")}</ul></section><section tabindex="0" aria-label="검토 초안과 근거"><h4>검토 초안 ${version ? `· v${esc(version.number || "")}` : ""}</h4><p>${esc(answer)}</p><h5>근거</h5><ul>${evidenceHtml(refs, "after")}</ul></section></div>
      <form id="review-editor" class="review-editor"><h4>답변 검토 초안</h4><p class="muted">같은 소속·자료 선택에서, 이 질문과 등록한 대체 질문에만 적용합니다. 다른 질문 전체를 자동으로 학습하지 않습니다.</p><label>답변<textarea name="answer" rows="6" ${canWrite ? "" : "disabled"}>${esc(answer)}</textarea></label><div class="review-fields"><label>검토자 이름<input name="reviewer" required value="${esc(reviewer)}" ${canWrite ? "" : "disabled"}><small>이름을 기록합니다. 로그인 인증 정보는 아닙니다.</small></label><label>유효 시작일<input type="date" name="valid_from" required value="${esc(edit.valid_from ?? version?.valid_from ?? d.context?.today ?? state.today)}" ${canWrite ? "" : "disabled"}></label><label>유효 종료일(선택)<input type="date" name="valid_until" value="${esc(edit.valid_until ?? version?.valid_until ?? "")}" ${canWrite ? "" : "disabled"}></label></div><label>대체 질문(한 줄에 하나씩)<textarea name="alternate_questions" rows="3" ${canWrite ? "" : "disabled"}>${esc(alternatives)}</textarea></label><label>변경 이유<input name="change_note" value="${esc(edit.change_note ?? "")}" placeholder="확인한 내용이나 변경 이유" ${canWrite ? "" : "disabled"}></label>
      <details class="review-source-picker" ${state.sourcesOpen ? "open" : ""}><summary>등록 자료에서 근거 선택</summary><div class="review-source-controls"><label>자료 검색<input type="search" name="source_query" value="${esc(state.sourceQuery || d.query || "")}" ${canWrite ? "" : "disabled"}></label><button type="button" class="secondary" id="review-source-search" ${canWrite ? "" : "disabled"}>자료 찾기</button></div><div class="review-sources" tabindex="0" aria-label="등록 자료 근거 후보">${sourceList || `<p class="muted">자료 검색을 실행해 선택 가능한 근거를 불러오세요.</p>`}</div></details>
      <div class="review-actions"><button type="button" class="primary" id="review-save-draft" data-requires-writable="true" ${canWrite ? "" : "disabled"}>검토 초안 저장</button><label class="review-confirm"><input type="checkbox" id="review-confirm" ${confirmed ? "checked" : ""} ${canWrite ? "" : "disabled"}>원문과 적용 범위를 확인했습니다.</label><button type="button" class="secondary" id="review-apply" data-requires-writable="true" ${canWrite && version?.id && confirmed && !state.edits[d.id] ? "" : "disabled"}>확인한 초안 적용</button></div>
      <div class="review-actions"><button type="button" class="secondary" id="review-resolve" data-requires-writable="true" ${canWrite ? "" : "disabled"}>해결 처리</button><button type="button" class="secondary" id="review-reopen" data-requires-writable="true" ${canWrite ? "" : "disabled"}>적용 중지하고 다시 검토</button><button type="button" class="secondary" id="review-disable" data-requires-writable="true" ${canWrite ? "" : "disabled"}>사용 중지</button></div>
      <section class="review-timeline"><h4>버전 및 변경 이력</h4><ol>${[...(d.versions || []).map((v) => ({ ...v, event: `버전 ${v.number || ""} 저장` })), ...(d.history || []).map((h) => ({ ...h, event: h.kind || "상태 변경" }))].map((x) => `<li><b>${esc(x.event)}</b> · ${esc(x.reviewer || x.detail?.reviewer || x.actor || d.reviewer || "기록된 사용자 없음")} · ${esc(x.created_at || x.at || "")}<p>${esc(x.change_note || x.note || x.detail?.change_note || "")}</p></li>`).join("") || "<li>기록이 없습니다.</li>"}</ol></section></form>`;
  }
  function latestDraft(d) { return (d.versions || []).find((v) => v.id === d.draft_version_id) || (d.versions || []).filter((v) => v.id !== d.active_version_id).at(-1); }
  function latestActive(d) { return (d.versions || []).find((v) => v.id === d.active_version_id) || null; }
  function markDirty() { const form = root.querySelector("#review-editor"); if (form && state.selected) { const edits = Object.fromEntries(new FormData(form).entries()); edits.evidence = selectedEvidence(); state.edits[state.selected] = edits; } state.dirty = true; state.confirmed = null; const apply = root.querySelector("#review-apply"); if (apply) apply.disabled = true; const confirm = root.querySelector("#review-confirm"); if (confirm) confirm.checked = false; const status = root.querySelector("[data-review-status]"); if (status) { status.textContent = "저장하지 않은 편집이 있습니다. 목록·필터를 바꿔도 편집 내용은 유지되며, 저장하기 전에는 적용할 수 없습니다."; status.className = "review-status warning"; } }
  function bindDetail() {
    const form = root.querySelector("#review-editor"); if (!form) return;
    form.addEventListener("input", (e) => { if (!e.target.matches("input[type=checkbox]") && e.target.name !== "source_query") markDirty(); });
    form.addEventListener("change", (e) => { if (e.target.matches(".review-source input[type=checkbox]")) markDirty(); });
    form.querySelector(".review-source-picker").addEventListener("toggle", (e) => { state.sourcesOpen = e.target.open; });
    form.querySelector('[name="source_query"]').addEventListener("input", (e) => { state.sourceQuery = e.target.value; state.sourceQueries[state.selected] = state.sourceQuery; });
    form.querySelector("#review-confirm").addEventListener("change", (e) => { state.confirmed = e.target.checked ? confirmedKey(state.detail) : null; const apply = form.querySelector("#review-apply"); if (apply) apply.disabled = !e.target.checked || !!state.edits[state.selected] || !latestDraft(state.detail)?.id || state.publicReadOnly; });
    form.querySelector("#review-source-search")?.addEventListener("click", searchSources);
    form.querySelectorAll("[data-fill-quote]").forEach((button) => button.addEventListener("click", () => { const row = button.closest(".review-source"), quote = row?.querySelector("textarea[data-quote-for]"), checkbox = row?.querySelector('input[type="checkbox"]'); if (!quote) return; if (!quote.value) { const fullText = row.querySelector(".review-source-text")?.textContent || ""; if (fullText) quote.value = fullText.slice(0, 20000); } if (checkbox && !checkbox.checked) { checkbox.checked = true; checkbox.dispatchEvent(new Event("change", { bubbles: true })); } if (quote.value) quote.dispatchEvent(new Event("input", { bubbles: true })); }));
    form.querySelector("#review-save-draft").addEventListener("click", saveDraft);
    form.querySelector("#review-apply").addEventListener("click", applyDraft);
    form.querySelector("#review-resolve").addEventListener("click", () => operation("resolve"));
    form.querySelector("#review-reopen").addEventListener("click", () => operation("reopen"));
    form.querySelector("#review-disable").addEventListener("click", () => operation("disable"));
  }
  async function refreshList() {
    const requestToken = ++state.listToken;
    const params = new URLSearchParams({ status: state.filter, query: state.query });
    const selectedAtStart = state.selected;
    try { const data = await req("GET", "?" + params); if (requestToken !== state.listToken) return; state.items = data.items || []; state.publicReadOnly = !!data.public_read_only; state.notice = data.notice || ""; if (selectedAtStart && state.selected === selectedAtStart) { const detailToken = ++state.detailToken; const detail = await req("GET", "/" + encodeURIComponent(selectedAtStart)); if (requestToken !== state.listToken || detailToken !== state.detailToken || state.selected !== selectedAtStart) return; state.detail = detail; state.confirmed = null; state.dirty = !!state.edits[selectedAtStart]; } state.selectedOutsideFilter = !!state.selected && !state.items.some((i) => i.id === state.selected); if (state.selectedOutsideFilter) state.items.unshift({ id: state.selected, query: state.detail?.query, state: state.detail?.state, rating: state.detail?.rating, reviewer: state.detail?.reviewer, applied_version: state.detail?.applied_version, updated_at: state.detail?.updated_at, validation_issues: state.detail?.validation_issues }); render(); }
    catch (e) { if (requestToken !== state.listToken) return; render(); say(`검토 목록을 불러오지 못했습니다: ${e.message}`, "error"); }
  }
  async function openItem(id) {
    state.selected = id; state.sources = []; state.sourceToken++; state.sourcesOpen = false; state.sourceQuery = state.sourceQueries[id] || state.edits[id]?.source_query || ""; state.dirty = !!state.edits[id];
    state.detail = null; state.confirmed = null; render();
    const requestToken = ++state.detailToken;
    try { const detail = await req("GET", "/" + encodeURIComponent(id)); if (requestToken !== state.detailToken || state.selected !== id) return; state.detail = detail; state.publicReadOnly = !!state.detail.public_read_only || state.publicReadOnly; state.notice = state.detail.notice || state.notice; state.confirmed = null; state.selectedOutsideFilter = !state.items.some((i) => i.id === id); if (state.selectedOutsideFilter) state.items.unshift({ id, query: detail.query, state: detail.state, rating: detail.rating, reviewer: detail.reviewer, applied_version: detail.applied_version, updated_at: detail.updated_at, validation_issues: detail.validation_issues }); render(); }
    catch (e) { if (requestToken !== state.detailToken) return; render(); say(`검토 항목을 불러오지 못했습니다: ${e.message}`, "error"); }
  }
  function formValues() { return Object.fromEntries(new FormData(root.querySelector("#review-editor")).entries()); }
  async function searchSources() {
    const id = state.selected, token = ++state.sourceToken, q = state.sourceQuery || state.detail?.query || "";
    state.sourcesOpen = true;
    try { const data = await req("GET", `/sources?review_id=${encodeURIComponent(id)}&query=${encodeURIComponent(q)}`); if (token !== state.sourceToken || state.selected !== id) return; state.sources = data.items || []; render(); say(`${state.sources.length}개 등록 자료를 찾았습니다.`, "success"); }
    catch (e) { if (token !== state.sourceToken || state.selected !== id) return; say(`등록 자료를 찾지 못했습니다: ${e.message}`, "error"); }
  }
  function selectedEvidence() {
    const visible = [...root.querySelectorAll(".review-source input[type=checkbox]")];
    const baseline = state.edits[state.selected]?.evidence || latestDraft(state.detail)?.evidence?.map((e) => ({ source_id: e.source_id, sha256: e.sha256, unit_index: e.unit_index, quote: e.quote })) || [];
    const choices = visible.map((c) => ({ checked: c.checked, reference: { source_id: c.dataset.sourceId, sha256: c.dataset.sha, unit_index: Number(c.dataset.unit), quote: root.querySelector(`[data-quote-for="${CSS.escape(`${c.dataset.sourceId}:${c.dataset.unit}`)}"]`)?.value || "" } }));
    return mergeEvidence(baseline, choices);
  }
  async function saveDraft() {
    if (!state.detail || state.publicReadOnly) return;
    const v = formValues(); if (!v.reviewer?.trim()) { root.querySelector('[name="reviewer"]').focus(); say("검토자 이름을 입력하세요.", "error"); return; }
    const evidence = selectedEvidence();
    if (evidence.length < 1 || evidence.length > 6) { say("검토 초안에는 확인한 근거를 1개 이상 6개 이하로 선택하세요.", "error"); root.querySelector(".review-source-picker")?.scrollIntoView({ behavior: "smooth", block: "center" }); root.querySelector("#review-source-search")?.focus(); return; }
    const missingQuote = evidence.find((ref) => !ref.quote?.trim());
    if (missingQuote) { say("선택한 근거의 인용문을 입력하거나 ‘원문 인용’을 눌러 채우세요.", "error"); const quote = root.querySelector(`[data-quote-for="${CSS.escape(`${missingQuote.source_id}:${missingQuote.unit_index}`)}"]`); quote?.focus(); return; }
    setBusy(true);
    try {
      const data = await req("POST", `/${encodeURIComponent(state.selected)}/versions`, { revision: state.detail.revision, answer: v.answer, reviewer: v.reviewer.trim(), alternate_questions: v.alternate_questions.split(/\r?\n/).map((x) => x.trim()).filter(Boolean), valid_from: v.valid_from, valid_until: v.valid_until || null, change_note: v.change_note, evidence });
      state.detail = data; state.dirty = false; delete state.edits[state.selected]; state.confirmed = null; state.sources = []; render(); say("검토 초안을 저장했습니다. 저장만으로 답변에 적용되지는 않습니다.", "success");
    } catch (e) { say(e.status === 409 ? `다른 검토자가 먼저 변경했습니다. 최신 내용을 불러와 비교한 뒤 다시 저장하세요. 현재 편집은 유지됩니다. ${e.message}` : `초안을 저장하지 못했습니다: ${e.message}`, "error"); if (e.status === 409) root.querySelector("#review-refresh")?.focus(); }
    finally { setBusy(false); }
  }
  async function applyDraft() {
    const d = state.detail, draft = d && latestDraft(d);
    if (!draft?.id || state.edits[state.selected]) { say("편집한 내용을 먼저 초안으로 저장하세요.", "error"); return; }
    if (!isConfirmed(state.confirmed, d)) { root.querySelector("#review-confirm")?.focus(); say("원문과 적용 범위를 확인한 뒤 적용할 수 있습니다.", "error"); return; }
    setBusy(true);
    try { state.detail = await req("PATCH", `/${encodeURIComponent(state.selected)}`, { revision: d.revision, operation: "apply", version_id: draft.id, reviewed_sha256: draft.sha256, confirmed: true }); state.dirty = false; state.confirmed = null; render(); say("확인한 초안을 적용했습니다.", "success"); await refreshList(); }
    catch (e) { say(e.status === 409 ? `자료나 검토 상태가 바뀌었습니다. 최신 상태를 다시 확인하세요. 초안은 유지됩니다. ${e.message}` : `초안을 적용하지 못했습니다: ${e.message}`, "error"); }
    finally { setBusy(false); }
  }
  async function operation(operation) {
    if (!state.detail || state.publicReadOnly) return;
    setBusy(true);
    try { state.detail = await req("PATCH", `/${encodeURIComponent(state.selected)}`, { revision: state.detail.revision, operation }); state.dirty = false; render(); say(operation === "resolve" ? "해결로 표시했습니다." : operation === "reopen" ? "적용을 중지하고 다시 검토를 엽니다." : "사용 중지했습니다.", "success"); await refreshList(); }
    catch (e) { say(e.status === 409 ? `상태가 바뀌었습니다. 최신 상태를 새로고침하세요. 편집 내용은 유지됩니다. ${e.message}` : `상태를 바꾸지 못했습니다: ${e.message}`, "error"); }
    finally { setBusy(false); }
  }
  async function load() {
    if (state.busy) return;
    state.today = document.querySelector("#today")?.value || state.today;
    state.filter = "open";
    const linkId = new URLSearchParams(location.search).get("review");
    await refreshList();
    if (linkId) await openItem(linkId);
  }
  async function attach(box, res, opts = {}) {
    const context = res.review_context;
    if (!context) return;
    const node = document.createElement("section"); node.className = "answer-review-feedback";
    const known = res.reviewed_answer;
    node.innerHTML = `<div class="answer-review-feedback-title"><b>이 답변을 검토해 주세요</b>${known ? `<span class="reviewed-badge">검토 답변 ${esc(known.reviewer || "")} · v${esc(known.version_number || known.version || known.number || "")}</span>` : ""}</div>${known?.local_review ? `<p class="muted">기관 내부 검토 기록입니다. 이 결과가 AI 학습에 사용되는 것은 아닙니다.</p>` : ""}<div class="answer-review-ratings" role="group" aria-label="답변 평가"><button type="button" class="small" data-rating="solved">해결됨</button><button type="button" class="small" data-rating="wrong">틀림</button><button type="button" class="small" data-rating="insufficient">근거 부족</button></div><label>의견(선택)<textarea rows="2" maxlength="2000" data-feedback-note placeholder="확인한 점이나 필요한 내용을 적어 주세요."></textarea></label><button type="button" class="secondary" data-feedback-note-save hidden>의견 저장</button><div class="answer-review-feedback-status" role="status" aria-live="polite"></div>`;
    box.append(node);
    let saved = null, ratingBusy = false;
    const feedbackStatus = (text, error = false) => { node.querySelector(".answer-review-feedback-status").textContent = text; node.querySelector(".answer-review-feedback-status").className = "answer-review-feedback-status" + (error ? " error" : ""); };
    const note = node.querySelector("[data-feedback-note]"), noteSave = node.querySelector("[data-feedback-note-save]");
    const payload = (rating) => ({ context, rating, note: note.value, original_answer: String(res.answer || res.summary || "").slice(0, 12000), original_evidence: (res.knowledge?.evidence || []).slice(0, 30).map((e) => ({ source_id: e.source_id || e.id, sha256: e.sha256, loc: e.loc, quote: String(e.quote || "").slice(0, 8000) })) });
    node.querySelectorAll("[data-rating]").forEach((button) => button.addEventListener("click", async () => {
      if (ratingBusy) return; ratingBusy = true; node.querySelectorAll("button").forEach((b) => { b.disabled = true; });
      try {
        if (!saved) saved = await req("POST", "", payload(button.dataset.rating));
        else saved = await req("PATCH", `/${encodeURIComponent(saved.id)}/feedback`, { revision: saved.revision, rating: button.dataset.rating, note: note.value });
        noteSave.hidden = false; noteSave.disabled = false; feedbackStatus("검토 의견을 저장했습니다."); node.querySelectorAll("[data-rating]").forEach((b) => { b.disabled = false; b.setAttribute("aria-pressed", String(b.dataset.rating === button.dataset.rating)); });
        const a = document.createElement("a"); a.href = detailUrl(saved.id); a.textContent = "검토함에서 열기"; a.className = "answer-review-open"; node.querySelector(".answer-review-open")?.remove(); node.querySelector(".answer-review-feedback-status").append(" ", a);
      } catch (e) { feedbackStatus(e.status === 409 ? `다른 변경이 저장되었습니다. 검토함을 새로고침하고 다시 확인하세요. ${e.message}` : `저장하지 못했습니다: ${e.message}`, true); node.querySelectorAll("[data-rating]").forEach((b) => { b.disabled = false; }); noteSave.disabled = false; }
      finally { ratingBusy = false; }
    }));
    note.addEventListener("input", () => { if (saved) noteSave.hidden = false; });
    noteSave.addEventListener("click", async () => {
      if (!saved) return; noteSave.disabled = true;
      try { saved = await req("PATCH", `/${encodeURIComponent(saved.id)}/feedback`, { revision: saved.revision, rating: saved.rating, note: note.value }); feedbackStatus("의견을 저장했습니다."); }
      catch (e) { feedbackStatus(e.status === 409 ? `최신 의견을 다시 불러와 확인하세요. 현재 입력은 유지됩니다. ${e.message}` : `의견을 저장하지 못했습니다: ${e.message}`, true); }
      finally { noteSave.disabled = false; }
    });
  }
  window.SeomuAnswerReview = { load, attach };
  if (window.__SEOMU_TEST__ === true) window.SeomuAnswerReview.testHooks = { confirmationKey: confirmedKey, isConfirmed, mergeEvidence, compareBaseline };
})();
