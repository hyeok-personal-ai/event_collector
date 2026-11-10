"""Public DOM checks for club pages; notification forms are not applications."""
import re
from urllib.parse import urlsplit
from bs4 import BeautifulSoup


def sopt_recruit_page(url):
    parsed=urlsplit(url)
    return parsed.hostname=='recruit.sopt.org' and parsed.path in ('','/')


def wait_for_club_content(page):
    if not sopt_recruit_page(page.url):
        return
    from playwright.sync_api import TimeoutError as BrowserTimeout
    try:
        page.wait_for_function('''() => {
          const text=document.body?.innerText||'';
          return !text.includes('페이지 로딩 중입니다') &&
            Array.from(document.querySelectorAll('h1')).some(el =>
              el.getClientRects().length && getComputedStyle(el).visibility!=='hidden' &&
              el.innerText.trim().length>0);
        }''',timeout=8000)
    except BrowserTimeout:
        raise ValueError('SOPT 공식 모집 페이지의 로딩이 끝나지 않았습니다. 모집 0건으로 확정하지 않고 다음 배치에서 재확인합니다.') from None


def club_status(event,html,visible_text=None):
    if not sopt_recruit_page(event['canonical_url']) or event.get('activity_type')!='club':
        return event
    soup=BeautifulSoup(html,'html.parser')
    heading=' '.join(h.get_text(' ',strip=True) for h in soup.select('h1'))
    closed=r'지금은\s*모집\s*기간이\s*아니에요'
    # Scope the verdict to the recruitment page's main heading, not a footer,
    # past announcement, part description or email-notification button.
    if re.search(closed,heading) and (visible_text is None or re.search(closed,visible_text)):
        return {**event,'status':'CLOSED','evidence':'SOPT 공식 모집 페이지의 현재 모집 기간 아님 안내 확인. 모집 알림 신청은 지원 접수가 아닙니다.'}
    return event
