# Standard·Flex 반복 비교

`gpt-6-sol`, `gpt-6-luna`의 Global Standard 배포에 같은 프롬프트를 보내 처리 시간과 사용량을 기록한다. 실제 요청에는 비용이 발생할 수 있다.

실험 개요와 결론은 [Standard·Flex 비교 실험](./experiment-report.md)에 정리했다.

## 실행

Python 3.10 이상이 필요하다. 아래 명령은 이 폴더에서 실행한다.

```bash
python -m pip install -r requirements.txt

export AZURE_OPENAI_ENDPOINT="https://YOUR-RESOURCE.openai.azure.com"
export AZURE_OPENAI_API_KEY="YOUR-KEY"

# 실제 배포 이름이 모델 ID와 다를 때만 설정
export AZURE_OPENAI_SOL_DEPLOYMENT="YOUR-SOL-DEPLOYMENT"
export AZURE_OPENAI_LUNA_DEPLOYMENT="YOUR-LUNA-DEPLOYMENT"

python compare.py
```

엔드포인트는 `/openai/v1/`을 제외한 리소스 기본 주소를 넣는다. `https://YOUR-RESOURCE.services.ai.azure.com` 형식도 사용할 수 있다. 환경변수는 실행 환경에 직접 설정하며 `.env` 파일을 자동으로 읽지는 않는다.

### 기본 시행 방식

- 프롬프트는 네트워크 설명, 회의록 요약, JSON 추출, 수리 문제, Python 코드 작성의 5개다. 내용은 [compare.py](./compare.py)의 `PROMPTS`에서 수정할 수 있다.
- 매 시행에서 두 모델 × 두 티어(`default`, `flex`)의 **4개 요청을 동시에** 보낸다.
- 다섯 프롬프트를 차례로 한 번씩 실행하는 과정을 **10회 반복**한다. 총 **50회 시행, 200개 요청**이다.
- 한 시행의 네 요청이 전부 끝나면 **10초 대기**한다. 요청 시작 시각을 기준으로 한 고정 주기는 아니며, 마지막 시행 뒤에는 기다리지 않는다.
- 대기 시간만 최소 490초이고, 실제 실행 시간에는 요청 처리 시간이 추가된다.
- 요청당 제한 시간은 900초다. 오류가 나도 해당 시행을 추가로 재시도하거나 Standard로 폴백하지 않고, 다음 시행으로 진행한다.
- 전체 응답을 받기까지의 시간을 측정한다. 스트리밍이나 첫 토큰 도착 시간 측정은 하지 않는다.
- 터미널에는 진행 상황과 토큰 사용량, 오류를 표시한다. 응답 전문은 결과 파일에서 확인한다.

짧은 점검이나 기존 단일 프롬프트 비교도 가능하다.

```bash
# 프롬프트 5개를 한 번씩, 시행 간 대기 없이 실행: 20개 요청
python compare.py --repeats 1 --interval 0

# 사용자 프롬프트 한 개로 한 번만 실행: 4개 요청
python compare.py --prompt "TCP와 UDP의 차이를 설명해줘." --repeats 1 --interval 0

# 저장 위치 지정. 기존 파일은 덮어쓰지 않는다.
python compare.py --output results/my-run.jsonl
```

## 저장 데이터

기본 저장 위치는 스크립트와 같은 폴더의 `results/<UTC 시각>_<실행 ID>.jsonl`이다. 실행마다 새 파일을 만들며, 한 줄에 JSON 객체 하나를 기록한다.

| `type` | 내용 |
| --- | --- |
| `run_start` | 스키마 버전, 실행 ID, 시작 시각, Python·SDK 버전, 프롬프트 목록, 모델별 배포 이름, 시행 횟수·순서, 간격·타임아웃·재시도 설정 |
| `request` | 실행 ID, 시행 번호 `trial`, 반복 번호 `repetition`, 프롬프트 ID·전문, 모델 ID·배포 이름, 요청·실제 티어, UTC 시작·종료 시각, 소요 시간(초), 성공 여부·결과 분류, 요청 ID, 사용량, 응답 전문·원본 응답, 오류 |
| `run_end` | 종료 시각·상태, 완료된 시행 수, 기록된 요청 수, 성공·실패 수, 전체 소요 시간 |

기본 설정을 정상적으로 끝내면 요청 결과 200줄과 시작·종료 메타데이터 각 1줄, 총 **202줄**이 된다. API 오류가 난 요청도 `request` 한 줄을 남긴다. 줄 순서는 요청 완료 순서이므로 보고서를 만들 때는 `run_id`, `trial`, `model_id`, `requested_service_tier`로 연결한다.

- `usage`에는 API가 반환한 입력·출력·전체 토큰과 캐시·추론 토큰 상세 정보가 들어간다. API가 제공하지 않은 값은 추정하지 않는다.
- `response`에는 전체 SDK 응답을, `output_text`에는 읽기 편한 응답 텍스트를 별도로 저장한다.
- `error`에는 예외 종류·메시지와 원인 예외를 포함한 traceback이 들어간다. HTTP 오류는 `http_status`와 `request_id`도 기록한다.
- 실제 티어가 요청과 다르거나 응답 상태가 `completed`가 아니면 `success`가 `false`다.
- 요청마다 파일을 `flush`하므로 중간에 중단해도 이미 기록된 결과는 남는다. `Ctrl+C`로 중단하면 진행 중인 요청은 `cancelled`로 기록하고 종료 상태는 `interrupted`로 남긴다. 강제 종료나 전원 장애에는 마지막 기록·종료 메타데이터가 없을 수 있다.
- API 키와 인증 헤더, 엔드포인트 설정값은 메타데이터에 저장하지 않는다. 다만 응답·오류에는 서비스가 반환한 내용이 포함되므로 결과 파일을 공유하기 전 확인한다. 기본 `results/` 폴더는 Git에서 제외한다.
- 사용량과 실제 청구 금액은 다르다. 특히 연결 실패·취소는 서버 처리 여부를 확정할 수 없으므로 비용이 0이라고 간주하지 않는다.

종료 코드는 모두 성공하면 `0`, 오류·티어 불일치·미완료 응답이 있으면 `1`, 잘못된 CLI 입력은 `2`, `Ctrl+C`는 `130`이다.

## 검증

실제 Azure 요청 없이 SDK의 HTTP 전송을 모의 처리해 검증한다.

```bash
python -m unittest discover -s . -p 'test_compare.py' -v
```

공식 문서: [Microsoft Foundry Flex processing](https://learn.microsoft.com/azure/foundry/openai/how-to/flex-processing)
