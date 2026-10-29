"use strict";
window.SeomuGuidance = (() => {
  const esc = (value) => String(value ?? "").replace(/[&<>"']/g, (char) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[char]));
  const localFormHref = (form) => {
    const href = String(form?.href ?? "");
    if (href === "index.html#forms") return href;
    return /^\/api\/documents\/[A-Za-z0-9_%.-]+\/download$/.test(href) || /^\/api\/institution-rules\/[a-f0-9]{32}\/versions\/[a-f0-9]{32}\/original$/.test(href) ? href : "";
  };
  const officialServiceUrl = (value) => {
    try {
      const url = new URL(String(value ?? ""));
      return url.protocol === "https:" && ["www.mpm.go.kr", "mpm.go.kr"].includes(url.hostname) && !url.username && !url.password && /^\/mpm\/info\//.test(url.pathname) ? url.href : "";
    } catch (_) { return ""; }
  };
  const serviceSnapshotHref = (value) => /^\/api\/service-guides\/[A-Za-z0-9_-]+\/original$/.test(String(value ?? "")) ? String(value) : "";
  function render(box, result) {
    const guidance = result?.guidance;
    if (!box || !guidance || typeof guidance !== "object") return;
    const section = document.createElement("section");
    section.className = "guidance-panel";
    const steps = Array.isArray(guidance.steps) ? guidance.steps : [];
    const scope = guidance.institution_scope && typeof guidance.institution_scope === "object" && !Array.isArray(guidance.institution_scope) ? guidance.institution_scope : null;
    const scopeOrganizations = Array.isArray(scope?.organizations) ? scope.organizations.filter(name => typeof name === "string" && name.trim()).map(name => name.trim()) : [];
    const scopeLabel = scope?.basis === "affiliation" ? "내 소속 기준" : scope?.basis === "question" ? "질문에서 지정한 기관" : "";
    const scopeHtml = scopeLabel && scopeOrganizations.length ? `<p class="guidance-context">${scopeLabel}: ${scopeOrganizations.map(esc).join(", ")}</p>` : "";
    const questions = Array.isArray(guidance.questions) ? guidance.questions : [];
    const deadlines = Array.isArray(guidance.deadlines) ? guidance.deadlines : [];
    const forms = Array.isArray(guidance.forms) ? guidance.forms : [];
    const evidence = guidance.manual?.evidence;
    const legalEvidence = result.knowledge?.evidence;
    const hasInstitutionRuleEvidence = guidance.topic === "institution" && Array.isArray(legalEvidence) && legalEvidence.some(item => item?.reference_kind === "institution_rule");
    const legalRefs = new Set(Array.isArray(legalEvidence) ? legalEvidence.map((item, index) => index + 1) : []);
    const deadlineHtml = `<section><h3>기한</h3>${deadlines.length ? `<ul>${deadlines.map(item => `<li>${esc(item?.text)}${Number.isSafeInteger(item?.ref) && legalRefs.has(item.ref) ? ` <button type="button" class="guidance-ref" data-guidance-evidence="${item.ref}">[근거 ${item.ref}]</button>` : ""}</li>`).join("")}</ul>` : `<p class="guidance-note">${hasInstitutionRuleEvidence ? "기관 자료의 기한은 위 원문 발췌와 적용 조건에서 확인하세요. 별도 기한 판정은 제공하지 않습니다." : "질문에 적용할 정확한 기한을 확인할 등록 근거가 부족해요. 아래 원문과 적용 조건을 확인해 주세요."}</p>`}</section>`;
    const formHtml = forms.length ? forms.map(form => {
      const href = localFormHref(form);
      const managed = form?.kind === "서식" && form?.reference_kind === "institution_rule" && href.match(/^\/api\/institution-rules\/([a-f0-9]{32})\/versions\/([a-f0-9]{32})\/original$/);
      const label = `${form?.name || "서식 보기"}${managed ? ` · 서식 · v${Number.isSafeInteger(form.version_number) ? form.version_number : "?"}` : ""}`;
      const managerHref = managed ? `index.html?rule=${managed[1]}&rule_version=${managed[2]}#docs` : "";
      return `<li>${href ? `<a href="${esc(href)}"${managed ? ' target="_blank" rel="noopener noreferrer"' : ""}>${esc(label)}</a>${managerHref ? ` · <a href="${esc(managerHref)}">관리</a>` : ""}` : esc(form?.name || "서식 이름 미확인")}${form?.synthetic === true ? " <span class=\"guidance-note\">합성·예시 서식 · 기관 현행 양식 확인</span>" : ""}</li>`;
    }).join("") : `<li>관련 서식이 연결되지 않았습니다. <a href="index.html#forms">등록 서식 확인</a></li>`;
    const map = guidance.map && typeof guidance.map === "object" ? guidance.map : null;
    const mapNodes = Array.isArray(map?.nodes) ? map.nodes : [];
    const serviceGuide = guidance.service_guide && typeof guidance.service_guide === "object" ? guidance.service_guide : null;
    const serviceEvidence = Array.isArray(serviceGuide?.evidence) ? serviceGuide.evidence : [];
    const serviceGuideHtml = serviceEvidence.length ? `<details class="guidance-details"><summary>인사혁신처 제도 안내·FAQ</summary>${serviceGuide.notice ? `<p>${esc(serviceGuide.notice)}</p>` : ""}<p class="guidance-note">국가공무원 제도 설명·FAQ입니다. 실제 적용과 최신 일수는 법령·기관 기준으로 확인하세요.</p><ul>${serviceEvidence.map(item => {
      if (!item || typeof item !== "object") return "";
      const officialHref = ["official_service_guide", "official_faq"].includes(item.reference_kind) ? officialServiceUrl(item.source_url) : "";
      const snapshotHref = serviceSnapshotHref(item.snapshot_url);
      return `<li><strong>${esc(item.title || "인사혁신처 자료")}</strong> · ${item.reference_kind === "official_faq" ? "FAQ" : "제도 안내"}${item.loc ? ` · ${esc(item.loc)}` : ""}${item.retrieved_at ? ` · 확인일 ${esc(item.retrieved_at)}` : ""}<blockquote>${esc(item.quote)}</blockquote>${officialHref ? ` <a href="${esc(officialHref)}" target="_blank" rel="noopener noreferrer">인사혁신처 원문</a>` : ""}${snapshotHref ? ` · <a href="${esc(snapshotHref)}">저장된 원문 텍스트</a>` : ""}</li>`;
    }).join("")}</ul>${serviceGuide.coverage && typeof serviceGuide.coverage === "object" ? `<p class="guidance-note">안내 페이지 ${esc(serviceGuide.coverage.guide_pages ?? 0)}개 · FAQ 질문 ${esc(serviceGuide.coverage.faq_questions ?? 0)}개 확인</p>` : ""}</details>` : "";
    const practice = Array.isArray(guidance.practice) ? guidance.practice : [];
    const practiceHtml = practice.length ? `<details class="guidance-details" open><summary>실무 기준 · 인사혁신처 예규</summary><p class="guidance-note">법령 조문 아래의 실무 운영 기준입니다. 소속 기관의 별도 기준을 함께 확인하세요.</p><ul>${practice.map(item => {
      if (!item || typeof item !== "object") return "";
      const official = item.official && typeof item.official === "object" ? item.official : {};
      return `<li><strong>${esc(official.title || item.title || "인사혁신처 예규")}</strong>${official.publication ? ` · ${esc(official.publication)}` : ""}${item.loc ? ` · ${esc(item.loc)}` : ""}<blockquote>${esc(item.quote || item.text || "")}</blockquote></li>`;
    }).join("")}</ul></details>` : "";
    section.innerHTML = `<h2>${esc(guidance.title || "업무 안내")}</h2>${guidance.context ? `<p class="guidance-context">${esc(guidance.context)}</p>` : ""}${scopeHtml}
      <section><h3>먼저 준비할 내용</h3>${hasInstitutionRuleEvidence ? `<ol><li><strong>적용 자료 확인</strong> 기관 자료가 현재 적용된 상태인지 확인하세요.</li><li><strong>적용 버전 확인</strong> 답변에 적용된 버전과 인용된 원문 발췌를 대조하세요.</li><li><strong>적용 조건 확인</strong> 기관, 대상, 상황 등 원문에 적힌 적용 조건을 확인하세요.</li></ol>` : steps.length ? `<ol>${steps.map(step => `<li><strong>${esc(step?.title || "준비 항목")}</strong>${step?.detail ? ` — ${esc(step.detail)}` : ""}</li>`).join("")}</ol>` : `<p class="guidance-note">등록된 처리 순서가 없습니다. 아래 근거 자료를 확인해 주세요.</p>`}</section>
      ${questions.length ? `<section><h3>추가로 확인할 사항</h3><ul>${questions.map(question => `<li>${esc(question)}</li>`).join("")}</ul></section>` : ""}${deadlineHtml}
      <section><h3>관련 서식</h3><ul>${formHtml}</ul></section>
      ${guidance.notice ? `<p class="guidance-note">${esc(guidance.notice)}</p>` : ""}${practiceHtml}${serviceGuideHtml}${guidance.ai_requested && !guidance.ai_used ? `<p class="guidance-note" role="status">로컬 AI 보조를 요청했지만 사용하지 못했습니다. 등록 자료를 바탕으로 안내합니다.</p>` : ""}
      <details class="guidance-details"><summary>e-사람 사용법 · 원문과 쪽수</summary>${guidance.manual?.notice ? `<p>${esc(guidance.manual.notice)}</p>` : ""}${guidance.manual?.scope ? `<p>${esc(guidance.manual.scope)}</p>` : ""}${typeof window.knowledgeAnswerHtml === "function" ? window.knowledgeAnswerHtml({ evidence, scope: guidance.manual?.scope }) || `<p class="guidance-note">연결된 매뉴얼 근거가 없습니다. <a href="folders.html">자료함에서 등록 자료 확인</a></p>` : `<p class="guidance-note">매뉴얼 근거를 표시할 수 없습니다. <a href="folders.html">자료함에서 등록 자료 확인</a></p>`}</details>
      ${map ? `<details class="guidance-details"><summary>자료 연결 확인</summary><p>안내 자료 ${mapNodes.length}개 · 연결 ${Array.isArray(map.edges) ? map.edges.length : 0}개</p><p class="guidance-note">${esc(map.note || "자료 사이의 연결 정보입니다.")}</p><ul>${mapNodes.map(node => `<li>${esc(node?.label || node?.title || node?.id || "자료")}${node?.kind ? ` · ${esc(node.kind)}` : ""}${node?.loc ? ` · ${esc(node.loc)}` : ""}${node?.page ? ` · ${esc(node.page)}쪽` : ""}${node?.sha256 ? ` · SHA-256 ${esc(node.sha256)}` : ""}</li>`).join("")}</ul></details>` : ""}`;
    const anchor = box.querySelector(".bot-hd");
    if (anchor) anchor.after(section); else box.prepend(section);
    section.querySelectorAll("[data-guidance-evidence]").forEach(button => button.addEventListener("click", () => {
      const scope = box.closest('.bubble') || box;
      const target = scope.querySelector(`.answer-original .ref[data-evidence-index="${CSS.escape(button.dataset.guidanceEvidence)}"]`);
      if (!target) return;
      let parent = target.parentElement;
      while (parent && parent !== scope) { if (parent.tagName === "DETAILS") parent.open = true; parent = parent.parentElement; }
      target.open = true; target.scrollIntoView({ block: "center", behavior: "smooth" });
    }));
  }
  return { render };
})();
