"""Recruitment facts from individual community posts, never related-card text."""
import re
from urllib.parse import urlsplit
from bs4 import BeautifulSoup

VERSION = 2
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


def recruitment_facts(event, html, observation=None):
    e = dict(event)
    if not community_post(e['canonical_url']):
        return e
    host = (urlsplit(e['canonical_url']).hostname or '').removeprefix('www.')
    soup = BeautifulSoup(html, 'html.parser')
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
    return e
