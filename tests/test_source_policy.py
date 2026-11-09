from dataclasses import replace
from pathlib import Path
from pnu_notice_feed import generator
from pnu_notice_feed.generator import load_sources, fetch_source_result, notice_to_feed_item, compact_state_item
from pnu_notice_feed.types import Notice


def test_registry_explicit_critical_policy_covers_real_recruitment_ids():
    sources = load_sources(Path(__file__).parents[1] / 'sources.json')
    ids = {s.id for s in sources}
    assert generator.CRITICAL_SOURCE_IDS <= ids
    assert all(s.critical is not None for s in sources)
    assert all(s.critical for s in sources if s.id in {'pnu-job-recruit-recommendation','pnu-job-recruit-internship'})


def test_disabled_sources_preserve_history_without_network_calls(monkeypatch):
    source = next(s for s in load_sources(Path(__file__).parents[1]/'sources.json') if not s.enabled)
    monkeypatch.setattr(generator, 'fetch_source', lambda *a, **k: (_ for _ in ()).throw(AssertionError('disabled source fetched')))
    result = fetch_source_result(source,10,'2026-11-09T16:00:00+09:00')
    assert result.status == 'disabled'
    assert result.error == source.disabled_reason
    assert not generator.source_is_degraded(result)


def test_library_replatform_preserves_canonical_id_and_replaces_broken_url(monkeypatch):
    source = next(s for s in load_sources(Path(__file__).parents[1]/'sources.json') if s.id=='pnu-library-notices')
    notice = Notice(source.id,source.name,source.id+':58212','[안내] 도서관 홈페이지 및 모바일 앱 개편 안내','https://lib.pusan.ac.kr/guide/notice/58212','2026-11-06',None,[],[],'hash')
    old = notice_to_feed_item(notice,'2026-11-09T11:32:21+09:00')
    new = replace(notice,notice_id=source.id+':okh54dsep2uuhtsi',url='https://lib.pusan.ac.kr/guide/notice/okh54dsep2uuhtsi')
    monkeypatch.setattr(generator,'fetch_source',lambda *a,**k:[new])
    state={'sources':{source.id:{'items':[old]}}}
    result=fetch_source_result(source,80,'2026-11-09T16:00:00+09:00',state)
    assert len(result.items)==1
    item=result.items[0]
    assert item['id']==old['id']
    assert item['url']==new.url
    assert compact_state_item(item)['_pnu']['upstream_notice_id']==new.notice_id


def test_registered_transient_source_has_one_bounded_retry_without_relaxing_validation(monkeypatch):
    source=next(s for s in load_sources(Path(__file__).parents[1]/'sources.json') if s.id=='pnu-museum-notices')
    attempts=[]
    def fetch(*a,**k):
        attempts.append(1)
        if len(attempts)==1:
            raise RuntimeError('K2Web catch-up boundary is missing and pagination is unavailable')
        return [Notice(source.id,source.name,source.id+':1765472','전시 안내','https://pnumuseum.pusan.ac.kr/notice','2026-10-23',None,[],[],'hash')]
    monkeypatch.setattr(generator,'fetch_source',fetch)
    monkeypatch.setattr(generator.time,'sleep',lambda _:None)
    result=fetch_source_result(source,80,'2026-11-09T17:40:00+09:00',fetch_attempts=2)
    assert result.status=='ok'
    assert len(attempts)==2
