from urllib.parse import urlsplit
"""Ephemeral runner: all queue state and leases live in the hosted D1 database."""
import argparse
import asyncio
import json
import os
import uuid
import time

import httpx
from .batch_common import public_event, preserve_club_status
from .batch_key import read_key
from .core import new_event, iso_now
from .sources import discover
from .collector import Fetcher, verify
from .browser import BrowserRenderer

SITE=os.environ.get('RADAR_SITE_URL','').rstrip('/')


class RemoteQueue:
    def __init__(self, client):
        self.client = client

    async def call(self, action, **payload):
        # Retries reuse byte-identical payloads, including report timestamps and run IDs.
        for attempt in range(3):
            try:
                response = await self.client.post(SITE+'/api/collector', json={'action': action, **payload})
                response.raise_for_status()
                return response.json()
            except (httpx.TransportError, httpx.HTTPStatusError) as exc:
                if isinstance(exc, httpx.HTTPStatusError) and exc.response.status_code < 500:
                    raise RuntimeError(f'Collector API {exc.response.status_code}: {exc.response.text[:500]}') from None
                if attempt == 2:
                    raise
                await asyncio.sleep(2**attempt)


async def collect(force=False, verify_limit=1000, dynamic_budget=64, time_budget=1800, cleanup_timeout=15):
    if SITE != 'https://tech-event-radar-kr.qkdrhkgn123.chatgpt.site':
        raise RuntimeError('RADAR_SITE_URL must match the approved Radar backend')
    run_id = os.environ.get('GITHUB_RUN_ID')
    repo = os.environ.get('GITHUB_REPOSITORY')
    if repo != 'hyeok-personal-ai/event_collector' or os.environ.get('GITHUB_REF') != 'refs/heads/main' or not run_id or not run_id.isdigit():
        raise RuntimeError('Cloud collection must run from the configured GitHub Actions repository')
    token = 'gha-'+run_id+'-'+os.environ.get('GITHUB_RUN_ATTEMPT','1')+'-'+uuid.uuid4().hex[:8]
    async with httpx.AsyncClient(headers={'Authorization':'Bearer '+read_key()},timeout=45,follow_redirects=False,trust_env=False) as client:
        queue=RemoteQueue(client)
        started=await queue.call('start',token=token,force=force,run_url=f'https://github.com/{repo}/actions/runs/{run_id}')
        if started['state']!='started':return started
        run=started['run']
        fetcher=Fetcher();renderer=BrowserRenderer(fetcher,budget=dynamic_budget) if dynamic_budget else None
        cleanup_failed=False
        failures=0
        attempted=0
        deadline=time.monotonic()+time_budget
        try:
            def record(result):
                run['sources'].append(result)
                print(json.dumps({'source':result['id'],'state':result['state'],'count':result['count']}),flush=True)
            candidates,_=await discover(fetcher,renderer,record)
            run['discovered']=len(candidates)
            for start in range(0,len(candidates),40):
                await queue.call('enqueue',token=token,items=[{'event':public_event(e),'priority':20 if e.get('activity_type')=='club' else 0} for e in candidates[start:start+40]])
            await queue.call('progress',token=token,run=run)
            await queue.call('prepare',token=token)
            sem=asyncio.Semaphore(6)
            host_locks={}
            async def check(item):
                nonlocal failures
                host=urlsplit(item['event']['canonical_url']).hostname
                async with sem, host_locks.setdefault(host,asyncio.Lock()):
                    e=new_event(**{'url':item['event']['canonical_url'],**{k:v for k,v in item['event'].items() if k!='canonical_url'}})
                    try:
                        result,_=await asyncio.wait_for(verify(e,fetcher,renderer),timeout=max(1,min(60,deadline-time.monotonic())))
                        if e.get('activity_type')=='club':result['activity_type']='club'
                        result=preserve_club_status(result)
                        if result.get('failure_count'):
                            raise ValueError(result.get('evidence','Verification failed'))
                        await queue.call('complete',token=token,id=item['id'],event=public_event(result),reported_at=iso_now())
                        run['verified']+=1
                    except Exception as exc:
                        failures+=1
                        await queue.call('fail',token=token,id=item['id'],error=(type(exc).__name__+': '+str(exc))[:350])
                        print(json.dumps({'verification_failed':item['id'],'type':type(exc).__name__}),flush=True)
            batch=0
            while attempted<verify_limit and time.monotonic()<deadline-10:
                selected=(await queue.call('claim',token=token,batch=batch,limit=min(40,verify_limit-attempted)))['items']
                if not selected:break
                outcomes=await asyncio.gather(*(check(item) for item in selected),return_exceptions=True)
                errors=[e for e in outcomes if isinstance(e,Exception)]
                if errors:raise errors[0]
                attempted+=len(selected);batch+=1
                run['attempted']=attempted
                await queue.call('progress',token=token,run=run)
            remaining=(await queue.call('prepare',token=token))['stats']
            run['deferred']=remaining['due']
            run['state']='partial' if failures or remaining['due'] or any(s['state'] not in ('ok','disabled') for s in run['sources']) else 'completed'
            messages=[]
            if failures:messages.append(f'원문 검증 실패 {failures}건 · 원인별 지연 재시도/점검 대기')
            if remaining['due']:messages.append(f"실행 예산 내 미처리 {remaining['due']}건 · 다음 배치 우선순위 유지")
            if messages:run['error']=' / '.join(messages)
        except Exception as exc:
            run.update(state='failed',error=(type(exc).__name__+': '+str(exc))[:350])
        finally:
            if renderer:
                try:
                    await asyncio.wait_for(renderer.close(),timeout=cleanup_timeout)
                except Exception as exc:
                    cleanup_failed=True
                    if run['state']!='failed':run['state']='partial'
                    run['error']=((run.get('error') or '')+' / 브라우저 종료 실패: '+type(exc).__name__).strip(' /')
            await fetcher.close()
            run['finished_at']=iso_now()
            await queue.call('finish',token=token,run=run)
        return {**{k:run.get(k) for k in ('run_id','state','discovered','verified','error','run_url')},'cleanup_failed':cleanup_failed}


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--force',action='store_true')
    args=parser.parse_args()
    result=asyncio.run(collect(args.force))
    print(json.dumps(result,ensure_ascii=False),flush=True)
    if result.get('cleanup_failed'):
        # Dedicated GitHub CLI only: results are persisted and stdout flushed above.
        # A stuck Playwright executor must not hold Python's interpreter shutdown.
        os._exit(1)
    if result.get('state')=='failed':raise SystemExit(1)


if __name__=='__main__':main()
