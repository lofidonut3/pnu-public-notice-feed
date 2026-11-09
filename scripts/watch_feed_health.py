"""Independent read-only freshness check with one bounded collection wake-up."""
from __future__ import annotations
import json
import os
import sys
import time
from datetime import datetime, timezone
from urllib.error import HTTPError
from urllib.request import Request, urlopen
if __package__:
    from .check_feed_health import parse_args, Thresholds, HealthReport, check_feed_health
else:
    from check_feed_health import parse_args, Thresholds, HealthReport, check_feed_health


def wake_collection(repository: str, token: str, *, now: datetime | None = None) -> str:
    """Do not start duplicate runs or repeatedly retry authentication failures."""
    headers = {'Accept':'application/vnd.github+json', 'Authorization':f'Bearer {token}', 'User-Agent':'PNU-feed-watchdog/1.0', 'X-GitHub-Api-Version':'2026-03-10'}
    base = f'https://api.github.com/repos/{repository}/actions/workflows/update-feed.yml'
    with urlopen(Request(base+'/runs?per_page=5', headers=headers), timeout=20) as response:
        runs = json.load(response)['workflow_runs']
    current = now or datetime.now(timezone.utc)
    for run in runs:
        age = (current - datetime.fromisoformat(run['created_at'].replace('Z','+00:00'))).total_seconds()
        if run['status'] in {'queued','in_progress','requested','waiting','pending'} and age < 20*60:
            return 'Collection is already queued or running; no duplicate wake-up.'
    if len(runs) >= 3 and all(run.get('conclusion')=='failure' for run in runs[:3]):
        return 'Automatic wake-up budget exhausted after three failed collection runs; operator action is required.'
    request = Request(base+'/dispatches', data=json.dumps({'ref':'main'}).encode(), method='POST', headers={**headers,'Content-Type':'application/json'})
    with urlopen(request, timeout=20) as response:
        if response.status == 200:
            created = json.load(response)
            run_id = created.get('workflow_run_id')
            if not isinstance(run_id,int) or isinstance(run_id,bool) or run_id < 1:
                raise RuntimeError('Collection wake-up did not return a valid run ID')
        elif response.status == 204:
            run_id = None
        else:
            raise RuntimeError(f'Unexpected collection wake-up status: {response.status}')
    if run_id is not None:
        url=f'https://api.github.com/repos/{repository}/actions/runs/{run_id}'
        for attempt in range(2):
            try:
                with urlopen(Request(url,headers=headers),timeout=20) as response:
                    observed=json.load(response)
                break
            except HTTPError as error:
                # A newly accepted run may not yet be visible. Retry only this
                # read once; never repeat the dispatch or mask access failures.
                if error.code != 404 or attempt:
                    raise
                error.close()
                time.sleep(1)
        if observed.get('id') != run_id or observed.get('event') != 'workflow_dispatch' or observed.get('head_branch') != 'main':
            raise RuntimeError('Collection wake-up read-back did not match the requested workflow')
    return f'Requested one collection run{f" ({run_id})" if run_id else ""}. Freshness must still be verified by the next monitor.'


def main(argv=None):
    args = parse_args(argv)
    thresholds = Thresholds(args.max_degraded_sources,args.max_backoff_sources,args.max_error_sources,args.max_critical_degraded_sources,args.max_public_total_mib,args.max_state_mib,args.min_event_count,args.fail_on_truncated_events,args.max_feed_age_minutes,args.max_source_age_minutes)
    try:
        report = check_feed_health(args.public_dir,args.state_path,args.base_url,args.timeout_seconds,thresholds)
    except Exception as error:
        report = HealthReport(['Published feed could not be inspected.'],[],[f'feed retrieval failed: {type(error).__name__}'])
    print('\n'.join(report.lines))
    for issue in report.issues:
        print(f'ERROR: {issue}', file=sys.stderr)
    exercise_recovery = os.environ.get('PNU_WATCHDOG_EXERCISE_RECOVERY') == '1'
    if report.issues or exercise_recovery:
        token = os.environ.get('GITHUB_TOKEN')
        repository = os.environ.get('GITHUB_REPOSITORY')
        if token and repository:
            try:
                print(wake_collection(repository,token))
            except Exception as error:
                # No response bodies, credentials or request headers in logs.
                detail = f'HTTP {error.code}' if isinstance(error, HTTPError) else type(error).__name__
                print(f'Collection wake-up failed: {detail}',file=sys.stderr)
                return 2
        elif exercise_recovery:
            print('Recovery exercise requires the repository-scoped Actions credential.',file=sys.stderr)
            return 2
        return 1 if report.issues else 0
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
