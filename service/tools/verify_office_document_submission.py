"""Read-only AI-off document questions and provenance checks in a submission installation."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
from urllib.parse import urlsplit

import httpx

ROOT = Path(__file__).resolve().parents[1]
CASES = (
    ('receipt', '공문을 접수한 뒤 담당 부서로 배부하는 절차는?', 'documents-receipt'),
    ('draft', '공문 기안에서 검토와 결재는 어떤 순서로 하나요?', 'documents-drafting'),
    ('distribution', '문서과에서 받은 공문은 어떻게 배부하나요?', 'documents-receipt'),
    ('duty', '공문은 당직 때 받으면 어떻게 접수하나요?', 'documents-receipt'),
    ('multi', '여러 부서와 관련된 공문은 어디서 접수하고 배부하나요?', 'documents-receipt'),
    ('timing', '공문은 접수 후 몇 시간 안에 배부해야 하나요?', 'documents-receipt'),
    ('review', '기안문 검토는 결재 전에 받나요?', 'documents-drafting'),
    ('skip', '공문 기안 검토자가 출장 중이면 검토를 생략해도 되나요?', 'documents-drafting'),
    ('proxy', '공문 결재권자가 출장 중이면 누가 대결하나요?', 'documents-drafting'),
    ('scope', '우리 부서 공문 결재선은?', None),
    ('outside', '공기업 공문 기안 결재 순서는?', None),
    ('copyright', '공문 저작권 검토는?', None),
    ('old', '2020년 공문 접수 절차는?', None),
    ('future', '2027년 공문 기안 결재는?', None),
    ('form', '공문 기안 양식파일을 내려받고 싶어요', None),
    ('budget-scope', '사무용품을 사려는데 무슨 목으로 구입해야 하나요?', None),
    ('family', '아이가 아파서 돌봐야 하는데 어떤 휴가를 써요?', 'regression'),
    ('health', '건강검진을 받으려는데 공가를 쓸 수 있나요?', 'regression'),
    ('car', '출장 때 공용차량을 타면 일비는 어떻게 되나요?', 'regression'),
    ('budget-local', '지방자치단체에서 사무용품을 사려는데 무슨 목으로 구입해야 하나요?', 'regression'),
    ('privacy', '교육 참석자 명단에 전화번호도 받아도 되나요?', 'regression'),
    ('record', '기록물 평가 폐기 절차는?', 'regression'),
    ('manual', 'e-사람 출장 결재선 변경 방법', 'regression'),
)


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def run(base):
    url = urlsplit(base)
    if url.scheme != 'http' or url.hostname not in {'127.0.0.1', 'localhost', '::1'} or url.path not in {'', '/'} or url.query or url.fragment or url.username:
        raise ValueError('Use the local private submission server URL')
    if not (ROOT / 'data/submission-installation.json').is_file():
        raise RuntimeError('Use a restored submission installation')
    submission_manifest = json.loads((ROOT / 'submission-manifest.json').read_text(encoding='utf-8'))
    release = submission_manifest['release_version']
    bundle = json.loads((ROOT / 'submission-data/knowledge.json').read_text(encoding='utf-8'))
    pack = ROOT / 'reference_data/office-documents-20261026'
    rows = json.loads((pack / 'manifest.json').read_text(encoding='utf-8'))
    expected = {r['id']: r for r in rows}
    assert len(expected) == len(rows) == 10
    before_config = sha(ROOT / 'config.json')
    checks, answers, originals = {}, {}, []
    with httpx.Client(base_url=base.rstrip('/'), timeout=45, trust_env=False) as client:
        def get(path):
            response = client.get(path)
            response.raise_for_status()
            return response.json()
        status = get('/api/gongmudam/status')
        checks['private_release'] = not status['public_demo'] and status['service_version'] == release
        checks['default_offline'] = get('/api/settings')['llm']['active'] == 'offline'
        sources = get('/api/knowledge/sources')
        installed = {s['id']: s for s in sources}
        checks['exact_bundled_sources_current'] = (
            len(installed) == len(sources) == len(bundle['sources']) == submission_manifest['sources']
            and set(installed) == {s['id'] for s in bundle['sources']}
            and all(s['current'] and s['enabled'] for s in sources)
        )
        checks['original_paths_inside_installation'] = all(Path(s['path']).resolve().is_relative_to(ROOT.resolve()) for s in sources)
        checks['new_sources_match_reviewed_metadata'] = all(
            key in installed and installed[key]['official'] == row
            and installed[key]['sha256'] == row['sha256']
            for key, row in expected.items()
        )
        checks['six_manuals_221_pages'] = sum(s.get('reference_kind') == 'system_manual' for s in sources) == 6 and sum(s.get('page_count', 0) for s in sources) == 221
        for key, query, wanted in CASES:
            response = client.post('/api/ask', json=dict(query=query, guidance=True, use_ai=False, today='2026-10-26'))
            response.raise_for_status()
            result = response.json()
            answers[key] = result
            reply = result['knowledge']
            evidence = reply['evidence']
            assert result['guidance']['ai_used'] is False and result.get('model') is None and reply.get('model') is None, key
            if wanted is None:
                assert not evidence, key
            elif wanted == 'regression':
                assert evidence or result['guidance']['manual']['evidence'], key
            else:
                tree = reply['tree']
                assert tree['kind'] == 'summary' and tree['rule_id'] == 'office:' + wanted, key
                for hit in evidence:
                    row = expected[hit['official']['id']]
                    assert hit['official'] == row and hit['sha256'] == row['sha256'], key
                    assert sha(pack / 'excerpts' / row['filename']) == row['sha256'], key
                    assert sha(pack / 'raw' / row['raw_file']) == row['raw_sha256'], key
                for branch in tree['branches']:
                    for item in branch['items']:
                        hit = evidence[item['ref'] - 1]
                        assert item['support_quotes'] and all(q in hit['text'] for q in item['support_quotes']), key
            checks['question_' + key] = True
        for row in rows:
            response = client.get(f"/api/office-sources/{row['sha256']}/original")
            response.raise_for_status()
            excerpt = (pack / 'excerpts' / row['filename']).read_text(encoding='utf-8')
            assert response.headers['content-type'].startswith('text/plain')
            assert response.text.endswith(excerpt) and row['source_url'] in response.text
            assert sha(pack / 'excerpts' / row['filename']) == row['sha256']
            originals.append(dict(id=row['id'], sha256=row['sha256'], passed=True))
        checks['ten_originals_text_source_and_hash'] = len(originals) == 10
    checks['model_config_unchanged'] = sha(ROOT / 'config.json') == before_config
    result = dict(checked_at=datetime.now(timezone.utc).isoformat(), release=release,
                  base_url=base, passed=all(checks.values()), registered_sources=len(sources),
                  checks=checks, questions=len(answers), answers=answers, originals=originals,
                  actual_model_calls=0, mutation=False,
                  scope='Stored snapshot retrieval and exact citation checks, not a fresh legal-currentness approval or physical second-PC test.')
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--base', default='http://127.0.0.1:8781')
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    result = run(args.base)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps({k: result[k] for k in ('release', 'passed', 'registered_sources', 'questions', 'actual_model_calls')}, ensure_ascii=False))
    raise SystemExit(0 if result['passed'] else 1)
