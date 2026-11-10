import asyncio
import unittest
import httpx
from playwright.sync_api import TimeoutError as BrowserTimeout
from app.club_pages import club_status, wait_for_club_content
from app.collector import verify
from app.core import new_event
from app.sources import discover

URL='https://recruit.sopt.org/'
SHELL='<title>SOPT 모집 지원하기</title><div>페이지 로딩 중입니다</div>'
HTML='<title>SOPT 모집 지원하기</title><h1>지금은 모집 기간이 아니에요.</h1><button>알림 신청하기</button><p>'+('공식 동아리 모집과 지원 자격 안내입니다. '*6)+'</p>'


class Fetcher:
    async def page(self,url):
        return httpx.Response(200,text=SHELL,headers={'content-type':'text/html'},request=httpx.Request('GET',url))


class Renderer:
    def __init__(self):self.urls=[]
    async def render(self,url):
        self.urls.append(url)
        return {'url':url,'http_status':200,'html':HTML,'text':'지금은 모집 기간이 아니에요. 알림 신청하기',
                'title':'SOPT 모집 지원하기','controls':[{'label':'알림 신청하기','disabled':False,'href':None,'tag':'button'}]}


class ClubPages(unittest.TestCase):
    def test_bounded_readiness_only_applies_to_exact_public_recruitment_page(self):
        class Page:
            def __init__(self,url):self.url=url;self.calls=[]
            def wait_for_function(self,script,timeout):self.calls.append((script,timeout))
        page=Page(URL);wait_for_club_content(page)
        self.assertEqual(len(page.calls),1)
        self.assertEqual(page.calls[0][1],8000)
        self.assertIn('페이지 로딩 중입니다',page.calls[0][0])
        for url in ['https://recruit.sopt.org.evil.example/','https://recruit.sopt.org/auth','https://www.sopt.org/']:
            page=Page(url);wait_for_club_content(page);self.assertEqual(page.calls,[])

    def test_loading_timeout_is_an_explicit_error_not_an_empty_success(self):
        class Page:
            url=URL
            def wait_for_function(self,*args,**kwargs):raise BrowserTimeout('timeout')
        with self.assertRaisesRegex(ValueError,'로딩이 끝나지'):
            wait_for_club_content(Page())
        class FailedRenderer:
            async def render(self,url):wait_for_club_content(Page())
        items,results=asyncio.run(discover(Fetcher(),FailedRenderer(),lambda r:None,selected={'club_sopt'}))
        self.assertEqual(items,[])
        self.assertEqual(results[0]['state'],'error')
        self.assertIn('모집 0건으로 확정하지',results[0]['error'])

    def test_discovery_keeps_a_watch_candidate_and_verification_reads_dynamic_status(self):
        renderer=Renderer()
        items,results=asyncio.run(discover(Fetcher(),renderer,lambda r:None,selected={'club_sopt'}))
        self.assertEqual((results[0]['state'],results[0]['count']),('ok',1))
        self.assertEqual(items[0]['status'],'CHECK_REQUIRED')
        result,_=asyncio.run(verify(items[0],Fetcher(),renderer))
        self.assertEqual(result['status'],'CLOSED')
        self.assertEqual(result['verification_method'],'browser')
        self.assertEqual(len(renderer.urls),2)
        self.assertIsNone(result.get('application_url'))
        self.assertIn('알림 신청은 지원 접수가 아닙니다',result['evidence'])

    def test_footer_text_notification_button_and_lookalikes_do_not_prove_closed_or_open(self):
        event=new_event(URL,'SOPT',activity_type='club')
        for html in ['<h1>모집 안내</h1><footer>지금은 모집 기간이 아니에요.</footer>',
                     '<h1>모집 알림 신청</h1><button>알림 신청하기</button>']:
            self.assertEqual(club_status(event,html)['status'],'CHECK_REQUIRED')
        self.assertEqual(club_status(event,HTML,'현재 지원 안내')['status'],'CHECK_REQUIRED')
        other={**event,'canonical_url':'https://recruit.sopt.org.evil.example/'}
        self.assertEqual(club_status(other,HTML),other)


if __name__=='__main__':unittest.main()
