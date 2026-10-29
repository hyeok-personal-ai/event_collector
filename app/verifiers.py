"""Site-specific checks and public application-form inspection."""
import re
from urllib.parse import urlsplit
from bs4 import BeautifulSoup
from .core import canonical, iso_now, parse_date, now

FORM_HOSTS=('docs.google.com','forms.gle','tally.so','tally.so','form.typeform.com','typeform.com','forms.office.com','form.naver.com','naver.me')
FORM_LINK=re.compile(r'(?:docs\.google\.com/forms/|forms\.gle/|tally\.so/r/|typeform\.com/to/|forms\.office\.com/|form\.naver\.com/)',re.I)
CONTACT_LINK=re.compile(r'(?:open\.kakao\.com/|discord\.gg/|discord\.com/invite/)',re.I)

def form_state(observation):
    text=observation['text']
    if re.search(r'응답을 더 이상 받지|더 이상 응답을 받|no longer accepting responses|form is closed|설문이 종료|접수가 종료|This form is currently closed',text,re.I):
        return 'CLOSED','신청폼에서 응답 종료 안내를 확인했습니다.'
    if re.search(r'Sign in to continue|로그인하여 계속|You need permission|액세스 권한이 필요|접근 권한이 필요',text,re.I):
        return 'CHECK_REQUIRED','신청폼에 로그인 또는 접근 권한이 필요합니다.'
    if re.search(r'Verify you are human|Verify that you are human|사람인지 확인|로봇이 아닙니다|I.m not a robot',text,re.I):
        return 'CHECK_REQUIRED','신청폼에 사람 확인 절차가 필요합니다. 자동으로 해결하지 않습니다.'
    controls=observation.get('controls',[])
    submit=any(not c['disabled'] and re.fullmatch(r'제출|Submit|다음|Next|시작하기|Start|신청하기|신청|등록하기|등록|참가 신청|Register|Send',c['label'],re.I)
               and (c.get('form_fields',0)>0 or not any('form_fields' in x for x in controls)) for c in controls)
    fields=sum(f.get('fields',0) for f in observation.get('forms',[])) or observation.get('input_count',0)
    if submit and fields>0:
        return 'OPEN','신청폼의 입력 필드와 활성 제출/다음 버튼을 확인했습니다. 실제 제출은 하지 않았습니다.'
    return 'CHECK_REQUIRED','신청폼은 열렸으나 현재 응답 가능 조건을 충분히 확인하지 못했습니다.'

def external_links(html,base):
    from urllib.parse import urljoin
    soup=BeautifulSoup(html,'html.parser')
    forms,contacts=[],[]
    for a in soup.select('a[href]'):
        url=urljoin(base,a['href'])
        try:url=canonical(url)
        except ValueError:continue
        if FORM_LINK.search(url) and url not in forms:forms.append(url)
        if CONTACT_LINK.search(url) and url not in contacts:contacts.append(url)
    return forms[:2],contacts[:2]

def site_markers(event,html,visible_text=None):
    """Status indicators are site-specific and do not infer form submission from HTTP 200."""
    e=dict(event)
    host=urlsplit(e['canonical_url']).hostname or ''
    soup=BeautifulSoup(html,'html.parser')
    text=visible_text or soup.get_text(' ',strip=True)
    if host.endswith('inflearn.com'):
        indicators=[b.get_text(' ',strip=True) for b in soup.select('button')]
        if '모집완료' in indicators or '모집 완료' in indicators:
            e.update(status='CLOSED',evidence='인프런 개별 모집글의 모집완료 표시 확인')
        elif '모집중' in indicators:
            e['listing_open']=True
            if e['status']=='CHECK_REQUIRED':e['evidence']='인프런 개별 글은 모집중입니다. 연결된 지원폼/연락 경로를 추가 검증합니다.'
    if visible_text and host.endswith('event-us.kr'):
        registration=re.search(r'\n신청\s*\n([^\n]*(?:\n[^\n]*){0,2})',text)
        if registration:
            dates=list(re.finditer(r'(\d{1,2})월\s*(\d{1,2})일(?:\([^)]*\))?\s*(\d{1,2}):(\d{2})',registration.group(1)))
            if len(dates)>=2:
                from datetime import datetime
                from .core import KST
                month,day,hour,minute=map(int,dates[-1].groups())
                year=int((e.get('start_at') or e.get('apply_deadline') or str(now().year))[:4])
                try:
                    deadline=datetime(year,month,day,hour,minute,tzinfo=KST).isoformat()
                    if e.get('apply_deadline') and e['apply_deadline']!=deadline:
                        e['date_conflicts']=[{'previous':e['apply_deadline'],'official':deadline,'resolved_by':'원문 신청기간'}]
                    e['apply_deadline']=deadline
                except ValueError:pass
        if re.search(r'모집\s*중|Now Open',text,re.I):e['listing_open']=True
        if re.search(r'모집\s*마감|접수\s*종료',text):
            e.update(status='CLOSED',evidence='이벤터스 개별 페이지의 렌더링된 접수 종료 표시 확인')
    if re.search('선발제|승인제|Request to Join|Approval Required',text,re.I):
        e['target']='신청 후 주최자 승인/선발 필요'
    return e

async def check_external(e,html,renderer,fetcher):
    forms,contacts=external_links(html,e['canonical_url'])
    if e.get('application_url') and canonical(e['application_url'])!=canonical(e['canonical_url']):
        forms=list(dict.fromkeys([e['application_url']]+forms))[:2]
    e['application_checks']=[]
    for url in forms:
        result={'url':url,'status':'CHECK_REQUIRED','checked_at':iso_now()}
        try:
            if not renderer:raise ValueError('브라우저 검증이 비활성화되어 있습니다.')
            page=await renderer.render(url)
            status,evidence=form_state(page)
            result.update(status=status,evidence=evidence)
            e['application_url']=page['url']
        except Exception as exc:
            result['evidence']=str(exc)[:300]
            if e.get('status')=='OPEN':e['status']='CHECK_REQUIRED'
        e['application_checks'].append(result)
    if forms:
        states={c['status'] for c in e['application_checks']}
        if states=={'OPEN'} and e.get('status') not in ('CLOSED','DEAD','SOLD_OUT'):
            e.update(status='WAITLIST' if e['status']=='WAITLIST' else 'OPEN',evidence=e['evidence']+' / '+e['application_checks'][0]['evidence'])
        elif states=={'CLOSED'}:
            e.update(status='CLOSED',evidence='확인한 신청폼이 모두 접수 종료 상태입니다.')
        else:
            e.update(status='CHECK_REQUIRED',evidence='신청 경로의 상태가 서로 다르거나 일부를 확인하지 못했습니다.')
    for url in contacts[:1]:
        result={'url':url,'status':'CHECK_REQUIRED','checked_at':iso_now()}
        try:
            r=await fetcher.page(url)
            body=BeautifulSoup(r.text,'html.parser').get_text(' ',strip=True)
            if r.status_code in (404,410) or re.search('삭제된 채팅방|존재하지 않는 채팅방|만료된 초대',body):
                result.update(status='DEAD',evidence='참가/연락 링크가 만료되거나 삭제되었습니다.')
            elif r.status_code==200 and re.search(r'Join.*Chat|채팅.*참여|참여하기|Accept Invite',body,re.I):
                result.update(status='CONTACT_AVAILABLE',evidence='참가/연락 버튼 확인. 잔여 모집 인원은 확인되지 않았습니다.')
            else:result['evidence']=f'연락 경로 접속 HTTP {r.status_code}. 참가 가능 여부는 미확정입니다.'
        except Exception as exc:result['evidence']=str(exc)[:200]
        e['application_checks'].append(result)
    if forms or contacts:e['external_checked_at']=iso_now()
    deadline=parse_date(e.get('apply_deadline'),True)
    end=parse_date(e.get('end_at') or e.get('start_at'),True)
    if (deadline and deadline<=now()) or (end and end<=now()):
        e.update(status='CLOSED',evidence='접수 마감 또는 행사 일정이 지났습니다. '+e['evidence'])
    return e

def github_decision(issue,comments,timeline):
    if issue.get('state')!='open':return 'CLOSED','GitHub 이슈가 닫혔습니다.'
    if issue.get('assignees'):return 'CHECK_REQUIRED','GitHub 이슈에 이미 담당자가 배정되어 있습니다.'
    prs=[n for n in timeline if n.get('event')=='cross-referenced' and 'pull_request' in n.get('source',{}).get('issue',{}) and n['source']['issue'].get('state')=='open']
    if prs:return 'CHECK_REQUIRED',f'진행 중인 연결 PR {len(prs)}개 확인. 중복 기여 가능성이 있습니다.'
    claims=[c for c in comments if re.search(r'working on|assign.{0,15}me|I.{0,10}(?:take|work)|pull request|\bPR\s*#?\d+|작업.{0,10}(?:시작|진행|하겠)|제가.{0,8}맡',c.get('body',''),re.I)]
    if claims:return 'CHECK_REQUIRED','댓글에서 작업 의사/진행 PR 언급을 확인했습니다. 유지관리자 확인이 필요합니다.'
    return 'OPEN','GitHub API: Open, 미할당, 조회한 타임라인에 진행 PR 없음, 조회한 댓글에 작업 선점 신호 없음.'

async def verify_github(event,fetcher):
    match=re.search(r'github\.com/([^/]+)/([^/]+)/issues/(\d+)',event['canonical_url'])
    if not match:return None
    owner,repo,num=match.groups()
    base=f'https://api.github.com/repos/{owner}/{repo}/issues/{num}'
    async def get(url):
        r=await fetcher.page(url);r.raise_for_status();return r.json(),r.headers
    issue,_=await get(base)
    comments,ch=await get(base+'/comments?per_page=100')
    timeline,th=await get(base+'/timeline?per_page=100')
    status,evidence=github_decision(issue,comments,timeline)
    if 'rel="next"' in ch.get('link','') or 'rel="next"' in th.get('link',''):
        status,evidence='CHECK_REQUIRED','댓글/타임라인이 100개를 초과해 전체 선점 여부를 확인하지 못했습니다.'
    e=dict(event)
    e.update(status=status,evidence=evidence,last_verified_at=iso_now(),last_checked_at=iso_now(),
             summary=(issue.get('body') or '')[:700],github={'assignees':len(issue.get('assignees',[])),'comments_checked':len(comments),'timeline_checked':len(timeline)},verification_method='github_api')
    return e
