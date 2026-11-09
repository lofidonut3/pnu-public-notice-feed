import io
import json
from datetime import datetime,timezone
from scripts import watch_feed_health as watchdog


class Response(io.BytesIO):
    status=204


def test_watchdog_dispatches_one_bounded_wake_and_does_not_claim_recovery(monkeypatch):
    calls=[]
    def request(req,timeout):
        calls.append(req)
        return Response(json.dumps({'workflow_runs':[]}).encode())
    monkeypatch.setattr(watchdog,'urlopen',request)
    result=watchdog.wake_collection('owner/repo','test-credential')
    assert len(calls)==2
    assert calls[1].method=='POST'
    assert json.loads(calls[1].data)=={'ref':'main'}
    assert 'must still be verified' in result


def test_watchdog_does_not_duplicate_pending_collection(monkeypatch):
    calls=[]
    def request(req,timeout):
        calls.append(req)
        return Response(json.dumps({'workflow_runs':[{'status':'in_progress','created_at':'2026-11-09T08:00:00Z'}]}).encode())
    monkeypatch.setattr(watchdog,'urlopen',request)
    result=watchdog.wake_collection('owner/repo','test-credential',now=datetime(2026,11,9,8,5,tzinfo=timezone.utc))
    assert len(calls)==1
    assert 'no duplicate' in result


def test_watchdog_stops_automatic_wakes_after_three_failed_runs(monkeypatch):
    calls=[]
    def request(req,timeout):
        calls.append(req)
        return Response(json.dumps({'workflow_runs':[{'status':'completed','conclusion':'failure','created_at':'2026-11-09T00:00:00Z'}]*3}).encode())
    monkeypatch.setattr(watchdog,'urlopen',request)
    result=watchdog.wake_collection('owner/repo','test-credential')
    assert len(calls)==1
    assert 'budget exhausted' in result
