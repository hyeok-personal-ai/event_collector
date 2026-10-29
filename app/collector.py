import asyncio
import hashlib
import ipaddress
import json
import re
import socket
import gzip
from pathlib import Path
from urllib.parse import urljoin, urlsplit
from urllib.robotparser import RobotFileParser

import httpx
from bs4 import BeautifulSoup
from .core import canonical, parse_date, now, iso_now, categories, activity_type

USER_AGENT = 'TechEventRadar/0.1 (+local personal event organizer)'
DEV_EVENT_URL = 'https://raw.githubusercontent.com/brave-people/Dev-Event/master/README.md'

async def public_url(url):
    # Canonical identity can omit a trailing slash; a network redirect target cannot.
    canonical(url)
    url=url.strip().split('#',1)[0]
    host = urlsplit(url).hostname
    try:
        addresses = await asyncio.wait_for(asyncio.get_running_loop().getaddrinfo(host, None, type=socket.SOCK_STREAM),timeout=10)
    except (OSError,TimeoutError):
        raise ValueError('DNS 조회 실패: 주소에 접속할 수 없습니다.')
    if not addresses or any(not ipaddress.ip_address(a[4][0]).is_global for a in addresses):
        raise ValueError('공개 인터넷 주소만 수집할 수 있습니다.')
    return url

class Fetcher:
    def __init__(self):
        self.client = httpx.AsyncClient(timeout=18, follow_redirects=False, headers={'User-Agent': USER_AGENT}, trust_env=False)
        self.robots = {}
        self.locks = {}

    async def close(self):
        await self.client.aclose()

    async def request(self, url, respect_robots=False):
        for _ in range(6):
            url = await public_url(url)
            if respect_robots:
                await self.allowed(url)
            async with self.client.stream('GET', url) as r:
                if r.is_redirect:
                    url = urljoin(url, r.headers.get('location', ''))
                    continue
                chunks, size = [], 0
                async for block in r.aiter_bytes():
                    size += len(block)
                    if size > 3_000_000:
                        raise ValueError('페이지가 너무 큽니다. 3 MB 제한을 초과했습니다.')
                    chunks.append(block)
                # aiter_bytes has already decoded compression. Do not decode a second time.
                headers = {k: v for k, v in r.headers.items() if k.lower() not in ('content-encoding', 'content-length')}
                return httpx.Response(r.status_code, headers=headers, content=b''.join(chunks), request=r.request)
        raise ValueError('리다이렉트 횟수를 초과했습니다.')

    async def allowed(self, url):
        p = urlsplit(url)
        origin = f'{p.scheme}://{p.netloc}'
        if origin not in self.robots:
            response = await self.request(origin + '/robots.txt')
            if response.status_code == 404:
                self.robots[origin] = None
            elif response.status_code >= 400:
                raise ValueError(f'robots.txt 확인 실패 (HTTP {response.status_code})')
            else:
                parser = RobotFileParser()
                parser.parse(response.text.splitlines())
                self.robots[origin] = parser
        parser = self.robots[origin]
        if parser and not parser.can_fetch(USER_AGENT, url):
            raise ValueError('robots.txt에서 자동 수집을 허용하지 않습니다.')

    async def page(self, url):
        url = await public_url(url)
        host = urlsplit(url).hostname
        lock = self.locks.setdefault(host, asyncio.Lock())
        async with lock:
            response = await self.request(url, respect_robots=True)
            await asyncio.sleep(.6)
            return response

def json_nodes(value):
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from json_nodes(child)
    elif isinstance(value, list):
        for child in value:
            yield from json_nodes(child)

def parse_page(html, url, previous, observation=None):
    soup = BeautifulSoup(html, 'html.parser')
    e = dict(previous)
    nodes = []
    for script in soup.select('script[type="application/ld+json"]'):
        try:
            nodes.extend(json_nodes(json.loads(script.string or script.get_text())))
        except (ValueError, TypeError):
            continue
    events = [n for n in nodes if any(str(t).endswith('Event') for t in (n.get('@type') if isinstance(n.get('@type'), list) else [n.get('@type', '')]))]
    # A collection page's many events must never be mistaken for one event detail.
    structured = events[0] if len(events) == 1 else {}
    for tag in soup.select('script,style,nav,footer,header,noscript'):
        tag.decompose()
    text = soup.get_text(' ', strip=True)
    lines = soup.get_text('\n', strip=True).splitlines()
    participant_sections = []
    for i, line in enumerate(lines):
        match = re.fullmatch(r'\s*(?:참가\s*자격|지원\s*자격|참가\s*대상|모집\s*대상|신청\s*자격)\s*[:：]?\s*(.{0,250})', line)
        if match:
            value = match[1].strip() or (lines[i+1].strip() if i+1 < len(lines) else '')
            if value:
                participant_sections.append(value[:250])
    e['eligibility_target'] = ' / '.join(participant_sections)[:1500]
    description = soup.select_one('meta[property="og:description"],meta[name="description"]')
    title = soup.select_one('meta[property="og:title"]')
    if structured.get('name'):
        e['title'] = str(structured['name'])[:300]
    elif title and title.get('content'):
        e['title'] = title['content'][:300]
    elif soup.title and soup.title.string:
        e['title'] = soup.title.string[:300]
    if len(e['title']) > 90 and previous.get('title') and previous['title'] != urlsplit(url).hostname:
        e['title'] = previous['title']
    if description and description.get('content'):
        e['summary'] = description['content'][:700]
    elif structured.get('description'):
        e['summary'] = BeautifulSoup(str(structured['description']), 'html.parser').get_text(' ', strip=True)[:700]
    for key, field in [('startDate', 'start_at'), ('endDate', 'end_at')]:
        value = parse_date(structured.get(key))
        if value:
            e[field] = value.isoformat()
    organizer = structured.get('organizer')
    if isinstance(organizer, dict):
        e['organizer'] = str(organizer.get('name') or e.get('organizer') or '')
    location = structured.get('location')
    if isinstance(location, dict):
        e['location'] = str(location.get('name') or ('온라인' if location.get('@type') == 'VirtualLocation' else e.get('location') or ''))
    offers = structured.get('offers') or []
    offers = [offers] if isinstance(offers, dict) else offers
    offers = [o for o in offers if isinstance(o, dict)] if isinstance(offers, list) else []
    active = []
    for offer in offers:
        start = parse_date(offer.get('validFrom') or offer.get('availabilityStarts'))
        end = parse_date(offer.get('validThrough') or offer.get('availabilityEnds'), True)
        if (not start or start <= now()) and (not end or end > now()):
            active.append(offer)
    deadlines = [parse_date(o.get('validThrough') or o.get('availabilityEnds'), True) for o in offers]
    # Never turn startDate into a registration deadline.
    if deadlines and all(deadlines):
        e['apply_deadline'] = max(deadlines).isoformat()
    if offers and all(str(o.get('price')) in ('0', '0.0', '0.00') for o in offers):
        e['price'] = '무료'
    elif offers and offers[0].get('price') is not None:
        e['price'] = str(offers[0]['price']) + ' ' + str(offers[0].get('priceCurrency', ''))
    controls = []
    for el in soup.select('a[href], button, input[type="submit"]'):
        label = el.get_text(' ', strip=True) or el.get('value', '')
        if re.fullmatch(r'.{0,20}(신청하기|참가 신청|등록하기|RSVP|Register|Get Tickets|Request to Join|Join Waitlist).{0,20}', label, re.I):
            actionable = el.name != 'a' or (el.get('href') and not el['href'].startswith(('#', 'javascript:')))
            if actionable and not el.has_attr('disabled') and el.get('aria-disabled') != 'true' and not el.has_attr('hidden'):
                controls.append((label, el.get('href')))
    if observation is not None:
        controls=[(c['label'],c.get('href')) for c in observation.get('controls',[])
                  if not c['disabled'] and re.search(r'신청|등록|RSVP|Register|Get Tickets|Request to Join|Waitlist',c['label'],re.I)]
    availability = [str(o.get('availability', '')).split('/')[-1] for o in active]
    status = 'CHECK_REQUIRED'
    evidence = '페이지 열람 성공. 현재 접수 가능 여부를 확정할 구조화 정보가 부족합니다.'
    # Look at event status and actionable controls, not unrelated text elsewhere on the page.
    signals = ' '.join(label for label, _ in controls)
    closed_controls = [el.get_text(' ', strip=True) for el in soup.select('button,[role="button"]')]
    if observation is not None:
        closed_controls=[c['label'] for c in observation.get('controls',[]) if c.get('tag')!='a']
    if 'EventCancelled' in str(structured.get('eventStatus', '')):
        status, evidence = 'CLOSED', '공식 Event 구조화 데이터: 행사 취소'
    elif offers and all(str(o.get('availability', '')).endswith('SoldOut') for o in offers):
        status, evidence = 'SOLD_OUT', '공식 티켓 구조화 데이터: 모든 티켓 SoldOut'
    elif any(re.fullmatch(r'\s*(매진|Sold Out)\s*', x, re.I) for x in closed_controls):
        status,evidence='SOLD_OUT','신청 영역에 매진 표시 확인'
    elif any(re.fullmatch(r'\s*(모집 마감|접수 종료|신청 마감|Registration Closed|매진|Sold Out)\s*', x, re.I) for x in closed_controls):
        status, evidence = 'CLOSED', '신청 영역에 마감/종료 표시 확인'
    elif re.search(r'Waitlist|대기신청|대기 신청', signals, re.I):
        status, evidence = 'WAITLIST', '활성 대기신청 버튼 확인. 일반 신청과 구분합니다.'
    elif structured and 'InStock' in availability and controls:
        status, evidence = 'OPEN', '개별 Event 구조화 데이터의 유효 티켓 InStock + 활성 신청 버튼 확인'
    deadline = parse_date(e.get('apply_deadline'), True)
    ended = parse_date(e.get('end_at') or e.get('start_at'), True)
    if (deadline and deadline <= now()) or (ended and ended <= now()):
        status, evidence = 'CLOSED', '확인된 접수 마감 또는 행사 일정이 지났습니다.'
    for _, href in controls:
        if href and not href.startswith(('#', 'javascript:')):
            try:
                e['application_url'] = canonical(urljoin(url, href))
                break
            except ValueError:
                pass
    if status in ('OPEN', 'WAITLIST'):
        application = e.get('application_url')
        # Cross-page forms need their own verifier; do not claim they are accepting submissions.
        if application and canonical(application) != canonical(url):
            status, evidence = 'CHECK_REQUIRED', evidence + ' / 외부 또는 별도 신청폼의 접수 상태는 추가 확인 필요'
    detected_categories = list(dict.fromkeys(previous.get('categories', []) + categories(e['title'] + ' ' + e.get('summary', ''))))
    if len(detected_categories) > 1 and 'General' in detected_categories:
        detected_categories.remove('General')
    detected_type = activity_type(e['title'])
    if re.search(r'github\.com/.+/issues/\d+', url):
        detected_type = 'oss_issue'
    elif detected_type == 'conference':
        detected_type = previous.get('activity_type', 'conference')
    e.update(status=status, evidence=evidence, last_verified_at=iso_now(),
             content_hash=hashlib.sha256(text.encode()).hexdigest(),
             categories=detected_categories, activity_type=detected_type)
    return e, text[:12000]

def store_raw(html):
    digest=hashlib.sha256(html.encode()).hexdigest()
    folder=Path(__file__).resolve().parent.parent/'data'/'raw'
    folder.mkdir(parents=True,exist_ok=True)
    target=folder/(digest+'.html.gz')
    if not target.exists():target.write_bytes(gzip.compress(html.encode('utf-8')))
    return str(target.relative_to(folder.parent))

async def verify(event, fetcher, renderer=None):
    e = dict(event)
    e.pop('browser_error',None)
    if e.get('needs_recheck') and e.get('discovered_deadline'):
        e['previous_deadline']=e.get('apply_deadline')
        e['apply_deadline']=e['discovered_deadline']
        e['status']='CHECK_REQUIRED'
        e['needs_recheck']=False
    raw=''
    try:
        from .verifiers import verify_github, site_markers, check_external
        if e.get('activity_type')=='oss_issue' and 'github.com/' in e['canonical_url']:
            result=await verify_github(e,fetcher)
            if result:return result,result.get('summary','')
        response = await fetcher.page(e['canonical_url'])
        if response.status_code in (404, 410):
            e.update(status='DEAD', evidence=f'원문 HTTP {response.status_code}', last_verified_at=iso_now())
            raw = ''
        elif response.status_code >= 400:
            raise ValueError(f'원문 접근 실패 (HTTP {response.status_code}). 기존 정보를 보존합니다.')
        elif 'html' not in response.headers.get('content-type', ''):
            raise ValueError('HTML 상세페이지가 아닙니다. 원문에서 확인해 주세요.')
        else:
            html=response.text
            e, raw = parse_page(html, str(response.url), e)
            e['verification_method']='http'
            e['raw_snapshot']=store_raw(html)
            e=site_markers(e,html)
            known_dynamic=any((urlsplit(e['canonical_url']).hostname or '').endswith(h) for h in ('event-us.kr','holaworld.io','daker.ai','meetup.com','letspl.me','ticketa.co','partiful.com'))
            expired=(parse_date(e.get('apply_deadline'),True) or now())<now() if e.get('apply_deadline') else False
            if renderer and not expired and (e['status']=='CHECK_REQUIRED' or (known_dynamic and e['status'] not in ('DEAD','SOLD_OUT'))):
                try:
                    page=await renderer.render(e['canonical_url'])
                    if page['http_status'] and page['http_status']>=400:
                        raise ValueError(f'브라우저 접속 HTTP {page["http_status"]}')
                    if re.search(r'Just a moment|Checking your browser|Access denied|보안 확인',page.get('title',''),re.I):
                        raise ValueError('사이트 접근 확인 화면입니다. 자동으로 우회하지 않습니다.')
                    html=page['html']
                    e,raw=parse_page(html,page['url'],e,observation=page)
                    e=site_markers(e,html,page['text'])
                    e.update(verification_method='browser',raw_snapshot=store_raw(html))
                except Exception as exc:
                    e['browser_error']=str(exc)[:300]
            if e['status'] not in ('CLOSED','SOLD_OUT','DEAD'):
                e=await check_external(e,html,renderer,fetcher)
            e['failure_count']=0
            e['error_kind']=None
    except (httpx.HTTPError, ValueError, OSError, KeyError, TypeError) as exc:
        e.update(status='CHECK_REQUIRED', evidence=str(exc) or type(exc).__name__,
                 failure_count=event.get('failure_count',0)+1,error_kind='access' if 'robots' in str(exc) else 'network')
        raw = ''
    e['last_checked_at'] = iso_now()
    return e, raw
