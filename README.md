# Event Collector

공개 개발자 행사·스터디·프로젝트·동아리 모집 안내를 수집하는 Python 배치입니다. GPT 예약이나 모델 API 없이 공개 목록과 원문을 확인합니다.

2026-11-11 검증 보완: 재검증 때 신청 주소를 현재 원문에서 다시 찾습니다. 원문에서 제거된 이전 신청폼이나 다른 추천 글의 신청 버튼을 재사용하지 않습니다. 신청폼이 로그인을 필수로 요구하면 그 이유를 표시하고 확인 필요로 유지하며, 선택적인 진행 상황 저장용 로그인 안내와 구분합니다.

검증 버전은 4입니다. 서버 대기열이 이전 판정의 미종료 커뮤니티 후보와 외부 신청 경로를 사용한 모집 중 항목을 한 번 재검증 대상으로 지정합니다. 완료하면 기존 재확인 주기로 돌아가며, 브라우저 한도 때문에 확인하지 못한 후보는 다음 날로 넘깁니다. 하루 한 번의 예약과 실행 예산은 유지합니다.

## 운영 설정

이 저장소가 일일 수집 실행 저장소입니다. 매일 09:17 KST에 실행하며 `main` 브랜치에서만 운영 키를 사용합니다. CI는 push/PR 시 실행하며 운영 키를 받지 않습니다.

- Actions 변수 `COLLECTION_ENABLED=true`일 때만 수집합니다. 이를 false로 바꾸거나 workflow를 Disable하면 중지합니다.
- `RADAR_SITE_URL`은 승인된 Radar 서버 주소와 정확히 일치해야 합니다. 임의 서버·리다이렉트로 인증키를 보내지 않습니다.
- `RADAR_BATCH_KEY`는 Actions secret입니다. 운영 값은 코드·이슈·로그에 적지 않습니다.
- 수동 Run workflow의 force는 당일 중복 검사만 생략하며, 실행 중인 배치 잠금은 무시하지 않습니다.
- 기존 저장소 수집 예약은 이전 작업에서 중지합니다. 두 저장소의 예약을 동시에 켜지 마세요.

서버는 `/api/collector`의 start/enqueue/progress/claim/complete/fail/finish 작업을 지원해야 합니다. 대기열과 잠금은 서버의 D1 DB에 보관하며, 러너 파일은 실행 간 상태 저장에 사용하지 않습니다. 이 저장소만으로 공개 웹사이트나 DB가 생성되지는 않습니다.

## 포함 범위와 보안

- 수집기 코드, 공개 소스 목록, 고정 버전 의존성, CI/수집 workflow, 합성 데이터 테스트만 포함합니다.
- 개인 정보·프로필·숨김/저장 설정·DB·수집 원문·로그·PDF/ZIP·브라우저 세션·인증키·기존 작업 이력은 포함하지 않습니다.
- 키는 환경 변수에서만 읽습니다. 로컬 Windows 인증 파일을 읽는 기능은 제외했습니다.
- robots.txt, TLS 검증, 공개 URL 검사, 동시 실행 제한을 유지합니다. 로그인·접근 차단을 우회하지 않습니다.
- Actions 권한은 contents:read이며 pull_request_target을 사용하지 않습니다. CI에는 운영 키를 전달하지 않습니다.

## 확인 방법

Python 3.12 환경에서 `python -m pip install -r requirements.txt`, `python -m unittest discover -s tests -v`를 실행합니다. 실제 수집에는 Playwright Chromium이 필요하며 수집 workflow에서 설치합니다.

후보 발견은 신청 가능 판정과 다릅니다. 일부 소스/원문 실패는 partial로 기록하고, 배치 자체가 실패하면 Actions도 실패합니다. 원문 검증은 40건씩 연속 처리하며 한 번에 최대 30분·1,000건입니다. 시간/건수 예산을 넘긴 항목은 미처리 개수와 함께 서버 대기열에 남깁니다.


## 검토한 실패 상황과 운영 한계

서버의 원자적 실행 잠금, 재발견 중복 방지, claim 응답 유실 시 동일 항목 반환, 완료 응답 유실 시 재전송 처리를 사용합니다. 프로세스가 강제 종료되면 서버 잠금은 2시간 뒤 만료되고 남은 작업은 다음 실행에서 복구합니다. 상태 화면은 2시간 실행 정체와 36시간 갱신 지연을 표시합니다.

GitHub 예약은 정확한 시각이나 매일 실행을 보장하는 타이머가 아닙니다. 플랫폼 지연·중단, 공개 저장소 장기 무활동, 외부 소스 차단·형식 변경이 생길 수 있습니다. 실패 원문은 대기열에 남고, 마감 7일 이내, 신규 미검증, 오래 기다린 재검증 순으로 처리합니다. 종료된 일회성 행사는 검증 대상에서 제외하고 삭제하지 않습니다. 동아리 모집 안내는 종료돼도 주 1회 확인합니다. 일반 신청 가능 항목은 3일, 불확실한 항목은 7일 뒤 재검증하며 마감 임박 항목은 매일 확인합니다. 연속 실패는 1일→2일 간격, 접근 제한은 7일 간격이며 3회 연속 실패하면 점검 대기로 분리합니다. 한 배치가 모든 후보를 검증한다고 보장하지 않습니다. Actions 실패 알림과 공개 상태 화면을 함께 확인하세요.

쓰기 권한 보유자는 workflow 코드를 수정할 수 있으므로 저장소 협업 권한도 신뢰 경계입니다. 키 노출이 의심되면 서버와 Actions의 키를 함께 교체하세요. Secret scanning과 push protection은 보조 수단이며 모든 비밀 형식을 감지하지는 않습니다.

검증된 행사별 공식 대체 경로는 `app/alternative-sources.json`에 관리합니다. AWS Community Day는 AWSKRUG 이벤터스 원문, NASA Seoul은 서울 운영팀 2026 안내를 우선 수집합니다. 원래 행사 ID를 유지하고 실제 확인 URL을 별도로 기록합니다. 동일 행사 식별 문구가 사라지거나 대체 원문이 실패하면 점검 대기로 전환하며 차단된 원문으로 되돌아가지 않습니다. 디모아 12주 웨비나는 동일 행사의 공식 대체 원문이 확인되지 않아 자동 재시도를 중지했습니다.


## 공식 대체 경로 자동 탐색

원문 접근 제한·삭제 또는 3회 연속 오류가 발생하면 `app/route_resolver.py`가 같은 배치에서 읽은 공식 출처의 링크와 발견 후보를 비교합니다. 공식 출처는 검토한 기업·기관·동아리 호스트로 제한하며, 행사 플랫폼 자체나 검색 결과의 제목만으로 공식성을 인정하지 않습니다. 행사명·숫자로 된 회차가 일치하고 새 원문에서 독립적으로 읽은 일정도 일치해야 자동 전환합니다.

탐색은 행사당 40초·후보 최대 4개입니다. 등록된 공식 출처와 연결 링크 내 탐색이며 인터넷 전체 검색은 아닙니다. 확인할 수 없으면 점검 대기로 보내 자동 재시도에서 제외합니다. 일시적인 네트워크 오류는 기존 지연 재시도를 유지합니다. 이미 확인한 경로는 다음 배치에서도 공식 연결과 행사 일치를 재확인하고, 차단된 원문을 다시 호출하지 않습니다. 사전 검토한 행사별 경로는 별도 식별 문구 검사도 유지합니다.

공개 보고에는 `collection_route`로 원래 URL, 실제 확인 URL, 공식 근거 URL, 확인 시각, 시도 결과와 보류 사유를 기록합니다. 실패 시에도 서버가 기존 행사 내용을 보존하며 상태와 경로 기록을 갱신합니다. 프로필이나 비밀키는 포함하지 않습니다. 테스트는 공식 링크 전환, 비공식 출처 거부, 다른 날짜·회차 거부, 경로 재사용과 근거 소실을 검증합니다.


## Noncommercial collection and source conditions
The Radar source-policy page records the 2026-11-10 audit of 61 source entries. A successful HTTP response or robots permission is not a reuse licence. Original post descriptions are not syndicated: public summaries consist of activity/location/price facts. No images, attachments, member lists, or account profiles are published.

Explicit automated-access restrictions on Redis, Devpost, Dev Korea and JetBrains are enforced in both HTTP and browser fetching, including subdomains and redirected/discovered URLs. Jumpit is held pending clarification of the linked terms. Disabled sources with no authorized alternative remain excluded; an unrelated directory is not presented as the same-event replacement. Rights holders may request removal/correction by opening an issue containing only the public URL and reason, without private personal information.


### 2026-11-10 모집 후보 재검증
개별 모집글의 현재 모집 표시와 신청폼 응답 가능 검증을 구분합니다. 제목의 ‘모집’만으로 OPEN을 판정하지 않으며 관련 글의 버튼·링크도 근거에서 제외합니다. 본문에 텍스트로 붙인 신청폼 URL도 확인하되 로그인·사람 확인은 우회하지 않습니다. 삭제된 개별 커뮤니티 글의 HTTP 404/410은 종료 대상으로 빼고 점검 대기를 반복하지 않습니다. 기존 미확정 후보는 새 판정 버전으로 한 번 재검증하며, 브라우저 예산이 소진된 후보는 다음 날 다시 확인합니다. 하루 배치와 30분 실행 예산은 유지합니다.

조건 검토 기록은 61곳 중 43곳이며 18곳은 추가 확인이 필요합니다. 이번에 HOLA·렛플·lablab·AWS·Microsoft·NVIDIA·MongoDB·Red Hat·Oracle·StartupJobs·모두의연구소 11곳을 추가 보류했습니다. 명시적 자동 수집 금지와 공개 재사용 허가 범위 미확정을 구분해서 기록하며, 검토 완료 자체가 이용 허락을 뜻하지 않습니다. HOLA 모집 버튼 파서는 준비되어 있으나 허가 확인 전 수집·공개하지 않습니다. 원문 HTML 보관은 기본 해제(`RADAR_STORE_RAW=1` 개발 점검에서만 선택). 기존 원문 전문을 공개하지 않습니다.

Dev-Event의 LICENSE·USAGE_POLICY를 확인해 후보 발굴을 중지했습니다. 과거 기록에서 경유가 식별된 URL은 공개를 보류하고, 별도 소스에서 독립적으로 다시 발견하면 이전 메타데이터를 대체한 뒤 원문을 재검증합니다. 향후 발견 소스 ID와 URL을 결과에 보존합니다. 과거 cloud_report 자료는 발견 경로를 소실한 항목이 있어 전체 출처 복원이 완료됐다고 주장하지 않습니다.

신청폼 검증 v3는 응답 가능 여부뿐 아니라 참가 신청 목적(제목·지원동기/분야 문항)을 확인합니다. 설문조사·수요조사는 모집 중으로 승격하지 않습니다. 동일한 공개 폼은 한 배치 내 결과를 재사용해 요청량을 줄이며 매일 새로 확인합니다. 이전 판정의 모집 중 후보와 브라우저 한도 미처리 후보는 새 기준으로 다시 검증합니다. 게시글 개수는 독립 모집의 개수와 다를 수 있습니다.


### 추가 이용 조건 검토와 경로 제한 (2026-11-10)
프로그래머스·AI Factory·DACON·DAKER의 자동 수집 또는 제3자 제공 제한을 검토해 허가 확인 전 보류했습니다. 이미 제외된 온오프믹스·LinkedIn·Partiful도 제한 근거를 보강했고, GDG 참가 약관은 콘텐츠 재사용 허가가 아님을 명시했습니다. 문서 검토는 43곳, 미확인은 18곳입니다. 조건 확인과 권리자 허가 획득은 다릅니다.

`restricted-sources.json`은 수집기와 공개 서버에 동일하게 반영합니다. 도메인뿐 아니라 최초 발견 소스 ID·URL과 검증 경로를 검사하여, 제외한 소스가 다른 목록이나 대체 경로를 통해 다시 수집·공개되는 것을 차단합니다. `tests/test-source-restrictions.cjs`로 두 배포본의 일치와 대기열 제외를 검사합니다. 기존 본문 복제 없이 최소 사실·원문 링크를 제공하더라도 모든 소스의 이용 허가를 확보한 것은 아닙니다.


### 검색 경유 재유입 방지 (2026-11-10)
원티드·로켓펀치의 자동 수집 제한을 공식 약관에서 확인해 도메인·출처 제한에도 반영했습니다. HACK:ON의 이용 규칙은 작성자 권리와 자체 서비스 표시 권한을 명시하므로 외부 재사용 허가로 간주하지 않습니다. 61곳 중 문서 검토 43곳, 추가 확인 18곳이며 26곳은 권한·조건 확인 대기로 수집과 공개를 보류합니다.

선택적인 Brave 검색 API의 질의는 활성 소스에서 생성하고, 결과도 활성 목록과 제한 정책을 다시 검사합니다. 검색 결과의 본문 발췌는 저장하지 않으며 발견한 소스와 URL을 남깁니다. 키가 없으면 직접 수집만 수행한다고 표시하고 GPT 자동 탐색이 연결됐다고 표시하지 않습니다. 실제 Brave API 실행은 키 연결을 전제로 하며, 기본 일일 배치에 새 유료 서비스나 추가 예약을 연결하지 않습니다.
