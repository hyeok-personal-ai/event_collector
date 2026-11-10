import os
import asyncio
import unittest
from unittest.mock import patch
from app.sources import SOURCES, extract_links
from app.core import canonical
from app.batch_common import public_event
from app.batch_key import read_key
from app.access_policy import RESTRICTED_SOURCES

class PublicCollectorTests(unittest.TestCase):
    def test_sideproject_keeps_nontechnical_roles_and_interests(self):
        import httpx
        from app.sources import discover
        class Fetcher:
            async def page(self,url):
                html='<a href="/projects/?bmode=view&idx=123">마케터 구성원 모집합니다</a><a href="/projects/?bmode=view&idx=124">문화생활 프로젝트 팀원 모집</a><a href="/projects/?page=2">다음 페이지</a>'
                return httpx.Response(200,text=html,request=httpx.Request('GET',url))
        items,results=asyncio.run(discover(Fetcher(),None,lambda r:None,selected={'sideproject'}))
        self.assertEqual(len(items),2)
        self.assertEqual((results[0]['state'],results[0]['count']),('ok',2))
        self.assertTrue(all(e['status']=='CHECK_REQUIRED' and e['discovery_source']=='sideproject' for e in items))
        self.assertTrue(all('idx=' in e['canonical_url'] for e in items))
        self.assertEqual([e['activity_type'] for e in items],['project','project'])

    def test_sideproject_titles_keep_explicit_activity_and_do_not_invent_it(self):
        from app.sources import extract_anchor,search_candidate
        from app.collector import parse_page
        s=next(s for s in SOURCES if s.id=='sideproject')
        url=s.url+'?bmode=view&idx=123'
        for title,kind in [('마케터 구성원을 모집합니다','project'),('문화생활 프로젝트 팀원 모집','project'),
                           ('독서 스터디 팀원 모집','study'),('무료 디자인 세미나','conference'),
                           ('함께하는 저녁 안내','other')]:
            with self.subTest(title=title):
                linked=extract_links('<a href="'+url+'">'+title+'</a>',s.url,s)[0]
                structured=extract_anchor(title,url,s.url,s)
                searched=search_candidate({'title':title,'url':url})
                for e in (linked,structured,searched):
                    self.assertEqual(e['activity_type'],kind)
                    self.assertEqual(e['status'],'CHECK_REQUIRED')
                detail,_=parse_page('<title>'+title+'</title>',url,linked)
                self.assertEqual(detail['activity_type'],kind)

    def test_restricted_sources_cannot_return_through_detail_or_provenance(self):
        from app.access_policy import assert_event_collection_allowed, RESTRICTED_HOSTS
        for host in RESTRICTED_HOSTS:
            for field in ('canonical_url','verification_url','discovery_url'):
                event={'canonical_url':'https://example.org/event',field:'https://WWW.'+host.upper()+'./detail'}
                with self.subTest(host=host,field=field),self.assertRaises(ValueError):
                    assert_event_collection_allowed(event)
        for source in RESTRICTED_SOURCES:
            with self.subTest(source=source),self.assertRaises(ValueError):
                assert_event_collection_allowed({'canonical_url':'https://example.org/event','discovery_source':source})
        assert_event_collection_allowed({'canonical_url':'https://disquiet.io.example.org/event','discovery_source':'eventus'})

    def test_platform_suffix_cannot_turn_every_activity_into_a_contest(self):
        from app.core import activity_type,new_event
        from app.collector import parse_page
        cases=[('AI 콘텐츠 페스티벌 2026','conference'),('AI 서비스 프로젝트 팀원 모집','project'),('2026 AI 해커톤 대회','hackathon'),('Python 스터디 모집','study'),('스터디 플래너 앱 베타 테스터 모집','other')]
        for title,kind in cases:
            branded=title+' | 공모전 대외활동-링커리어'
            with self.subTest(title=title):
                self.assertEqual(activity_type(branded),kind)
                url='https://linkareer.com/activity/12345'
                old=new_event(url,branded,activity_type='hackathon')
                parsed,_=parse_page('<title>'+branded+'</title>',url,old)
                self.assertEqual(parsed['title'],title)
                self.assertEqual(parsed['activity_type'],kind)
                self.assertEqual(parsed['status'],'CHECK_REQUIRED')
        self.assertEqual(activity_type('베타 테스트를 준비하는 프로젝트 팀원 모집'),'project')
        self.assertEqual(activity_type('스터디라이브 숏폼 마케터 1기',fallback='other'),'other')
        self.assertEqual(activity_type('AI 개발자 추가 모집',fallback='other'),'other')
        self.assertEqual(activity_type('Python 스터디원 모집',fallback='other'),'study')

    def test_filtered_listing_finds_candidates_without_claiming_recruitment(self):
        import httpx
        from urllib.parse import parse_qs,urlsplit
        from app.sources import discover
        class Fetcher:
            async def page(self,url):
                query=parse_qs(urlsplit(url).query)
                html='<a href="/activity/12">AI 스터디 모집</a><a href="/activity/12"><h5>AI 스터디 모집</h5></a><a href="/activity/13">문화 교류 서포터즈</a>' if query.get('filterBy_interestIDs')==['13'] else '<a href="/activity/13">문화 교류 서포터즈</a>'
                return httpx.Response(200,text=html,headers={'content-type':'text/html'},request=httpx.Request('GET',url))
        items,results=asyncio.run(discover(Fetcher(),None,lambda r:None,selected={'linkareer'}))
        self.assertEqual(len(items),1)
        self.assertEqual(items[0]['status'],'CHECK_REQUIRED')
        self.assertEqual(items[0]['discovery_source'],'linkareer')
        self.assertIn('filterBy_interestIDs=13',items[0]['discovery_url'])
        self.assertEqual((results[0]['state'],results[0]['count']),('ok',1))

    def test_empty_keyword_selection_is_distinct_from_missing_listing(self):
        import httpx
        from app.sources import discover
        class Fetcher:
            def __init__(self,html):self.html=html
            async def page(self,url):return httpx.Response(200,text=self.html,request=httpx.Request('GET',url))
        _,results=asyncio.run(discover(Fetcher('<a href="/activity/13">문화 교류 서포터즈</a>'),None,lambda r:None,selected={'linkareer'}))
        self.assertEqual(results[0]['state'],'empty')
        self.assertIn('공개 목록 1개를 읽었으나',results[0]['error'])
        _,results=asyncio.run(discover(Fetcher('<p>Loading...</p>'),None,lambda r:None,selected={'linkareer'}))
        self.assertIn('추출하지 못했습니다',results[0]['error'])

    def test_catalog_replacements_are_active(self):
        sources={s.id:s for s in SOURCES}
        self.assertEqual(len(sources),len(SOURCES))
        for s in SOURCES:
            if not s.enabled:
                self.assertTrue(s.note)
                self.assertTrue(s.replacements or s.id in RESTRICTED_SOURCES, 'Excluded sources need an active alternative or an explicit policy restriction')
            for replacement in s.replacements:
                self.assertTrue(sources[replacement].enabled)

    def test_luma_navigation_is_not_an_event(self):
        source=next(s for s in SOURCES if s.id=='openai')
        items=extract_links('<a href="/ai?k=t">Featured in AI</a><a class="event-link" aria-label="Codex workshop" href="/workshop"></a>',source.url,source)
        self.assertEqual([e['title'] for e in items],['Codex workshop'])
        self.assertEqual(items[0]['status'],'CHECK_REQUIRED')

    def test_public_payload_excludes_private_fields(self):
        payload=public_event({'title':'Public event','canonical_url':'https://example.com/event','profile':{'age':25},'saved':True,'raw_excerpt':'private','secret':'private'})
        self.assertFalse({'profile','saved','raw_excerpt','secret'} & payload.keys())

    def test_credentials_require_environment(self):
        with patch.dict(os.environ,{},clear=True):
            with self.assertRaises(RuntimeError):read_key()

    def test_tracking_does_not_duplicate_event(self):
        self.assertEqual(canonical('https://www.meetup.com/awskrug/events/123/?eventOrigin=group'),'https://www.meetup.com/awskrug/events/123')

    def test_keit_detail_heading_overrides_generic_site_title(self):
        from app.collector import parse_page
        from app.core import new_event
        url='https://www.keit.re.kr/board.es?act=view&list_no=123'
        event,_=parse_page('<title>목록 | 공지사항</title><h2 class="title">AI 솔루션 챌린지 공고</h2><p>참여 안내</p>',url,new_event(url,'AI challenge'))
        self.assertEqual(event['title'],'AI 솔루션 챌린지 공고')
        self.assertNotEqual(event['status'],'OPEN')

    def test_unapproved_destination_is_rejected_before_reading_secret(self):
        from app import cloud_batch
        with patch.object(cloud_batch,'SITE','https://example.com'),patch.object(cloud_batch,'read_key') as key:
            with self.assertRaises(RuntimeError):asyncio.run(cloud_batch.collect())
            key.assert_not_called()

    def test_non_main_branch_is_rejected_before_reading_secret(self):
        from app import cloud_batch
        with patch.object(cloud_batch,'SITE','https://tech-event-radar-kr.qkdrhkgn123.chatgpt.site'),patch.dict(os.environ,{'GITHUB_REPOSITORY':'hyeok-personal-ai/event_collector','GITHUB_RUN_ID':'123','GITHUB_REF':'refs/heads/other'}),patch.object(cloud_batch,'read_key') as key:
            with self.assertRaises(RuntimeError):asyncio.run(cloud_batch.collect())
            key.assert_not_called()

    def test_daily_run_drains_multiple_pages(self):
        from app import cloud_batch as batch
        from app.core import new_event
        calls=[]
        async def call(self,action,**data):
            calls.append((action,data))
            if action=='start':return {'state':'started','run':{'run_id':data['token'],'sources':[],'verified':0}}
            if action=='prepare':return {'stats':{'due':0}}
            if action=='claim':
                page=data['batch']
                return {'items':[{'id':str(page),'event':new_event('https://example.com/'+str(page),'Event')} ] if page<2 else []}
            return {'state':'saved'}
        async def discover(fetcher,renderer,record):
            record({'id':'test','state':'ok','count':2});return [],[]
        async def verify(event,*args):return event,''
        with patch.object(batch,'SITE','https://tech-event-radar-kr.qkdrhkgn123.chatgpt.site'),patch.dict(os.environ,{'GITHUB_REPOSITORY':'hyeok-personal-ai/event_collector','GITHUB_RUN_ID':'123','GITHUB_REF':'refs/heads/main'}),patch.object(batch,'read_key',return_value='test-only'),patch.object(batch.RemoteQueue,'call',call),patch.object(batch,'discover',discover),patch.object(batch,'verify',verify):
            result=asyncio.run(batch.collect(dynamic_budget=0))
        self.assertEqual(result['verified'],2)
        self.assertEqual([d['batch'] for a,d in calls if a=='claim'],[0,1,2])
        self.assertEqual(calls[-1][0],'finish')

    def test_failed_item_keeps_legacy_identity_and_counts_attempt(self):
        from app import cloud_batch as batch
        calls=[]
        legacy='https://example.com/모집/?q=a%20b'
        async def call(self,action,**data):
            calls.append((action,data))
            if action=='start':return {'state':'started','run':{'run_id':data['token'],'sources':[],'verified':0}}
            if action=='prepare':return {'stats':{'due':0}}
            if action=='claim':return {'items':[{'id':'one','event':{'canonical_url':legacy,'title':'Study'}}] if data['batch']==0 else []}
            return {'state':'saved'}
        async def discover(*args):return [],[]
        async def verify(event,*args):
            self.assertEqual(event['canonical_url'],legacy)
            return {**event,'failure_count':1,'collection_route':{'state':'alternate','original_url':legacy}},''
        with patch.object(batch,'SITE','https://tech-event-radar-kr.qkdrhkgn123.chatgpt.site'),patch.dict(os.environ,{'GITHUB_REPOSITORY':'hyeok-personal-ai/event_collector','GITHUB_RUN_ID':'123','GITHUB_REF':'refs/heads/main'}),patch.object(batch,'read_key',return_value='test-only'),patch.object(batch.RemoteQueue,'call',call),patch.object(batch,'discover',discover),patch.object(batch,'verify',verify):
            result=asyncio.run(batch.collect(dynamic_budget=0))
        self.assertEqual(result['state'],'partial')
        failure=next(d for a,d in calls if a=='fail')
        self.assertNotIn('route',failure)  # Failed writes never claim a successful alternate path.
        self.assertEqual(calls[-1][1]['run']['attempted'],1)

if __name__=='__main__':unittest.main()
