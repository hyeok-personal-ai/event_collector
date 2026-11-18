import unittest
from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch

import httpx

from app.official_programs import CNCF_DOCS, CNCF_TREE, DALE_URL, cncf_window, verify_program
from app.sources import discover


TERM = 'programs/lfx-mentorship/2027/01-Mar-May/README.md'
WINDOW = '| Mentee Applications Open | Wed, Feb 3, 00:00 UTC – Tue, Feb 16, 23:59 UTC |'


class OfficialProgramTests(unittest.IsolatedAsyncioTestCase):
    async def test_official_date_window_uses_utc(self):
        fetcher = AsyncMock()
        fetcher.github_api.return_value = httpx.Response(200, text=WINDOW, request=httpx.Request('GET', CNCF_TREE))
        for day, status in [(2, 'CHECK_REQUIRED'), (3, 'OPEN'), (17, 'CLOSED')]:
            with self.subTest(day=day), patch('app.official_programs.now', return_value=datetime(2027, 2, day, tzinfo=timezone.utc)):
                event = await verify_program({'canonical_url': CNCF_DOCS + TERM}, fetcher)
                self.assertEqual(event['status'], status)
                self.assertEqual(event['apply_deadline'], '2027-02-17T08:59:00+09:00')
                self.assertEqual(event.get('recruitment_basis'), 'listing' if status == 'OPEN' else None)
        self.assertIsNone(cncf_window(WINDOW.replace(' UTC', ''), 2027))

    async def test_listing_needs_explicit_current_recruitment(self):
        fetcher = AsyncMock()
        html = ''.join(
            f'<a class="card-link" href="/programs/{slug}"><div class="program-card-head"><span>{badge}</span></div><strong>{title}</strong></a>'
            for slug, badge, title in [('daleui', '상시 모집', '달레 UI'), ('leetcode', '9기 진행 중', '리트코드 스터디')]
        )
        fetcher.page.return_value = httpx.Response(200, text=html, request=httpx.Request('GET', DALE_URL))
        log = []
        events, _ = await discover(fetcher, None, log.append, {'dale_programs', 'dev_event', 'luma', 'eventus'})
        self.assertEqual([event['canonical_url'] for event in events], [DALE_URL + '/daleui'])
        self.assertEqual([entry['state'] for entry in log].count('disabled'), 3)
        self.assertEqual((await verify_program(events[0], fetcher))['status'], 'OPEN')
