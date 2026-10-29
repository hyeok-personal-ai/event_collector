import asyncio
import json
import unittest
from unittest.mock import patch
import httpx
from app.core import new_event
from app.collector import verify
from app.route_resolver import observe, same_event

TITLE='Example Developer Conference 2027'
ORIGINAL='https://organizer.example/broken'
ALTERNATE='https://tickets.example/same-event'
PROOF='https://organizer.example/events'


class Fetcher:
    def __init__(self, year=2027, date='2027-01-15', official=True):
        self.seen=[]
        self.year=year
        self.date=date
        self.route_candidates=[new_event(ALTERNATE,title=TITLE)]
        self.official_pages={}
        page=PROOF if official else 'https://untrusted.example/events'
        observe(self,httpx.Response(200,headers={'content-type':'text/html'},
            text=f'<a href="{ALTERNATE}">{TITLE}</a>',request=httpx.Request('GET',page)))

    async def page(self,url):
        self.seen.append(url)
        if url==ORIGINAL:
            raise ValueError('HTTP 403')
        if url==ALTERNATE:
            obj={'@type':'Event','name':TITLE.replace('2027',str(self.year)),'startDate':self.date}
            html=f'<script type="application/ld+json">{json.dumps(obj)}</script><h1>{obj["name"]}</h1>'
        else:
            html='<title>Official home</title>'
        return httpx.Response(200,headers={'content-type':'text/html'},text=html,request=httpx.Request('GET',url))


class RouteResolverTests(unittest.TestCase):
    def setUp(self):
        self.trust=patch('app.route_resolver.official_hosts',return_value={'organizer.example'})
        self.trust.start()
        self.addCleanup(self.trust.stop)
        self.event=new_event(ORIGINAL,title=TITLE,start_at='2027-01-15')

    def check(self,fetcher,event=None):
        return asyncio.run(verify(event or self.event,fetcher))[0]

    def test_blocked_original_switches_with_official_outgoing_link(self):
        f=Fetcher();r=self.check(f)
        self.assertEqual(r['canonical_url'],ORIGINAL)
        self.assertEqual(r['id'],self.event['id'])
        self.assertEqual(r['verification_url'],ALTERNATE)
        self.assertEqual(r['collection_route']['proof_url'],PROOF)
        self.assertEqual(r['collection_route']['state'],'alternate')
        self.assertFalse(r['failure_count'])

    def test_aggregator_match_is_not_official_proof(self):
        f=Fetcher(official=False);r=self.check(f)
        self.assertEqual(r['collection_route']['state'],'review')
        self.assertNotIn(ALTERNATE,f.seen)
        self.assertIn('대체 원문 점검 필요',r['evidence'])

    def test_wrong_annual_edition_or_day_is_review(self):
        for f in (Fetcher(year=2026),Fetcher(date='2027-01-16'),Fetcher(date=None)):
            r=self.check(f)
            self.assertEqual(r['collection_route']['state'],'review')
            self.assertEqual(r['start_at'],'2027-01-15')
            self.assertEqual(r['collection_route']['attempts'][-1]['outcome'],'mismatch')

    def test_confirmed_route_reused_without_blocked_original(self):
        event=self.check(Fetcher())
        f=Fetcher();r=self.check(f,event)
        self.assertEqual(r['collection_route']['state'],'alternate')
        self.assertNotIn(ORIGINAL,f.seen)

    def test_missing_official_link_does_not_reuse_untrusted_platform(self):
        event=self.check(Fetcher())
        f=Fetcher(official=False);r=self.check(f,event)
        self.assertEqual(r['collection_route']['state'],'review')
        self.assertNotIn(ORIGINAL,f.seen)

    def test_manual_route_overrides_review_and_preserves_identity(self):
        event={**self.event,'_manual_route':{'url':ALTERNATE,'proof_url':ALTERNATE}}
        f=Fetcher();r=self.check(f,event)
        self.assertEqual(r['collection_route']['state'],'alternate')
        self.assertEqual(r['id'],event['id'])
        self.assertNotIn(ORIGINAL,f.seen)

    def test_manual_wrong_event_returns_review(self):
        event={**self.event,'_manual_route':{'url':ALTERNATE,'proof_url':ALTERNATE}}
        r=self.check(Fetcher(year=2026),event)
        self.assertEqual(r['collection_route']['state'],'review')
        self.assertTrue(r['failure_count'])

    def test_manual_proof_requires_actual_link(self):
        event={**self.event,'_manual_route':{'url':ALTERNATE,'proof_url':PROOF}}
        r=self.check(Fetcher(),event)
        self.assertEqual(r['collection_route']['state'],'review')
        self.assertIn('연결되는 링크',r['evidence'])

    def test_dates_must_be_independent(self):
        self.assertFalse(same_event(self.event,{'title':TITLE}))
        self.assertFalse(same_event(self.event,{'title':TITLE+' 2','start_at':'2027-01-15'}))


if __name__=='__main__':
    unittest.main()
