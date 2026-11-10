import unittest
from app.access_policy import assert_collection_allowed
from app.sources import SOURCES
from app.batch_common import public_event

class AccessPolicyTests(unittest.TestCase):
    def test_blocked_host_and_subdomain(self):
        for url in ['https://redis.io/events/x','https://x.devpost.com/','https://blog.jetbrains.com/','https://dev-korea.com/events','https://jumpit.saramin.co.kr/event/x','https://holaworld.io/study/x','https://www.startupjobs.kr/events','https://www.nvidia.com/events','https://aws.amazon.com/events']:
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
