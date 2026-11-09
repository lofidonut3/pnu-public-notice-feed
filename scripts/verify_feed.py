"""Independent persisted-output verifier. Does not invoke the generator."""
from __future__ import annotations
import argparse
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sys
from xml.etree import ElementTree
import jsonschema

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from scripts.check_feed_health import build_report, Thresholds, SizeSummary


def read(path):
    return json.loads(path.read_text(encoding='utf-8'))


def verify(public_dir, state_path, baseline_dir=None, corrections_path=None, *, structure_only=False):
    issues=[]
    index,events,latest=(read(public_dir/name) for name in ['index.json','events.json','latest.json'])
    state=read(state_path)
    docs={f.stem:read(f) for f in (public_dir/'archive').glob('*.json')}
    items={}
    counts=Counter()
    event_ids=[]
    for month,doc in docs.items():
        for item in doc['items']:
            items[item['id']]=item
            counts[item['id']]+=1
            if item['_archive']['archive_month'] != month:
                issues.append(f"item in wrong archive file: {item['id']}")
        for event in doc['events']:
            event_ids.append(event['event_id'])
    if any(n != 1 for n in counts.values()):
        issues.append('duplicate archived item IDs')
    if len(event_ids)!=len(set(event_ids)):
        issues.append('duplicate durable event IDs')
    for doc in docs.values():
        for event in doc['events']:
            target=event['archive_file'].removeprefix('./archive/').removesuffix('.json')
            if not any(i['id']==event['archive_item_id'] for i in docs.get(target,{}).get('items',[])):
                issues.append(f"broken event archive reference: {event['event_id']}")
    for entry in index['archives']['months']:
        raw=(public_dir/entry['url'].removeprefix('./')).read_bytes()
        if hashlib.sha256(raw).hexdigest()!=entry['sha256']:
            issues.append(f"archive manifest checksum mismatch: {entry['month']}")
    for name,data in [('index',index),('events',events),('latest',latest)]+[('archive-month',d) for d in docs.values()]:
        schema=read(ROOT/'schema'/f'{name}.schema.json')
        validator=jsonschema.validators.validator_for(schema)(schema,format_checker=jsonschema.FormatChecker())
        failures=list(validator.iter_errors(data))
        if failures:
            issues.append(f'schema {name}: {len(failures)} violations')
    for source in state['sources'].values():
        for item in source['items']:
            if item['id'] not in items:
                issues.append(f"state item missing from archive: {item['id']}")
    registry={s['id']:s for s in read(ROOT/'sources.json')['sources']}
    today=datetime.now(timezone.utc).date().isoformat()
    for item in latest['items']:
        if not registry[item['_pnu']['source_id']].get('enabled',True):
            issues.append(f"disabled source in latest: {item['id']}")
        if item['_pnu'].get('content_access',{}).get('availability') in {'superseded','unavailable_after_source_migration'}:
            issues.append(f"unavailable historical item in latest: {item['id']}")
        if (item['_pnu'].get('published_at') or '')[:10]>today:
            issues.append(f"future publication date in latest: {item['id']}")
    ElementTree.parse(public_dir/'rss.xml')
    sizes=SizeSummary(None,None,None,*((public_dir/f).stat().st_size for f in ['index.json','events.json','latest.json']))
    health=build_report(index,events,latest,sizes,Thresholds(100,100,50,0,None,None,1,False))
    if not structure_only:
        issues.extend(health.issues)
    preserved=None
    if baseline_dir:
        old_docs=[read(f) for f in (baseline_dir/'archive').glob('*.json')]
        old_events={e['event_id'] for d in old_docs for e in d['events']}
        if not old_events<=set(event_ids):
            issues.append('previously published event IDs were removed')
        old_items={i['id']:i for d in old_docs for i in d['items']}
        if not set(old_items)<=set(items):
            issues.append('previously archived notice IDs were removed')
        for iid,old in old_items.items():
            if items.get(iid,{}).get('_archive',{}).get('first_seen_at') != old['_archive']['first_seen_at']:
                issues.append(f'first observation changed: {iid}')
        preserved={'published_event_ids':len(old_events),'archived_item_ids':len(old_items)}
    if corrections_path:
        corrections=read(corrections_path)
        for iid,update in corrections['updates'].items():
            item=items[iid]
            if 'published_at' in update and item['_pnu'].get('published_at') != update['published_at']:
                issues.append(f'official date correction missing: {iid}')
            if 'url' in update and item['url'] != update['url']:
                issues.append(f'official library URL correction missing: {iid}')
            if 'content_access' in update and any(item['_pnu'].get('content_access',{}).get(k)!=v for k,v in update['content_access'].items()):
                issues.append(f'historical source availability classification missing: {iid}')
    return {'checked_at':datetime.now(timezone.utc).isoformat(),'generated_at':index['generated_at'],'archive_files':len(docs),'notice_count':len(items),'event_count':len(event_ids),'preserved':preserved,'health_issues':health.issues,'issues':issues,'passed':not issues}


def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--public-dir',type=Path,default=ROOT/'public')
    p.add_argument('--state',type=Path,default=ROOT/'cache/feed-state.json')
    p.add_argument('--baseline-dir',type=Path)
    p.add_argument('--corrections',type=Path)
    p.add_argument('--report',type=Path)
    p.add_argument('--structure-only',action='store_true',help='Validate storage/contracts only; source freshness is reported separately and remains enforced by the monitor.')
    a=p.parse_args(argv)
    report=verify(a.public_dir,a.state,a.baseline_dir,a.corrections,structure_only=a.structure_only)
    serialized=json.dumps(report,ensure_ascii=False,indent=2)
    if a.report:a.report.write_text(serialized,encoding='utf-8')
    print(serialized)
    return 0 if report['passed'] else 1


if __name__=='__main__':
    raise SystemExit(main())
