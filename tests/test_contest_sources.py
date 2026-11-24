import unittest
from datetime import date, datetime
from unittest.mock import AsyncMock, patch

import httpx

from app.contest_sources import HACKALENDAR_URL, SEOUL_HACKATHON, hackalendar_candidates, mois_application_window, mois_notice_url, verify_seoul_hackathon
from app.core import KST


class ContestSourceTests(unittest.IsolatedAsyncioTestCase):
    async def test_seoul_hackathon_uses_official_window(self):
        fetcher = AsyncMock()
        fetcher.page.return_value = httpx.Response(
            200, request=httpx.Request('GET', SEOUL_HACKATHON),
            text='<h1>Dopamine Seoul 24</h1><td data-bind-type="receiptDate">2026-11-18 08:00 ~ 2026-12-07 23:59</td>')
        for current, expected in ((datetime(2026, 11, 24, tzinfo=KST), 'OPEN'),
                                  (datetime(2026, 12, 7, 23, 59, tzinfo=KST), 'CLOSED')):
            with patch('app.contest_sources.now', return_value=current):
                result = await verify_seoul_hackathon({'canonical_url': SEOUL_HACKATHON}, fetcher)
            self.assertEqual(result['status'], expected)
            self.assertEqual(result['apply_deadline'], '2026-12-07T23:59:00+09:00')

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
