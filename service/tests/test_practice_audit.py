import unittest
import csv
import json
import tempfile
from pathlib import Path
from unittest.mock import Mock
from unittest.mock import patch

from tools.audit_practice_questions import evaluate_case, run_cases, write_reports, _validate_cases, _compare_live_catalog, _all_evidence


def source(source_id="law1", title="연가 규정", text="연가는 1년에 21일입니다.", sha="hash1"):
    return {"id": source_id, "title": title, "sha256": sha, "enabled": True, "current": True,
            "units": [{"loc": "제1조", "text": text}]}


def case(**changes):
    value = {"id": "q1", "category": "leave", "question": "연가 일수는?", "expected": "answer",
             "require_source_groups": [["연가 규정"]], "answer_terms_groups": [["21일"]]}
    value.update(changes)
    return value


def response(evidence=None, answer="연가는 21일입니다.", mode="source_search", manual=None):
    return {"mode": mode, "model": None, "answer": answer,
            "knowledge": {"evidence": evidence or [], "answer": answer},
            "guidance": {"questions": [], "manual": {"evidence": manual or []}}}


class PracticeAuditTests(unittest.TestCase):
    def test_correct_source_and_answer_pass(self):
        evidence = {"source_id": "law1", "sha256": "hash1", "title": "연가 규정", "loc": "제1조",
                    "quote": "연가는 1년에 21일입니다."}
        result = evaluate_case(case(), response([evidence]), [source()])
        self.assertEqual(result["verdict"], "근거 연결 확인")

    def test_unrelated_source_does_not_pass_with_answer_terms(self):
        evidence = {"source_id": "law1", "sha256": "hash1", "title": "출장 규정", "loc": "제1조",
                    "quote": "출장은 사전 승인합니다."}
        result = evaluate_case(case(require_source_groups=[["연가"]]), response([evidence]), [source(title="출장 규정", text=evidence["quote"])])
        self.assertEqual(result["verdict"], "답변 점검 필요")

    def test_missing_required_source_fails(self):
        result = evaluate_case(case(), response([]), [source()])
        self.assertEqual(result["verdict"], "답변 점검 필요")

    def test_bad_hash_or_quote_fails(self):
        evidence = {"source_id": "law1", "sha256": "old-hash", "title": "연가 규정", "loc": "제1조", "quote": "그럴듯한 근거"}
        result = evaluate_case(case(), response([evidence]), [source()])
        self.assertEqual(result["verdict"], "답변 점검 필요")

    def test_quote_can_span_only_contiguous_registered_units_in_order(self):
        units = [{"loc": "1행", "text": "첫째 문장."}, {"loc": "2행", "text": "둘째 문장."},
                 {"loc": "3행", "text": "셋째 문장."}]
        src = source(text="", sha="hash1") | {"units": units}
        evidence = {"source_id": "law1", "sha256": "hash1", "title": "연가 규정", "loc": "1~2행",
                    "quote": "첫째 문장.\n둘째 문장."}
        valid = evaluate_case(case(require_source_groups=[["연가"]]), response([evidence]), [src])
        self.assertEqual(valid["verdict"], "근거 연결 확인")
        evidence["quote"] = "첫째 문장.\n셋째 문장."
        invalid = evaluate_case(case(require_source_groups=[["연가"]]), response([evidence]), [src])
        self.assertEqual(invalid["verdict"], "답변 점검 필요")

    def test_answer_terms_and_manual_quote_allow_whitespace_only_variation(self):
        evidence = [{"source_id": "manual", "sha256": "manualhash", "title": "시스템 매뉴얼", "loc": "1쪽",
                     "quote": "결재를 취 소하려면 메뉴를 선택합니다."}]
        result = response([], answer="결재를 취 소하려면 메뉴를 선택합니다.", mode="structured_guidance", manual=evidence)
        result["guidance"]["manual"]["evidence"] = evidence
        manual_case = case(expected="answer", evidence_channel="manual", require_source_groups=[["시스템 매뉴얼"]],
                           answer_terms_groups=[["취소"]])
        check = evaluate_case(manual_case, result, [source("manual", "시스템 매뉴얼", "결재를 취소하려면 메뉴를 선택합니다.", "manualhash")])
        self.assertEqual(check["verdict"], "근거 연결 확인")

    def test_missing_outcome_does_not_pass_irrelevant_answer(self):
        result = evaluate_case(case(expected="missing", require_source_groups=[], answer_terms_groups=[]),
                               response([], answer="오늘은 날씨가 좋습니다."), [])
        self.assertEqual(result["verdict"], "답변 점검 필요")

    def test_manual_evidence_does_not_satisfy_legal_source_group(self):
        manual = [{"source_id": "manual", "sha256": "manualhash", "title": "연가 규정 매뉴얼", "loc": "1쪽",
                   "quote": "연가 21일"}]
        evidence = [{"source_id": "law1", "sha256": "hash1", "title": "출장 규정", "loc": "제1조",
                     "quote": "출장은 사전 승인합니다."}]
        result = evaluate_case(case(require_source_groups=[["연가 규정"]]), response(evidence, manual=manual),
                               [source(title="출장 규정", text=evidence[0]["quote"]),
                                source("manual", "연가 규정 매뉴얼", "연가 21일", "manualhash")])
        self.assertEqual(result["verdict"], "답변 점검 필요")

    def test_manual_case_uses_manual_citation_and_terms_without_legal_evidence(self):
        manual = [{"source_id": "manual", "sha256": "manualhash", "title": "시스템 매뉴얼", "loc": "1쪽",
                   "quote": "화면에서 신청 버튼을 누릅니다."}]
        result = response([], answer="", mode="structured_guidance", manual=manual)
        result["guidance"]["manual"]["evidence"] = manual
        manual_case = case(expected="answer", evidence_channel="manual", require_source_groups=[["시스템 매뉴얼"]],
                           answer_terms_groups=[["신청 버튼"]])
        check = evaluate_case(manual_case, result, [source("manual", "시스템 매뉴얼", "화면에서 신청 버튼을 누릅니다.", "manualhash")])
        self.assertEqual(check["verdict"], "근거 연결 확인")

    def test_manual_notice_counts_for_terms_and_manual_evidence_blocks_insufficiency(self):
        manual = [{"source_id": "manual", "sha256": "manualhash", "title": "시스템 매뉴얼", "loc": "1쪽",
                   "quote": "화면 안내"}]
        result = response([], answer="", mode="structured_guidance", manual=manual)
        result["guidance"]["manual"]["evidence"] = manual
        result["guidance"]["manual"]["notice"] = "결재를 취 소하려면 이 메뉴를 누릅니다."
        src = [source("manual", "시스템 매뉴얼", "화면 안내", "manualhash")]
        manual_answer = case(expected="answer", evidence_channel="manual", require_source_groups=[["시스템 매뉴얼"]],
                             answer_terms_groups=[["취소"]])
        self.assertEqual(evaluate_case(manual_answer, result, src)["verdict"], "근거 연결 확인")
        missing = case(expected="missing", evidence_channel="manual", require_source_groups=[], answer_terms_groups=[])
        check = evaluate_case(missing, result, src)
        self.assertTrue(any("designated channel" in error for error in check["failures"]))

    def test_same_source_location_is_retained_across_evidence_channels(self):
        evidence = {"source_id": "law1", "sha256": "hash1", "title": "자료", "loc": "제1조", "quote": "인용"}
        result = response([evidence], manual=[evidence])
        rows = _all_evidence(result)
        self.assertEqual([channel for channel, _ in rows], ["knowledge", "manual"])

    def test_in_process_rejects_any_ai_provider_call(self):
        case_row = case()
        with patch("app.knowledge.sources", return_value=[source()]), \
             patch("app.main.api_ask", return_value=response([{ "source_id": "law1", "sha256": "hash1",
                  "title": "연가 규정", "loc": "제1조", "quote": "연가는 1년에 21일입니다."}])) as ask, \
             patch("app.llm.get_provider", side_effect=AssertionError("AI called")):
            rows, _ = run_cases([case_row], "http://127.0.0.1:8787", "2026-10-26", in_process=True)
        self.assertEqual(rows[0]["verdict"], "근거 연결 확인")
        ask.assert_called_once_with({"query": case_row["question"], "guidance": True, "use_ai": False, "today": "2026-10-26"})

    def test_http_catalog_without_units_keeps_local_hydrated_sources_for_quote_check(self):
        local = source()
        evidence = {"source_id": "law1", "sha256": "hash1", "title": "연가 규정", "loc": "제1조",
                    "quote": "연가는 1년에 21일입니다."}
        reply = response([evidence])
        api_response = Mock()
        api_response.__enter__ = Mock(return_value=api_response)
        api_response.__exit__ = Mock(return_value=False)
        api_response.read.return_value = json.dumps(reply, ensure_ascii=False).encode("utf-8")
        catalog = [{key: value for key, value in local.items() if key != "units"}]
        with patch("app.knowledge.sources", return_value=[local]), \
             patch("tools.audit_practice_questions._fetch_json", return_value=catalog), \
             patch("tools.audit_practice_questions.urllib.request.urlopen", return_value=api_response):
            rows, registry = run_cases([case()], "http://127.0.0.1:8787", "2026-10-26", in_process=False)
        self.assertIn("units", registry[0])
        self.assertEqual(rows[0]["verdict"], "근거 연결 확인")

    def test_live_catalog_identity_hash_status_mismatch_is_explicit(self):
        local = source()
        catalog = [{"id": "law1", "sha256": "different", "enabled": True, "current": True}]
        with self.assertRaisesRegex(RuntimeError, "sha256 mismatch"):
            _compare_live_catalog([local], catalog)

    def test_ai_model_metadata_fails_for_all_outcomes(self):
        result = response([], answer="소속 기관 확인이 필요합니다.", mode="structured_guidance")
        result["knowledge"]["model"] = "unexpected-model"
        check = evaluate_case(case(expected="institution", require_source_groups=[], answer_terms_groups=[]), result, [])
        self.assertEqual(check["verdict"], "답변 점검 필요")

    def test_clarification_with_primary_evidence_fails_conservatively(self):
        evidence = [{"source_id": "law1", "sha256": "hash1", "title": "연가 규정", "loc": "제1조",
                     "quote": "연가는 21일입니다."}]
        result = response(evidence, answer="연가는 21일입니다.", mode="source_clarification")
        result["guidance"]["questions"] = ["어떤 상황인지 알려주세요."]
        check = evaluate_case(case(expected="clarify", require_source_groups=[], answer_terms_groups=[]), result, [source()])
        self.assertEqual(check["verdict"], "답변 점검 필요")

    def test_insufficiency_with_primary_evidence_fails_conservatively(self):
        evidence = [{"source_id": "law1", "sha256": "hash1", "title": "연가 규정", "loc": "제1조",
                     "quote": "연가는 21일입니다."}]
        result = response(evidence, answer="등록 자료에서 확인할 수 없습니다.")
        check = evaluate_case(case(expected="missing", require_source_groups=[], answer_terms_groups=[]), result, [source()])
        self.assertEqual(check["verdict"], "답변 점검 필요")

    def test_report_csv_and_html_have_expected_columns_and_counts(self):
        answer_evidence = {"source_id": "law1", "sha256": "hash1", "title": "규정", "loc": "제1조",
                           "quote": "<quote>", "official": {"source_url": "https://example.test/?a=1&b=2"}}
        manual_evidence = {"source_id": "manual", "sha256": "manualhash", "title": "매뉴얼", "loc": "2쪽", "quote": "manual quote"}
        row = {"id": "<q>", "category": "복무", "question": "Q", "expected": "answer", "verdict": "근거 연결 확인",
               "failures": [], "source_titles": ["규정"], "response": {"answer": "actual <answer>", "notice": "notice",
               "knowledge": {"evidence": [answer_evidence]}, "guidance": {"manual": {"notice": "manual notice", "evidence": [manual_evidence]}}}, "checks": {}}
        with tempfile.TemporaryDirectory() as temp:
            report = write_reports([row], Path(temp))
            with (Path(temp) / "report.csv").open(encoding="utf-8-sig", newline="") as f:
                csv_rows = list(csv.DictReader(f))
            page = (Path(temp) / "report.html").read_text(encoding="utf-8")
        self.assertEqual(report["counts"]["근거 연결 확인"], 1)
        self.assertEqual(csv_rows[0]["expected"], "answer")
        self.assertIn("<td>answer</td>", page)
        self.assertIn("&lt;q&gt;", page)
        self.assertIn("<details>", page)
        self.assertIn("actual &lt;answer&gt;", page)
        self.assertIn("manual notice", page)
        self.assertIn("&lt;quote&gt;", page)
        self.assertIn("https://example.test/?a=1&amp;b=2", page)
        self.assertIn("manual quote", page)

    def test_duplicate_case_ids_are_rejected(self):
        rows = [case(id="dup"), case(id="dup")]
        rows.extend(case(id=f"q{i}") for i in range(3, 101))
        with self.assertRaisesRegex(ValueError, "duplicate"):
            _validate_cases(rows)


if __name__ == "__main__":
    unittest.main()
