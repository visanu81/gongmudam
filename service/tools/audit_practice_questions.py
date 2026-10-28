"""Run a structural, offline audit of representative practice questions."""
from __future__ import annotations

import argparse
import csv
import html
import json
import re
import sys
import time
import urllib.error
import urllib.request
from datetime import date
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CASES = ROOT / "reference_data" / "practice_questions_100.json"
DEFAULT_TODAY = "2026-10-26"
VERDICTS = {"answer": "근거 연결 확인", "clarify": "추가 질문 필요",
            "institution": "기관 자료 필요", "missing": "자료 보강 필요"}


def _text(value: Any) -> str:
    return value if isinstance(value, str) else ""


def _answer_text(result: dict[str, Any]) -> str:
    parts = [_text(result.get("answer"))]
    knowledge = result.get("knowledge") if isinstance(result.get("knowledge"), dict) else {}
    parts.append(_text(knowledge.get("answer")))
    parts.append(_text(knowledge.get("notice")))
    parts.append(_text(result.get("notice")))
    tree = knowledge.get("tree") if isinstance(knowledge.get("tree"), dict) else {}
    for branch in tree.get("branches", []) if isinstance(tree.get("branches"), list) else []:
        if isinstance(branch, dict):
            for item in branch.get("items", []) if isinstance(branch.get("items"), list) else []:
                if isinstance(item, dict): parts.append(_text(item.get("text")))
    guide = result.get("guidance") if isinstance(result.get("guidance"), dict) else {}
    for question in guide.get("questions", []) if isinstance(guide.get("questions"), list) else []:
        parts.append(_text(question))
    manual = guide.get("manual") if isinstance(guide.get("manual"), dict) else {}
    parts.append(_text(manual.get("answer")))
    parts.extend((_text(manual.get("notice")), _text(manual.get("scope"))))
    for entry in manual.get("evidence", []) if isinstance(manual.get("evidence"), list) else []:
        if isinstance(entry, dict): parts.extend((_text(entry.get("quote")), _text(entry.get("text"))))
    return "\n".join(parts)


def _all_evidence(result: dict[str, Any]) -> list[tuple[str, dict[str, Any]]]:
    out: list[tuple[str, dict[str, Any]]] = []
    seen: set[tuple[str, str, str]] = set()
    knowledge = result.get("knowledge") if isinstance(result.get("knowledge"), dict) else {}
    guide = result.get("guidance") if isinstance(result.get("guidance"), dict) else {}
    manual = guide.get("manual") if isinstance(guide.get("manual"), dict) else {}
    service = guide.get("service_guide") if isinstance(guide.get("service_guide"), dict) else {}
    for channel, rows in (("knowledge", knowledge.get("evidence")), ("manual", manual.get("evidence")),
                          ("service_guide", service.get("evidence"))):
        for entry in rows if isinstance(rows, list) else []:
            if not isinstance(entry, dict): continue
            key = (channel, str(entry.get("source_id") or entry.get("id") or ""),
                   str(entry.get("loc") or entry.get("page") or ""))
            if key in seen: continue
            seen.add(key); out.append((channel, entry))
    return out


def _groups_match(groups: Any, candidates: list[str]) -> tuple[bool, list[str]]:
    failures = []
    if not isinstance(groups, list): return False, ["require_source_groups must be a list"]
    for i, group in enumerate(groups):
        if not isinstance(group, list) or not group or not all(isinstance(p, str) for p in group):
            failures.append(f"source group {i + 1} is invalid"); continue
        if not any(re.search(pattern, candidate, re.I) for pattern in group for candidate in candidates):
            failures.append(f"required source group {i + 1} did not match")
    return not failures, failures


def _citation_valid(entry: dict[str, Any], registry: dict[str, dict[str, Any]]) -> tuple[bool, str]:
    sid, sha = entry.get("source_id") or entry.get("id"), entry.get("sha256")
    source = registry.get(str(sid))
    if not source or not source.get("enabled") or not source.get("current") or source.get("sha256") != sha:
        return False, "citation source is absent, disabled, stale, or has a mismatched hash"
    quote = entry.get("quote") or entry.get("text")
    if not isinstance(quote, str) or not quote.strip(): return False, "citation has no quote text"
    units = source.get("units") if isinstance(source.get("units"), list) else []
    selected = [unit for unit in units if isinstance(unit, dict)]
    loc = _text(entry.get("loc"))
    span = re.search(r"(\d+)\s*[~\-–]\s*(\d+)\s*행", loc)
    if span:
        start, end = map(int, span.groups())
        located = [unit for unit in selected if (m := re.search(r"^\s*(\d+)\s*행\s*$", _text(unit.get("loc"))))
                   and start <= int(m.group(1)) <= end]
        if located: selected = located
    else:
        exact_loc = [unit for unit in selected if _text(unit.get("loc")) and _text(unit.get("loc")) == loc]
        if exact_loc: selected = exact_loc
    # Legal retrieval can combine adjacent source units into one displayed
    # excerpt. Preserve their registered order and separators when validating.
    joined = "\n".join(_text(unit.get("text")) for unit in selected)
    texts = [_text(unit.get("text")) for unit in selected]
    if any(quote in text for text in texts): return True, ""
    if quote in joined: return True, "contiguous registered units match"
    compact = lambda value: re.sub(r"\s+", "", value)
    if compact(quote) in compact(joined): return True, "whitespace-normalized match across registered units"
    return False, "citation quote is not present in registered source text"


def evaluate_case(case: Any, result: Any, registered_sources: list[dict[str, Any]]) -> dict[str, Any]:
    failures: list[str] = []
    if not isinstance(case, dict) or not isinstance(result, dict):
        return {"verdict": "답변 점검 필요", "failures": ["case or response is not an object"], "checks": {}}
    expected = case.get("expected")
    if expected not in VERDICTS: failures.append("unknown expected outcome")
    registry = {str(s.get("id")): s for s in registered_sources if isinstance(s, dict) and s.get("id")}
    evidence = result.get("knowledge", {}).get("evidence", []) if isinstance(result.get("knowledge"), dict) else []
    evidence = evidence if isinstance(evidence, list) else []
    combined = _all_evidence(result)
    legal = [(channel, e) for channel, e in combined if channel == "knowledge"]
    manual = [(channel, e) for channel, e in combined if channel == "manual"]
    source_evidence = manual if case.get("evidence_channel") == "manual" else legal
    candidates = [" ".join(str(e.get(k) or "") for k in ("title", "loc", "source_id", "id")) for _, e in source_evidence]
    text = _answer_text(result)
    term_groups = case.get("answer_terms_groups", [])
    term_failures = []
    if not isinstance(term_groups, list): term_failures.append("answer_terms_groups must be a list")
    else:
        for i, group in enumerate(term_groups):
            if not isinstance(group, list) or not group or not all(isinstance(t, str) for t in group):
                term_failures.append(f"answer term group {i + 1} is invalid")
            elif not any(re.sub(r"\s+", "", term) in re.sub(r"\s+", "", text) for term in group):
                term_failures.append(f"required answer term group {i + 1} missing")
    citation_checks = []
    for channel, entry in combined:
        if channel == "service_guide":
            citation_checks.append({"channel": channel, "checked": False, "reason": "service guide catalog reference; source text validation unavailable"})
            continue
        ok, why = _citation_valid(entry, registry)
        citation_checks.append({"channel": channel, "checked": True, "passed": ok, "reason": why})
        if not ok: failures.append(f"invalid {channel} citation: {why}")

    knowledge = result.get("knowledge") if isinstance(result.get("knowledge"), dict) else {}
    if result.get("model") is not None or knowledge.get("model") is not None or result.get("mode") == "source_llm" or knowledge.get("mode") == "source_llm":
        failures.append("AI/model metadata present in no-AI audit response")

    if expected == "answer":
        if not source_evidence: failures.append("answer requires evidence in its designated channel")
        if not case.get("require_source_groups"): failures.append("answer requires nonempty require_source_groups")
        _, group_failures = _groups_match(case.get("require_source_groups"), candidates)
        failures.extend(group_failures); failures.extend(term_failures)
    elif expected == "clarify":
        guidance = result.get("guidance") if isinstance(result.get("guidance"), dict) else {}
        questions = guidance.get("questions") if isinstance(guidance.get("questions"), list) else []
        explicit = bool(questions) or result.get("mode") == "source_clarification"
        if not explicit: failures.append("no explicit follow-up question or source clarification")
        if legal: failures.append("clarify outcome returned primary legal evidence")
        if result.get("mode") == "source_clarification" and not evidence and not _text(result.get("answer")).strip():
            pass  # Empty answer with this mode is the conservative clarification classification.
        elif not questions: failures.append("clarification lacks a follow-up question")
    elif expected in {"institution", "missing"}:
        wording = (r"소속.{0,30}(확인|알려)|기관.{0,30}(확인|기준|자료|필요|등록|추가|알려)|적용.{0,15}(기관|신분)"
                   if expected == "institution" else
                   r"등록.{0,15}(자료|근거)|추가.{0,15}(자료|근거)|직접 근거.{0,15}(못|없)|확인하지 못|찾지 못")
        if legal or (case.get("evidence_channel") == "manual" and manual):
            failures.append("insufficiency outcome returned evidence in the designated channel")
        if not re.search(wording, text): failures.append("no explicit institution/material insufficiency wording")
        if not text.strip(): failures.append("insufficiency response is empty")
        if case.get("answer_terms_groups") and not term_failures: failures.append("insufficiency response unexpectedly matches all answer terms")

    forbidden = case.get("forbidden_sources", [])
    if isinstance(forbidden, list):
        for pat in forbidden:
            if not isinstance(pat, str): failures.append("forbidden_sources contains a non-string pattern")
            elif any(re.search(pat, candidate, re.I) for candidate in candidates): failures.append(f"forbidden source matched: {pat}")
    else: failures.append("forbidden_sources must be a list")
    verdict = VERDICTS.get(expected, "답변 점검 필요") if not failures else "답변 점검 필요"
    return {"verdict": verdict, "failures": failures, "checks": {"knowledge_evidence_count": len(evidence),
            "source_group_candidates": candidates, "answer_terms_failures": term_failures,
            "citations": citation_checks, "actual_mode": result.get("mode"),
            "requested_ai": False, "actual_model": result.get("model")}}


def _validate_cases(cases: Any) -> list[dict[str, Any]]:
    if not isinstance(cases, list) or len(cases) != 100: raise ValueError("cases JSON must contain exactly 100 cases")
    required = {"id", "category", "question", "expected", "require_source_groups", "answer_terms_groups"}
    identifiers = set()
    for i, case in enumerate(cases):
        if not isinstance(case, dict) or not required.issubset(case): raise ValueError(f"case {i + 1} missing required fields")
        if case["expected"] not in VERDICTS: raise ValueError(f"case {i + 1} has invalid expected")
        if not isinstance(case["question"], str) or not case["question"].strip(): raise ValueError(f"case {i + 1} has empty question")
        if not isinstance(case["id"], str) or case["id"] in identifiers: raise ValueError(f"case {i + 1} has duplicate or invalid id")
        identifiers.add(case["id"])
    return cases


def _fetch_json(base_url: str, path: str) -> Any:
    with urllib.request.urlopen(base_url.rstrip("/") + path, timeout=30) as response:
        return json.loads(response.read().decode("utf-8"))


def _compare_live_catalog(local_sources: list[dict[str, Any]], catalog: Any) -> None:
    if not isinstance(catalog, list): raise ValueError("live source catalog must be a list")
    local = {str(row.get("id")): row for row in local_sources if isinstance(row, dict) and row.get("id")}
    remote = {str(row.get("id")): row for row in catalog if isinstance(row, dict) and row.get("id")}
    problems = []
    for sid in sorted(set(local) | set(remote)):
        if sid not in local: problems.append(f"live source missing from local registry: {sid}"); continue
        if sid not in remote: problems.append(f"local source missing from live catalog: {sid}"); continue
        for field in ("sha256", "enabled", "current"):
            if field not in remote[sid]:
                problems.append(f"live catalog missing {field}: {sid}")
            elif local[sid].get(field) != remote[sid].get(field):
                problems.append(f"live/local {field} mismatch: {sid}")
    if problems: raise RuntimeError("live source catalog differs from local hydrated registry: " + "; ".join(problems[:20]))


def run_cases(cases: list[dict[str, Any]], base_url: str, today: str, in_process: bool = False) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    if str(ROOT) not in sys.path: sys.path.insert(0, str(ROOT))
    from app import knowledge
    # The local API catalog may omit source units; validate exact quotes against
    # the installed registry and its current source files in both run modes.
    registered = knowledge.sources()
    if in_process:
        from app import llm, main
    else:
        parts = urlsplit(base_url)
        if parts.scheme not in {"http", "https"} or parts.hostname not in {"localhost", "127.0.0.1", "::1"}:
            raise ValueError("base URL must point to localhost/loopback")
        live_catalog = _fetch_json(base_url, "/api/knowledge/sources")
        _compare_live_catalog(registered, live_catalog)
    registry = [s for s in registered if isinstance(s, dict) and s.get("enabled") and s.get("current")]
    results = []
    for case in cases:
        start = time.monotonic()
        request = {"query": case["question"], "guidance": True, "use_ai": False, "today": today}
        try:
            if in_process:
                with __import__("unittest.mock", fromlist=["patch"]).patch.object(llm, "get_provider", side_effect=AssertionError("AI provider must not be called")):
                    reply = main.api_ask(request)
            else:
                data = json.dumps(request, ensure_ascii=False).encode("utf-8")
                req = urllib.request.Request(base_url.rstrip("/") + "/api/ask", data=data, headers={"Content-Type": "application/json"})
                with urllib.request.urlopen(req, timeout=60) as response: reply = json.loads(response.read().decode("utf-8"))
            check = evaluate_case(case, reply, registry)
        except Exception as exc:
            reply = None; check = {"verdict": "답변 점검 필요", "failures": [f"{type(exc).__name__}: {exc}"], "checks": {}}
        results.append({"id": case["id"], "category": case["category"], "question": case["question"],
                        "expected": case["expected"], "verdict": check["verdict"], "failures": check["failures"],
                        "checks": check["checks"], "response": reply, "elapsed_seconds": round(time.monotonic()-start, 3),
                        "requested_ai": False, "actual_model": reply.get("model") if isinstance(reply, dict) else None,
                        "source_titles": [e.get("title", "") for _, e in _all_evidence(reply)] if isinstance(reply, dict) else []})
    return results, registry


def write_reports(results: list[dict[str, Any]], output: Path) -> dict[str, Any]:
    output.mkdir(parents=True, exist_ok=True)
    counts = {label: sum(r["verdict"] == label for r in results) for label in (*VERDICTS.values(), "답변 점검 필요")}
    report = {"scope": "자동 구조 점검이며 법적 정답을 보증하지 않습니다. 실제 사용자 조사는 수행하지 않았습니다.",
              "total": len(results), "counts": counts,
              "service_guide_citations_unchecked": sum(1 for row in results for cite in row.get("checks", {}).get("citations", [])
                                                         if not cite.get("checked")), "cases": results}
    (output / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    with (output / "report.csv").open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=["category", "id", "question", "expected", "verdict", "failures", "source_titles"], extrasaction="ignore")
        writer.writeheader()
        for r in results: writer.writerow({**r, "failures": "; ".join(r["failures"]), "source_titles": "; ".join(r["source_titles"])})
    def detail(row: dict[str, Any]) -> str:
        response = row.get("response") if isinstance(row.get("response"), dict) else {}
        guide = response.get("guidance") if isinstance(response.get("guidance"), dict) else {}
        manual = guide.get("manual") if isinstance(guide.get("manual"), dict) else {}
        text_blocks = [("답변", _text(response.get("answer"))), ("안내", _text(response.get("notice"))),
                       ("매뉴얼 안내", "\n".join(v for v in (_text(manual.get("notice")), _text(manual.get("scope"))) if v))]
        text_html = "".join(f"<h4>{html.escape(label)}</h4><pre>{html.escape(value)}</pre>" for label, value in text_blocks if value)
        cite_html = []
        for channel, evidence in _all_evidence(response):
            if channel == "service_guide": continue
            official = evidence.get("official") if isinstance(evidence.get("official"), dict) else {}
            fields = [("채널", channel), ("출처", _text(evidence.get("title"))),
                      ("위치", _text(evidence.get("loc") or evidence.get("page"))),
                      ("SHA-256", _text(evidence.get("sha256"))),
                      ("원문 인용", _text(evidence.get("quote") or evidence.get("text"))),
                      ("공식 URL", _text(official.get("source_url")))]
            cite_html.append("<article>" + "".join(f"<h4>{html.escape(label)}</h4><pre>{html.escape(value)}</pre>" for label, value in fields if value) + "</article>")
        citation_html = "<h3>근거 인용</h3>" + ("".join(cite_html) if cite_html else "<p>인용된 1차 자료·매뉴얼이 없습니다.</p>")
        return "<details><summary>답변·근거 보기</summary>" + text_html + citation_html + "</details>"

    rows = "".join("<tr data-category=\"{}\"><td>{}</td><td>{}</td><td>{}</td><td>{}</td><td>{}</td><td>{}</td><td>{}</td><td>{}</td></tr>".format(
        html.escape(str(r["category"]), quote=True), html.escape(str(r["category"])), html.escape(str(r["id"])),
        html.escape(str(r["question"])), html.escape(str(r["expected"])), html.escape(str(r["verdict"])), html.escape("; ".join(r["failures"])),
        html.escape("; ".join(r["source_titles"])), detail(r)) for r in results)
    count_rows = "".join(f"<li>{html.escape(label)}: {count}</li>" for label, count in counts.items())
    page = """<!doctype html><meta charset=utf-8><title>실무 질문 자동 점검</title><style>body{font:15px system-ui,sans-serif;margin:2rem;color:#202b32}h1{color:#194a51}table{border-collapse:collapse;width:100%;margin-top:1rem}th,td{padding:.55rem;border:1px solid #cbd5d8;text-align:left;vertical-align:top}th{background:#edf3f3;position:sticky;top:0}td:nth-child(3){min-width:20rem}tr:nth-child(even){background:#f7f9f9}select{padding:.4rem}details{min-width:16rem}pre{white-space:pre-wrap;overflow-wrap:anywhere;background:#f3f6f6;padding:.6rem}article{border-top:1px solid #cbd5d8;padding:.5rem}</style><h1>실무 질문 자동 점검</h1><p>자동 구조 점검이며 법적 정답을 보증하지 않습니다. 실제 사용자 조사는 수행하지 않았습니다.</p><h2>판정 건수</h2><ul>""" + count_rows + """</ul><label>분류 필터 <select id=f><option value=''>전체</option></select></label><table><thead><tr><th>분류</th><th>ID</th><th>질문</th><th>기대</th><th>판정</th><th>실패 사유</th><th>출처</th><th>세부 보기</th></tr></thead><tbody>""" + rows + """</tbody></table><script>const s=document.querySelector('#f'), rows=[...document.querySelectorAll('tbody tr')];[...new Set(rows.map(r=>r.dataset.category))].sort().forEach(x=>{let o=document.createElement('option');o.value=x;o.textContent=x;s.append(o)});s.onchange=()=>rows.forEach(r=>r.hidden=!!s.value&&r.dataset.category!==s.value)</script>"""
    (output / "report.html").write_text(page, encoding="utf-8")
    return report


def main_cli(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cases", type=Path, default=DEFAULT_CASES)
    parser.add_argument("--base-url", default="http://127.0.0.1:8787")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--today", default=DEFAULT_TODAY)
    parser.add_argument("--in-process", action="store_true")
    args = parser.parse_args(argv)
    try:
        date.fromisoformat(args.today)
        cases = _validate_cases(json.loads(args.cases.read_text(encoding="utf-8-sig")))
        results, _ = run_cases(cases, args.base_url, args.today, args.in_process)
        report = write_reports(results, args.output)
    except Exception as exc:
        parser.error(f"audit failed: {type(exc).__name__}: {exc}")
    print(json.dumps({"total": report["total"], "counts": report["counts"]}, ensure_ascii=False))
    return 0 if report["counts"]["답변 점검 필요"] == 0 else 1


if __name__ == "__main__": raise SystemExit(main_cli())
