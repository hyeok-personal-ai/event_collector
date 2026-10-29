"""Source catalog, public-list collectors and optional search API discovery."""
import asyncio
import json
import os
import re
from dataclasses import dataclass, asdict, replace
from urllib.parse import urljoin, urlsplit
from bs4 import BeautifulSoup
from .core import new_event, canonical, categories, activity_type, iso_now
from .importers import parse_dev_event
from .collector import DEV_EVENT_URL, json_nodes

@dataclass(frozen=True)
class Source:
    id: str
    name: str
    group: str
    url: str
    pattern: str
    dynamic: bool = False
    keyword: bool = False
    search_only: bool = False
    club: bool = False
    enabled: bool = True
    note: str = ''
    replacements: tuple = ()
    adapter: str = ''
    match_query: bool = False

SOURCES = [
    Source('club_yapp','YAPP','동아리·연합 커뮤니티','https://www.yapp.co.kr/',r'(?:www\.)?yapp\.co\.kr/.*',club=True),
    Source('club_depromeet','디프만','동아리·연합 커뮤니티','https://www.depromeet.com/recruit',r'(?:www\.)?depromeet\.com/.*',club=True),
    Source('club_sopt','SOPT','동아리·연합 커뮤니티','https://recruit.sopt.org/',r'(?:recruit\.)?sopt\.org/.*',True,club=True),
    Source('club_dnd','DND','동아리·연합 커뮤니티','https://dnd.ac/',r'dnd\.ac/.*',club=True),
    Source('club_nexters','넥스터즈','동아리·연합 커뮤니티','https://nexters.co.kr/',r'nexters\.co\.kr/.*',club=True),
    Source('club_prography','프로그라피','동아리·연합 커뮤니티','https://prography.org/',r'prography\.org/.*',club=True),
    Source('club_mashup','Mash-Up','동아리·연합 커뮤니티','https://recruit.mash-up.kr/',r'(?:recruit\.)?mash-up\.kr/.*',True,club=True),
    Source('club_cotato','코테이토','동아리·연합 커뮤니티','https://recruit.cotato.kr/',r'(?:recruit\.)?cotato\.kr/.*',True,club=True),
    Source('club_ausg','AUSG','동아리·연합 커뮤니티','https://ausg.me/',r'ausg\.me/.*',club=True),
    Source('club_sipe','SIPE','동아리·연합 커뮤니티','https://sipe.team/',r'sipe\.team/.*',True,club=True),
    Source('club_cloudclub','Cloud Club','동아리·연합 커뮤니티','https://cloudclub.kr/',r'cloudclub\.kr/.*',club=True),
    Source('dev_event','Dev-Event','행사 플랫폼',DEV_EVENT_URL,''),
    Source('eventus','이벤터스 · IT','행사 플랫폼','https://event-us.kr/search?keyword=개발자',r'event-us\.kr/[^/?]+/event/\d+',True),
    Source('onoffmix','온오프믹스 · IT','행사 플랫폼','https://onoffmix.com/event/main',r'onoffmix\.com/event/\d+',True,True),
    Source('luma','Luma · Seoul','행사 플랫폼','https://luma.com/seoul',r'luma\.com/[a-zA-Z0-9-]+$',True,True),
    Source('meetup','AWSKRUG Meetup','개발자 커뮤니티','https://www.meetup.com/awskrug/events/',r'meetup\.com/(?:ko-kr/)?[^/]+/events/\d+',True),
    Source('ticketa','Ticketaco','행사 플랫폼','https://ticketa.co/',r'ticketa\.co/(?:en/)?event/[a-zA-Z0-9]+',True,True),
    Source('partiful','Partiful','행사 플랫폼','https://partiful.com/',r'partiful\.com/e/[a-zA-Z0-9]+',True,True),
    Source('okky','OKKY 모임·스터디','스터디·프로젝트','https://okky.kr/community/gathering',r'okky\.kr/articles/\d+'),
    Source('inflearn_projects','인프런 프로젝트','스터디·프로젝트','https://www.inflearn.com/community/projects',r'inflearn\.com/projects/\d+'),
    Source('inflearn_studies','인프런 스터디','스터디·프로젝트','https://www.inflearn.com/community/studies',r'inflearn\.com/studies/\d+'),
    Source('hola','HOLA','스터디·프로젝트','https://holaworld.io/',r'holaworld\.io/study/[a-fA-F0-9]+',True),
    Source('letspl','렛플','스터디·프로젝트','https://letspl.me/project',r'letspl\.me/project/\d+',True),
    Source('teampik','TeamPIK','스터디·프로젝트','https://www.team-pik.com/',r'(?:teampik\.com|team-pik\.com)/(?:team|project|recruit)/[^/?]+',True),
    Source('disquiet','Disquiet','스터디·프로젝트','https://disquiet.io/',r'disquiet\.io/(?:post|product)/[^/?]+',True,True),
    Source('linkareer','링커리어 IT 대외활동','커리어·대회','https://linkareer.com/list/activity',r'linkareer\.com/activity/\d+',True,True),
    Source('dacon','DACON','해커톤·공모전','https://dacon.io/competitions',r'dacon\.io/competitions/(?:official|open)/\d+/overview'),
    Source('daker','DAKER','해커톤·공모전','https://daker.ai/public/hackathons',r'daker\.ai/public/hackathons/[a-zA-Z0-9-]+',True),
    Source('aifactory','AI Factory','해커톤·공모전','https://aifactory.space/competition',r'aifactory\.space/(?:competition|task)/\d+',True),
    Source('hackon','HACK:ON','해커톤·공모전','https://hackon.kr/',r'hackon\.kr/e/[a-zA-Z0-9]+',True),
    Source('lablab','lablab.ai','해커톤·공모전','https://lablab.ai/ai-hackathons',r'lablab\.ai/ai-hackathons/[a-zA-Z0-9-]+'),
    Source('devpost','Devpost','해커톤·공모전','https://devpost.com/hackathons',r'(?:[a-zA-Z0-9-]+\.devpost\.com|devpost\.com/hackathons/[^/?]+)',True,True),
    Source('devkorea','Dev Korea','개발자 커뮤니티','https://dev-korea.com/events',r'dev-korea\.com/events/[^/?]+'),
    Source('gdg','GDG Korea','개발자 커뮤니티','https://gdg.community.dev/',r'gdg\.community\.dev/events/details/[^/?]+',True,True),
    Source('pytorch','PyTorch Korea','개발자 커뮤니티','https://discuss.pytorch.kr/latest.json',r'discuss\.pytorch\.kr/t/[^/?]+/\d+',False,True),
    Source('openinfra','OpenInfra Korea','개발자 커뮤니티','https://www.meetup.com/openstack-and-open-infrastructure-korea/',r'meetup\.com/(?:ko-kr/)?[^/]+/events/\d+',True),
    Source('cncf','CNCF Events','개발자 커뮤니티','https://www.cncf.io/events/',r'cncf\.io/(?:events|kubecon-cloudnativecon-events)/[^/?]+|community\.cncf\.io/events/details/[^/?]+|events\.linuxfoundation\.org/[^/?]+'),
    Source('pycon','PyCon Korea','개발자 커뮤니티','https://pycon.kr/',r'pycon\.kr/[^/?]*(?:program|ticket|registration)[^/?]*',True),
    Source('aws','AWS Korea','기업 공식','https://aws.amazon.com/ko/events/',r'(?:aws\.amazon\.com|aws-experience\.com)/[^?#]*(?:event|summit|workshop)[^?#]*',False,True),
    Source('google','Google Developers','기업 공식','https://developers.google.com/events',r'developers\.google\.com/events/[^/?]+|gdg\.community\.dev/events/details/[^/?]+|(?:rsvp|cloudonair)\.withgoogle\.com/events/[^/?]+|cloud\.google\.com/events/[^/?]+|developer\.android\.com/events/[^/?]+'),
    Source('microsoft','Microsoft Events','기업 공식','https://events.microsoft.com/',r'events\.microsoft\.com/event/[^?#]+',True,True),
    Source('nvidia','NVIDIA Korea','기업 공식','https://www.nvidia.com/ko-kr/events/',r'nvidia\.com/[^?#]*(?:event|ai-day|gtc)[^?#]+',False,True),
    Source('mongodb','MongoDB Events','기업 공식','https://www.mongodb.com/events',r'mongodb\.com/(?:events|local)/[^/?]+'),
    Source('redis','Redis Events','기업 공식','https://redis.io/events/',r'redis\.io/(?:events|resources/webinars|resources/videos)/[^/?]+'),
    Source('redhat','Red Hat Korea','기업 공식','https://www.redhat.com/ko/events',r'redhat\.com/(?:ko|en)/(?:events|engage)/[^/?]+'),
    Source('oracle','Oracle Korea','기업 공식','https://www.oracle.com/kr/events/',r'oracle\.com/[^?#]*(?:event|webinar)[^?#]+',False,True),
    Source('jetbrains','JetBrains Events','기업 공식','https://www.jetbrains.com/company/conferences/',r'(?:jetbrains\.com|lp\.jetbrains\.com)/[^?#]*(?:event|day|conference|webinar)[^?#]*'),
    Source('openai','OpenAI Events','기업 공식','https://events.openai.com/',r'events\.openai\.com/[^/?]+',True),
    Source('meta','Meta Developers','기업 공식','https://dev.meta.ai/events',r'(?:developers\.facebook\.com|dev\.meta\.ai)/events/[^/?]+',True,search_only=True),
    Source('wanted','원티드 이벤트','커리어·대회','https://www.wanted.co.kr/events',r'(?:wanted\.co\.kr/events/[^/?]+|event\.wanted\.co\.kr/[^/?]+)',True,True),
    Source('programmers','프로그래머스','커리어·대회','https://programmers.co.kr/competitions',r'(?:career\.)?programmers\.co\.kr/competitions/\d+',True),
    Source('github_spring','GitHub · Spring Plugin','OSS','https://api.github.com/search/issues?q=repo%3Aexplyt%2Fspring-plugin+is%3Aissue+is%3Aopen+no%3Aassignee&per_page=6&sort=updated',r'github\.com/explyt/spring-plugin/issues/\d+'),
    Source('github_airflow','GitHub · Apache Airflow','OSS','https://api.github.com/search/issues?q=repo%3Aapache%2Fairflow+is%3Aissue+is%3Aopen+no%3Aassignee+label%3A%22good+first+issue%22&per_page=6&sort=updated',r'github\.com/apache/airflow/issues/\d+'),
    Source('jumpit','점핏 공개 행사','커리어·대회','https://jumpit.saramin.co.kr/',r'jumpit\.saramin\.co\.kr/(?:event|education)/[^/?]+',search_only=True),
    Source('rocketpunch','로켓펀치 공개 행사','커리어·대회','https://www.rocketpunch.com/',r'rocketpunch\.com/(?:events|event)/[^/?]+',search_only=True),
    Source('linkedin','LinkedIn 공개 행사','커리어·대회','https://www.linkedin.com/',r'linkedin\.com/events/[^/?]+',search_only=True),
    Source('government','정부·공공기관 공모전','해커톤·공모전','https://www.k-startup.go.kr/',r'[a-z0-9.-]+\.go\.kr/.+',search_only=True),
    Source('university','KAIST 전산학부 공개 세미나','대학 공개행사','https://cs.kaist.ac.kr/colloquium/',r'cs\.kaist\.ac\.kr/(?:colloquium|board/view).*'),
]

TECH = re.compile(r'개발|테크|(?<![A-Za-z])AI(?![A-Za-z])|GenAI|LLM|데이터|클라우드|백엔드|해커톤|스터디|소프트웨어|보안|코딩|프로그래|GitHub|AWS|Cloud|DevOps|Python|Spring|(?<![A-Za-z])RAG(?![A-Za-z])|OSS',re.I)

REPAIRS = {
    'meetup':dict(url='https://www.meetup.com/awskrug/',note='행사 탭의 빈 SSR 대신 공식 그룹 첫 화면의 예정 행사와 Event JSON을 읽습니다.'),
    'aifactory':dict(url='https://aifactory.space/ko/competition',pattern=r'aifactory\.space/(?:ko/|en/)?(?:competitions|competition|task)/\d+',note='새 언어 경로와 복수형 competitions 상세 주소를 지원합니다.'),
    'microsoft':dict(url='https://www.microsoft.com/ko-kr/events',pattern=r'(?:microsoft\.com/[a-z-]+/events/local-events/[^/?]+|events\.microsoft\.com/event/[^?#]+)',keyword=False,note='이전 Events 도메인에서 이동한 공식 지역별 행사 목록을 사용합니다.'),
    'mongodb':dict(pattern=r'mongodb\.com/(?:events|resources)/.+',adapter='mongodb',note='공개 HTML의 PathFactory JSON에서 Live Webinar·Workshop·Event만 추출합니다. 녹화 영상은 제외합니다.'),
    'jetbrains':dict(url='https://blog.jetbrains.com/category/events/',pattern=r'blog\.jetbrains\.com/[^/]+/20\d{2}/\d{2}/.+',note='공식 블로그 Events 분류에서 행사 공지를 읽습니다. 일반 제품 소식은 제외합니다.'),
    'oracle':dict(name='Oracle Developer 공식 행사',url='https://www.oracle.com/uk/developer/events/',pattern=r'(?:ai-dev\.deeplearning\.ai/|reg\.rf\.oracle\.com/flow/.+)',keyword=False,note='일반 검색 화면 대신 개발자 행사 페이지가 직접 연결한 등록 페이지를 읽습니다. 글로벌 행사 포함.'),
    'cncf':dict(url='https://ocgroups.dev/cncf',pattern=r'(?:ocgroups\.dev/cncf/group/[^/]+/event/[^/?]+|events\.linuxfoundation\.org/[^/?]+)',note='기존 community.cncf.io가 이전한 공식 Open Community Groups 목록입니다.'),
    'openai':dict(name='OpenAI Codex 커뮤니티 행사',url='https://luma.com/codex-community',pattern=r'luma\.com/(?!codex-community$|discover$|signin$)[a-zA-Z0-9-]+$',note='OpenAI 공식 개발자 Community/Meetups 페이지가 연결하는 Luma 캘린더입니다.'),
    'pycon':dict(url='https://2026.pycon.kr/',adapter='event_page',note='공식 2026 연례 행사 안내입니다. 지난 행사도 포함되며 신규 모집으로 단정하지 않습니다.'),
    'meta':dict(name='Meta Connect 공식 안내',url='https://developers.meta.com/connect/',adapter='event_page',search_only=False,note='삭제된 dev.meta.ai/events 대신 공식 Connect 안내를 확인합니다. 현재는 지난 행사 다시보기입니다.'),
    'jumpit':dict(note='텍스트 없는 이미지 배너도 행사 상세 링크를 추출하고 원문에서 제목·접수를 확인합니다.'),
}
RETIRED = {
    'pycon':('2026 공식 주소도 GitHub 서버에서 HTTP 403. Dev-Event와 공개 스터디 목록으로 보완하며 파이콘 공지 전체 수집은 보장하지 않습니다.',('dev_event','modulabs')),
    'onoffmix':('robots.txt에서 자동 수집 금지. 행사 범위는 StartupJobs로 보완하며 온오프믹스 전체를 대신한다고 보장하지 않습니다.',('startupjobs',)),
    'teampik':('사이트 TLS 인증서 만료. 같은 목적의 사이드 프로젝트·모두모임 모집 목록으로 대체합니다.',('sideproject','modulabs')),
    'wanted':('GitHub 러너에서 robots 확인 HTTP 403. 공개 개발자 행사 목록으로 보완합니다.',('startupjobs','jumpit')),
    'rocketpunch':('공개 첫 화면 HTTP 403, 행사 전용 목록 확인 불가. StartupJobs로 보완합니다.',('startupjobs',)),
    'linkedin':('robots.txt에서 자동 수집 금지. 공개 행사·커뮤니티 원문으로 보완합니다.',('startupjobs','modulabs')),
    'partiful':('소개 페이지에는 행사 목록이 없고 Explore는 일반 친목 행사 중심입니다. 개발자 행사 목록으로 대체합니다.',('startupjobs',)),
    'disquiet':('개편된 홈은 제품·일반 게시글 중심이며 프로젝트 모집 전용 목록이 아닙니다. 실제 모집 목록으로 대체합니다.',('sideproject','modulabs')),
}
SOURCES=[replace(s,**REPAIRS.get(s.id,{})) for s in SOURCES]
SOURCES=[replace(s,enabled=False,note=RETIRED[s.id][0],replacements=RETIRED[s.id][1]) if s.id in RETIRED else s for s in SOURCES]
SOURCES += [
    Source('startupjobs','StartupJobs · 개발자 행사','행사 플랫폼','https://www.startupjobs.kr/events',r'startupjobs\.kr/events/\d+-[^/?]+',keyword=True,note='국내 행사 보완 소스입니다. 기술 키워드로 거르고 원문에서 개별 검증합니다.'),
    Source('sideproject','사이드 프로젝트 · 팀원 모집','스터디·프로젝트','https://sideproject.co.kr/projects/',r'sideproject\.co\.kr/projects/?\?.*\bidx=\d+',keyword=True,match_query=True,note='프로젝트 상세 게시물의 idx를 식별합니다. 단순 목록·페이지 이동은 제외합니다.'),
    Source('modulabs','모두의연구소 · 모두모임','스터디·프로젝트','https://modulabs.co.kr/community/momos',r'modulabs\.co\.kr/community/momos/\d+$',keyword=True,note='공개 스터디·세미나 모집 목록입니다. 채팅·회원 정보·피드는 수집하지 않습니다.'),
]

def catalog():
    return [{**asdict(s),'replacements':list(s.replacements)} for s in SOURCES]

def source_match(url,source):
    parsed=urlsplit(url)
    host=(parsed.hostname or '').removeprefix('www.')
    target=host+parsed.path+('?' + parsed.query if source.match_query and parsed.query else '')
    return bool(re.match('^(?:'+source.pattern+')',target,re.I)) if source.pattern else False

def extract_links(html, base_url, source):
    soup=BeautifulSoup(html,'html.parser')
    found={}
    for a in soup.select('a[href]'):
        if source.id=='openai' and 'event-link' not in a.get('class',[]):continue
        href=urljoin(base_url,a['href'])
        heading=a.select_one('h1,h2,h3,h4,[class*="title"],[data-testid*="title"]')
        if source.id=='aifactory':heading=a.select_one('p.font-bold') or heading
        lines=[x for x in a.get_text('\n',strip=True).splitlines() if x not in ('모집중','모집완료','무료','유료')]
        title=heading.get_text(' ',strip=True) if heading else (lines[0] if lines else a.get('aria-label') or a.get('title') or '')
        if not title and source.id=='jumpit' and source_match(href,source):title='점핏 · 개발자 이벤트 안내'
        if re.fullmatch(r'Register(?: now| today)?|Learn more|Learn about the hackathon|Read more|Details|등록 및 세부 정보|등록하기|자세히 보기',title,re.I):
            parent=a.parent
            for _ in range(4):
                if parent is None:break
                heading=parent.select_one('h2,h3,h4')
                if heading:
                    title=heading.get_text(' ',strip=True)
                    break
                parent=parent.parent
            else:title=urlsplit(href).path.strip('/').split('/')[-1].replace('-',' ')
        if not source_match(href,source) or len(title)<4:
            continue
        if source.keyword and not TECH.search(title):
            continue
        try:
            url=canonical(href)
            if source.url and url==canonical(source.url):continue
            if re.fullmatch(r'Events?|View all events|See all events|Browse events|모든 이벤트|행사 목록|이벤트|행사',title,re.I):continue
            title=re.sub(r'^(모집중|모집완료)\s*','',title)[:180]
            e=new_event(url,title,provenance=source.id,evidence=source.name+' 공개 목록에서 발견. 개별 접수 상태 검증 전.')
            e['activity_type']='oss_issue' if '/issues/' in url else activity_type(title)
            if '/projects/' in url or source.id=='letspl':e['activity_type']='project'
            if '/studies/' in url:e['activity_type']='study'
            if source.id in ('dacon','daker','aifactory','hackon','devpost','lablab'):e['activity_type']='hackathon'
            found[url]=e
        except ValueError:
            pass
    # Links in SSR JSON are source records, never executed JavaScript.
    for script in soup.select('script#__NEXT_DATA__,script[type="application/ld+json"]'):
        if source.id=='openai':continue
        try:
            nodes=json_nodes(json.loads(script.string or script.get_text()))
            for n in nodes:
                title=n.get('title') or n.get('name') or n.get('projectName')
                href=n.get('eventUrl') or n.get('url') or n.get('link')
                if isinstance(title,str) and isinstance(href,str):
                    extra=extract_anchor(title,href,base_url,source)
                    if extra:
                        # Meetup's named Event object is more precise than a card's price/seat label.
                        if n.get('eventUrl'):found[extra['canonical_url']]=extra
                        else:found.setdefault(extra['canonical_url'],extra)
        except (ValueError,TypeError,RecursionError):pass
    if source.adapter=='mongodb':
        for script in soup.select('script'):
            text=script.get_text()
            marker=re.search(r'window\.__PATHFACTORY__\s*=\s*',text)
            if not marker:continue
            try:data,_=json.JSONDecoder().raw_decode(text[marker.end():])
            except ValueError:continue
            for n in json_nodes(data):
                if n.get('contentTypeName') not in ('Live Webinar','Live Workshop','MongoDB Event','Industry Event'):continue
                href=n.get('canonicalUrl');title=n.get('title')
                if not isinstance(href,str) or not isinstance(title,str):continue
                extra=extract_anchor(title,href,base_url,source)
                if extra:
                    extra['summary']=(n.get('description') or '')[:700]
                    found[extra['canonical_url']]=extra
    return list(found.values())[:35]

def extract_anchor(title,href,base,source):
    from html import escape
    if not source_match(urljoin(base,href),source):return None
    if source.url and canonical(urljoin(base,href))==canonical(source.url):return None
    if source.keyword and not TECH.search(title):return None
    try:return new_event(urljoin(base,href),title[:180],provenance=source.id)
    except ValueError:return None

async def discover(fetcher, renderer, record, selected=None):
    sem=asyncio.Semaphore(4)
    dynamic_sem=asyncio.Semaphore(1)
    async def one(s):
        async with sem:
            result={'id':s.id,'name':s.name,'group':s.group,'url':s.url,'count':0,'method':'http','state':'running','error':None}
            try:
                if not s.enabled:
                    result.update(state='disabled',method='policy',error=s.note,checked_at=iso_now())
                    record(result)
                    return result
                if not s.url:
                    result.update(state='missing',method='none',error='구체적인 공개 목록 URL이 없는 탐색 범주입니다. 수집 소스 설정이 필요합니다.')
                    record(result)
                    return result
                r=await fetcher.page(s.url)
                r.raise_for_status()
                if s.id.startswith('github_'):
                    items=[new_event(i['html_url'],i['title'],activity_type='oss_issue',summary=(i.get('body') or '')[:700],provenance=s.id) for i in r.json().get('items',[]) if not i.get('pull_request')]
                elif s.id=='pytorch':
                    topics=r.json().get('topic_list',{}).get('topics',[])
                    items=[new_event(f'https://discuss.pytorch.kr/t/{t["slug"]}/{t["id"]}',t['title'],provenance=s.id)
                           for t in topics if re.search(r'밋업|모임|행사|컨퍼런스|PyTorch Day|워크숍|스터디',t['title'],re.I)]
                elif s.adapter=='event_page':
                    title=BeautifulSoup(r.text,'html.parser').title
                    if not title or not re.search(r'PyCon|Meta Connect',title.get_text(),re.I):raise ValueError('공식 행사 페이지의 제목을 확인하지 못했습니다.')
                    items=[new_event(s.url,title.get_text()[:180],source=s.name,provenance=s.id,evidence='공식 단일 행사 안내입니다. 모집 가능 여부와 행사 날짜는 원문 검증 전입니다.')]
                elif s.club:
                    items=club_candidates(r.text,str(r.url),s)
                else:
                    items=parse_dev_event(r.text) if s.id=='dev_event' else extract_links(r.text,str(r.url),s)
                if not items and renderer and (s.dynamic or 'html' in r.headers.get('content-type','')):
                    async with dynamic_sem:
                        rendered=await renderer.render(s.url)
                    items=club_candidates(rendered['html'],rendered['url'],s) if s.club else extract_links(rendered['html'],rendered['url'],s)
                    result['method']='browser'
                result['count']=len(items)
                result['state']='ok' if items else 'empty'
                if not items:result['error']='공개 목록에서 후보를 추출하지 못했습니다. 형식 변경·지역 목록·로그인 여부 확인 필요.'
                for e in items:yield_items.append(e)
            except Exception as exc:
                message=str(exc) or type(exc).__name__
                status=getattr(getattr(exc,'response',None),'status_code',None)
                blocked='robots' in message or status in (401,403,429) or 'CERTIFICATE_VERIFY_FAILED' in message
                if status==404:message='등록한 공개 목록 주소가 없어졌습니다(HTTP 404). 공식 대체 주소 확인이 필요합니다.'
                elif status in (401,403,429):message=f'사이트가 자동 접근을 제한했습니다(HTTP {status}). 로그인·차단을 우회하지 않습니다.'
                elif 'certificate has expired' in message:message='공식 사이트의 TLS 인증서가 만료됐습니다. 사이트 운영자 조치가 필요합니다.'
                result.update(state='blocked' if blocked else 'error',error=message[:300])
            result['checked_at']=iso_now()
            record(result)
            return result
    yield_items=[]
    results=await asyncio.gather(*(one(s) for s in SOURCES if selected is None or s.id in selected))
    return yield_items,results


def club_candidates(html, url, source):
    """A recruitment watch page is a candidate, never proof that intake is open."""
    soup=BeautifulSoup(html,'html.parser')
    for node in soup.select('script,style,noscript'):node.decompose()
    text=soup.get_text(' ',strip=True)
    if len(text)<80 or not re.search(r'모집|지원|동아리|커뮤니티|recruit|join',text,re.I):return []
    e=new_event(source.url,source.name+' · 동아리 모집 안내',activity_type='club',
                source=source.name,organizer=source.name,summary='공식 동아리·커뮤니티 모집 안내 페이지입니다. 현재 기수·모집 기간·참가 조건은 원문 검증 결과를 확인하세요.',
                provenance=source.id,evidence='공식 안내 페이지 발견. 알림 신청과 실제 모집은 구분하며, 모집 중으로 추정하지 않습니다.')
    return [e]

def search_queries():
    from .core import now
    period=now().strftime('%Y년 %m월')
    return [
        f'{period} 개발자 행사 밋업 컨퍼런스 모집 site:event-us.kr',
        f'{period} AI 개발자 서울 site:luma.com OR site:meetup.com OR site:ticketa.co OR site:partiful.com',
        f'{period} 백엔드 프로젝트 모집 site:inflearn.com/projects OR site:okky.kr/articles OR site:letspl.me/project',
        f'{period} 개발 스터디 모집 site:holaworld.io OR site:teampik.com OR site:disquiet.io',
        f'{period} 해커톤 공모전 접수 site:dacon.io OR site:daker.ai OR site:aifactory.space OR site:hackon.kr',
        f'{period} AI hackathon registration site:lablab.ai OR site:devpost.com',
        f'{period} 개발자 행사 GDG AWSKRUG PyTorchKR OpenInfra CNCF PyCon',
        f'{period} Korea developer event AWS Google Microsoft NVIDIA MongoDB Redis RedHat Oracle JetBrains OpenAI Meta',
        f'{period} 개발자 멘토링 행사 site:wanted.co.kr OR site:programmers.co.kr OR site:jumpit.saramin.co.kr OR site:rocketpunch.com',
        f'{period} 개발자 행사 site:linkedin.com/events',
        f'{period} 소프트웨어 AI 해커톤 공모전 모집 site:go.kr OR site:ac.kr',
    ]

async def discover_search_api(fetcher):
    """Optional user-owned Brave key; no credential is ever returned to the UI."""
    key=os.environ.get('BRAVE_SEARCH_API_KEY')
    if not key:return [],{'state':'agent_bridge','message':'검색은 연결된 Codex 자동 탐색에서 수행합니다. Brave 키는 선택 사항입니다.'}
    items={}
    for query in search_queries()[:6]:
        response=await fetcher.client.get('https://api.search.brave.com/res/v1/web/search',headers={'X-Subscription-Token':key},params={'q':query,'count':10})
        response.raise_for_status()
        for r in response.json().get('web',{}).get('results',[]):
            url=r.get('url','')
            for s in SOURCES:
                if source_match(url,s):
                    try:items[url]=new_event(url,r.get('title','')[:180],summary=r.get('description','')[:700],provenance='web_search')
                    except ValueError:pass
                    break
        await asyncio.sleep(1)
    return list(items.values()),{'state':'ok','count':len(items)}
