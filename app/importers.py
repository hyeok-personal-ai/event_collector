"""Import report tables as unverified candidates, never as live availability."""
import re
from .core import KST, now, new_event, categories, activity_type, canonical
from datetime import datetime

def clean(text):
    return re.sub(r'[*_`]|[🆕⭐⏰🔄]', '', text).strip()

def report_date(text):
    m = re.search(r'(20\d{2})년\s*(\d{1,2})월\s*(\d{1,2})일', text)
    return datetime(*map(int, m.groups()), tzinfo=KST).isoformat() if m else None

def short_date(text, year, deadline=True):
    if re.search(r'\bET\b|\bPT\b|\bUTC\b|\bPST\b|\bEST\b', text):
        return None
    matches = list(re.finditer(r'(\d{1,2})[/.]\s*(\d{1,2})(?:\s*(?:\([^)]*\))?\s*(\d{1,2}):(\d{2}))?', text))
    if not matches:
        return None
    m = matches[-1] if deadline else matches[0]
    month, day, hour, minute = m.groups()
    try:
        return datetime(year, int(month), int(day), int(hour or (23 if deadline else 0)),
                        int(minute or (59 if deadline else 0)), tzinfo=KST).isoformat()
    except ValueError:
        return None

def parse_report(text):
    reported = report_date(text)
    year = int(reported[:4]) if reported else now().year
    headers, found = [], {}
    for line in text.splitlines():
        if not line.startswith('|'):
            continue
        # Some event titles contain pipes inside Markdown links; preserve link content.
        cells = [clean(x) for x in re.split(r'\|(?=(?:[^\[]*\[[^\]]*\])*[^\]]*$)', line.strip('|'))]
        if not headers or any(x in ('활동', '이름') for x in cells):
            headers = cells
            continue
        if all(re.fullmatch(r'[:\-\s]+', x) for x in cells):
            continue
        row = dict(zip(headers, cells))
        link = re.search(r'\[[^\]]*\]\((https?://[^\s)]+)\)', line)
        title = row.get('활동') or row.get('이름')
        if not link or not title or title == '—':
            continue
        try:
            url = canonical(link.group(1))
        except ValueError:
            continue
        info = row.get('상태·마감') or row.get('마감') or row.get('상태/마감') or row.get('현재 상태·일정') or row.get('상태·일정') or ''
        summary = row.get('핵심 기술·활동') or row.get('핵심 내용·혜택') or row.get('추천 이유') or row.get('취준 가치') or ''
        field = row.get('분야/유형', '')
        place = row.get('지역/방식', '')
        # An event date / an ambiguous range is not an application deadline.
        deadline = None if re.search('행사|개최|대회·|~|→', info) and '마감' not in info else short_date(info, year)
        # Preserve ambiguity rather than recommending the later of conflicting dates.
        conflict = bool(re.search('실제.*접수|날짜.*충돌|마감.*다르', summary))
        if conflict:
            deadline = None
        price = '무료' if '무료' in place else '유료' if re.search(r'유료|\d[천만]?원', place) else '확인 필요'
        e = new_event(url, title, summary=summary, categories=categories(field + ' ' + title + ' ' + summary),
                      activity_type='oss_issue' if re.search(r'github\.com/.+/issues/\d+', url) else activity_type(field + ' ' + title),
                      apply_deadline=deadline, location=place, price=price,
                      reported_at=reported, provenance='chatgpt_report',
                      evidence='GPT 대화에서 가져온 후보입니다. 현재 원문을 검증하지 않았습니다. 당시 표시: ' + info + (' / 날짜 충돌: ' + summary if conflict else ''))
        if url in found:
            old = found[url]
            if not old['apply_deadline'] and deadline:
                old['apply_deadline'] = deadline
            if len(summary) > len(old['summary']):
                old['summary'] = summary
        else:
            found[url] = e
    return list(found.values())

def parse_dev_event(text):
    year, results = now().year, []
    for line in text.splitlines():
        heading = re.match(r'##\s*`?(\d{2,4})년', line)
        if heading:
            year = int(heading.group(1))
            if year < 100:
                year += 2000
        m = re.match(r'- __\[(.+)\]\((https?://.+)\)__', line)
        if m:
            try:
                results.append(new_event(m.group(2), m.group(1), provenance='dev_event', evidence='Dev-Event 목록에서 발견. 상세 원문 확인 필요.'))
            except ValueError:
                pass
        elif results and line.strip().startswith('- '):
            e = results[-1]
            label, _, value = line.strip()[2:].partition(':')
            value = value.strip().replace('`', '')
            if label == '분류':
                e['location'] = value.split(',')[0]
                e['price'] = '무료' if '무료' in value else '유료' if '유료' in value else '확인 필요'
                e['categories'] = categories(e['title'] + ' ' + value)
                e['activity_type'] = activity_type(e['title'] + ' ' + value)
            elif label == '주최':
                e['organizer'] = value
            elif label == '접수':
                e['apply_deadline'] = short_date(value, year)
                e['evidence'] += ' 목록의 접수기간: ' + value
            elif label == '일시':
                e['start_at'] = short_date(value, year, False)
                e['end_at'] = short_date(value, year, True)
    return results
