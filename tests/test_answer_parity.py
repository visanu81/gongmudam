import importlib.util
from pathlib import Path
import unittest


SCRIPT = Path(__file__).resolve().parents[1] / "tools" / "check_answer_parity.py"
SPEC = importlib.util.spec_from_file_location("check_answer_parity", SCRIPT)
parity = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(parity)


def answer(*, title="same", sha="abc", ref=1, text="advice", quotes=None, ai=False,
           article="Article 1", kind="summary", rule="rule"):
    return {
        "guidance": {"ai_used": ai},
        "knowledge": {
            "tree": {"kind": kind, "title": title, "rule_id": rule,
                     "branches": [{"label": "Branch", "items": [{"text": text, "ref": ref,
                                  "support_quotes": quotes or ["source quote"]}]}]},
            "evidence": [{"sha256": sha, "official": {"title": "Official title", "article": article},
                          "id": "environment-specific-id", "url": "file:///different/path"}],
        },
    }


class AnswerParityTests(unittest.TestCase):
    def test_equal_signatures_ignore_reference_ids_and_source_urls(self):
        left = answer()
        right = answer()
        right["knowledge"]["evidence"][0]["id"] = "another-id"
        right["knowledge"]["evidence"][0]["url"] = "https://different.example/source"
        self.assertEqual(parity.compare_answers(left, right)["mismatches"], [])

    def test_title_mismatch_is_reported(self):
        result = parity.compare_answers(answer(title="left"), answer(title="right"))
        self.assertIn("grounded_answer", result["mismatches"])

    def test_differing_citations_are_reported(self):
        result = parity.compare_answers(answer(sha="left"), answer(sha="right"))
        self.assertIn("grounded_answer", result["mismatches"])

    def test_ai_unexpected_is_reported_per_side(self):
        result = parity.compare_answers(answer(ai=True), answer())
        self.assertIn("local_ai_used", result["mismatches"])

    def test_expected_title_substring_is_required_on_both_sides(self):
        result = parity.compare_answers(answer(title="local title"), answer(title="public title"), "wanted")
        self.assertIn("local_expected_title", result["mismatches"])
        self.assertIn("public_expected_title", result["mismatches"])
