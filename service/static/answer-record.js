"use strict";
(() => {
  const allowedModes = new Set(["source_llm", "source_search", "source_unavailable", "source_clarification", "structured_guidance"]);
  const text = (value) => value == null ? "" : String(value);
  const line = (label, value) => value == null || value === "" ? [] : [`${label}: ${text(value)}`];
  const list = (value) => Array.isArray(value) ? value : [];
  const recordText = (response, today) => {
    const knowledge = response.knowledge && typeof response.knowledge === "object" ? response.knowledge : {};
    const evidence = list(knowledge.evidence);
    const tree = knowledge.tree && typeof knowledge.tree === "object" ? knowledge.tree : null;
    const out = ["서무비서 답변 확인 기록", `표시시각 (Asia/Seoul): ${new Intl.DateTimeFormat("ko-KR", { timeZone: "Asia/Seoul", dateStyle: "full", timeStyle: "medium", hour12: false }).format(new Date())}`];
    out.push(...line("안내 기준일", today), "", "질문 원문", text(response.query), "", "응답 방식", ({ source_llm: "원문 + 로컬 AI 구절 선택", source_search: "등록 원문만", source_unavailable: "자료 부족", source_clarification: "추가 상황 필요", structured_guidance: "등록 자료 기반 구조화 안내" })[response.mode]);
    if (response.model != null) out.push(...line("모델", response.model));
    if (response.profile != null) out.push(...line("프로필", response.profile));
    out.push("", "요약", text(response.summary));
    const pay = response.pay_calculation && typeof response.pay_calculation === "object" ? response.pay_calculation : null;
    if (pay) {
      out.push("", text(pay.title));
      list(pay.lines).forEach((l) => { if (l && typeof l === "object") out.push(`- ${text(l.label)}: ${Number(l.amount).toLocaleString("ko-KR")}원 (${text(l.formula)})`); });
      if (list(pay.needs).length) out.push(`계산에 필요한 정보: ${list(pay.needs).map(text).join(", ")}`);
      list(pay.notes).forEach((n) => out.push(text(n)));
      list(pay.sources).forEach((s) => { if (s && typeof s === "object") out.push(`계산 근거: ${text(s.law)} ${text(s.title)} (개정 ${text(s.revised)}) ${text(s.source_url)} SHA-256 ${text(s.sha256)}`); });
      out.push(text(pay.scope));
    }
    const guidance = response.guidance && typeof response.guidance === "object" ? response.guidance : null;
    if (guidance) {
      out.push("", "실무 준비 안내", ...line("제목", guidance.title), ...line("상황", guidance.context));
      list(guidance.steps).forEach((step) => {
        if (!step || typeof step !== "object") return;
        out.push(`- ${text(step.title)}${step.detail ? `: ${text(step.detail)}` : ""}`);
      });
      list(guidance.questions).forEach((question) => out.push(`확인 질문: ${text(question)}`));
      list(guidance.deadlines).forEach((deadline) => {
        if (!deadline || typeof deadline !== "object") return;
        const ref = Number.isInteger(deadline.ref) && deadline.ref > 0 ? ` [법령 근거 ${deadline.ref}]` : "";
        out.push(`기한 안내: ${text(deadline.text)}${ref}`);
      });
      list(guidance.forms).forEach((form) => {
        if (!form || typeof form !== "object") return;
        out.push(`서식: ${text(form.name)}${form.href ? ` (${text(form.href)})` : ""}${form.synthetic ? " · 합성·예시 서식, 기관 현행 양식 확인" : ""}`);
      });
      out.push(...line("실무 안내 범위", guidance.notice));
    }
    if (tree) {
      out.push("", "한눈에 보기", ...line("제목", tree.title));
      list(tree.branches).forEach((branch) => {
        if (!branch || typeof branch !== "object") return;
        out.push(...line("분기", branch.label));
        list(branch.items).forEach((item) => {
          if (!item || typeof item !== "object") return;
          const ref = Number.isInteger(item.ref) && item.ref > 0 && item.ref <= evidence.length ? ` [근거 ${item.ref}]` : "";
          out.push(`- ${text(item.text)}${ref}`);
        });
      });
      out.push(...line("참고", tree.note));
    }
    out.push("", "답변 원문", text(response.answer), ...line("안내", response.notice));
    if (evidence.length) out.push("", "출처 및 인용 원문");
    evidence.forEach((entry, i) => {
      if (!entry || typeof entry !== "object") return;
      out.push(` [근거 ${i + 1}]`, ...line("제목", entry.title), ...line("종류", entry.kind), ...line("기관", entry.institution), ...line("시행일", entry.effective_date), ...line("위치", entry.loc), ...line("자료 ID", entry.source_id ?? entry.id), ...line("SHA-256", entry.sha256));
      const official = entry.official && typeof entry.official === "object" ? entry.official : {};
      ["source_url", "download_url", "issuer", "publication", "retrieved_at", "scope"].forEach((key) => out.push(...line(key, official[key])));
      out.push("인용 원문:", text(entry.quote));
      if (entry.model_selected_quote != null) out.push("AI 선택 구절 (참고):", text(entry.model_selected_quote));
    });
    const manualEvidence = list(guidance?.manual?.evidence);
    if (manualEvidence.length) {
      out.push("", "e-사람 사용법 · 등록 매뉴얼 원문 (화면 조작 안내, 법령 근거와 별도)");
      manualEvidence.forEach((entry) => {
        if (!entry || typeof entry !== "object") return;
        out.push(...line("제목", entry.title), ...line("PDF 쪽수", entry.page), ...line("자료 ID", entry.source_id ?? entry.id), ...line("SHA-256", entry.sha256), "인용 원문:", text(entry.quote), "");
      });
    } else if (guidance?.manual?.notice) out.push("", "e-사람 사용법", text(guidance.manual.notice));
    const serviceGuide = guidance?.service_guide && typeof guidance.service_guide === "object" ? guidance.service_guide : null;
    const serviceEvidence = list(serviceGuide?.evidence);
    if (serviceEvidence.length) {
      out.push("", "인사혁신처 제도 안내·FAQ · 법령 근거 및 e-사람 매뉴얼과 별도", ...line("안내", serviceGuide.notice), "국가공무원 제도 설명·FAQ입니다. 실제 적용과 최신 일수는 법령·기관 기준으로 확인하세요.");
      serviceEvidence.forEach((entry) => {
        if (!entry || typeof entry !== "object") return;
        out.push(...line("제목", entry.title), ...line("종류", entry.reference_kind === "official_faq" ? "FAQ" : "제도 안내"), ...line("위치", entry.loc), ...line("인사혁신처 원문", entry.source_url), ...line("저장된 원문 텍스트", entry.snapshot_url), ...line("확인일", entry.retrieved_at), ...line("SHA-256", entry.sha256), "인용 원문:", text(entry.quote), "");
      });
    }
    const experiences = list(knowledge.experiences).filter((x) => x && typeof x === "object");
    if (experiences.length) {
      out.push("", "처리 경험 · 공식 근거 아님");
      experiences.forEach((x) => out.push(...line("상황", x.situation), ...line("처리", x.handling), ...line("주의점", x.caution), ""));
    }
    const excluded = list(knowledge.excluded).filter((x) => x && typeof x === "object");
    if (excluded.length) { out.push("", "답변 근거에서 제외한 자료"); excluded.forEach((x) => out.push(...line("제목", x.title), ...line("사유", x.reason))); }
    out.push("", "답변 당시의 확인 기록입니다. 원문의 현재 유효성이나 기관 승인을 뜻하지 않습니다.");
    return out.join("\n");
  };
  const filenameTime = () => new Intl.DateTimeFormat("sv-SE", { timeZone: "Asia/Seoul", year: "numeric", month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit", second: "2-digit", hour12: false }).format(new Date()).replace(/[-: ]/g, "");
  const attach = (box, response, options = {}) => {
    if (!box || !response || !allowedModes.has(response.mode)) return;
    const existing = box.querySelector(":scope > .answer-record-actions");
    if (existing) return;
    let snapshot;
    try { snapshot = recordText(response, options.today); } catch (_) { return; }
    const actions = document.createElement("div");
    actions.className = "answer-record-actions";
    const help = document.createElement("span"); help.textContent = "질문·요약·원문·출처를 TXT나 한글(HWPX)로 보관합니다.";
    const status = document.createElement("span"); status.className = "answer-record-status"; status.setAttribute("role", "status"); status.setAttribute("aria-live", "polite");
    const button = document.createElement("button"); button.type = "button"; button.className = "secondary answer-record-button"; button.textContent = "답변 기록 저장";
    button.addEventListener("click", () => {
      let url;
      let anchor;
      try {
        const blob = new Blob(["\uFEFF", snapshot], { type: "text/plain;charset=utf-8" });
        url = URL.createObjectURL(blob);
        anchor = document.createElement("a"); anchor.href = url; anchor.download = `seomu-answer-${filenameTime()}.txt`; anchor.style.display = "none";
        document.body.appendChild(anchor); anchor.click();
        status.textContent = "파일 저장 요청을 보냈습니다. 브라우저 다운로드를 확인하세요.";
      } catch (_) { status.textContent = "파일을 저장하지 못했습니다. 브라우저 다운로드 설정을 확인하세요."; }
      finally {
        anchor?.remove();
        if (url) window.setTimeout(() => URL.revokeObjectURL(url), 1000);
      }
    });
    // The same record as a 한글 document; the server builds the HWPX file.
    const hwpx = document.createElement("button"); hwpx.type = "button"; hwpx.className = "secondary answer-record-hwpx"; hwpx.textContent = "한글로 저장";
    hwpx.addEventListener("click", async () => {
      let url;
      let anchor;
      const filename = `seomu-answer-${filenameTime()}.hwpx`;
      hwpx.disabled = true; status.textContent = "한글 문서를 만들고 있습니다…";
      try {
        const res = await fetch("/api/exports/hwpx", { method: "POST", headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ title: `서무비서 답변 · ${text(response.query).slice(0, 60) || "질문"}`, text: snapshot, filename }) });
        if (!res.ok) throw new Error(String(res.status));
        url = URL.createObjectURL(await res.blob());
        anchor = document.createElement("a"); anchor.href = url; anchor.download = filename; anchor.style.display = "none";
        document.body.appendChild(anchor); anchor.click();
        status.textContent = "한글 파일 저장 요청을 보냈습니다. 브라우저 다운로드를 확인하세요.";
      } catch (_) { status.textContent = "한글 파일을 만들지 못했습니다. 잠시 후 다시 시도하거나 TXT로 저장하세요."; }
      finally {
        hwpx.disabled = false;
        anchor?.remove();
        if (url) window.setTimeout(() => URL.revokeObjectURL(url), 1000);
      }
    });
    actions.append(help, button, hwpx, status);
    box.appendChild(actions);
  };
  window.SeomuAnswerRecord = Object.freeze({ attach });
})();
