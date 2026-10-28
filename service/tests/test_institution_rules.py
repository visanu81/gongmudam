"""Institution-owned rule versioning and retrieval API regressions."""
from __future__ import annotations

import hashlib
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from app import folders, institution_rules, knowledge, llm, main, guidance


RULE = {
    "title": "교육자료 제출 안내",
    "institution": "합성 검증기관",
    "kind": "기관 지침",
    "keywords": ["교육자료 제출"],
    "text": "교육자료 제출기한은 3일 전입니다.",
    "effective_date": "2026-01-01",
    "scope_notes": "",
    "change_note": "초안 작성",
}


class InstitutionRulesApiTest(unittest.TestCase):
    def setUp(self):
        self.profile_patch = patch.object(
            knowledge.config, "active_profile",
            return_value={"provider": "offline", "_name": "offline"},
        )
        self.profile_patch.start()
        self.addCleanup(self.profile_patch.stop)
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.db_path = Path(self.temp.name) / "folders.db"
        self.db_patch = patch.object(folders, "DB_PATH", self.db_path)
        self.db_patch.start()
        self.addCleanup(self.db_patch.stop)
        institution_rules.initialize()
        # No context manager: the application lifespan initializes unrelated live stores.
        self.client = TestClient(main.app)
        self.addCleanup(self.client.close)

    def create(self, **changes):
        body = dict(RULE)
        body.update(changes)
        response = self.client.post("/api/institution-rules", json=body)
        self.assertEqual(response.status_code, 201, response.text)
        return response.json()

    def apply(self, doc, version=None):
        version = version or doc["versions"][-1]
        return self.client.patch(
            f"/api/institution-rules/{doc['id']}",
            json={"revision": doc["revision"], "operation": "apply",
                  "version_id": version["id"], "reviewed_sha256": version["sha256"]},
        )

    def test_create_starts_as_disabled_immutable_draft(self):
        doc = self.create()
        self.assertEqual(doc["revision"], 1)
        self.assertFalse(doc["enabled"])
        self.assertIsNone(doc["active_version_id"])
        self.assertEqual(doc["versions"][0]["number"], 1)
        self.assertEqual(doc["versions"][0]["text"], RULE["text"])
        self.assertEqual(doc["versions"][0]["sha256"], hashlib.sha256(RULE["text"].encode()).hexdigest())

    def form_and_instruction(self):
        form=self.create(title="제출확인서",kind="서식",keywords=["제출확인서"],text="제출확인서의 필수 항목은 부서명입니다.",effective_date="2026-10-01")
        form=self.apply(form).json()
        instruction=self.create(text="교육자료 제출기한은 3일 전입니다. 필요한 서식은 제출확인서입니다.")
        instruction=self.apply(instruction).json()
        return form,instruction

    def ask_instruction(self,doc,institution="합성 검증기관",today="2026-10-26"):
        response=self.client.post('/api/ask',json={'query':institution+' 교육자료 제출 기한은?',
            'guidance':True,'use_ai':False,'institution_rule_id':doc['id'],'today':today})
        self.assertEqual(response.status_code,200,response.text)
        return response.json()

    def test_referenced_applied_form_is_linked_even_when_question_targets_instruction(self):
        form,instruction=self.form_and_instruction()
        reply=self.ask_instruction(instruction)
        related=reply['guidance']['forms']
        self.assertEqual(len(related),1)
        self.assertEqual(related[0]['source_id'],form['source_id'])
        self.assertEqual(related[0]['kind'],'서식')
        self.assertEqual(related[0]['version_number'],1)
        original=self.client.get(related[0]['href'])
        self.assertEqual(original.status_code,200,original.text)
        self.assertEqual(original.text,form['versions'][0]['text'])

    def test_form_kind_is_preserved_in_catalog_and_answer_for_legacy_source_payload(self):
        form,_=self.form_and_instruction()
        with folders.db() as c:
            import json
            payload=json.loads(c.execute('SELECT payload FROM knowledge_sources WHERE id=?',(form['source_id'],)).fetchone()[0])
            payload['kind']='기관 지침'
            c.execute('UPDATE knowledge_sources SET payload=? WHERE id=?',(json.dumps(payload,ensure_ascii=False),form['source_id']))
        source=next(s for s in knowledge.sources() if s['id']==form['source_id'])
        self.assertEqual(source['kind'],'서식')
        response=self.client.post('/api/ask',json={'query':'합성 검증기관 제출확인서 필수 항목은?',
            'guidance':True,'use_ai':False,'institution_rule_id':form['id'],'today':'2026-10-26'})
        self.assertEqual(response.status_code,200,response.text)
        evidence=response.json()['knowledge']['evidence']
        self.assertTrue(evidence)
        self.assertEqual(evidence[0]['kind'],'서식')

    def test_related_forms_exclude_other_institutions_disabled_and_wrong_date(self):
        form,instruction=self.form_and_instruction()
        other=self.create(title='제출확인서',kind='서식',institution='다른 기관',keywords=['제출확인서'])
        self.apply(other)
        unrelated=self.create(title='회의실 신청서',kind='서식',keywords=['회의실 신청서'])
        self.apply(unrelated)
        related=self.ask_instruction(instruction)['guidance']['forms']
        self.assertEqual([f['source_id'] for f in related],[form['source_id']])
        earlier=self.ask_instruction(instruction,today='2026-09-30')
        self.assertTrue(earlier['knowledge']['evidence'])
        self.assertFalse(earlier['guidance']['forms'])
        disabled=self.client.patch('/api/institution-rules/'+form['id'],json={'revision':form['revision'],'operation':'disable'}).json()
        self.assertFalse(self.ask_instruction(instruction)['guidance']['forms'])
        deleted=self.client.patch('/api/institution-rules/'+form['id'],json={'revision':disabled['revision'],'operation':'delete'}).json()
        self.assertFalse(self.ask_instruction(instruction)['guidance']['forms'])
        self.client.patch('/api/institution-rules/'+form['id'],json={'revision':deleted['revision'],'operation':'restore'})
        self.assertFalse(self.ask_instruction(instruction)['guidance']['forms'])

    def test_unapplied_form_draft_is_not_linked(self):
        self.create(title='제출확인서',kind='서식',keywords=['제출확인서'])
        instruction=self.apply(self.create(text='필요한 서식은 제출확인서입니다.')).json()
        self.assertFalse(self.ask_instruction(instruction)['guidance']['forms'])

    def test_related_form_keeps_applied_version_until_new_draft_is_applied(self):
        form,instruction=self.form_and_instruction()
        newer=self.client.post('/api/institution-rules/'+form['id']+'/versions',json={
            **RULE,'title':'제출확인서','kind':'서식','keywords':['제출확인서'],
            'text':'제출확인서의 필수 항목은 부서명과 연락처입니다.','revision':form['revision']}).json()
        self.assertEqual(self.ask_instruction(instruction)['guidance']['forms'][0]['version_number'],1)
        self.apply(newer)
        related=self.ask_instruction(instruction)['guidance']['forms'][0]
        self.assertEqual(related['version_number'],2)
        self.assertIn('연락처',self.client.get(related['href']).text)

    def test_broad_institution_keyword_does_not_replace_recognized_travel_topic(self):
        doc = self.create(keywords=["출장"])
        self.assertEqual(self.apply(doc).status_code, 200)
        self.assertEqual(guidance.topic("다른 기관 출장 신청 방법은?")[0], "travel")

    def test_manager_question_scope_keeps_only_selected_institution_document(self):
        first = self.create()
        self.assertEqual(self.apply(first).status_code, 200)
        other = self.create(title="다른 교육자료 안내", text="교육자료 제출은 별도 검토합니다.")
        self.assertEqual(self.apply(other).status_code, 200)
        found = knowledge.retrieve("합성 검증기관 교육자료 제출 기한은?", None,
                                   institution_rule_id=first["id"])
        managed = [h for h in found["hits"] if h.get("reference_kind") == "institution_rule"]
        self.assertTrue(managed)
        self.assertEqual({h["managed_rule_id"] for h in managed}, {first["id"]})

    def test_list_and_detail_expose_all_versions_without_live_database_data(self):
        doc = self.create()
        listed = self.client.get("/api/institution-rules").json()["items"]
        self.assertIn(doc["id"], {item["id"] for item in listed})
        detail = self.client.get(f"/api/institution-rules/{doc['id']}").json()
        self.assertEqual(detail["versions"][0]["text"], RULE["text"])

    def test_new_version_increments_revision_and_preserves_old_snapshot(self):
        doc = self.create()
        old = dict(doc["versions"][0])
        response = self.client.post(
            f"/api/institution-rules/{doc['id']}/versions",
            json={**RULE, "text": "교육자료 제출기한은 5일 전입니다.",
                  "change_note": "기한 변경", "revision": doc["revision"],
                  "based_on": old["id"]},
        )
        self.assertEqual(response.status_code, 201, response.text)
        updated = response.json()
        self.assertEqual(updated["revision"], 2)
        self.assertEqual([v["number"] for v in updated["versions"]], [1, 2])
        self.assertEqual(updated["versions"][0], old)
        self.assertEqual(updated["versions"][1]["text"], "교육자료 제출기한은 5일 전입니다.")

    def test_compare_reports_version_content_and_metadata_changes(self):
        doc = self.create()
        newer = self.client.post(
            f"/api/institution-rules/{doc['id']}/versions",
            json={**RULE, "text": "교육자료 제출기한은 5일 전입니다.",
                  "effective_date": "2026-02-01", "change_note": "수정",
                  "revision": doc["revision"], "based_on": doc["versions"][0]["id"]},
        ).json()
        result = self.client.get(
            f"/api/institution-rules/{doc['id']}/compare",
            params={"from_version": doc["versions"][0]["id"], "to_version": newer["versions"][-1]["id"]},
        )
        self.assertEqual(result.status_code, 200, result.text)
        self.assertIn("교육자료 제출기한은 3일 전입니다.", result.text)
        self.assertIn("교육자료 제출기한은 5일 전입니다.", result.text)

    def test_reviewed_application_publishes_source_with_original_provenance(self):
        doc = self.create()
        response = self.apply(doc)
        self.assertEqual(response.status_code, 200, response.text)
        applied = response.json()
        self.assertEqual(applied["revision"], 2)
        self.assertTrue(applied["enabled"])
        self.assertEqual(applied["source_id"], f"institution:{doc['id']}")
        source = next((row for row in knowledge.sources() if row.get("id") == applied["source_id"]), None)
        self.assertIsNotNone(source)
        self.assertEqual(source["reference_kind"], "institution_rule")
        self.assertEqual(source["sha256"], doc["versions"][0]["sha256"])
        self.assertNotIn("official", source)

    def test_unapplied_draft_never_appears_in_retrieval_or_answer(self):
        self.create()
        with patch.object(knowledge.config, "active_profile", return_value={"provider": "offline"}), \
                patch.object(knowledge, "_experience_hits", return_value=[]), \
                patch.object(llm, "get_provider", side_effect=AssertionError("AI-off request constructed a provider")):
            response = self.client.post("/api/ask", json={
                "query": "합성 검증기관 교육자료 제출 기한은?", "guidance": True,
                "use_ai": False, "knowledge_library_id": "institution-rules", "today": "2026-10-25",
            })
        self.assertEqual(response.status_code, 200, response.text)
        self.assertNotIn("3일 전", response.text)

    def test_applied_current_version_is_the_only_retrieved_version(self):
        doc = self.create()
        applied = self.apply(doc).json()
        second = self.client.post(
            f"/api/institution-rules/{doc['id']}/versions",
            json={**RULE, "text": "교육자료 제출기한은 5일 전입니다.",
                  "change_note": "기한 변경", "revision": applied["revision"],
                  "based_on": doc["versions"][0]["id"]},
        ).json()
        with patch.object(knowledge.config, "active_profile", return_value={"provider": "offline"}), \
                patch.object(knowledge, "_experience_hits", return_value=[]), \
                patch.object(llm, "get_provider", side_effect=AssertionError("AI-off request constructed a provider")):
            draft_answer = self.client.post("/api/ask", json={
                "query": "합성 검증기관 교육자료 제출 기한은?", "guidance": True,
                "use_ai": False, "knowledge_library_id": "institution-rules", "today": "2026-10-25",
            })
        self.assertEqual(draft_answer.status_code, 200, draft_answer.text)
        self.assertIn("3일 전", draft_answer.text)
        self.assertNotIn("5일 전", draft_answer.text)
        draft = second["versions"][-1]
        applied_again = self.apply(second, draft)
        self.assertEqual(applied_again.status_code, 200, applied_again.text)
        with patch.object(knowledge.config, "active_profile", return_value={"provider": "offline"}), \
                patch.object(knowledge, "_experience_hits", return_value=[]), \
                patch.object(llm, "get_provider", side_effect=AssertionError("AI-off request constructed a provider")):
            live_answer = self.client.post("/api/ask", json={
                "query": "합성 검증기관 교육자료 제출 기한은?", "guidance": True,
                "use_ai": False, "knowledge_library_id": "institution-rules", "today": "2026-10-25",
            })
        self.assertEqual(live_answer.status_code, 200, live_answer.text)
        self.assertIn("5일 전", live_answer.text)
        self.assertNotIn("3일 전", live_answer.text)
        original = self.client.get(
            f"/api/institution-rules/{doc['id']}/versions/{doc['versions'][0]['id']}/original"
        )
        self.assertEqual(original.status_code, 200, original.text)
        self.assertEqual(original.text, RULE["text"])

    def test_stale_revision_and_unreviewed_checksum_are_rejected(self):
        doc = self.create()
        applied = self.apply(doc)
        self.assertEqual(applied.status_code, 200, applied.text)
        stale = self.client.patch(f"/api/institution-rules/{doc['id']}", json={
            "revision": doc["revision"], "operation": "disable",
        })
        self.assertEqual(stale.status_code, 409, stale.text)
        current = applied.json()
        mismatch = self.client.patch(f"/api/institution-rules/{doc['id']}", json={
            "revision": current["revision"], "operation": "apply",
            "version_id": doc["versions"][0]["id"], "reviewed_sha256": "0" * 64,
        })
        self.assertIn(mismatch.status_code, (409, 422), mismatch.text)

    def test_future_effective_draft_cannot_be_applied_early(self):
        doc = self.create(effective_date="2099-01-01")
        response = self.apply(doc)
        self.assertEqual(response.status_code, 422, response.text)

    def test_disabled_deleted_and_restored_sources_stay_out_of_retrieval(self):
        doc = self.create()
        applied = self.apply(doc).json()
        disabled = self.client.patch(f"/api/institution-rules/{doc['id']}", json={
            "revision": applied["revision"], "operation": "disable",
        })
        self.assertEqual(disabled.status_code, 200, disabled.text)
        self.assertFalse(disabled.json()["enabled"])
        deleted = self.client.patch(f"/api/institution-rules/{doc['id']}", json={
            "revision": disabled.json()["revision"], "operation": "delete",
        })
        self.assertEqual(deleted.status_code, 200, deleted.text)
        self.assertFalse(deleted.json().get("enabled", False))
        self.assertNotIn(applied["source_id"], {s.get("id") for s in knowledge.sources()})
        restored = self.client.patch(f"/api/institution-rules/{doc['id']}", json={
            "revision": deleted.json()["revision"], "operation": "restore",
        })
        self.assertEqual(restored.status_code, 200, restored.text)
        self.assertFalse(restored.json()["enabled"])
        source = next(s for s in knowledge.sources() if s.get("id") == applied["source_id"])
        self.assertFalse(source["enabled"])
        self.assertEqual(knowledge.retrieve("합성 검증기관 교육자료 제출 기한은?", "institution-rules")["hits"], [])

    def test_deleted_documents_reject_edit_and_application_but_keep_original(self):
        doc = self.create()
        deleted = self.client.patch(f"/api/institution-rules/{doc['id']}", json={
            "revision": doc["revision"], "operation": "delete",
        }).json()
        edit = self.client.post(f"/api/institution-rules/{doc['id']}/versions", json={
            **RULE, "revision": deleted["revision"], "based_on": doc["versions"][0]["id"],
        })
        self.assertEqual(edit.status_code, 409, edit.text)
        blocked_apply = self.client.patch(f"/api/institution-rules/{doc['id']}", json={
            "revision": deleted["revision"], "operation": "apply",
            "version_id": doc["versions"][0]["id"],
            "reviewed_sha256": doc["versions"][0]["sha256"],
        })
        self.assertEqual(blocked_apply.status_code, 409, blocked_apply.text)
        original = self.client.get(
            f"/api/institution-rules/{doc['id']}/versions/{doc['versions'][0]['id']}/original"
        )
        self.assertEqual(original.status_code, 200, original.text)
        self.assertEqual(original.text, RULE["text"])

    def test_wrong_institution_question_does_not_return_local_rule(self):
        doc = self.create()
        self.apply(doc)
        with patch.object(knowledge.config, "active_profile", return_value={"provider": "offline"}), \
                patch.object(knowledge, "_experience_hits", return_value=[]), \
                patch.object(llm, "get_provider", side_effect=AssertionError("AI-off request constructed a provider")):
            response = self.client.post("/api/ask", json={
                "query": "다른 기관 교육자료 제출 기한은?", "guidance": True,
                "use_ai": False, "knowledge_library_id": "institution-rules", "today": "2026-10-25",
            })
        self.assertEqual(response.status_code, 200, response.text)
        self.assertNotIn("3일 전", response.text)

    def test_public_demo_blocks_rule_mutations(self):
        old = getattr(main.app.state, "public_demo", None)
        main.app.state.public_demo = True
        try:
            response = self.client.post("/api/institution-rules", json=RULE)
            self.assertEqual(response.status_code, 403, response.text)
            upload = self.client.post("/api/institution-rules/upload", data={
                "title": RULE["title"], "institution": RULE["institution"],
                "keywords": '["교육자료 제출"]',
            }, files={"file": ("rule.txt", RULE["text"].encode(), "text/plain")})
            self.assertEqual(upload.status_code, 403, upload.text)
            self.assertEqual(self.client.get("/api/institution-rules").status_code, 200)
        finally:
            if old is None:
                delattr(main.app.state, "public_demo")
            else:
                main.app.state.public_demo = old

    def test_rows_survive_reopening_the_same_database(self):
        doc = self.create()
        institution_rules.initialize()
        reopened = self.client.get(f"/api/institution-rules/{doc['id']}")
        self.assertEqual(reopened.status_code, 200, reopened.text)
        self.assertEqual(reopened.json()["versions"][0]["text"], RULE["text"])

    def test_text_upload_and_revision_preserve_each_original_file(self):
        first_bytes = "교육자료 제출기한은 3일 전입니다.\n".encode()
        response = self.client.post("/api/institution-rules/upload", data={
            "title": RULE["title"], "institution": RULE["institution"],
            "keywords": '["교육자료 제출"]', "kind": RULE["kind"],
            "effective_date": RULE["effective_date"], "change_note": "파일 등록",
        }, files={"file": ("기관지침.txt", first_bytes, "text/plain")})
        self.assertEqual(response.status_code, 201, response.text)
        doc = response.json()
        first = doc["versions"][0]
        self.assertEqual(first["origin"]["sha256"], hashlib.sha256(first_bytes).hexdigest())
        self.assertEqual(first["origin"]["bytes"], len(first_bytes))
        saved_file = self.client.get(
            f"/api/institution-rules/{doc['id']}/versions/{first['id']}/file"
        )
        self.assertEqual(saved_file.status_code, 200, saved_file.text)
        self.assertEqual(saved_file.content, first_bytes)

        second_bytes = "교육자료 제출기한은 5일 전입니다.\n".encode()
        updated = self.client.post("/api/institution-rules/upload", data={
            "title": RULE["title"], "institution": RULE["institution"],
            "keywords": '["교육자료 제출"]', "kind": RULE["kind"],
            "effective_date": RULE["effective_date"], "change_note": "기한 변경",
            "rule_id": doc["id"], "revision": doc["revision"],
        }, files={"file": ("기관지침.txt", second_bytes, "text/plain")})
        self.assertEqual(updated.status_code, 201, updated.text)
        second = updated.json()["versions"][-1]
        self.assertEqual(len(updated.json()["versions"]), 2)
        first_again = self.client.get(
            f"/api/institution-rules/{doc['id']}/versions/{first['id']}/file"
        )
        second_file = self.client.get(
            f"/api/institution-rules/{doc['id']}/versions/{second['id']}/file"
        )
        self.assertEqual(first_again.content, first_bytes)
        self.assertEqual(second_file.content, second_bytes)
        self.assertEqual(self.client.get(
            f"/api/institution-rules/{doc['id']}/versions/{first['id']}/original"
        ).text, first["text"])

    def test_partial_pdf_upload_is_rejected_without_creating_a_draft(self):
        response = self.client.post("/api/institution-rules/upload", data={
            "title": RULE["title"], "institution": RULE["institution"],
            "keywords": '["교육자료 제출"]',
        }, files={"file": ("partial.pdf", b"%PDF-1.7\npartial", "application/pdf")})
        self.assertEqual(response.status_code, 422, response.text)
        self.assertEqual(self.client.get("/api/institution-rules").json()["items"], [])

    def test_import_of_protected_official_knowledge_is_rejected(self):
        official = {
            "id": "protected-law", "title": "공통 법령", "sha256": "a" * 64,
            "official": {"source": "fixture"}, "current": True, "limited": False,
            "reference_kind": "legal", "units": [{"loc": "제1조", "text": "보호된 본문"}],
        }
        with patch.object(knowledge, "sources", return_value=[official]):
            response = self.client.post("/api/institution-rules/import", json={
                "source_type": "knowledge", "source_id": official["id"],
                "sha256": official["sha256"], "institution": RULE["institution"],
                "keywords": ["교육자료 제출"],
            })
        self.assertEqual(response.status_code, 422, response.text)
        self.assertEqual(self.client.get("/api/institution-rules").json()["items"], [])


if __name__ == "__main__":
    unittest.main()
