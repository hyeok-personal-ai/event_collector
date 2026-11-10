import asyncio
import unittest
from unittest.mock import patch
import httpx
from app.core import new_event
from app.recruitment import recruitment_facts
from app.verifiers import external_links
from app.collector import verify, store_raw


class RecruitmentTests(unittest.TestCase):
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
