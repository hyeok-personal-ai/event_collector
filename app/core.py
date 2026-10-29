"""Normalization and conservative, evidence-based event classification."""
import hashlib
import re
from datetime import datetime, timedelta, timezone
from urllib.parse import urlsplit, urlunsplit, parse_qsl, urlencode

KST = timezone(timedelta(hours=9))
STATUSES = ('OPEN', 'WAITLIST', 'CHECK_REQUIRED', 'CLOSED', 'SOLD_OUT', 'DEAD')

def now():
    return datetime.now(KST)

def iso_now():
    return now().isoformat(timespec='seconds')

def canonical(url):
    p = urlsplit(url.strip())
    if p.scheme not in ('http', 'https') or not p.hostname or p.username or p.password:
        raise ValueError('http 또는 https 공개 URL을 입력해 주세요.')
    if p.port not in (None, 80, 443):
        raise ValueError('기본 HTTP 포트만 지원합니다.')
    query = [(k, v) for k, v in parse_qsl(p.query, keep_blank_values=True)
             if not k.lower().startswith('utm_') and k.lower() not in ('fbclid', 'gclid')]
    if p.hostname in ('meetup.com','www.meetup.com'):
        query=[(k,v) for k,v in query if k.lower()!='eventorigin']
    if p.hostname in ('mongodb.com','www.mongodb.com'):
        query=[(k,v) for k,v in query if k.lower()!='tck']
    if p.hostname in ('sideproject.co.kr','www.sideproject.co.kr') and p.path.rstrip('/')=='/projects':
        query=[(k,v) for k,v in query if k not in ('q','t')]
    path = re.sub(r'^/(?:ko-kr|en)/', '/', p.path) if 'meetup.com' in p.netloc or 'ticketa.co' in p.netloc else p.path
    return urlunsplit((p.scheme.lower(), p.netloc.lower(), path.rstrip('/') or '/', urlencode(sorted(query)), ''))

def parse_date(value, end_of_day=False):
    if not value:
        return None
    try:
        value = str(value).strip()
        d = datetime.fromisoformat(value.replace('Z', '+00:00'))
        if len(value) == 10 and end_of_day:
            d = d.replace(hour=23, minute=59, second=59)
        return (d if d.tzinfo else d.replace(tzinfo=KST)).astimezone(KST)
    except (ValueError, TypeError):
        return None

def categories(text):
    rules = {
        'AI': r'\bAI\b|LLM|RAG|Agent|인공지능|머신러닝|Claude|PyTorch',
        'Backend': r'Backend|백엔드|Spring|NestJS|Java\b|서버|API|PostgreSQL|Redis|Kafka',
        'Cloud': r'Cloud|클라우드|AWS|Azure|Kubernetes|DevOps|Infra|인프라|SRE|EKS|배포',
        'Data': r'Data|데이터|Database|MongoDB|PostgreSQL|Airflow|DB\b',
        'OSS': r'OSS|Open Source|오픈소스|GitHub|PR\b',
        'Security': r'Security|보안|해킹|버그바운티|블록체인',
        'Web / Mobile': r'Web|Mobile|웹|앱|Frontend|Android|Kotlin|프론트|Game|게임',
        'Career': r'Career|커리어|취업|채용|멘토링|이력서',
    }
    return [k for k, pattern in rules.items() if re.search(pattern, text, re.I)] or ['General']

def activity_type(text):
    for label, pattern in [('club', '동아리|연합 커뮤니티'), ('hackathon', '해커톤|hackathon|대회|공모전|competition'),
                           ('project', '프로젝트|project'), ('study', '스터디|study'),
                           ('oss_issue', r'issues/\d+|이슈|번역팀'), ('meetup', '밋업|meetup|모임')]:
        if re.search(pattern, text, re.I):
            return label
    return 'conference'

def score(event):
    text = ' '.join(str(event.get(k) or '') for k in ('title', 'summary', 'tech_stack'))
    axes = {
        '결과물': 30 if re.search(r'GitHub|\bPR\b|배포|데모|Demo|수상|시연|MVP', text, re.I) else 8,
        '백엔드 적합성': 20 if 'Backend' in event.get('categories', []) else 5,
        '운영 경험': 20 if re.search('실고객|실사용|운영|장애|성능|모니터링|production', text, re.I) else 4,
        '네트워킹': 15 if re.search('밋업|Meetup|컨퍼런스|Conference|네트워킹|교류|멘토', text, re.I) else 5,
        '구조 명확성': (5 if event.get('apply_deadline') else 0) + (5 if event.get('location') else 0),
        '시간 대비 효율': 5 if event.get('price') == '무료' else 2,
    }
    return sum(axes.values()), axes

def decorate(event, current=None):
    e = dict(event)
    current = current or now()
    deadline = parse_date(e.get('apply_deadline'), True)
    ended = parse_date(e.get('end_at') or e.get('start_at'), True)
    e['stored_status'] = e.get('status', 'CHECK_REQUIRED')
    if (deadline and deadline <= current) or (ended and ended <= current):
        if e['status'] not in ('DEAD', 'SOLD_OUT'):
            e['status'] = 'CLOSED'
    verified = parse_date(e.get('last_verified_at'))
    ttl = 12 if deadline and deadline - current < timedelta(days=3) else 24
    e['stale'] = not verified or current - verified > timedelta(hours=ttl)
    if e['stale'] and e['status'] in ('OPEN', 'WAITLIST'):
        e['status'] = 'CHECK_REQUIRED'
    e['days_left'] = (deadline.date() - current.date()).days if deadline else None
    e['score'], e['score_axes'] = score(e)
    return e

def new_event(url, title='', **fields):
    url = canonical(url)
    base = dict(id=hashlib.sha256(url.encode()).hexdigest()[:16], canonical_url=url,
                detail_url=url, application_url=None, title=title or urlsplit(url).hostname,
                source=urlsplit(url).hostname, organizer='', summary='', categories=[],
                activity_type='conference', status='CHECK_REQUIRED', apply_deadline=None,
                start_at=None, end_at=None, location='', price='확인 필요', target='',
                tech_stack='', outcomes='', evidence='원문 재검증이 필요합니다.',
                last_verified_at=None, last_checked_at=None, reported_at=None,
                content_hash=None, created_at=iso_now(), updated_at=iso_now(),
                saved=False, change='NEW', provenance='manual')
    base.update(fields)
    if not base['categories']:
        base['categories'] = categories(base['title'] + ' ' + base['summary'])
    return base
