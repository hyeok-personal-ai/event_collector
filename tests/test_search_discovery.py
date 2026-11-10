import asyncio
import os
import unittest
from unittest.mock import patch

from app.sources import SOURCES, search_candidate, search_queries, discover_search_api


class SearchDiscoveryTests(unittest.TestCase):
    def test_restricted_and_disabled_sources_cannot_reenter_from_search(self):
        for url in (
            'https://www.wanted.co.kr/events/test',
            'https://www.rocketpunch.com/events/test',
            'https://holaworld.io/study/abcdef123456',
            'https://www.team-pik.com/team/test',
            'https://disquiet.io/post/test',
        ):
            with self.subTest(url=url):
                self.assertIsNone(search_candidate({'url':url,'title':'개발 프로젝트 모집'}))

    def test_allowed_candidate_preserves_origin_without_copied_snippet(self):
        e=search_candidate({'url':'https://www.inflearn.com/studies/123456',
                            'title':'Python 개발 스터디 모집','description':'ORIGINAL POST AND PRIVATE CONTACT'})
        self.assertEqual(e['status'],'CHECK_REQUIRED')
        self.assertEqual(e['activity_type'],'study')
        self.assertEqual(e['discovery_source'],'inflearn_studies')
        self.assertEqual(e['discovery_url'],e['canonical_url'])
        self.assertEqual(e['summary'],'')
        self.assertIsNone(e['last_verified_at'])

    def test_query_targets_follow_current_enabled_sources(self):
        queries=' '.join(search_queries())
        self.assertIn('site:www.inflearn.com',queries)
        for name in ('holaworld.io','dacon.io','wanted.co.kr','rocketpunch.com','disquiet.io'):
            self.assertNotIn('site:'+name,queries)
        with patch('app.sources.SOURCES',[s for s in SOURCES if s.id!='inflearn_studies' and s.id!='inflearn_projects']):
            self.assertNotIn('inflearn.com',' '.join(search_queries()))

    def test_no_key_never_claims_gpt_automation_is_connected(self):
        with patch.dict(os.environ,{},clear=True):
            events,status=asyncio.run(discover_search_api(None))
        self.assertEqual(events,[])
        self.assertEqual(status['state'],'disabled')

    def test_unknown_unsafe_or_fake_host_cannot_enter_queue(self):
        for value in ({'url':'https://inflearn.com.evil.example/studies/123'},
                      {'url':'javascript:alert(1)'},{'url':'http://127.0.0.1/studies/123'},
                      {'url':None},None):
            self.assertIsNone(search_candidate(value))
