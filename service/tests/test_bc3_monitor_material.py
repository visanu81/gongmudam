"""Existing frozen monitor assertions with a source-only fixture, not HTTP acceptance."""
from pathlib import Path
import socket
import tempfile
import unittest
from unittest.mock import patch
from app import regulation_registry as registry, travel_calculator as calculator
import test_regulation_monitor as original

class MonitorMaterialTests(unittest.TestCase):
    source_fixture=original.MonitorTest.source_fixture
    october23_fixture=original.MonitorTest.october23_fixture

    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.root=Path(self.temp.name)
        self.patches=[patch.object(registry,'DB_PATH',self.root/'monitor.db'),
            patch.object(registry,'OBJECTS',self.root/'objects'),
            patch.object(socket.socket,'connect',side_effect=AssertionError('No real network in source fixture test')),
            patch.object(socket,'getaddrinfo',side_effect=AssertionError('No real DNS in source fixture test'))]
        for item in self.patches:item.start()
        self.addCleanup(self.cleanup)
        registry.initialize();self.base=calculator.load_bundle()

    def cleanup(self):
        for item in reversed(self.patches):item.stop()
        self.temp.cleanup()

for name in [
    'test_real_registered_fixtures_match_without_network',
    'test_current_annex_pointer_is_followed_and_failure_never_certifies',
    'test_october23_other_law_header_is_not_a_travel_regulation_change',
    'test_national_body_and_attachment_edits_are_still_changes',
    'test_national_identity_and_layout_fail_closed',
    'test_html_table_and_link_and_current_version_change_detection',
    'test_pdf_change_and_malformed_download_never_count_as_unchanged',
    'test_source_url_redirect_guard',
    'test_embedded_table_image_identifier_changes_are_material',
    'test_latest_list_attachment_version_conflict_fails_closed',
    'test_archived_evidence_corruption_cannot_be_reused',
]:
    setattr(MonitorMaterialTests,name,getattr(original.MonitorTest,name))

if __name__=='__main__':unittest.main()
