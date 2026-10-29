# Event Collector

공개 개발자 행사·스터디·프로젝트·동아리 모집 안내를 수집하는 Python 배치입니다. GPT 예약이나 모델 API 없이 공개 목록과 원문을 확인합니다.

## 현재 연결 상태

이 저장소에는 공개 가능한 수집기 코드만 있습니다. **CI는 push/PR 시 실행되며, 수집 예약은 아직 활성화하지 않았습니다.** 기존 운영 수집기는 별도 저장소에서 계속 실행됩니다.

`collect.yml`에는 매일 09:17 KST 예약과 수동 실행 트리거가 준비되어 있습니다. 저장소 변수 `COLLECTION_ENABLED=true`일 때만 실행합니다. 연결 전에는 예약 또는 수동 실행이 발생해도 수집 job은 건너뜁니다.

## 운영 연결 순서

1. 기존 Radar 서버의 GitHub 실행 URL 허용 목록에 `hyeok-personal-ai/event_collector`를 추가하고 배포합니다. 서버 코드는 이 저장소에 포함하지 않았습니다.
2. 저장소 Actions 변수 `RADAR_SITE_URL`에 해당 HTTPS 서버 주소를 설정합니다.
3. Actions secret `RADAR_BATCH_KEY`에 서버와 일치하는 키를 설정합니다. 키는 코드·이슈·로그에 적지 않습니다.
4. 기존 수집 예약을 중지하고 `COLLECTION_ENABLED=true`를 설정합니다.
5. 수동 실행으로 외부 DB 대기열, 원문 결과, 소스 상태 화면 반영을 확인합니다. 이후 하루 한 번 실행합니다.

서버는 `/api/collector`의 start/enqueue/progress/claim/complete/fail/finish 작업을 지원해야 합니다. 대기열과 잠금은 서버의 D1 DB에 보관하며, 러너 파일은 실행 간 상태 저장에 사용하지 않습니다. 이 저장소만으로 공개 웹사이트나 DB가 생성되지는 않습니다.

## 포함 범위와 보안

- 수집기 코드, 공개 소스 목록, 고정 버전 의존성, CI/수집 workflow, 합성 데이터 테스트만 포함합니다.
- 개인 정보·프로필·숨김/저장 설정·DB·수집 원문·로그·PDF/ZIP·브라우저 세션·인증키·기존 작업 이력은 포함하지 않습니다.
- 키는 환경 변수에서만 읽습니다. 로컬 Windows 인증 파일을 읽는 기능은 제외했습니다.
- robots.txt, TLS 검증, 공개 URL 검사, 동시 실행 제한을 유지합니다. 로그인·접근 차단을 우회하지 않습니다.
- Actions 권한은 contents:read이며 pull_request_target을 사용하지 않습니다. CI에는 운영 키를 전달하지 않습니다.

## 확인 방법

Python 3.12 환경에서 `python -m pip install -r requirements.txt`, `python -m unittest discover -s tests -v`를 실행합니다. 실제 수집에는 Playwright Chromium이 필요하며 수집 workflow에서 설치합니다.

후보 발견은 신청 가능 판정과 다릅니다. 일부 소스/원문 실패는 partial로 기록하고, 배치 자체가 실패하면 Actions도 실패합니다. 원문 검증은 배치당 최대 80건이며 남은 항목은 서버 대기열에 보존합니다.
