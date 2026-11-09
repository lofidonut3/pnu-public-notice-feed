"""Apply independently captured metadata corrections without replaying notices.

This command does not fetch pages or emit notifications. Canonical item IDs,
event IDs and observation timestamps are immutable. Run dry first; pass --apply
only after reviewing the JSON change summary and retaining a Git snapshot.
"""
from __future__ import annotations
import argparse
import copy
from datetime import datetime
import hashlib
import json
from pathlib import Path
import re
import sys
from urllib.parse import urlparse

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from pnu_notice_feed.archive import read_archive_docs, rebuild_archive_doc, sync_event_metadata_with_items, write_json_if_changed


def repair_documents(state, docs, corrections, source_adapters):
    state, docs = copy.deepcopy(state), copy.deepcopy(docs)
    original_docs = copy.deepcopy(docs)
    original_ids = {i['id'] for d in docs.values() for i in d['items']}
    original_events = {e['event_id'] for d in docs.values() for e in d['events']}
    changed = set()
    changed_fields = {}

    def fix(item):
        iid = item['id']
        pnu = item.setdefault('_pnu', {})
        source_id = pnu['source_id']
        correction = corrections.get('updates', {}).get(iid, {})
        fields = []
        if correction:
            host = urlparse(correction['evidence_url']).hostname or ''
            if not (host == 'pusan.ac.kr' or host.endswith('.pusan.ac.kr')):
                raise ValueError(f'Correction evidence is not an official PNU URL: {iid}')
        if 'published_at' in correction:
            value = correction['published_at']
            datetime.strptime(value, '%Y-%m-%d')
            if pnu.get('published_at') != value:
                pnu['published_at'] = value
                item['date_published'] = value+'T00:00:00+09:00'
                fields.append('published_at')
        if 'url' in correction and item.get('url') != correction['url']:
            item['url'] = correction['url']
            access = pnu.setdefault('content_access', {})
            access['detail_url'] = correction['url']
            fields.append('url')
        if 'upstream_notice_id' in correction:
            pnu['upstream_notice_id'] = correction['upstream_notice_id']
        if 'content_access' in correction:
            access=pnu.setdefault('content_access', {})
            if any(access.get(k)!=v for k,v in correction['content_access'].items()):
                access.update(correction['content_access'])
                fields.append('content_access')
        if source_adapters.get(source_id) == 'k2web-board':
            clean = re.sub(r'\s+새글\s*$', '', item['title']).strip()
            if clean != item['title']:
                item['title'] = clean
                fields.append('title_ui_badge')
            if fields:
                pnu['content_hash'] = hashlib.sha256(f"{item['title']}\n{pnu.get('published_at') or ''}\n{item['url']}".encode()).hexdigest()
                if pnu.get('detail_content_hash'):
                    pnu['content_hash'] = hashlib.sha256(f"{pnu['content_hash']}\n{pnu['detail_content_hash']}".encode()).hexdigest()
        if fields:
            changed.add(iid)
            changed_fields[iid] = fields
            if '_archive' in item:
                item['_archive']['current_content_hash'] = pnu.get('content_hash')
                item['_archive']['metadata_corrected_at'] = corrections['captured_at']
        return fields

    for source in state['sources'].values():
        for item in source.get('items', []):
            fix(item)
    moved = []
    for month, doc in list(docs.items()):
        retained = []
        for item in doc['items']:
            fix(item)
            target = (item['_pnu'].get('published_at') or month)[:7]
            if item['id'] in corrections.get('updates', {}) and target != month:
                item['_archive']['archive_month'] = target
                moved.append((target,item))
            else:
                retained.append(item)
        doc['items'] = retained
        for event in doc['events']:
            update = corrections.get('updates', {}).get(event.get('archive_item_id'), {})
            if 'published_at' in update:
                event['published_at'] = update['published_at']
            if 'url' in update:
                event['url'] = update['url']
    for target,item in moved:
        docs.setdefault(target, {'items':[], 'events':[]})['items'].append(item)
    docs = sync_event_metadata_with_items(docs)
    for month, doc in docs.items():
        if doc != original_docs.get(month):
            docs[month] = rebuild_archive_doc(month,doc,corrections['captured_at'])
    assert {i['id'] for d in docs.values() for i in d['items']} == original_ids
    assert {e['event_id'] for d in docs.values() for e in d['events']} == original_events
    return state,docs,{'corrected_item_count':len(changed),'moved_item_count':len(moved),'changed_fields':changed_fields,'item_ids_preserved':True,'event_ids_preserved':True}


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--public-dir',type=Path,default=Path('public'))
    parser.add_argument('--state',type=Path,default=Path('cache/feed-state.json'))
    parser.add_argument('--corrections',type=Path,required=True)
    parser.add_argument('--sources',type=Path,default=Path('sources.json'))
    parser.add_argument('--apply',action='store_true')
    args=parser.parse_args(argv)
    state=json.loads(args.state.read_text(encoding='utf-8'))
    docs=read_archive_docs(args.public_dir/'archive')
    corrections=json.loads(args.corrections.read_text(encoding='utf-8'))
    adapters={s['id']:s['adapter'] for s in json.loads(args.sources.read_text(encoding='utf-8'))['sources']}
    new_state,new_docs,summary=repair_documents(state,docs,corrections,adapters)
    summary['apply']=args.apply
    if args.apply:
        for month,doc in new_docs.items():
            write_json_if_changed(args.public_dir/'archive'/f'{month}.json',doc,True)
        write_json_if_changed(args.state,new_state,True)
    print(json.dumps(summary,ensure_ascii=False,indent=2))
    return 0


if __name__=='__main__':
    raise SystemExit(main())
