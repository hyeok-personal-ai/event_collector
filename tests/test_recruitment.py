import asyncio
import unittest
from unittest.mock import patch
import httpx
from app.core import new_event
from app.recruitment import recruitment_facts
from app.verifiers import external_links
from app.collector import verify, store_raw


class RecruitmentTests(unittest.TestCase):
    def test_expired_recruitment_range_overrides_stale_open_badge(self):
        from datetime import datetime
        from app.core import KST
        e=new_event('https://www.inflearn.com/studies/123/example','동아리 모집')
        html='<main><span class="sub-title__created-at"><span class="sub-title__value">26.11.04 01:01</span></span><button>모집중</button><p>문화패스는 11월 30일까지 사용</p><p>📩 모집 기간: 10/26(월) ~ 11.06(금)</p></main>'
        with patch('app.recruitment.now',return_value=datetime(2026,11,10,tzinfo=KST)):
            result=recruitment_facts(e,html)
        self.assertEqual(result['apply_deadline'],'2026-11-06T23:59:59+09:00')
        self.assertEqual(result['status'],'CLOSED')
        crawler_html='<main><h1>동아리 모집</h1><div><time datetime="2026-11-03T16:01:55.448Z">작성일</time></div><p>📩 모집 기간: 10/26(월) ~ 11.06(금)</p></main>'
        with patch('app.recruitment.now',return_value=datetime(2026,11,10,tzinfo=KST)):
            result=recruitment_facts(e,crawler_html)
        self.assertEqual(result['apply_deadline'],'2026-11-06T23:59:59+09:00')
        self.assertEqual(result['status'],'CLOSED')
        # A known deadline must also win when the page has no parseable range.
        with patch('app.recruitment.now',return_value=datetime(2026,11,10,tzinfo=KST)):
            result=recruitment_facts({**e,'apply_deadline':'2026-11-06'},'<main><button>모집중</button></main>')
        self.assertEqual(result['status'],'CLOSED')

    def test_recruitment_dates_require_article_context_and_unambiguous_ranges(self):
        from bs4 import BeautifulSoup
        from app.recruitment import inflearn_recruitment_deadline
        def extract(body,posted='26.12.20 10:00'):
            html=('<span class="sub-title__created-at"><span class="sub-title__value">'+posted+'</span></span>' if posted else '')+body
            return inflearn_recruitment_deadline(BeautifulSoup(html,'html.parser'))
        self.assertEqual(extract('<p>접수 기간: 12/20 ~ 01/05</p>'),'2027-01-05T23:59:59+09:00')
        self.assertEqual(extract('<p>모집 기간: 2026.10.26 ~ 2026.11.06</p>',None),'2026-11-06T23:59:59+09:00')
        for body,posted in [('<p>활동 기간: 12/20 ~ 01/05</p>','26.12.20 10:00'),('<p>모집 기간: 12/20 ~ 01/05</p>',None),('<p>모집 기간: 12/20 ~ 01/05 18:00</p>','26.12.20 10:00'),('<p>모집 기간: 12/20 ~ 01/05</p><p>모집 기간: 12/20 ~ 01/10</p>','26.12.20 10:00'),('<p>모집 기간: 12/20 ~ 02/30</p>','26.12.20 10:00')]:
            with self.subTest(body=body,posted=posted):self.assertIsNone(extract(body,posted))

    def test_plain_form_link_and_recommendation_scope(self):
        url='https://www.inflearn.com/studies/123/example'
        html='<main><h1>스터디</h1><p>지원 https://forms.gle/actual.</p><a href="https://www.inflearn.com/studies/456/other">다른 글 https://forms.gle/wrong</a></main><footer><a href="https://forms.gle/footer">문의</a></footer>'
        self.assertEqual(external_links(html,url),(['https://forms.gle/actual'],[]))

    def test_title_and_related_open_badge_do_not_confirm_recruitment(self):
        e=new_event('https://www.inflearn.com/projects/123/example','모집 중 프로젝트')
        e['status']='CHECK_REQUIRED'
        r=recruitment_facts(e,'<main><h1>모집 중 프로젝트</h1><a href="https://www.inflearn.com/projects/2/other"><button>모집중</button></a></main>')
        self.assertEqual(r['status'],'CHECK_REQUIRED')
        self.assertEqual(r['activity_type'],'project')
        from app.verifiers import site_markers
        r=site_markers(e,'<main><h1>프로젝트</h1><a href="https://www.inflearn.com/projects/2/other"><button>모집완료</button></a></main>')
        self.assertEqual(r['status'],'CHECK_REQUIRED')

    def test_active_listing_is_distinct_from_form_confirmation(self):
        e=new_event('https://holaworld.io/study/abcdef123')
        e['status']='CHECK_REQUIRED'
        html='<div class="_mainCard_x"><div class="_infoRow_x"><span class="_label_x">모집 구분</span><span class="_value_x">스터디</span></div><button class="_applyButton_x">지원하기</button></div>'
        observed={'controls':[{'label':'지원하기','disabled':False}]}
        r=recruitment_facts(e,html,observed)
        self.assertEqual((r['status'],r['activity_type'],r['recruitment_basis']),('OPEN','study','listing'))
        self.assertEqual(recruitment_facts(e,html,{'controls':[]})['status'],'CHECK_REQUIRED')
        self.assertEqual(recruitment_facts(e,html.replace('>지원하기<','>모집 마감<'),observed)['status'],'CLOSED')
        self.assertEqual(recruitment_facts(e,html.replace('class="_applyButton_x"','class="_applyButton_x" disabled'),observed)['status'],'CHECK_REQUIRED')

    def test_deleted_post_exits_review_without_changing_identity(self):
        class Fetcher:
            async def page(self,url):
                return httpx.Response(404,request=httpx.Request('GET',url))
        e=new_event('https://www.inflearn.com/studies/123/example')
        r,_=asyncio.run(verify(e,Fetcher()))
        self.assertEqual(r['status'],'DEAD')
        self.assertEqual(r['failure_count'],0)
        self.assertEqual(r['collection_route']['state'],'direct')
        self.assertEqual(r['canonical_url'],e['canonical_url'])

    def test_production_does_not_persist_raw_posts(self):
        with patch.dict('os.environ',{},clear=True):
            self.assertIsNone(store_raw('<p>private contact in public post</p>'))

    def test_survey_and_unknown_form_are_not_recruitment(self):
        from app.verifiers import application_state
        page={'text':'입력 제출','title':'스터디 지원서','controls':[{'label':'제출','disabled':False,'form_fields':1}],'input_count':1}
        self.assertEqual(application_state(page,{'title':'스터디 모집'})[0],'OPEN')
        self.assertEqual(application_state({**page,'title':'자기계발 설문조사'},{'title':'스터디'})[0],'CHECK_REQUIRED')
        self.assertEqual(application_state(page,{'title':'[설문] 자기계발 조사'})[0],'CHECK_REQUIRED')
        self.assertEqual(application_state({**page,'title':'이름 없는 폼'},{'title':'스터디 모집'})[0],'CHECK_REQUIRED')
        self.assertEqual(application_state({**page,'title':'앱 프로젝트','text':'지원동기 지원분야 제출'},{'title':'프로젝트 모집'})[0],'OPEN')

    def test_same_public_form_is_rendered_once_per_batch(self):
        from unittest.mock import AsyncMock
        from app.browser import BrowserRenderer
        async def check():
            fetcher=type('Fetcher',(),{'allowed':AsyncMock()})()
            renderer=BrowserRenderer(fetcher,budget=1)
            result={'url':'https://docs.google.com/forms/d/e/public/viewform','http_status':200,'title':'스터디 지원서'}
            with patch('app.collector.public_url',new=AsyncMock()),patch.object(renderer,'_render',return_value=result) as render:
                try:
                    self.assertEqual(await renderer.render('https://forms.gle/public'),result)
                    self.assertEqual(await renderer.render('https://forms.gle/public'),result)
                    self.assertEqual(await renderer.render(result['url']),result)
                    self.assertEqual(render.call_count,1)
                    self.assertEqual(renderer.used,1)
                finally:await renderer.close()
        asyncio.run(check())

    def test_login_and_error_pages_are_not_applications(self):
        from app.verifiers import application_state
        page={'text':'이메일 또는 휴대전화 다음','title':'행사 참가 신청','url':'https://accounts.google.com/v3/signin/identifier','controls':[{'label':'다음','disabled':False,'form_fields':1}],'input_count':1}
        self.assertEqual(application_state(page,{'title':'해커톤'})[0],'CHECK_REQUIRED')
        for url in ['https://login.microsoftonline.com/common/oauth2/authorize','https://nid.naver.com/nidlogin.login','https://example.org/login']:
            self.assertEqual(application_state({**page,'url':url},{'title':'해커톤'})[0],'CHECK_REQUIRED')
        public={**page,'url':'https://docs.google.com/forms/d/e/public/viewform','title':'스터디 신청서','text':'로그인하면 진행 상황을 저장할 수 있습니다. 이름 참가 신청 다음'}
        self.assertEqual(application_state(public,{'title':'스터디'})[0],'OPEN')
        self.assertEqual(application_state({**public,'http_status':403},{'title':'스터디'})[0],'CHECK_REQUIRED')
        self.assertEqual(application_state({**public,'title':'로그인 - 참가 신청'},{'title':'스터디'})[0],'CHECK_REQUIRED')
        closed={**public,'url':'https://docs.google.com/forms/d/e/public/closedform','controls':[],'input_count':0,'text':'응답을 받지 않고 있습니다.'}
        self.assertEqual(application_state(closed,{'title':'스터디'})[0],'CLOSED')
        self.assertEqual(application_state({**closed,'text':''},{'title':'스터디'})[0],'CLOSED')
        self.assertEqual(application_state({**closed,'http_status':403},{'title':'스터디'})[0],'CHECK_REQUIRED')

    def test_auth_redirect_preserves_public_application_link(self):
        from app.verifiers import check_external
        from unittest.mock import AsyncMock
        form='https://forms.gle/real'
        login='https://accounts.google.com/v3/signin/identifier'
        async def check():
            renderer=type('Renderer',(),{'render':AsyncMock(return_value={'url':login,'title':'Google 로그인','text':'이메일 다음','input_count':1,'controls':[{'label':'다음','disabled':False,'form_fields':1}]})})()
            event={'canonical_url':'https://example.org/event/1','application_url':login,'status':'OPEN','title':'스터디 신청'}
            result=await check_external(event,f'<main><a href="{form}">신청서</a></main>',renderer,None)
            renderer.render.assert_awaited_once_with(form)
            self.assertEqual(result['status'],'CHECK_REQUIRED')
            self.assertEqual(result['application_url'],form)
            self.assertIn('로그인 화면',result['evidence'])
        asyncio.run(check())
