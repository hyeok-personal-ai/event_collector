import unittest
from datetime import date
from unittest.mock import AsyncMock

import httpx

from app.contest_sources import HACKALENDAR_URL, hackalendar_candidates, mois_application_window, mois_notice_url


class ContestSourceTests(unittest.IsolatedAsyncioTestCase):
    def test_korean_application_dates_are_not_event_dates(self):
        self.assertEqual(mois_application_window(
            '참가자는 8 월 26 일 ( 수 ) 부터 9 월 29 일 ( 화 ) 까지 모델을 제출할 수 있다.', 2026),
            (date(2026, 8, 26), date(2026, 9, 29)))
        self.assertIsNone(mois_application_window('본선 일시는 12 월 1 일부터 12 월 2 일까지이다.', 2026))
        self.assertIsNone(mois_notice_url('https://other.example/frt/bbs/type010/commonSelectBoardArticle.do?bbsId=BBSMSTR_000000000008&nttId=123'))

    async def test_hackalendar_feed_cannot_reenable_restricted_hosts_or_declare_open(self):
        instance = AsyncMock()
        base = dict(status='published', name='Organized hackathon', description='Original description')
        instance.page.return_value = httpx.Response(
            200, request=httpx.Request('GET', HACKALENDAR_URL),
            json={'data': [{**base, 'registrationUrl': 'https://lu.ma/example'},
                           {**base, 'registrationUrl': 'https://example.org/event'}]})
        event, = await hackalendar_candidates(instance)
        self.assertEqual(event['canonical_url'], 'https://example.org/event')
        self.assertEqual(event['status'], 'CHECK_REQUIRED')
        self.assertEqual(event['summary'], '')
