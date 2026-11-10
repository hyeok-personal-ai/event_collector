"""Explicitly restricted sources are blocked even when discovered via another list."""
from urllib.parse import urlsplit

RESTRICTED_HOSTS = ('redis.io', 'devpost.com', 'dev-korea.com', 'jetbrains.com', 'jumpit.saramin.co.kr', 'holaworld.io', 'letspl.me', 'nvidia.com', 'aws.amazon.com', 'oracle.com', 'mongodb.com', 'microsoft.com', 'redhat.com', 'lablab.ai', 'lablab.build', 'startupjobs.kr', 'modulabs.co.kr')

def assert_collection_allowed(url):
    host = (urlsplit(url).hostname or '').lower().rstrip('.')
    if any(host == h or host.endswith('.' + h) for h in RESTRICTED_HOSTS):
        raise ValueError('이용약관 제한 또는 공개 색인 허가 확인 대기: 수집 중지')
