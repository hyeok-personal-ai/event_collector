"""Read recruitment facts from two licensed organizer sources."""
import re
from calendar import monthrange
from datetime import datetime, timedelta, timezone
from urllib.parse import urljoin, urlsplit

from bs4 import BeautifulSoup

from .core import KST, iso_now, new_event, now
from .recruitment import VERSION

DALE_URL = 'https://dalestudy.com/programs'
CNCF_TREE = 'https://api.github.com/repos/cncf/mentoring/git/trees/main?recursive=1'
CNCF_API = 'https://api.github.com/repos/cncf/mentoring/contents/'
CNCF_DOCS = 'https://github.com/cncf/mentoring/blob/main/'
CNCF_PATH = r'programs/lfx-mentorship/(20\d{2})/\d{2}-[A-Za-z]{3}-([A-Za-z]{3})/README\.md'
DATE = r'(?:Mon|Tue|Wed|Thu|Fri|Sat|Sun), ([A-Z][a-z]{2}) (\d{1,2}), (\d{2}:\d{2}) UTC'
MONTHS = 'Jan Feb Mar Apr May Jun Jul Aug Sep Oct Nov Dec'.split()


def dale_programs(html):
    records = []
    for card in BeautifulSoup(html, 'html.parser').select('a.card-link[href]'):
        path = card['href']
        if not re.fullmatch(r'/programs/[a-z0-9-]+', path):
            continue
        title, badge = card.select_one('strong'), card.select_one('.program-card-head > span:last-child')
        if not title or not badge:
            continue
        title = title.get_text(' ', strip=True)
        kind = 'study' if title.endswith('스터디') else 'project' if path == '/programs/daleui' else None
        if kind:
            records.append((urljoin(DALE_URL, path), title, kind, badge.get_text(' ', strip=True)))
    if not records:
        raise ValueError('달레 스터디 공식 프로그램 카드 또는 모집 상태를 찾지 못했습니다.')
    return records


def dale_is_open(badge):
    return bool(re.fullmatch(r'(?:상시 모집|(?:\d+기 )?모집\s*중)', badge))


async def dale_listing(fetcher):
    response = await fetcher.page(DALE_URL)
    response.raise_for_status()
    if str(response.url).rstrip('/') != DALE_URL:
        raise ValueError('달레 스터디 공식 목록 주소가 변경되었습니다.')
    return dale_programs(response.text)


def cncf_window(markdown, year):
    row = re.search(r'^\|\s*Mentee Applications Open\s*\|([^|]+)\|', markdown, re.M)
    dates = re.fullmatch(DATE + r'\s*[-–—]\s*' + DATE, row[1].strip()) if row else None
    if not dates:
        return None
    def timestamp(month, day, clock):
        hour, minute = map(int, clock.split(':'))
        return datetime(year, MONTHS.index(month) + 1, int(day), hour, minute, tzinfo=timezone.utc)
    start, end = timestamp(*dates.groups()[:3]), timestamp(*dates.groups()[3:])
    return (start, end) if start < end else None


def cncf_paths(payload, current):
    if payload.get('truncated') or not isinstance(payload.get('tree'), list):
        raise ValueError('CNCF 공식 문서 목록을 전부 읽지 못했습니다.')
    paths = []
    for item in payload['tree']:
        match = re.fullmatch(CNCF_PATH, item.get('path', '')) if item.get('type') == 'blob' else None
        if not match or int(match[1]) not in (current.year - 1, current.year, current.year + 1) or match[2] not in MONTHS:
            continue
        year, month = int(match[1]), MONTHS.index(match[2]) + 1
        last_day = datetime(year, month, monthrange(year, month)[1], tzinfo=KST)
        if last_day.date() >= (current - timedelta(days=30)).date():
            paths.append(item['path'])
    return sorted(paths, reverse=True)[:8]


async def verify_program(event, fetcher):
    url = event['canonical_url']
    if url.startswith(DALE_URL + '/') and re.fullmatch(r'/programs/[a-z0-9-]+', urlsplit(url).path):
        record = next((r for r in await dale_listing(fetcher) if r[0] == url), None)
        if not record:
            raise ValueError('달레 스터디 공식 목록에서 프로그램을 확인하지 못했습니다.')
        _, title, kind, badge = record
        status = 'OPEN' if dale_is_open(badge) else 'CHECK_REQUIRED'
        if re.fullmatch(r'(?:\d+기 )?모집\s*(?:마감|완료)', badge):
            status = 'CLOSED'
        evidence = '달레 스터디 공식 목록의 프로그램 상태: ' + badge
        return program_verdict(event, title, kind, status, evidence, DALE_URL)

    match = re.fullmatch(CNCF_PATH, url.removeprefix(CNCF_DOCS)) if url.startswith(CNCF_DOCS) else None
    if not match:
        return None
    response = await fetcher.github_api(CNCF_API + match[0], raw=True)
    response.raise_for_status()
    window = cncf_window(response.text, int(match[1]))
    if not window:
        raise ValueError('CNCF 공식 일정에서 시간대가 명시된 멘티 지원 기간을 확인하지 못했습니다.')
    start, end = window
    current = now()
    status = 'CLOSED' if current >= end else 'OPEN' if current >= start else 'CHECK_REQUIRED'
    title = 'CNCF LFX 멘토링 · ' + match[0].split('/')[-2] + ' (' + match[1] + ')'
    result = program_verdict(event, title, 'project', status, 'CNCF 공식 멘티 지원 일정(UTC) 확인', url,
                             apply_deadline=end.astimezone(KST).isoformat())
    if current < start:
        # Recheck every daily batch until the announced application window opens.
        result['verification_version'] = 1
    return result


def program_verdict(event, title, kind, status, evidence, verification_url, apply_deadline=None):
    checked = iso_now()
    result = dict(event, title=title, activity_type=kind, status=status, evidence=evidence,
                  apply_deadline=apply_deadline, last_verified_at=checked, last_checked_at=checked,
                  verification_url=verification_url, failure_count=0, error_kind=None,
                  verification_version=VERSION, application_url=event['canonical_url'])
    if status == 'OPEN':
        result['recruitment_basis'] = 'listing'
    else:
        result.pop('recruitment_basis', None)
    return result


async def lf_registration(event, fetcher):
    url = event['canonical_url']
    if not re.fullmatch(r'https://events\.linuxfoundation\.org/[a-z0-9]+(?:-[a-z0-9]+)*', url):
        return event
    registration = url + '/register/'
    response = await fetcher.page(registration)
    if response.status_code == 404 or str(response.url).rstrip('/') != registration.rstrip('/'):
        return event
    response.raise_for_status()
    links = BeautifulSoup(response.text, 'html.parser').select('main a[href]')
    statuses = set()
    for link in links:
        destination = urlsplit(link['href'])
        if destination.scheme != 'https' or destination.netloc != 'register.linuxfoundation.org' or destination.path in ('', '/'):
            continue
        if link.get('aria-disabled') == 'true' or link.has_attr('disabled'):
            continue
        label = link.get_text(' ', strip=True).strip('!').lower()
        if label == 'register now':
            statuses.add('OPEN')
        elif label in ('registration is sold out', 'sold out'):
            statuses.add('SOLD_OUT')
        elif label in ('registration is closed', 'registration closed'):
            statuses.add('CLOSED')
    if len(statuses) == 1:
        status = statuses.pop()
        event.update(status=status, application_url=registration, verification_url=registration,
                     evidence='Linux Foundation 공식 등록 페이지에서 ' + {'OPEN':'신청 버튼', 'SOLD_OUT':'매진 표시','CLOSED':'접수 마감 표시'}[status] + ' 확인')
        event.pop('recruitment_basis', None)
        if status == 'OPEN':
            event['recruitment_basis'] = 'listing'
    return event
