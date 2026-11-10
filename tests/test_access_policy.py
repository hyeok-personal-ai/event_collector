import unittest
from app.access_policy import assert_collection_allowed
from app.sources import SOURCES
from app.batch_common import public_event

class AccessPolicyTests(unittest.TestCase):
    def test_blocked_host_and_subdomain(self):
        for url in ['https://redis.io/events/x','https://x.devpost.com/','https://blog.jetbrains.com/','https://dev-korea.com/events','https://jumpit.saramin.co.kr/event/x']:
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
