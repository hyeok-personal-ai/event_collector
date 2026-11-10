"""Official club application deadlines; never infer intake from a date alone."""
import re
from datetime import datetime
from urllib.parse import urlsplit
from .core import KST, now


def club_deadline(event, text):
    url=urlsplit(event.get('canonical_url',''))
    if url.hostname!='sipe.team' or url.path.rstrip('/')!='/recruit' or event.get('activity_type')!='club':
        return event
    result=dict(event)
    result.pop('apply_deadline',None)
    # Only the application section: announcement, interviews and activity dates
    # must not become application deadlines, and absent years stay unknown.
    section=re.search(r'서류\s*접수(.{0,220})',text,re.S)
    values=set()
    if section:
        window=re.split(r'서류\s*합격|오프라인\s*인터뷰|정규\s*활동',section[1])[0]
        for parts in re.findall(r'(20\d{2})년\s*(\d{1,2})월\s*(\d{1,2})일\s*(\d{1,2}):(\d{2})\s*마감',window):
            try:values.add(datetime(*map(int,parts),tzinfo=KST).isoformat())
            except ValueError:pass
    if result.get('evidence')=='확인된 접수 마감 또는 행사 일정이 지났습니다.':
        result.update(status='CHECK_REQUIRED',evidence='현재 모집 안내의 접수 기간을 다시 확인합니다.')
    if len(values)==1:
        result['apply_deadline']=next(iter(values))
        if datetime.fromisoformat(result['apply_deadline'])<=now():
            result.update(status='CLOSED',evidence='공식 모집 안내의 서류 접수 마감일이 지났습니다.')
    return result
