"""Ephemeral runner: all queue state and leases live in the hosted D1 database."""
import argparse
import asyncio
import json
import os
import uuid

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


async def collect(force=False, verify_limit=80, dynamic_budget=24):
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
        failures=0
        try:
            def record(result):
                run['sources'].append(result)
                print(json.dumps({'source':result['id'],'state':result['state'],'count':result['count']}),flush=True)
            candidates,_=await discover(fetcher,renderer,record)
            run['discovered']=len(candidates)
            for start in range(0,len(candidates),40):
                await queue.call('enqueue',token=token,items=[{'event':public_event(e),'priority':20 if e.get('activity_type')=='club' else 0} for e in candidates[start:start+40]])
            await queue.call('progress',token=token,run=run)
            selected=(await queue.call('claim',token=token,limit=verify_limit))['items']
            sem=asyncio.Semaphore(3)
            async def check(item):
                nonlocal failures
                async with sem:
                    e=new_event(**{'url':item['event']['canonical_url'],**{k:v for k,v in item['event'].items() if k!='canonical_url'}})
                    try:
                        result,_=await asyncio.wait_for(verify(e,fetcher,renderer),timeout=75)
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
            # Complete the workers before releasing the run lease, even if one API call fails.
            outcomes=await asyncio.gather(*(check(item) for item in selected),return_exceptions=True)
            errors=[e for e in outcomes if isinstance(e,Exception)]
            if errors:raise errors[0]
            run['state']='partial' if failures or any(s['state'] not in ('ok','disabled') for s in run['sources']) else 'completed'
            if failures:run['error']=f'원문 검증 실패 {failures}건 · 대기열에서 다음 날 재시도'
        except Exception as exc:
            run.update(state='failed',error=(type(exc).__name__+': '+str(exc))[:350])
        finally:
            if renderer:await renderer.close()
            await fetcher.close()
            run['finished_at']=iso_now()
            await queue.call('finish',token=token,run=run)
        return {k:run.get(k) for k in ('run_id','state','discovered','verified','error','run_url')}


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--force',action='store_true')
    args=parser.parse_args()
    result=asyncio.run(collect(args.force))
    print(json.dumps(result,ensure_ascii=False),flush=True)
    if result.get('state')=='failed':raise SystemExit(1)


if __name__=='__main__':main()
