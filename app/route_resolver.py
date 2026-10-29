"""Bounded official-link discovery. No search credentials, GPT, or access bypass.

Trust comes from curated organizer origins and their observed outgoing links,
never from a search result's title or an arbitrary event's claimed organizer.
"""
import asyncio
import re
from difflib import SequenceMatcher
from urllib.parse import urljoin, urlsplit
from bs4 import BeautifulSoup
from .core import canonical, iso_now, parse_date, new_event


def official_hosts():
    # Multi-tenant listing platforms are deliberately excluded, even when the
    # catalog's label describes an official organization using that platform.
    from .sources import SOURCES
    shared = {'luma.com', 'meetup.com', 'www.meetup.com', 'event-us.kr', 'github.com'}
    hosts = {urlsplit(s.url).hostname for s in SOURCES
             if (s.group == '기업 공식' or s.club or s.id in ('university', 'cncf', 'pycon', 'pytorch'))}
    return (hosts - shared) | {'awskr.org', 'cday2026.awskr.org', 'nasaspaceappskr.org',
                             'www.spaceappschallenge.org', 'www.dimoa.co.kr'}


def trusted(url):
    return urlsplit(url).hostname in official_hosts()


def normalize(text):
    return ' '.join(re.findall(r'[a-z0-9가-힣]+', str(text).lower()))


def title_match(a, b):
    a, b = normalize(a), normalize(b)
    # Numbers (year, edition, generation) must agree, even for near-identical titles.
    if len(a) < 10 or len(b) < 10 or set(re.findall(r'\d+', a)) != set(re.findall(r'\d+', b)):
        return False
    return SequenceMatcher(None, a, b).ratio() >= .86


def same_event(event, fresh):
    if not title_match(event.get('title', ''), fresh.get('title', '')):
        return False
    # Require independently parsed dates. Never inherit the original dates into
    # the candidate: that would make a changed annual event pass by accident.
    matched = False
    for key in ('start_at', 'end_at', 'apply_deadline'):
        old, new = parse_date(event.get(key)), parse_date(fresh.get(key))
        if old and new:
            if old.date() != new.date():
                return False
            matched = True
    return matched


def observe(fetcher, response):
    if response.status_code != 200 or 'html' not in response.headers.get('content-type', ''):
        return
    url = canonical(str(response.url))
    if not trusted(url):
        return
    soup = BeautifulSoup(response.text, 'html.parser')
    links = []
    for a in soup.select('a[href]')[:600]:
        try:
            target = canonical(urljoin(url, a['href']))
        except ValueError:
            continue
        links.append((target, a.get_text(' ', strip=True)[:250]))
    pages = getattr(fetcher, 'official_pages', {})
    if len(pages) < 120 or url in pages:
        pages[url] = links
    fetcher.official_pages = pages


def routing(event, state, selected=None, proof=None, reason='', attempts=None):
    return dict(state=state, original_url=event['canonical_url'], selected_url=selected,
                proof_url=proof, reason=reason[:700], checked_at=iso_now(), attempts=(attempts or [])[-6:])


def needs_alternative(result, event):
    text = result.get('evidence', '') + ' ' + result.get('browser_error', '')
    return (result.get('status') == 'DEAD' or
            bool(re.search(r'robots|HTTP (?:401|403|404|410|429)|CERTIFICATE|인증서|접근 확인|Access denied', text, re.I)) or
            bool(result.get('failure_count') and event.get('_queue_failures', 0) >= 2))


async def resolve(event, fetcher, renderer, verify_page, initial, prior_attempts=None):
    original = event['canonical_url']
    attempts = list(prior_attempts or [])
    if not attempts and (event.get('collection_route') or {}).get('state') != 'alternate':
        attempts.append(dict(url=original, outcome='blocked', reason=initial.get('evidence', '원문 접근 제한')[:200]))

    async def search():
        # Discovery has already observed official list pages in this batch.
        # If this organizer's origin was not observed, inspect its public home
        # once. All requests still use SSRF, robots, TLS and size protections.
        parts = urlsplit(original)
        root = f'{parts.scheme}://{parts.netloc}/'
        if trusted(root) and canonical(root) not in getattr(fetcher, 'official_pages', {}):
            try:
                response = await fetcher.page(root)
                observe(fetcher, response)
            except Exception:
                pass
        candidates = {}
        discovered = getattr(fetcher, 'route_candidates', [])
        matching = {canonical(e['canonical_url']) for e in discovered
                    if title_match(event.get('title', ''), e.get('title', ''))}
        # A trusted organizer URL or a link observed on its page is the proof.
        for e in discovered:
            url = canonical(e['canonical_url'])
            if url in matching and trusted(url):
                candidates[url] = url
        for proof, links in getattr(fetcher, 'official_pages', {}).copy().items():
            for url, label in links:
                if url in matching or title_match(event.get('title', ''), label):
                    candidates[url] = proof
        # Reuse the last confirmed route without probing the blocked original.
        previous = event.get('collection_route') or {}
        if previous.get('state') == 'alternate' and previous.get('selected_url') and previous.get('proof_url'):
            proof = previous['proof_url']
            selected = previous['selected_url']
            if trusted(proof) and canonical(proof) not in getattr(fetcher, 'official_pages', {}):
                try:
                    observe(fetcher, await fetcher.page(proof))
                except Exception:
                    pass
            # The proof link must still be observed, or the selected page itself
            # must be on a curated official origin.
            if trusted(selected) or any(u == canonical(selected) for u, _ in getattr(fetcher, 'official_pages', {}).get(canonical(proof), [])):
                candidates = {canonical(selected): proof, **candidates}
        for url, proof in list(candidates.items())[:4]:
            if url == canonical(original) or any(canonical(a['url']) == url for a in attempts):
                continue
            fresh, raw = await verify_page(new_event(url), fetcher, renderer)
            if fresh.get('failure_count') or fresh.get('status') == 'DEAD':
                attempts.append(dict(url=url, outcome='unavailable', reason=fresh.get('evidence', '')[:200]))
                continue
            if not same_event(event, fresh):
                attempts.append(dict(url=url, outcome='mismatch', reason='행사명·회차·독립적으로 읽은 날짜의 일치 미확인'))
                continue
            attempts.append(dict(url=url, outcome='confirmed', reason='공식 경로 연결 및 행사명·일정 일치 확인'))
            fresh.update(canonical_url=original, verification_url=url, source=urlsplit(url).hostname,
                         activity_type=event.get('activity_type', 'conference'),
                         collection_route=routing(event, 'alternate', url, proof, '공식 페이지와의 연결 및 행사명·일정 일치 확인', attempts))
            fresh['evidence']='공식 대체 경로 자동 전환: '+url+' / '+fresh.get('evidence', '')
            return fresh, raw
        return None

    try:
        found = await asyncio.wait_for(search(), timeout=40)
        if found:
            return found
        reason = '등록된 공식 소스·연결 링크에서 동일 행사와 일정이 확인되는 대체 원문을 찾지 못했습니다.'
    except (TimeoutError, ValueError, OSError) as exc:
        reason = '공식 대체 경로 탐색을 완료하지 못했습니다: '+type(exc).__name__
    return {**event, 'status': 'CHECK_REQUIRED', 'failure_count': 1,
            'last_checked_at':iso_now(),
            'evidence': '대체 원문 점검 필요: '+reason,
            'collection_route': routing(event, 'review', reason=reason, attempts=attempts)}, ''
