import asyncio
import unittest
from unittest.mock import patch
from datetime import datetime
import httpx
from app.club_dates import club_deadline
from app.core import KST, new_event
from app.collector import verify
from app.verifiers import external_links


class ClubDates(unittest.TestCase):
    def setUp(self):
        self.event=new_event('https://sipe.team/recruit','SIPE',activity_type='club')
        for module in ('club_dates','collector','verifiers','recruitment'):
            clock=patch('app.'+module+'.now',return_value=datetime(2026,11,11,tzinfo=KST))
            clock.start();self.addCleanup(clock.stop)

    def test_explicit_application_deadline_not_activity_or_interview_date(self):
        text='서류 접수 11.02 ~ 11.16 2026년 11월 16일 23:59 마감 서류 합격자 발표 11.30 정규 활동 시작 2027년 1월 16일'
        result=club_deadline(self.event,text)
        self.assertEqual(result['apply_deadline'],'2026-11-16T23:59:00+09:00')
        self.assertEqual(result['status'],'CHECK_REQUIRED')
        self.assertNotIn('apply_deadline',{k:v for k,v in self.event.items() if v is not None})

    def test_missing_year_conflict_invalid_day_and_non_application_dates_stay_unknown(self):
        for text in ['서류 접수 11월 16일 23:59 마감',
                     '서류 접수 2026년 11월 16일 23:59 마감 2026년 11월 17일 23:59 마감',
                     '서류 접수 2026년 2월 30일 23:59 마감',
                     '서류 접수 추후 공지 서류 합격자 발표 2026년 11월 16일 23:59 마감']:
            result=club_deadline({**self.event,'apply_deadline':'2025-01-01'},text)
            self.assertNotIn('apply_deadline',result)

    def test_past_deadline_is_closed_and_lookalike_host_is_not_special_cased(self):
        text='서류 접수 2026년 11월 1일 23:59 마감'
        self.assertEqual(club_deadline(self.event,text)['status'],'CLOSED')
        other={**self.event,'canonical_url':'https://sipe.team.evil.example/recruit'}
        self.assertEqual(club_deadline(other,text),other)

    def test_actual_registered_route_keeps_home_identity_and_checks_recruit_page(self):
        class Fetcher:
            async def page(self,url):
                self.url=url
                return httpx.Response(200,headers={'content-type':'text/html'},request=httpx.Request('GET',url),
                    text='<title>사이퍼 모집 - SIPE</title><main>지원자격 서류 접수 2026년 11월 16일 23:59 마감</main>')
        fetcher=Fetcher()
        event=new_event('https://sipe.team/','SIPE',activity_type='club')
        result,_=asyncio.run(verify(event,fetcher))
        self.assertEqual(fetcher.url,'https://sipe.team/recruit')
        self.assertEqual(result['canonical_url'],event['canonical_url'])
        self.assertEqual(result['verification_url'],fetcher.url)
        self.assertEqual(result['apply_deadline'],'2026-11-16T23:59:00+09:00')
        self.assertEqual(result['status'],'CHECK_REQUIRED')
        self.assertEqual(result['collection_route']['state'],'alternate')

    def test_official_club_navigation_form_is_found_but_community_navigation_stays_excluded(self):
        html='<header><a href="https://forms.gle/current-club-form">Join Us</a></header><main>지원자격 및 모집 안내</main>'
        self.assertEqual(external_links(html,'https://sipe.team/recruit')[0],['https://forms.gle/current-club-form'])
        self.assertEqual(external_links(html,'https://okky.kr/articles/123')[0],[])
        self.assertEqual(external_links(html,'https://sipe.team.evil.example/recruit')[0],[])


if __name__=='__main__':unittest.main()
