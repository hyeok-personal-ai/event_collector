import os
import asyncio
import unittest
from unittest.mock import patch
from app.sources import SOURCES, extract_links
from app.core import canonical
from app.batch_common import public_event
from app.batch_key import read_key

class PublicCollectorTests(unittest.TestCase):
    def test_catalog_replacements_are_active(self):
        sources={s.id:s for s in SOURCES}
        self.assertEqual(len(sources),len(SOURCES))
        for s in SOURCES:
            if not s.enabled:
                self.assertTrue(s.note)
                self.assertTrue(s.replacements)
            for replacement in s.replacements:
                self.assertTrue(sources[replacement].enabled)

    def test_luma_navigation_is_not_an_event(self):
        source=next(s for s in SOURCES if s.id=='openai')
        items=extract_links('<a href="/ai?k=t">Featured in AI</a><a class="event-link" aria-label="Codex workshop" href="/workshop"></a>',source.url,source)
        self.assertEqual([e['title'] for e in items],['Codex workshop'])
        self.assertEqual(items[0]['status'],'CHECK_REQUIRED')

    def test_public_payload_excludes_private_fields(self):
        payload=public_event({'title':'Public event','canonical_url':'https://example.com/event','profile':{'age':25},'saved':True,'raw_excerpt':'private','secret':'private'})
        self.assertFalse({'profile','saved','raw_excerpt','secret'} & payload.keys())

    def test_credentials_require_environment(self):
        with patch.dict(os.environ,{},clear=True):
            with self.assertRaises(RuntimeError):read_key()

    def test_tracking_does_not_duplicate_event(self):
        self.assertEqual(canonical('https://www.meetup.com/awskrug/events/123/?eventOrigin=group'),'https://www.meetup.com/awskrug/events/123')

    def test_unapproved_destination_is_rejected_before_reading_secret(self):
        from app import cloud_batch
        with patch.object(cloud_batch,'SITE','https://example.com'),patch.object(cloud_batch,'read_key') as key:
            with self.assertRaises(RuntimeError):asyncio.run(cloud_batch.collect())
            key.assert_not_called()

    def test_non_main_branch_is_rejected_before_reading_secret(self):
        from app import cloud_batch
        with patch.object(cloud_batch,'SITE','https://tech-event-radar-kr.qkdrhkgn123.chatgpt.site'),patch.dict(os.environ,{'GITHUB_REPOSITORY':'hyeok-personal-ai/event_collector','GITHUB_RUN_ID':'123','GITHUB_REF':'refs/heads/other'}),patch.object(cloud_batch,'read_key') as key:
            with self.assertRaises(RuntimeError):asyncio.run(cloud_batch.collect())
            key.assert_not_called()

    def test_daily_run_drains_multiple_pages(self):
        from app import cloud_batch as batch
        from app.core import new_event
        calls=[]
        async def call(self,action,**data):
            calls.append((action,data))
            if action=='start':return {'state':'started','run':{'run_id':data['token'],'sources':[],'verified':0}}
            if action=='prepare':return {'stats':{'due':0}}
            if action=='claim':
                page=data['batch']
                return {'items':[{'id':str(page),'event':new_event('https://example.com/'+str(page),'Event')} ] if page<2 else []}
            return {'state':'saved'}
        async def discover(fetcher,renderer,record):
            record({'id':'test','state':'ok','count':2});return [],[]
        async def verify(event,*args):return event,''
        with patch.object(batch,'SITE','https://tech-event-radar-kr.qkdrhkgn123.chatgpt.site'),patch.dict(os.environ,{'GITHUB_REPOSITORY':'hyeok-personal-ai/event_collector','GITHUB_RUN_ID':'123','GITHUB_REF':'refs/heads/main'}),patch.object(batch,'read_key',return_value='test-only'),patch.object(batch.RemoteQueue,'call',call),patch.object(batch,'discover',discover),patch.object(batch,'verify',verify):
            result=asyncio.run(batch.collect(dynamic_budget=0))
        self.assertEqual(result['verified'],2)
        self.assertEqual([d['batch'] for a,d in calls if a=='claim'],[0,1,2])
        self.assertEqual(calls[-1][0],'finish')

if __name__=='__main__':unittest.main()
