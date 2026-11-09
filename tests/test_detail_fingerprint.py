import pytest
from pnu_notice_feed.detail_fingerprint import body_fingerprint, is_detail_baseline_only


def test_body_only_edit_changes_fingerprint_but_site_chrome_does_not():
    before='<div>조회 12</div><div class="view viewCont"><p>신청 마감 11월 10일</p></div>'
    chrome=before.replace('조회 12','조회 99')
    after=before.replace('마감 11월 10일','마감 11월 20일')
    assert body_fingerprint(before)==body_fingerprint(chrome)
    assert body_fingerprint(before)!=body_fingerprint(after)


def test_unknown_detail_layout_fails_explicitly():
    with pytest.raises(ValueError,match='container'):
        body_fingerprint('<div>접근 권한이 없습니다.</div>')


def test_alternate_official_nano_article_template_is_supported():
    assert body_fingerprint('<div class="artclView"><div id="hwpEditorBoardContent">장학금 신청 안내</div></div>')


def test_initial_fingerprint_is_metadata_baseline_not_a_notice_edit():
    old={'title':'공지','url':'https://cse.pusan.ac.kr/notice','_pnu':{'published_at':'2026-11-09'}}
    new={**old,'_pnu':{**old['_pnu'],'detail_content_hash':'new'}}
    assert is_detail_baseline_only(old,new)
    assert not is_detail_baseline_only(old,{**new,'title':'수정된 공지'})
