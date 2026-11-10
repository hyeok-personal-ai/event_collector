"""Recruitment facts from individual community posts, never related-card text."""
import re
from datetime import datetime, timedelta
from urllib.parse import urlsplit
from bs4 import BeautifulSoup
from .core import KST, now, parse_date

VERSION = 3
COMMUNITY_HOSTS = ('inflearn.com', 'holaworld.io', 'okky.kr')


def community_post(url):
    p = urlsplit(url)
    host = (p.hostname or '').removeprefix('www.')
    return ((host == 'inflearn.com' and bool(re.match(r'^/(studies|projects)/\d+', p.path))) or
            (host == 'holaworld.io' and bool(re.fullmatch(r'/study/[a-fA-F0-9]+', p.path))) or
            (host == 'okky.kr' and bool(re.match(r'^/articles/\d+', p.path))))


def post_content(html, url):
    """Do not pick up contact/form links from recommended posts or navigation."""
    soup = BeautifulSoup(html, 'html.parser')
    host = (urlsplit(url).hostname or '').removeprefix('www.')
    if host == 'inflearn.com':
        main = soup.select_one('main')
        if not main:
            return BeautifulSoup('', 'html.parser')
        for a in main.select('a[href]'):
            if re.search(r'inflearn\.com/(?:studies|projects)/\d+', a['href']):
                a.decompose()
        return main
    if host == 'holaworld.io':
        return soup.select_one('[class*="postContent_"],.tiptap,.ProseMirror') or BeautifulSoup('', 'html.parser')
    if host == 'okky.kr':
        return soup.select_one('[data-testid="article-content"],.tiptap,.ProseMirror,.prose,article') or BeautifulSoup('', 'html.parser')
    for tag in soup.select('nav,header,footer,aside,script,style'):
        tag.decompose()
    return soup


def community_recruitment_deadline(main):
    """Only labelled date-only recruitment ranges/deadlines, not activity dates.

    Missing years are anchored to the article's own publication date, not today.
    Ambiguous ranges and unsupported time expressions remain unparsed.
    """
    published = main.select_one('.sub-title__created-at .sub-title__value')
    posted = None
    # Inflearn's crawler response uses a semantic time element in the header.
    times = main.select('time[datetime]')
    if len(times) == 1:
        posted = parse_date(times[0].get('datetime'))
    if published:
        match = re.fullmatch(r'(\d{2}|\d{4})\.(\d{1,2})\.(\d{1,2})\s+\d{2}:\d{2}', published.get_text(strip=True))
        if match:
            try:
                year = int(match[1]) + (2000 if len(match[1]) == 2 else 0)
                posted = datetime(year, int(match[2]), int(match[3]), tzinfo=KST)
            except ValueError:
                pass
    date = r'(?:(20\d{2})[./-])?(\d{1,2})[./-](\d{1,2})(?:\s*\(([월화수목금토일])\))?'
    pattern = r'(?:모집|지원|접수)\s*기간\s*[:：]\s*' + date + r'\s*[~～–]\s*' + date + r'\s*$'
    single = r'(?:모집|지원|접수)\s*(?:기간|마감)\s*[:：]\s*(?:~\s*)?(?:(20\d{2}|\d{2})년\s*)?(\d{1,2})월\s*(\d{1,2})일\s*(?:\(([월화수목금토일])\))?\s*까지\s*$'
    numeric_single = r'(?:모집|지원|접수)\s*(?:기간|마감)\s*[:：]\s*(?:~\s*)?' + date + r'\s*까지\s*$'
    deadlines = set()
    lines = main.get_text('\n', strip=True).splitlines()
    # Join only a standalone field label and its immediate value, never prose.
    lines = [line+' '+lines[i+1] if re.search(r'(?:모집|지원|접수)\s*(?:기간|마감)\s*[:：]?\s*$',line) and i+1<len(lines) else line for i,line in enumerate(lines)]
    def weekday_matches(value, weekday):
        return not weekday or '월화수목금토일'[value.weekday()] == weekday
    for line in lines:
        match = re.search(pattern, line)
        if not match:
            one = re.search(single, line) or re.search(numeric_single, line)
            if one:
                year, month, day, weekday = one.groups()
                if not year and not posted:
                    continue
                try:
                    y = int(year) + (2000 if len(year)==2 else 0) if year else posted.year
                    end = datetime(y,int(month),int(day),23,59,59,tzinfo=KST)
                    if not year:
                        end = min([end.replace(year=y+d) for d in (-1,0,1)],key=lambda d:abs(d-posted))
                        if abs(end-posted)>timedelta(days=90):
                            continue
                    if not weekday_matches(end,weekday):
                        return None  # A contradictory weekday makes this field ambiguous.
                    deadlines.add(end.isoformat())
                except ValueError:
                    continue
            continue
        sy, sm, sd, sw, ey, em, ed, ew = match.groups()
        if not sy and not posted:
            continue
        try:
            year = int(sy) if sy else posted.year
            start = datetime(year, int(sm), int(sd), tzinfo=KST)
            if not sy:
                candidates = [start.replace(year=year+delta) for delta in (-1, 0, 1)]
                start = min(candidates, key=lambda d: abs(d-posted))
                if abs(start-posted) > timedelta(days=90):
                    continue
            endyear = int(ey) if ey else start.year + (int(em) < start.month)
            end = datetime(endyear, int(em), int(ed), 23, 59, 59, tzinfo=KST)
            if not weekday_matches(start,sw) or not weekday_matches(end,ew):
                return None
            if timedelta(0) <= end-start <= timedelta(days=180):
                deadlines.add(end.isoformat())
        except ValueError:
            continue
    return next(iter(deadlines)) if len(deadlines) == 1 else None


def recruitment_facts(event, html, observation=None):
    e = dict(event)
    if not community_post(e['canonical_url']):
        return e
    host = (urlsplit(e['canonical_url']).hostname or '').removeprefix('www.')
    soup = BeautifulSoup(html, 'html.parser')
    if host in ('inflearn.com', 'okky.kr'):
        extracted_deadline = community_recruitment_deadline(post_content(html,e['canonical_url']))
        if extracted_deadline and not e.get('apply_deadline'):
            e['apply_deadline'] = extracted_deadline
    if host == 'inflearn.com':
        e['activity_type'] = 'study' if '/studies/' in e['canonical_url'] else 'project'
        # A crawl-friendly article may omit the platform's recruitment status.
        # Never infer OPEN from its title or a recommended article's badge.
        main = post_content(html, e['canonical_url'])
        labels = [x.get_text(' ', strip=True) for x in main.select('button')]
        if any(x in ('모집완료', '모집 완료', '모집 마감') for x in labels):
            e.update(status='CLOSED', evidence='인프런 개별 모집글의 모집 완료 표시 확인')
        elif '모집중' in labels or '모집 중' in labels:
            e.update(status='OPEN', recruitment_basis='listing', evidence='개별 모집글의 모집 중 표시 확인. 지원폼 응답 가능 여부와 최종 선발은 별도입니다.')
    elif host == 'holaworld.io' and observation:
        info = soup.select_one('[class*="mainCard_"]')
        if not info:
            return e
        fields = {}
        for row in info.select('[class*="infoRow_"],[class*="fullWidthRow_"]'):
            label = row.select_one('[class*="label_"]')
            value = row.select_one('[class*="value_"]')
            if label and value:
                fields[label.get_text(strip=True)] = value.get_text(' ', strip=True)
        kind = fields.get('모집 구분')
        if kind not in ('스터디', '프로젝트'):
            return e
        e['activity_type'] = 'study' if kind == '스터디' else 'project'
        mode = fields.get('진행 방식', '')
        if mode in ('온라인', '오프라인', '온/오프라인'):
            e.update(location=mode, attendance_mode={'온라인':'online','오프라인':'offline','온/오프라인':'hybrid'}[mode])
        languages = [i.get('alt') for i in info.select('[class*="languages_"] img[alt]')]
        if languages:
            e['tech_stack'] = ', '.join(dict.fromkeys(languages))[:300]
        buttons = info.select('button[class*="applyButton_"]')
        labels = [b.get_text(' ', strip=True) for b in buttons]
        visible = observation.get('controls', [])
        if any(re.fullmatch(r'모집\s*(?:마감|완료)|마감된 모집', x) for x in labels):
            e.update(status='CLOSED', evidence='HOLA 개별 글의 모집 마감 버튼 확인')
        elif any(b.get_text(strip=True)=='지원하기' and not b.has_attr('disabled') and b.get('aria-disabled')!='true' for b in buttons) and any(c.get('label')=='지원하기' and not c.get('disabled') for c in visible):
            e.update(status='OPEN', recruitment_basis='listing', application_url=e['canonical_url'],
                     evidence='HOLA 개별 모집 정보와 현재 보이는 활성 지원하기 버튼 확인. 연락·지원은 원문에서 진행하며 잔여 인원과 선발은 주최자가 결정합니다.')
    deadline = parse_date(e.get('apply_deadline'), True)
    if deadline and deadline <= now():
        e.update(status='CLOSED', evidence='개별 모집글에서 확인한 모집 마감일이 지났습니다. 모집 중 버튼보다 마감일을 우선합니다.')
    return e
