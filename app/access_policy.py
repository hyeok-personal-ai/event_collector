"""Explicitly restricted sources are blocked even when discovered via another list."""
from urllib.parse import urlsplit

RESTRICTED_HOSTS = ('redis.io', 'devpost.com', 'dev-korea.com', 'jetbrains.com', 'jumpit.saramin.co.kr', 'holaworld.io', 'letspl.me', 'nvidia.com', 'aws.amazon.com', 'oracle.com', 'mongodb.com', 'microsoft.com', 'redhat.com', 'lablab.ai', 'lablab.build', 'startupjobs.kr', 'modulabs.co.kr')

def assert_collection_allowed(url):
    p=urlsplit(url)
    host = (p.hostname or '').lower().rstrip('.')
    if host in ('raw.githubusercontent.com','github.com','api.github.com') and '/dev-event/' in (p.path.lower()+'/'):
        raise ValueError('이용약관의 Dev-Event 데이터 수집 제한: 서면 허가 전 중지')
    if any(host == h or host.endswith('.' + h) for h in RESTRICTED_HOSTS):
        raise ValueError('이용약관 제한 또는 공개 색인 허가 확인 대기: 수집 중지')
