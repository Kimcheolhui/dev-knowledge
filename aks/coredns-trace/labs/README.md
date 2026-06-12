# AKS CoreDNS trace plugin Labs

작성일: 2026-06-11

이 폴더는 AKS CoreDNS `trace` 플러그인을 실제로 적용하고, DNS trace 산출값과 application trace 연계 가능성을 확인하기 위한 실행형 lab 문서 모음이다.

## 실습 흐름

| 순서 | 문서                                                                                   | 확인 내용                                                           |
| ---- | -------------------------------------------------------------------------------------- | ------------------------------------------------------------------- |
| 1    | [01-precheck-and-backup.md](01-precheck-and-backup.md)                                 | CoreDNS 현재 상태, `trace` plugin 포함 여부, ConfigMap 백업         |
| 2    | [02-enable-trace-with-zipkin.md](02-enable-trace-with-zipkin.md)                       | Zipkin 배포, `trace.override` 적용, CoreDNS 재시작                  |
| 3    | [03-generate-query-and-inspect-trace.md](03-generate-query-and-inspect-trace.md)       | DNS query 발생, Zipkin UI/API에서 span field 확인                   |
| 4    | [04-application-trace-correlation.md](04-application-trace-correlation.md)             | OpenTelemetry app trace와 CoreDNS trace ID 비교                     |
| 5    | [05-dns-protocol-trace-context-adoption.md](05-dns-protocol-trace-context-adoption.md) | DNS protocol-level trace context 표준화 시도와 AKS 적용 가능성 정리 |
| 6    | [06-cleanup-and-result-summary.md](06-cleanup-and-result-summary.md)                   | `trace.override` 제거, lab 리소스 삭제, 결론 정리                   |

## 공통 전제

- 현재 kube context가 테스트 대상 AKS 클러스터를 가리킨다.
- `kubectl` 사용 권한이 있다.
- `kube-system/coredns-custom` ConfigMap을 생성/수정할 수 있다.
- 테스트 중 CoreDNS deployment rollout restart가 가능하다.
- 로컬에 `envsubst`가 있다. 없으면 patch template의 `${ZIPKIN_ENDPOINT}`, `${TRACE_EVERY}` 값을 직접 치환한다.
- `curl`과 `jq`가 있으면 Zipkin API 결과를 확인하기 편하다. `jq`는 선택 사항이다.
- 가능하면 운영 클러스터가 아닌 dev/test 클러스터에서 수행한다.

## 공통 변수

모든 lab 문서는 이 폴더에서 실행하는 것을 기준으로 한다.

```bash
cd /home/cheolhuikim/studyspace/dev-knowledge/aks/coredns-trace/labs

export LAB_NS=trace-lab
export LAB_RUN_ID=$(date +%Y%m%d-%H%M%S)
export LAB_ARTIFACT_DIR="$PWD/artifacts/$LAB_RUN_ID"

mkdir -p "$LAB_ARTIFACT_DIR"
echo "$LAB_ARTIFACT_DIR"
```

실험 결과는 각 문서의 `실행 결과 기록` 영역에 직접 붙여 넣는다. 원본 yaml, trace JSON, log처럼 길이가 긴 결과는 `$LAB_ARTIFACT_DIR` 아래에 저장한 뒤 파일명만 문서에 적어도 된다.

## 기본 sampling 값

CoreDNS `trace` 플러그인의 `every` 값은 n개 query 중 1개만 trace한다. 테스트 클러스터에서 빠르게 확인할 때는 `10`, 공유 클러스터에서는 `1000` 이상부터 시작한다.

```bash
export TRACE_EVERY=10
```

## 참고

- CoreDNS `trace`는 Zipkin 또는 Datadog endpoint로 trace를 전송한다.
- 이 lab은 먼저 Zipkin에 직접 전송해 trace 생성 여부를 확인한다.
- 이후 OpenTelemetry Collector의 Zipkin receiver와 OTLP receiver를 함께 사용해 CoreDNS trace와 application trace를 같은 수집기 로그에서 비교한다.
- 같은 backend 또는 collector로 모을 수 있다는 것과 같은 trace tree로 이어진다는 것은 별개다.
