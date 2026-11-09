from scripts.repair_feed_metadata import repair_documents


def test_official_date_repair_moves_item_and_preserves_cursor_and_first_observation():
    item={'id':'cse:1388562','title':'졸업 서류 제출 ~2027.1.8.',
        'url':'https://cse.pusan.ac.kr/bbs/cse/2055/1388562/artclView.do',
        '_pnu':{'source_id':'cse','published_at':'2027-01-08','content_hash':'bad'},
        '_archive':{'archive_month':'2027-01','first_seen_at':'2026-10-28T00:00:00+09:00','current_content_hash':'bad'}}
    event={'event_id':'durable-cursor','event_type':'added','notice_id':item['id'],'archive_item_id':item['id'],'source_id':'cse','seen_at':'2026-10-28T00:00:00+09:00','published_at':'2027-01-08'}
    state={'sources':{'cse':{'items':[item]}}}
    docs={'2027-01':{'items':[item],'events':[]},'2026-10':{'items':[],'events':[event]}}
    corrections={'captured_at':'2026-11-09T00:00:00+09:00','updates':{item['id']:{'published_at':'2023-12-12','evidence_url':item['url']}}}
    repaired,archives,summary=repair_documents(state,docs,corrections,{'cse':'k2web-board'})
    assert archives['2023-12']['items'][0]['_archive']['first_seen_at']==item['_archive']['first_seen_at']
    fixed_event=archives['2026-10']['events'][0]
    assert fixed_event['event_id']=='durable-cursor'
    assert fixed_event['archive_file']=='./archive/2023-12.json'
    assert fixed_event['published_at']=='2023-12-12'
    assert summary['corrected_item_count']==1
    assert repaired['sources']['cse']['items'][0]['_pnu']['published_at']=='2023-12-12'
    again,again_archives,again_summary=repair_documents(repaired,archives,corrections,{'cse':'k2web-board'})
    assert again==repaired
    assert again_archives==archives
    assert again_summary['corrected_item_count']==0
