import io
import json
import pytest
from datetime import datetime,timezone
from urllib.error import HTTPError
from scripts import watch_feed_health as watchdog


class Response(io.BytesIO):
    status=204


@pytest.mark.parametrize('code,readback_recovers', [(404,True),(404,False),(403,False)])
def test_new_run_readback_is_bounded_and_never_repeats_dispatch(monkeypatch,code,readback_recovers):
    calls=[]
    reads=0
    sleeps=[]
    def request(req,timeout):
        nonlocal reads
        calls.append(req)
        if '/actions/runs/123' in req.full_url:
            reads+=1
            if reads==1 or not readback_recovers:
                raise HTTPError(req.full_url,code,'synthetic read-back failure',{},None)
            payload={'id':123,'event':'workflow_dispatch','head_branch':'main'}
        elif req.get_method()=='POST':
            payload={'workflow_run_id':123}
        else:
            payload={'workflow_runs':[]}
        response=Response(json.dumps(payload).encode())
        response.status=200
        return response
    monkeypatch.setattr(watchdog,'urlopen',request)
    monkeypatch.setattr(watchdog.time,'sleep',sleeps.append)
    if readback_recovers:
        assert '(123)' in watchdog.wake_collection('owner/repo','test-credential')
    else:
        with pytest.raises(HTTPError):
            watchdog.wake_collection('owner/repo','test-credential')
    assert sum(call.get_method()=='POST' for call in calls)==1
    assert reads==(2 if code==404 else 1)
    assert sleeps==([1] if code==404 else [])


def test_current_api_dispatch_response_is_read_back_before_success(monkeypatch):
    calls=[]
    replies=[{'workflow_runs':[]},{'workflow_run_id':123},{'id':123,'event':'workflow_dispatch','head_branch':'main'}]
    def request(req,timeout):
        calls.append(req)
        result=Response(json.dumps(replies.pop(0)).encode())
        result.status=200
        return result
    monkeypatch.setattr(watchdog,'urlopen',request)
    assert '(123)' in watchdog.wake_collection('owner/repo','test-credential')
    assert calls[-1].full_url.endswith('/actions/runs/123')
    assert calls[1].headers['X-github-api-version']=='2026-03-10'


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


def test_controlled_recovery_exercise_does_not_claim_success_when_dispatch_fails(monkeypatch):
    from scripts.check_feed_health import HealthReport
    monkeypatch.setattr(watchdog,'check_feed_health',lambda *a:HealthReport(['healthy'],[],[]))
    monkeypatch.setenv('PNU_WATCHDOG_EXERCISE_RECOVERY','1')
    monkeypatch.setenv('GITHUB_REPOSITORY','owner/repo')
    monkeypatch.setenv('GITHUB_TOKEN','test-credential')
    monkeypatch.setattr(watchdog,'wake_collection',lambda *a: (_ for _ in ()).throw(RuntimeError('synthetic failure')))
    assert watchdog.main([])==2
