"""Discover contests through a reusable feed and first-party public notices."""
import re
from datetime import date, datetime, timedelta
from urllib.parse import parse_qs, urlencode, urljoin, urlsplit

from bs4 import BeautifulSoup

from .access_policy import assert_collection_allowed
from .core import KST, canonical, new_event, now, parse_date
from .official_programs import program_verdict

HACKALENDAR_URL = 'https://hackalendar.com/api/events?limit=40'
SEOUL_PRESS_DATA = 'https://data.seoul.go.kr/dataList/OA-22195/S/1/datasetView.do'
SEOUL_HACKATHON = 'https://www.startup-plus.kr/project/PRJ007715'
SEOUL_HACKATHON_NAME = '2026 서울 야간경제 활성화 해커톤 (Dopamine Seoul 24)'
MOIS_ROOT = 'https://www.mois.go.kr'
MOIS_LIST = MOIS_ROOT + '/frt/bbs/type010/commonSelectBoardList.do'
MOIS_ARTICLE = '/frt/bbs/type010/commonSelectBoardArticle.do'
MOIS_BOARD = 'BBSMSTR_000000000008'
MOIS_URL = MOIS_LIST + '?' + urlencode({'bbsId': MOIS_BOARD, 'searchCnd': '0', 'searchWrd': '경진대회'})
TECH_CONTEST = re.compile(r'해커톤|해킹|인공지능|\bAI\b|소프트웨어|공공데이터|로봇|빅데이터', re.I)
RESULT_NOTICE = re.compile(r'수상작|결과\s*발표|선정\s*결과|성황리|시상식|왕중왕전|몰렸다')


async def seoul_hackathon_candidate(fetcher):
    response = await fetcher.page(SEOUL_PRESS_DATA)
    response.raise_for_status()
    soup = BeautifulSoup(response.text, 'html.parser')
    licence = soup.select_one('.ccl-txt img[src*="opentype04"]')
    if not licence or '공공누리 4유형' not in licence.parent.get_text(' ', strip=True):
        raise ValueError('서울시 보도자료 데이터의 공공누리 제4유형 표시를 확인하지 못했습니다.')
    return new_event(SEOUL_HACKATHON, SEOUL_HACKATHON_NAME, activity_type='hackathon', country_code='KR',
                     location='서울', organizer='서울특별시 · 서울경제진흥원')


async def verify_seoul_hackathon(event, fetcher):
    response = await fetcher.page(SEOUL_HACKATHON)
    response.raise_for_status()
    if canonical(str(response.url)) != SEOUL_HACKATHON:
        raise ValueError('서울경제진흥원 공식 접수 주소가 달라졌습니다.')
    soup = BeautifulSoup(response.text, 'html.parser')
    receipt = soup.select_one('[data-bind-type="receiptDate"]')
    guide = soup.select_one('[data-guide]')
    published = BeautifulSoup(guide['data-guide'], 'html.parser') if guide else soup
    match = re.fullmatch(r'(20\d{2}-\d\d-\d\d \d\d:\d\d)\s*~\s*(20\d{2}-\d\d-\d\d \d\d:\d\d)',
                         receipt.get_text(' ', strip=True) if receipt else '')
    if not match or 'Dopamine Seoul 24' not in published.get_text(' ', strip=True):
        raise ValueError('서울경제진흥원 공식 공고에서 같은 행사와 접수 일시를 확인하지 못했습니다.')
    start, end = (datetime.fromisoformat(value).replace(tzinfo=KST) for value in match.groups())
    if start >= end:
        raise ValueError('공식 공고의 접수 시작과 마감 일시가 일치하지 않습니다.')
    status = 'CLOSED' if now() >= end else 'OPEN' if now() >= start else 'CHECK_REQUIRED'
    return program_verdict(event, SEOUL_HACKATHON_NAME, 'hackathon', status,
                           '서울경제진흥원 공식 접수 기간 확인', SEOUL_HACKATHON,
                           apply_deadline=end.isoformat())


async def hackalendar_candidates(fetcher):
    response = await fetcher.page(HACKALENDAR_URL)
    response.raise_for_status()
    if canonical(str(response.url)) != HACKALENDAR_URL:
        raise ValueError('Hackalendar 공식 API 주소가 변경되었습니다.')
    records = response.json().get('data')
    if not isinstance(records, list):
        raise ValueError('Hackalendar에서 행사 배열을 확인하지 못했습니다.')
    found = {}
    for row in records:
        title, raw_url = row.get('name'), row.get('registrationUrl')
        deadline = parse_date(row.get('registrationDeadline'), True)
        end = parse_date(row.get('endAt') or row.get('startAt'), True)
        if not isinstance(title, str) or not title.strip() or not isinstance(raw_url, str) or row.get('status') != 'published':
            continue
        if (deadline and deadline < now()) or (end and end < now()):
            continue
        try:
            url = canonical(raw_url)
            assert_collection_allowed(url)
        except ValueError:
            continue
        found[url] = new_event(url, title[:180], activity_type='hackathon',
                               apply_deadline=deadline.isoformat() if deadline else None,
                               start_at=row.get('startAt') if parse_date(row.get('startAt')) else None,
                               end_at=row.get('endAt') if parse_date(row.get('endAt')) else None,
                               evidence='Hackalendar API에서 확인한 후보입니다. 주최자 공개 모집 상태는 검증 전입니다.')
    return list(found.values())


def mois_notice_url(href):
    parsed = urlsplit(urljoin(MOIS_ROOT, href))
    qs = parse_qs(parsed.query)
    ids = qs.get('nttId', [])
    if parsed.netloc != 'www.mois.go.kr' or parsed.path.split(';', 1)[0] != MOIS_ARTICLE:
        return None
    if qs.get('bbsId') != [MOIS_BOARD] or len(ids) != 1 or not ids[0].isdigit():
        return None
    return MOIS_ROOT + MOIS_ARTICLE + '?' + urlencode({'bbsId': MOIS_BOARD, 'nttId': ids[0]})


async def mois_candidates(fetcher):
    found = {}
    for keyword in ('경진대회', '해커톤', '공모전'):
        url = MOIS_LIST + '?' + urlencode({'bbsId': MOIS_BOARD, 'searchCnd': '0', 'searchWrd': keyword})
        response = await fetcher.page(url)
        response.raise_for_status()
        for link in BeautifulSoup(response.text, 'html.parser').select('a[href*="nttId"]'):
            canonical_url = mois_notice_url(link['href'])
            title = link.get_text(' ', strip=True)
            if not canonical_url or not TECH_CONTEST.search(title) or RESULT_NOTICE.search(title):
                continue
            row = link.find_parent('tr') or link.parent
            posted = re.search(r'\b(20\d{2})[.\-](\d{2})[.\-](\d{2})\b', row.get_text(' ', strip=True))
            if posted and date(*map(int, posted.groups())) < now().date() - timedelta(days=180):
                continue
            found[canonical_url] = new_event(canonical_url, title[:180],
                                             activity_type='hackathon' if '해커톤' in title else 'conference')
    return list(found.values())[:12]


def mois_application_window(body, year):
    dated = r'(?:\b(20\d{2})\s*년\s*)?(\d{1,2})\s*월\s*(\d{1,2})\s*일(?:\s*\(\s*[월화수목금토일]\s*\))?'
    pattern = dated + r'\s*(?:부터|~|∼)\s*' + dated + r'\s*(?:까지)?'
    windows = set()
    for sentence in re.split(r'[.!?\n]+', body):
        if not re.search(r'접수|신청|제출', sentence) or re.search(r'수상작|심사|발표', sentence):
            continue
        match = re.search(pattern, sentence)
        if match:
            y1, m1, d1, y2, m2, d2 = match.groups()
            start = date(int(y1 or year), int(m1), int(d1))
            end = date(int(y2 or (start.year + (int(m2) < start.month))), int(m2), int(d2))
            if start <= end:
                windows.add((start, end))
    return windows.pop() if len(windows) == 1 else None


async def verify_mois(event, fetcher):
    url = event['canonical_url']
    response = await fetcher.page(url)
    response.raise_for_status()
    if mois_notice_url(str(response.url)) != url:
        raise ValueError('행정안전부 보도자료 원문 주소가 달라졌습니다.')
    area = BeautifulSoup(response.text, 'html.parser').select_one('.table_detail_area')
    licence = area.select_one('.bbs_open') if area else None
    if not licence or not re.search(r'공공누리\s*1\s*유형', licence.get_text(' ', strip=True)):
        raise ValueError('해당 보도자료의 공공누리 1유형 표시를 확인하지 못했습니다.')
    heading, info, detail = area.select_one('h4.subject'), area.select_one('.table_info'), area.select_one('.desc')
    if not heading or not info or not detail:
        raise ValueError('행정안전부 모집 보도자료 형식이 변경되었습니다.')
    title = ' '.join(heading.find_all(string=True, recursive=False)).strip()
    year = re.search(r'등록일\s*:\s*(20\d{2})', info.get_text(' ', strip=True))
    window = mois_application_window(detail.get_text(' ', strip=True), int(year[1])) if year else None
    today = now().date()
    status, deadline = 'CHECK_REQUIRED', None
    if window:
        start, end = window
        deadline = end.isoformat()
        if end < today:
            status = 'CLOSED'
        elif start <= today < end:
            status = 'OPEN'
    return program_verdict(event, title[:180] or event['title'], event['activity_type'], status,
                           '행정안전부 공공누리 1유형 보도자료의 접수 일정 확인' if window else '공식 보도자료에서 접수 기간 미확인',
                           url, apply_deadline=deadline)
