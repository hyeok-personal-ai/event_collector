"""Read organizer announcements with a documented public reuse licence."""
import re
from datetime import date, timedelta
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from .core import canonical, new_event, now
from .official_programs import program_verdict

FOSDEM_URL = 'https://fosdem.org/'
FOSDEM_CALL = r'https://fosdem\.org/(20\d{2})/news/(?:call-for-[a-z0-9-]+|[a-z0-9-]+-call-for-participation)'
WIKIMEDIA_URL = 'https://www.mediawiki.org/wiki/Wikimedia_Hackathon_2027/Participants'


async def official_page(fetcher, url, expected):
    response = await fetcher.page(url)
    response.raise_for_status()
    actual = canonical(str(response.url))
    if not re.fullmatch(expected, actual):
        raise ValueError('등록된 공식 모집 경로와 응답 주소가 다릅니다.')
    return BeautifulSoup(response.text, 'html.parser'), actual


async def fosdem_calls(fetcher, year=None):
    if year is None:
        _, homepage = await official_page(fetcher, FOSDEM_URL, r'https://fosdem\.org/20\d{2}')
        year = homepage.rsplit('/', 1)[1]
    calendar = f'https://fosdem.org/{year}/calendar'
    soup, base = await official_page(fetcher, calendar + '/', re.escape(calendar))
    if not soup.select_one('a[href*="creativecommons.org/licenses/by/4.0"]'):
        raise ValueError('FOSDEM 일정 페이지의 CC BY 4.0 표시를 확인하지 못했습니다.')
    calls = {}
    for row in soup.select('main li[data-date]'):
        time, link, label = row.select_one('time[datetime]'), row.select_one('a[href]'), row.select_one('span')
        if not time or not link or not label or 'deadline' not in label.get_text(' ', strip=True).lower():
            continue
        url = canonical(urljoin(base, link['href']))
        if re.fullmatch(FOSDEM_CALL, url):
            calls[url] = (link.get_text(' ', strip=True), date.fromisoformat(time['datetime']))
    return calls


async def discover_open_calls(source_id, fetcher):
    if source_id == 'wikimedia_hackathon':
        await wikimedia_registration(fetcher)
        return [new_event(WIKIMEDIA_URL, 'Wikimedia Hackathon 2027', activity_type='hackathon')]
    calls = await fosdem_calls(fetcher)
    return [new_event(url, title, activity_type='conference') for url, (title, deadline) in calls.items()
            if deadline >= now().date() - timedelta(days=30)]


async def wikimedia_registration(fetcher):
    soup, _ = await official_page(fetcher, WIKIMEDIA_URL, re.escape(WIKIMEDIA_URL))
    if not soup.select_one('#footer-info-copyright a[href="https://creativecommons.org/licenses/by-sa/4.0/"]'):
        raise ValueError('Wikimedia 참가 안내의 CC BY-SA 4.0 표시를 확인하지 못했습니다.')
    marker = soup.select_one('.mw-parser-output #Registration')
    if not marker:
        raise ValueError('Wikimedia 공식 페이지에서 참가 등록 영역을 찾지 못했습니다.')
    heading = marker if marker.name in ('h2', 'h3') else marker.find_parent(['h2', 'h3'])
    if heading is None:
        raise ValueError('Wikimedia 참가 등록 영역의 형식이 변경되었습니다.')
    if 'mw-heading' in heading.parent.get('class', []):
        heading = heading.parent
    for paragraph in heading.next_siblings:
        if getattr(paragraph, 'name', None) == 'p':
            text = paragraph.get_text(' ', strip=True)
            if re.search(r'\b(?:general )?registration\b', text, re.I):
                return text
        elif getattr(paragraph, 'name', None) in ('h2', 'h3') or 'mw-heading' in getattr(paragraph, 'attrs', {}).get('class', []):
            break
    raise ValueError('Wikimedia 공식 페이지에서 일반 참가 등록 문구를 찾지 못했습니다.')


async def verify_open_call(event, fetcher):
    url = event['canonical_url']
    if url == WIKIMEDIA_URL:
        text = await wikimedia_registration(fetcher)
        status = 'CHECK_REQUIRED'
        if re.search(r'\b(?:general )?registration (?:is|has) (?:now )?closed\b', text, re.I):
            status = 'CLOSED'
        elif re.search(r'\b(?:general )?registration is (?:now )?open\b', text, re.I):
            status = 'OPEN'
        return program_verdict(event, 'Wikimedia Hackathon 2027', 'hackathon', status,
                               '공식 일반 참가 등록 안내 확인', url)
    match = re.fullmatch(FOSDEM_CALL, url)
    if not match or event.get('discovery_source') != 'fosdem_calls':
        return None
    record = (await fosdem_calls(fetcher, match[1])).get(url)
    if not record:
        raise ValueError('FOSDEM 공식 일정에서 해당 모집 마감일을 찾지 못했습니다.')
    title, deadline = record
    today = now().date()
    status = 'CLOSED' if deadline < today else 'CHECK_REQUIRED'
    if deadline > today:
        soup, _ = await official_page(fetcher, url + '/', re.escape(url))
        if (soup.select_one('a[href*="creativecommons.org/licenses/by/4.0"]')
                and soup.select_one('main a[href="https://fosdem.org/submit"]')):
            status = 'OPEN'
    result = program_verdict(event, title, 'conference', status, '공식 모집 공고와 제출 마감일 확인',
                             url, apply_deadline=deadline.isoformat())
    return result
