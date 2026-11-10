import unittest
from app.access_policy import assert_collection_allowed
from app.sources import SOURCES
from app.batch_common import public_event

class AccessPolicyTests(unittest.TestCase):
    def test_blocked_host_and_subdomain(self):
        for url in ['https://raw.githubusercontent.com/brave-people/Dev-Event/master/README.md','https://redis.io/events/x','https://x.devpost.com/','https://blog.jetbrains.com/','https://dev-korea.com/events','https://jumpit.saramin.co.kr/event/x','https://holaworld.io/study/x','https://www.startupjobs.kr/events','https://www.nvidia.com/events','https://aws.amazon.com/events']:
            with self.assertRaises(ValueError):assert_collection_allowed(url)
        assert_collection_allowed('https://notredis.io/study')
    def test_source_disabled(self):
        for s in SOURCES:
            if s.id in ('redis','devpost','devkorea','jetbrains','jumpit'):self.assertFalse(s.enabled)
    def test_description_is_facts_and_input_unchanged(self):
        e={'title':'Study','summary':'ORIGINAL POST BODY','activity_type':'study','location':'Online','price':'무료'}
        result=public_event(e)
        self.assertNotIn('ORIGINAL',result['summary'])
        self.assertEqual(e['summary'],'ORIGINAL POST BODY')
    def test_structured_location_preserves_country_and_virtual_mode(self):
        from app.collector import location_facts
        f=location_facts({'location':{'@type':'Place','name':'Coworking venue','address':{'addressLocality':'Taipei','addressCountry':{'@type':'Country','name':'TW'}}}})
        self.assertEqual(f['country_code'],'TW')
        self.assertIn('Taipei',f['location'])
        self.assertEqual(location_facts({'location':{'@type':'VirtualLocation','name':'Zoom'}})['attendance_mode'],'online')
        self.assertEqual(location_facts({'location':[{'@type':'VirtualLocation'},{'@type':'Place','name':'Seoul venue'}]})['attendance_mode'],'hybrid')
        self.assertIsNone(location_facts({'location':{'name':'Secret venue'}})['country_code'])

    def test_shortlink_robots_unavailable_is_not_access_denied(self):
        import asyncio, httpx
        from unittest.mock import AsyncMock
        from app.collector import Fetcher
        async def check():
            f=Fetcher()
            try:
                f.request=AsyncMock(return_value=httpx.Response(400,text='Invalid Dynamic Link'))
                await f.allowed('https://forms.gle/publicForm')
                for code in [401,403,429,500]:
                    f.robots.clear()
                    f.request=AsyncMock(return_value=httpx.Response(code,text='Access denied'))
                    with self.assertRaises(ValueError): await f.allowed('https://forms.gle/publicForm')
                f.robots.clear()
                f.request=AsyncMock(return_value=httpx.Response(400,text='Access denied'))
                with self.assertRaises(ValueError): await f.allowed('https://forms.gle/publicForm')
                f.request=AsyncMock(return_value=httpx.Response(200,text='User-agent: *\nDisallow: /private'))
                with self.assertRaises(ValueError): await f.allowed('https://docs.google.com/private')
            finally: await f.close()
        asyncio.run(check())


import asyncio
import unittest
from app.access_policy import assert_collection_allowed, assert_event_collection_allowed
from app.collector import verify
from app.core import new_event
from app.sources import SOURCES


class RestrictedSourceTests(unittest.TestCase):
    def test_restricted_details_cannot_reenter_through_another_source(self):
        for host in ('programmers.co.kr', 'daker.ai', 'dacon.io', 'aifactory.space', 'partiful.com', 'linkedin.com', 'onoffmix.com'):
            with self.subTest(host=host):
                with self.assertRaises(ValueError):
                    assert_collection_allowed('https://www.'+host+'/events/example')
        assert_collection_allowed('https://programmers.co.kr.example.org/event')
        assert_collection_allowed('https://example.org/programmers.co.kr')

    def test_held_provenance_blocks_before_fetch_or_alternative_lookup(self):
        class NoNetwork:
            async def page(self, url):
                raise AssertionError('restricted-origin event must not be fetched')
        event=new_event('https://example.org/public-event', 'Community meetup')
        for provenance in ({'discovery_source':'programmers'}, {'discovery_url':'https://daker.ai/public/hackathons/a'}):
            with self.subTest(provenance=provenance), self.assertRaises(ValueError):
                asyncio.run(verify({**event, **provenance}, NoNetwork()))

    def test_restricted_source_catalog_and_provenance_are_consistent(self):
        from app.access_policy import RESTRICTED_SOURCES
        for source in SOURCES:
            if source.id in RESTRICTED_SOURCES:
                self.assertFalse(source.enabled, source.id)
        with self.assertRaises(ValueError):
            assert_collection_allowed('https://github.com/brave-people/%44ev-Event/blob/master/README.md')
        assert_event_collection_allowed({'canonical_url':'https://example.org/a','discovery_source':'eventus'})
