"""Isolated, read-only Chromium rendering for the collector (no user profile)."""
import asyncio
import concurrent.futures
import json
import re
import os
from pathlib import Path
from urllib.parse import urlsplit

def read_only_request(method,url,body=None):
    if method in ('GET','HEAD','OPTIONS'):return True
    if method!='POST':return False
    parsed=urlsplit(url)
    if parsed.hostname=='firestore.googleapis.com' and parsed.path.endswith(':runQuery'):
        return True
    if re.search(r'/(?:api/)?graphql/?$',parsed.path):
        try:
            data=json.loads(body or '{}')
            operations=data if isinstance(data,list) else [data]
            return bool(operations) and all(isinstance(op,dict) and isinstance(op.get('query'),str)
                and re.match(r'\s*(?:query\b|\{)',op['query']) and not re.search(r'\bmutation\b|\bsubscription\b',op['query']) for op in operations)
        except (ValueError,TypeError):return False
    return False

class BrowserRenderer:
    def __init__(self, fetcher, budget=24):
        os.environ.setdefault('PLAYWRIGHT_BROWSERS_PATH',str(Path(__file__).resolve().parent.parent/'data'/'playwright'))
        self.fetcher = fetcher
        self.remaining = budget
        self.used = 0
        self.executor = concurrent.futures.ThreadPoolExecutor(max_workers=1, thread_name_prefix='radar-browser')
        self.driver = self.browser = None
        self.loop = None
        self.semaphore = asyncio.Semaphore(1)

    async def render(self, url):
        from .collector import public_url
        await public_url(url)
        await self.fetcher.allowed(url)
        async with self.semaphore:
            if self.remaining <= 0:
                raise ValueError('이번 실행의 브라우저 검증 한도에 도달했습니다. 다음 실행에서 재시도합니다.')
            self.remaining -= 1
            self.used += 1
            self.loop = asyncio.get_running_loop()
            return await self.loop.run_in_executor(self.executor, self._render, url)

    def _guard(self, route):
        from .collector import public_url
        request = route.request
        try:
            if urlsplit(request.url).scheme not in ('http', 'https'):
                return route.abort()
            # Viewing public pages must not submit applications, join events, or mutate accounts.
            if not read_only_request(request.method,request.url,request.post_data):
                return route.abort()
            if request.resource_type in ('image', 'media', 'font'):
                return route.abort()
            host = urlsplit(request.url).hostname
            if host not in self.checked_hosts:
                asyncio.run_coroutine_threadsafe(public_url(request.url), self.loop).result(timeout=15)
                self.checked_hosts.add(host)
            if request.is_navigation_request():
                asyncio.run_coroutine_threadsafe(self.fetcher.allowed(request.url), self.loop).result(timeout=20)
            return route.continue_()
        except Exception:
            return route.abort()

    def _render(self, url):
        from playwright.sync_api import sync_playwright, TimeoutError as BrowserTimeout
        if self.browser is None:
            if self.driver is None:self.driver = sync_playwright().start()
            try:
                self.browser = self.driver.chromium.launch(headless=True)
            except Exception:
                # Failed launches must release Playwright's running loop on this
                # executor thread, otherwise every later source fails as nested Sync API.
                self.driver.stop()
                self.driver = None
                raise
        context = self.browser.new_context(locale='ko-KR', timezone_id='Asia/Seoul', service_workers='block', accept_downloads=False)
        self.checked_hosts = set()
        context.route('**/*', self._guard)
        context.route_web_socket('**/*', lambda ws: ws.close())
        page = context.new_page()
        try:
            response = page.goto(url, wait_until='domcontentloaded', timeout=25000)
            try:
                page.wait_for_load_state('networkidle', timeout=4000)
            except BrowserTimeout:
                pass
            # All observations come from rendered DOM, including visibility and disabled state.
            observation = page.evaluate('''() => {
              const visible = el => !!(el.getClientRects().length) && getComputedStyle(el).visibility !== 'hidden';
              const controls = Array.from(document.querySelectorAll('a[href],button,input[type=submit],[role=button]')).filter(visible).slice(0,500).map(el=>({
                label:(el.innerText||el.value||el.getAttribute('aria-label')||'').trim().slice(0,200),
                href:el.href||null, disabled:el.disabled||el.getAttribute('aria-disabled')==='true', tag:el.tagName.toLowerCase(),
                form_fields:el.closest('form,[role=form]')?Array.from(el.closest('form,[role=form]').querySelectorAll('input:not([type=hidden]),textarea,select,[role=textbox],[role=radio]')).filter(f=>visible(f)&&!f.disabled).length:0
              }));
              const forms = Array.from(document.forms).filter(visible).map(f=>({action:f.action, fields:Array.from(f.querySelectorAll('input,textarea,select,[role=textbox],[role=radio]')).filter(el=>visible(el)&&!el.disabled).length}));
              const input_count=Array.from(document.querySelectorAll('input:not([type=hidden]),textarea,select,[role=textbox],[role=radio]')).filter(el=>visible(el)&&!el.disabled).length;
              return {text:document.body.innerText.slice(0,70000), controls, forms, input_count, title:document.title};
            }''')
            observation.update(html=page.content()[:3_000_000], url=page.url,
                               http_status=response.status if response else None, method='browser')
            return observation
        finally:
            context.close()

    def _close(self):
        if self.browser:
            self.browser.close()
        if self.driver:
            self.driver.stop()

    async def close(self):
        await asyncio.get_running_loop().run_in_executor(self.executor, self._close)
        self.executor.shutdown(wait=False)
