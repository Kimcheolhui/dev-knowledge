# AKS CoreDNS trace plugin 테스트

작성일: 2026-06-11

이 문서는 AKS CoreDNS의 `trace` 플러그인을 실제로 활성화해 DNS query trace가 어떤 형태로 수집되는지 확인하고, 이후 application tracing과 통합 또는 correlation이 가능한지 검증하기 위한 문서이다.

## 목표

1. AKS CoreDNS에 `trace` 플러그인을 적용했을 때 실제 trace가 생성되는지 확인한다.
2. 생성된 CoreDNS trace에 어떤 span name, tag, trace ID, client 정보, query 정보가 포함되는지 확인한다.
3. 애플리케이션 OpenTelemetry trace와 CoreDNS trace가 같은 trace tree로 이어지는지 확인한다.
4. trace context가 이어지지 않는다면 timestamp, query name, client Pod IP, workload metadata 기반 correlation 가능성을 확인한다.
5. Zipkin 단독 수집 이후 OpenTelemetry Collector, Application Insights, Azure Managed Grafana까지 확장 가능한지 판단한다.

## 전제

이미 확인한 내용은 다음과 같다.

- AKS CoreDNS 바이너리에는 `trace` 플러그인이 컴파일되어 있다.
- 기본 CoreDNS 설정에는 `trace`가 적용되어 있지 않다.
- AKS는 main CoreFile 직접 수정이 아니라 `kube-system/coredns-custom` ConfigMap의 `.override` 또는 `.server` 방식으로 CoreDNS custom 설정을 적용한다.
- AKS 문서상 built-in CoreDNS plugin은 지원되고, third-party plugin은 지원되지 않는다.

## 검증 범위

### 포함

- `coredns-custom`을 통한 `trace` 플러그인 활성화
- Zipkin server로 CoreDNS trace 수집
- 테스트 Pod 또는 샘플 앱에서 DNS query 발생
- Zipkin UI/API에서 CoreDNS trace field 확인
- OpenTelemetry application trace와 CoreDNS trace ID 비교
- OpenTelemetry Collector의 Zipkin receiver를 통한 중계 가능성 확인
- Azure Monitor Application Insights 또는 Grafana 연계 가능성 정리

### 제외

- 운영 클러스터 상시 적용
- CoreDNS 이미지 재빌드 또는 third-party plugin 추가
- CoreDNS를 DoH endpoint로 별도 운영하는 실험
- DNS trace context propagation을 위한 custom EDNS0 설계

## Lab 문서

실제 실행 절차는 별도 lab 문서로 분리한다.

| 문서                                                                                             | 목적                                                  |
| ------------------------------------------------------------------------------------------------ | ----------------------------------------------------- |
| [labs/README.md](labs/README.md)                                                                 | 전체 lab 순서와 공통 변수                             |
| [labs/01-precheck-and-backup.md](labs/01-precheck-and-backup.md)                                 | 현재 CoreDNS 상태 확인과 백업                         |
| [labs/02-enable-trace-with-zipkin.md](labs/02-enable-trace-with-zipkin.md)                       | Zipkin 배포와 CoreDNS `trace` 적용                    |
| [labs/03-generate-query-and-inspect-trace.md](labs/03-generate-query-and-inspect-trace.md)       | DNS query 발생과 CoreDNS trace field 확인             |
| [labs/03-generate-query-and-inspect-trace-02.md](labs/03-generate-query-and-inspect-trace-02.md) | CoreDNS `debug` plugin을 켠 trace log 확인            |
| [labs/04-application-trace-correlation.md](labs/04-application-trace-correlation.md)             | 애플리케이션 OpenTelemetry trace와 CoreDNS trace 비교 |
| [labs/05-dns-protocol-trace-context-adoption.md](labs/05-dns-protocol-trace-context-adoption.md) | DNS protocol-level trace context 표준화 시도 정리     |
| [labs/06-cleanup-and-result-summary.md](labs/06-cleanup-and-result-summary.md)                   | 정리와 최종 결과 기록                                 |

## 실험 가설

| 항목                              | 예상                                                                                                                                  |
| --------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------- |
| CoreDNS trace 생성                | `trace` 설정과 Zipkin endpoint가 정상일 경우 생성될 가능성이 높음                                                                     |
| DNS query 관련 tag                | query name, query type, protocol, remote/client IP, rcode 등 확인 가능 예상                                                           |
| application trace와 trace ID 연결 | 일반 Pod -> CoreDNS UDP/TCP DNS 경로에서는 자동 연결되지 않을 가능성이 높음                                                           |
| DoH 기반 trace context 연결       | CoreDNS trace plugin 코드상 DoH HTTP request header에서 OpenTracing context를 추출하는 경로가 있으나, AKS 기본 kube-dns 경로와는 별개 |
| 현실적 통합 방식                  | 같은 trace tree보다는 timestamp/query/client/workload 기준 correlation 가능성 검토가 현실적                                           |

## 구성 순서

### 1. 현재 상태 스냅샷

CoreDNS 이미지, 플러그인 목록, 기본 Corefile, `coredns-custom` 존재 여부를 기록한다. 이 단계는 핵심 검증은 아니지만 적용 전후 비교와 롤백을 위해 필요하다.

확인 대상:

- CoreDNS deployment image
- `coredns -plugins` 출력 중 `trace`
- `kube-system/coredns` ConfigMap
- `kube-system/coredns-custom` ConfigMap
- CoreDNS Pod log baseline

### 2. Zipkin 수집기 배포

가장 작은 실험 단위로 Zipkin server를 먼저 배포한다.

구조:

```text
CoreDNS trace plugin
  -> Zipkin protocol
Zipkin server
  -> Zipkin UI/API
```

이 단계의 목적은 Application Insights나 Collector를 붙이기 전에 CoreDNS trace plugin 자체가 trace를 내보내는지 확인하는 것이다.

### 3. CoreDNS trace 설정 적용

`kube-system/coredns-custom` ConfigMap에 `trace.override`를 추가한다.

초기 실험에서는 trace 생성 여부 확인이 목적이므로 sampling은 작게 시작한다. 공유 클러스터라면 `every 1000` 이상으로 시작하고, 테스트 클러스터라면 짧은 시간 동안만 `every 1` 또는 `every 10`을 검토한다.

확인 대상:

- CoreDNS rollout 성공 여부
- CoreDNS Pod log의 Corefile parse error 여부
- Zipkin endpoint 연결 실패 로그 여부
- DNS resolution 정상 동작 여부

### 4. DNS query 발생 및 CoreDNS trace 확인

테스트 Pod에서 `nslookup`, `dig`, `curl` 등을 사용해 DNS query를 발생시킨다. 이후 Zipkin에서 CoreDNS trace가 생성되는지 확인한다.

확인할 값:

- service name
- trace ID / span ID
- span name
- query name
- query type
- protocol
- remote/client IP
- response code
- duration
- error tag 존재 여부

이 단계의 성공 기준은 “CoreDNS trace가 Zipkin에 들어오고, DNS query 분석에 필요한 최소 field가 확인된다”이다.

### 5. 샘플 애플리케이션 trace와 비교

DNS lookup을 유발하는 샘플 앱을 준비하고 OpenTelemetry instrumentation을 적용한다. 앱 endpoint 호출 1회가 외부 hostname resolve와 outbound HTTP call을 만들도록 구성한다.

비교 대상:

- application trace ID
- CoreDNS trace ID
- application outbound HTTP span timestamp
- CoreDNS DNS query span timestamp
- hostname/query name
- client Pod IP 또는 workload 정보

판단 기준:

- 같은 trace ID로 이어지면 parent-child 관계 또는 trace context 전달 경로를 추가 분석한다.
- trace ID가 다르면 일반 AKS DNS 경로에서는 context propagation이 되지 않는 것으로 정리한다.
- 대신 timestamp, query name, client Pod IP, namespace/workload label로 correlation 가능한지 확인한다.

### 6. OpenTelemetry Collector 중계 검토

Zipkin 직접 수집이 확인되면 Collector를 중간에 넣는다.

구조:

```text
CoreDNS trace plugin
  -> Zipkin protocol
OpenTelemetry Collector zipkin receiver
  -> Zipkin / Tempo / Azure Monitor 후보
```

검증 포인트:

- Collector의 Zipkin receiver가 CoreDNS span을 정상 수신하는가?
- Collector exporter를 통해 동일 trace backend 또는 Azure Monitor 계열로 보낼 수 있는가?
- 변환 후에도 CoreDNS trace의 query-related tag가 보존되는가?

### 7. Application Insights / Grafana 연계 판단

마지막으로 Azure-native 시각화와 운영 관점에서 어디까지 붙일지 판단한다.

검토안:

- Application trace: OpenTelemetry -> Application Insights
- CoreDNS trace: CoreDNS `trace` -> Zipkin 또는 Collector Zipkin receiver
- 통합 보기: Azure Managed Grafana에서 Azure Monitor data source와 Zipkin/Tempo data source를 함께 사용

중요한 판단은 “같은 backend에 넣을 수 있는가”와 “같은 trace tree로 이어지는가”를 분리해서 보는 것이다. Collector를 통해 같은 관측 플랫폼으로 보낼 수 있더라도, trace ID가 다르면 UI에서는 별도 trace로 보일 수 있다.

### 8. DNS 프로토콜 레벨 trace context adoption 확인

application trace와 CoreDNS trace가 같은 trace tree로 이어지지 않는다면, DNS 프로토콜 자체에 trace context를 싣기 위한 시도가 있는지 확인한다.

검토 대상:

- EDNS `TRACEPARENT` Internet-Draft
- IANA EDNS0 Option Codes registry 등록 여부
- CoreDNS/AKS 기본 DNS 경로에서 사용 가능한지 여부
- PowerDNS 구현 사례를 protocol draft 구현/실험 사례로 해석할 수 있는지 여부

## 리스크와 주의사항

- CoreDNS는 클러스터 DNS 경로이므로 테스트 클러스터 또는 짧은 시간의 제한된 sampling으로 실험한다.
- `every 1`은 모든 query를 trace하므로 부하와 데이터량이 커질 수 있다.
- `coredns-custom` 수정 전후 ConfigMap을 백업한다.
- CoreDNS rollout 후 DNS resolution, CoreDNS readiness, Pod log를 즉시 확인한다.
- 문제가 생기면 `trace.override`를 제거하고 CoreDNS deployment를 rolling restart한다.

## 산출물

- 적용 전 CoreDNS 상태 기록
- Zipkin 배포 및 접속 정보
- 적용한 `coredns-custom` manifest
- CoreDNS trace sample screenshot 또는 JSON
- application trace와 CoreDNS trace 비교 결과
- DNS 프로토콜 레벨 trace context adoption 시도와 현재 한계 정리
- 통합 가능성 결론
  - same trace tree 가능 여부
  - backend-level aggregation 가능 여부
  - metadata correlation 가능 여부

## 최종 결론 형식

PoC 종료 후 아래 형태로 정리한다.

```text
AKS CoreDNS trace plugin은 coredns-custom으로 활성화 가능/불가했다.
활성화 후 Zipkin으로 DNS query trace가 수집됨/수집되지 않음.
수집된 span에는 <확인된 주요 field>가 포함됨.
일반 Pod -> CoreDNS UDP/TCP DNS 경로에서 application trace ID와 CoreDNS trace ID는 동일함/다름.
따라서 application trace와 CoreDNS trace는 parent-child trace로 통합 가능/불가하고,
현실적인 correlation key는 <timestamp, query name, client Pod IP, workload metadata 등>이다.
Collector/Azure Monitor/Grafana 연계는 <가능/제약 있음/추가 검증 필요>로 판단한다.
```

## 레퍼런스

- CoreDNS plugin 목록: https://coredns.io/plugins/
- CoreDNS trace plugin 문서: https://coredns.io/plugins/trace/
- CoreDNS debug plugin 문서: https://coredns.io/plugins/debug/
- CoreDNS trace plugin source: https://github.com/coredns/coredns/blob/master/plugin/trace/trace.go
- CoreDNS trace plugin setup source: https://github.com/coredns/coredns/blob/master/plugin/trace/setup.go
- CoreDNS `HTTPRequestKey` 문서: https://pkg.go.dev/github.com/coredns/coredns/core/dnsserver#HTTPRequestKey
- AKS CoreDNS customization 문서: https://learn.microsoft.com/en-us/azure/aks/coredns-custom
- OpenTelemetry Collector 문서: https://opentelemetry.io/docs/collector/
- OpenTelemetry Collector Zipkin receiver: https://github.com/open-telemetry/opentelemetry-collector-contrib/tree/main/receiver/zipkinreceiver
- Azure Monitor Application Insights OpenTelemetry 문서: https://learn.microsoft.com/en-us/azure/azure-monitor/app/opentelemetry-overview
- W3C Trace Context: https://www.w3.org/TR/trace-context/
- EDNS `TRACEPARENT` draft repository: https://github.com/PowerDNS/draft-edns-otel-trace-ids
- EDNS `TRACEPARENT` rendered draft: https://powerdns.github.io/draft-edns-otel-trace-ids/draft-edns-otel-trace-ids.txt
- IETF datatracker entry for EDNS `TRACEPARENT`: https://datatracker.ietf.org/doc/draft-edns-otel-trace-ids/
- IANA DNS Parameters: https://www.iana.org/assignments/dns-parameters/dns-parameters.xhtml
