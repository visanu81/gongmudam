"""Compare read-only grounded answers from local and public Gongmudam APIs."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date
from pathlib import Path
from typing import Any

import httpx


def _knowledge(answer: dict[str, Any]) -> dict[str, Any]:
    value = answer.get("knowledge")
    return value if isinstance(value, dict) else {}


def _evidence_signature(answer: dict[str, Any]) -> list[tuple[str, str, str]]:
    evidence = _knowledge(answer).get("evidence")
    if not isinstance(evidence, list):
        return []
    rows = []
    for entry in evidence:
        if not isinstance(entry, dict):
            continue
        sha = entry.get("sha256")
        official = entry.get("official")
        official = official if isinstance(official, dict) else {}
        title = official.get("title", entry.get("title"))
        article = official.get("article", entry.get("article"))
        if all(isinstance(value, str) for value in (sha, title, article)):
            rows.append((sha, title, article))
    return sorted(rows)


def grounded_signature(answer: dict[str, Any]) -> dict[str, Any]:
    """Return semantic tree content with evidence references resolved by metadata."""
    tree = _knowledge(answer).get("tree")
    if not isinstance(tree, dict):
        tree = {}
    evidence = _knowledge(answer).get("evidence")
    evidence = evidence if isinstance(evidence, list) else []
    branches = []
    for branch in tree.get("branches", []) if isinstance(tree.get("branches"), list) else []:
        if not isinstance(branch, dict):
            continue
        items = []
        for item in branch.get("items", []) if isinstance(branch.get("items"), list) else []:
            if not isinstance(item, dict):
                continue
            ref = item.get("ref")
            resolved = None
            if isinstance(ref, int) and not isinstance(ref, bool) and 1 <= ref <= len(evidence):
                entry = evidence[ref - 1]
                if isinstance(entry, dict):
                    official = entry.get("official")
                    official = official if isinstance(official, dict) else {}
                    resolved = (entry.get("sha256"), official.get("title", entry.get("title")),
                                official.get("article", entry.get("article")))
            quotes = item.get("support_quotes", [])
            if not isinstance(quotes, list):
                quotes = []
            items.append({"text": item.get("text"), "evidence": resolved,
                          "support_quotes": sorted(q for q in quotes if isinstance(q, str))})
        branches.append({"label": branch.get("label"), "items": items})
    return {"kind": tree.get("kind"), "title": tree.get("title"),
            "rule_id": tree.get("rule_id"), "branches": branches}


def compare_answers(local: dict[str, Any], public: dict[str, Any], expected_title: str | None = None) -> dict[str, Any]:
    mismatches: list[str] = []
    local_sig, public_sig = grounded_signature(local), grounded_signature(public)
    equal = local_sig == public_sig and _evidence_signature(local) == _evidence_signature(public)
    if not equal:
        mismatches.append("grounded_answer")
    local_ai_used = (local.get("guidance", {}).get("ai_used")
                     if isinstance(local.get("guidance"), dict) else None)
    public_ai_used = (public.get("guidance", {}).get("ai_used")
                      if isinstance(public.get("guidance"), dict) else None)
    if local_ai_used is not False:
        mismatches.append("local_ai_used")
    if public_ai_used is not False:
        mismatches.append("public_ai_used")
    if expected_title is not None:
        for side, sig in (("local", local_sig), ("public", public_sig)):
            if not isinstance(sig["title"], str) or expected_title not in sig["title"]:
                mismatches.append(f"{side}_expected_title")
    return {"equal": equal, "mismatches": mismatches,
            "local": {"title": local_sig["title"], "kind": local_sig["kind"],
                      "rule_id": local_sig["rule_id"], "evidence": _evidence_signature(local),
                      "ai_used": local_ai_used},
            "public": {"title": public_sig["title"], "kind": public_sig["kind"],
                       "rule_id": public_sig["rule_id"], "evidence": _evidence_signature(public),
                       "ai_used": public_ai_used}}


def _load_cases(path: Path) -> list[Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    cases = value.get("cases") if isinstance(value, dict) else value
    if not isinstance(cases, list):
        raise ValueError("cases JSON must be a list or an object with a cases list")
    return cases


def _request(client: httpx.Client, url: str, question: str, today: str) -> dict[str, Any]:
    response = client.post(url.rstrip("/") + "/api/ask", json={
        "query": question, "guidance": True, "use_ai": False, "today": today,
    })
    response.raise_for_status()
    answer = response.json()
    if not isinstance(answer, dict):
        raise ValueError("API response root is not an object")
    return answer


def run(local_url: str, public_url: str, cases: list[Any], today: str) -> dict[str, Any]:
    results = []
    with httpx.Client(timeout=60.0) as client:
        for index, case in enumerate(cases):
            result: dict[str, Any] = {"id": case.get("id") if isinstance(case, dict) else None,
                                      "status": "fail", "equal": False, "mismatches": [],
                                      "local": {}, "public": {}}
            try:
                if (not isinstance(case, dict) or not isinstance(case.get("question"), str)
                        or not case["question"].strip()):
                    raise ValueError("case must have a non-empty question")
                answers: dict[str, dict[str, Any]] = {}
                for side, url in (("local", local_url), ("public", public_url)):
                    try:
                        answer = _request(client, url, case["question"], today)
                        result[side] = compare_answers(answer, answer)[side]
                        answers[side] = answer
                    except Exception as exc:
                        result[side] = {"error": f"{type(exc).__name__}: {exc}"}
                if "error" in result["local"] or "error" in result["public"]:
                    result["mismatches"] = [side + "_error" for side in ("local", "public") if "error" in result[side]]
                    result["error"] = True
                else:
                    outcome = compare_answers(answers["local"], answers["public"],
                                              case.get("expected_title") if isinstance(case.get("expected_title"), str) else None)
                    result.update(outcome)
                    result["status"] = "pass" if not outcome["mismatches"] else "fail"
            except Exception as exc:
                result["error"] = f"{type(exc).__name__}: {exc}"
                result["mismatches"] = ["case_error"]
            results.append(result)
    passed = sum(row["status"] == "pass" for row in results)
    return {"today": today, "cases": results,
            "summary": {"all_pass": passed == len(results), "passed": passed,
                        "failed": len(results) - passed, "total": len(results)}}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--local", required=True, help="local API base URL")
    parser.add_argument("--public", required=True, help="public API base URL")
    parser.add_argument("--cases", required=True, type=Path, help="JSON QA case list")
    parser.add_argument("--output", required=True, type=Path, help="output report JSON path")
    parser.add_argument("--today", default=date.today().isoformat(), help="date sent to both APIs (YYYY-MM-DD)")
    args = parser.parse_args(argv)
    try:
        cases = _load_cases(args.cases)
        report = run(args.local, args.public, cases, args.today)
    except Exception as exc:
        parser.error(f"cannot run parity check: {type(exc).__name__}: {exc}")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report["summary"], ensure_ascii=False))
    return 0 if report["summary"]["all_pass"] else 1


if __name__ == "__main__":
    sys.exit(main())
