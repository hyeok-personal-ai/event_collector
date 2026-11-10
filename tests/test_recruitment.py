import asyncio
import unittest
from unittest.mock import patch
import httpx
from app.core import new_event
from app.recruitment import recruitment_facts
from app.verifiers import external_links
from app.collector import verify, store_raw


class RecruitmentTests(unittest.TestCase):
    def test_removed_application_link_is_not_reused_from_previous_verification(self):
        from unittest.mock import AsyncMock
        class Fetcher:
            async def page(self,url):
                return httpx.Response(200,text='<article><h1>스터디 안내</h1><p>다음 모집은 추후 안내합니다.</p></article>',headers={'content-type':'text/html'},request=httpx.Request('GET',url))
        renderer=type('Renderer',(),{'render':AsyncMock()})()
        event=new_event('https://okky.kr/articles/123','스터디 안내',status='OPEN',application_url='https://forms.gle/previous')
        result,_=asyncio.run(verify(event,Fetcher(),renderer))
        renderer.render.assert_not_awaited()
        self.assertEqual(result['status'],'CHECK_REQUIRED')
        self.assertFalse(result.get('application_url'))

    def test_community_related_application_button_does_not_override_article_scope(self):
        from app.verifiers import check_external
        from unittest.mock import AsyncMock
        renderer=type('Renderer',(),{'render':AsyncMock()})()
        event=new_event('https://okky.kr/articles/123','스터디',application_url='https://forms.gle/related')
        result=asyncio.run(check_external(event,'<article><p>모집 안내 예정</p></article><aside><a href="https://forms.gle/related">신청하기</a></aside>',renderer,None))
        renderer.render.assert_not_awaited()
        self.assertFalse(result.get('application_url'))

    def test_current_article_form_replaces_historical_form(self):
        from app.verifiers import check_external
        from unittest.mock import AsyncMock
        current='https://forms.gle/current'
        page={'url':current,'title':'스터디 지원서','text':'지원 동기','controls':[{'label':'제출','disabled':False,'form_fields':1}],'input_count':1}
        renderer=type('Renderer',(),{'render':AsyncMock(return_value=page)})()
        event=new_event('https://okky.kr/articles/123','스터디',application_url='https://forms.gle/old')
        result=asyncio.run(check_external(event,f'<article><p>지원 {current}</p></article>',renderer,None))
        renderer.render.assert_awaited_once_with(current)
        self.assertEqual(result['status'],'OPEN')
        self.assertEqual(result['application_url'],current)

    def test_required_login_notice_is_explained_without_rejecting_optional_sign_in(self):
        from app.verifiers import application_state
        page={'url':'https://docs.google.com/forms/d/e/example/viewform','title':'스터디 지원서','controls':[{'label':'제출','disabled':False,'form_fields':1}],'input_count':1}
        for text in ['계속하려면 로그인','이 설문지를 작성하려면 로그인해야 합니다.','You must sign in to fill out this form.']:
            with self.subTest(text=text):
                state,reason=application_state({**page,'text':text},{'title':'스터디'})
                self.assertEqual(state,'CHECK_REQUIRED')
                self.assertIn('로그인',reason)
        self.assertEqual(application_state({**page,'text':'로그인하면 진행 상황을 저장할 수 있습니다.'},{'title':'스터디'})[0],'OPEN')

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
        from app.recruitment import community_recruitment_deadline
        def extract(body,posted='26.12.20 10:00'):
            html=('<span class="sub-title__created-at"><span class="sub-title__value">'+posted+'</span></span>' if posted else '')+body
            return community_recruitment_deadline(BeautifulSoup(html,'html.parser'))
        self.assertEqual(extract('<p>접수 기간: 12/20 ~ 01/05</p>'),'2027-01-05T23:59:59+09:00')
        self.assertEqual(extract('<p>모집 기간: 2026.10.26 ~ 2026.11.06</p>',None),'2026-11-06T23:59:59+09:00')
        for body,posted in [('<p>활동 기간: 12/20 ~ 01/05</p>','26.12.20 10:00'),('<p>모집 기간: 12/20 ~ 01/05</p>',None),('<p>모집 기간: 12/20 ~ 01/05 18:00</p>','26.12.20 10:00'),('<p>모집 기간: 12/20 ~ 01/05</p><p>모집 기간: 12/20 ~ 01/10</p>','26.12.20 10:00'),('<p>모집 기간: 12/20 ~ 02/30</p>','26.12.20 10:00')]:
            with self.subTest(body=body,posted=posted):self.assertIsNone(extract(body,posted))

    def test_plain_form_link_and_recommendation_scope(self):
        url='https://www.inflearn.com/studies/123/example'
        html='<main><h1>스터디</h1><p>지원 https://forms.gle/actual.</p><a href="https://www.inflearn.com/studies/456/other">다른 글 https://forms.gle/wrong</a></main><footer><a href="https://forms.gle/footer">문의</a></footer>'
        self.assertEqual(external_links(html,url),(['https://forms.gle/actual'],[]))

    def test_labelled_single_deadlines_and_split_labels(self):
        from bs4 import BeautifulSoup
        from app.recruitment import community_recruitment_deadline
        def extract(body):
            return community_recruitment_deadline(BeautifulSoup('<time datetime="2026-11-04T12:00:00+09:00"></time>'+body,'html.parser'))
        self.assertEqual(extract('<p>- 지원기간: 26년 11월 14일까지</p>'),'2026-11-14T23:59:59+09:00')
        self.assertEqual(extract('<b>- 모집 기간</b><p>: ~11/20 (금)까지</p>'),'2026-11-20T23:59:59+09:00')
        self.assertEqual(extract('<p>접수 마감: 2026년 11월 14일까지</p>'),'2026-11-14T23:59:59+09:00')
        for body in ['<p>활동 기간: 26년 11월 14일까지</p>', '<p>지원 기간: ~2026년</p>', '<p>모집 기간: ~11/20 (일)까지</p>', '<p>모집 기간: 26년 11월 14일 18시까지</p>', '<p>모집 기간: 26년 11월 14일까지</p><p>지원 기간: 26년 11월 15일까지</p>']:
            with self.subTest(body=body):self.assertIsNone(extract(body))

    def test_okky_deadline_uses_own_article_not_adjacent_cards(self):
        from datetime import datetime
        from app.core import KST
        event=new_event('https://okky.kr/articles/1565400?topic=gathering','프로젝트')
        html='<article><time datetime="2026-10-14T09:13:01"></time><b>- 모집 기간</b><p>: ~10/18 (일)까지</p></article><aside>모집 기간: ~12/20까지</aside>'
        with patch('app.recruitment.now',return_value=datetime(2026,11,10,tzinfo=KST)):
            result=recruitment_facts(event,html)
        self.assertEqual(result['apply_deadline'],'2026-10-18T23:59:59+09:00')
        self.assertEqual(result['status'],'CLOSED')

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
