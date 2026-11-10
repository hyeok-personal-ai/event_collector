"""Explicitly restricted sources are blocked even when discovered via another list."""
from urllib.parse import urlsplit, unquote
from pathlib import Path
import json

POLICY = json.loads(Path(__file__).with_name('restricted-sources.json').read_text(encoding='utf-8'))
RESTRICTED_HOSTS = tuple(POLICY['hosts'])
RESTRICTED_SOURCES = frozenset(POLICY['source_ids'])

def assert_collection_allowed(url):
    p=urlsplit(url)
    host = (p.hostname or '').lower().rstrip('.')
    if host in ('raw.githubusercontent.com','github.com','api.github.com') and '/dev-event/' in (unquote(p.path).lower()+'/'):
        raise ValueError('이용약관의 Dev-Event 데이터 수집 제한: 서면 허가 전 중지')
    if any(host == h or host.endswith('.' + h) for h in RESTRICTED_HOSTS):
        raise ValueError('이용약관 제한 또는 공개 색인 허가 확인 대기: 수집 중지')

def assert_event_collection_allowed(event):
    if event.get('discovery_source') in RESTRICTED_SOURCES:
        raise ValueError('최초 발견 소스의 이용 조건 확인 대기: 수집 중지')
    for key in ('canonical_url', 'discovery_url', 'verification_url'):
        if event.get(key):
            assert_collection_allowed(event[key])
