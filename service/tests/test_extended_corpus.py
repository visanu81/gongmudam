import json
import unittest

from tools.audit_question_relevance import ROOT, _run_cases
from tools.check_question_answers import DEFAULT_MANIFEST, load_sources
from app import answer_tree, official_sources


class ExtendedCorpusTest(unittest.TestCase):
    def test_manifest_has_verified_v38_and_v40_collections(self):
        rows = json.loads(DEFAULT_MANIFEST.read_text(encoding="utf-8"))
        old_rows = [row for row in rows if row.get("collection") not in {"v40", "v70"}]
        extended_rows = [row for row in rows if row.get("collection") == "v40"]
        national_rows = [row for row in rows if row.get("collection") == "v70"]
        self.assertEqual(len(old_rows), 14)
        self.assertEqual(len(extended_rows), 11)
        annex_rows = [row for row in extended_rows if row.get("annex")]
        self.assertEqual(len(annex_rows), 5)
        self.assertEqual(len(national_rows), 5)
        self.assertEqual({row["article"].split("(", 1)[0] for row in national_rows},
                         {"제18조", "제19조", "제20조", "제25조", "제26조"})
        for row in national_rows:
            self.assertEqual(row["title"], "국가공무원 복무규정")
            self.assertEqual(row["institution"], "국가공무원")
            self.assertEqual(row["issuer"], "인사혁신처")
            self.assertEqual(row["kind"], "법령·규정")
            self.assertRegex(row["source_url"], r"^https://(?:www\.)?law\.go\.kr/")
            self.assertRegex(row["sha256"], r"^[0-9a-f]{64}$")
            self.assertRegex(row["raw_sha256"], r"^[0-9a-f]{64}$")
        verified_sources, problems = load_sources(DEFAULT_MANIFEST)
        self.assertFalse(problems, problems)
        self.assertEqual(len(verified_sources), 30)
        for row in rows:
            self.assertIsNotNone(official_sources.metadata(row["sha256"]), row["filename"])

    def test_v40_question_cases_pass(self):
        cases_path = ROOT / "reference_data" / "question_checks_v40.json"
        cases = json.loads(cases_path.read_text(encoding="utf-8"))
        verified_sources, problems = load_sources(DEFAULT_MANIFEST)
        self.assertFalse(problems, problems)
        results = _run_cases(cases, verified_sources, include_extended=True)
        failures = [{"id": item.get("id"), "failures": item.get("failures"),
                     "mode": item.get("mode"), "articles": item.get("articles"), "rules": item.get("rules")}
                    for item in results if not item.get("passed")]
        self.assertEqual(len(results), len(cases))
        self.assertEqual(failures, [], json.dumps(failures, ensure_ascii=False, indent=2))

    def test_tampered_domestic_annex_digest_disables_extended_summary(self):
        cases = json.loads((ROOT / "reference_data" / "question_checks_v40.json").read_text(encoding="utf-8"))
        case = next(item for item in cases if item.get("id") == "domestic-seoul")
        verified_sources, problems = load_sources(DEFAULT_MANIFEST)
        self.assertFalse(problems, problems)
        result = _run_cases([case], verified_sources, include_extended=True)[0]["result"]
        knowledge = result["knowledge"]
        annex_hit = next(hit for hit in knowledge["evidence"]
                         if hit.get("official", {}).get("title") == "공무원 여비 규정"
                         and hit.get("official", {}).get("article", "").startswith("별표 2"))
        annex_hit["sha256"] = "0" * 64
        rebuilt = answer_tree.build(case["question"], knowledge)
        self.assertEqual(rebuilt["kind"], "extract")


if __name__ == "__main__":
    unittest.main()
