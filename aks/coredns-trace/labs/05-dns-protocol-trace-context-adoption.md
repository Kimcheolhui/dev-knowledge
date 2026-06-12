# 05. DNS protocol-level trace context adoption

이 문서는 `04` 실습에서 확인한 “application trace와 CoreDNS trace가 같은 trace tree로 자동 연결되지 않는다”는 결과를 DNS 프로토콜 레벨의 표준화 시도 관점에서 정리한다.

## 목표

- DNS 프로토콜 자체에 OpenTelemetry 또는 trace context를 싣기 위한 시도가 있는지 확인한다.
- EDNS `TRACEPARENT` Internet-Draft의 목적과 현재 성숙도를 정리한다.
- 이 시도가 AKS CoreDNS trace 실험 결과와 어떤 관계가 있는지 판단한다.
- PowerDNS 구현 사례를 CoreDNS 대체안이 아니라 protocol draft 구현/실험 사례로 분리해서 해석한다.

## 1. 결론 요약

| 질문                                                            | 판단                                                                                                                           |
| --------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------ |
| DNS 프로토콜 자체에서 trace context를 전달하려는 시도가 있는가? | 있다. EDNS option으로 `TRACEPARENT`를 정의하려는 Internet-Draft가 있다.                                                        |
| OpenTelemetry가 DNS 표준에 직접 들어가는 형태인가?              | 정확히는 OpenTelemetry SDK가 아니라 W3C Trace Context의 `traceparent` 값을 DNS EDNS option으로 싣는 접근이다.                  |
| 현재 RFC 또는 널리 배포된 표준인가?                             | 아니다. 현재는 Internet-Draft 단계이며 intended status는 Informational이다.                                                    |
| IANA EDNS option code가 정식 할당되었는가?                      | 현재 draft text에서는 option code가 `TBD1`로 남아 있고, IANA EDNS0 Option Codes registry에 `TRACEPARENT` 항목은 보이지 않는다. |
| AKS CoreDNS 기본 경로에서 사용할 수 있는가?                     | 현재는 아니다. client resolver, CoreDNS, upstream DNS 쪽 지원이 모두 필요하다.                                                 |
| PowerDNS 구현은 어떤 의미인가?                                  | CoreDNS 대체안이라기보다 EDNS `TRACEPARENT` draft를 구현해 보는 실험/참조 사례로 보는 것이 맞다.                               |

따라서 현재 PoC의 결론은 유지된다.

```text
일반 AKS Pod -> CoreDNS UDP/TCP DNS 경로에서는 application trace ID가 CoreDNS trace ID로 자동 전파되지 않는다.

다만 DNS protocol level에서 이를 해결하려는 표준화 시도는 있으며, 가장 직접적인 후보는 EDNS TRACEPARENT Internet-Draft다.
```

## 2. 관련 Internet-Draft

가장 직접적인 문서는 다음 draft다.

- Datatracker: https://datatracker.ietf.org/doc/draft-edns-otel-trace-ids/
- Draft source repository: https://github.com/PowerDNS/draft-edns-otel-trace-ids
- Rendered draft text: https://powerdns.github.io/draft-edns-otel-trace-ids/draft-edns-otel-trace-ids.txt

제목은 다음과 같다.

```text
Communicating Distributed Trace IDs in EDNS
```

draft의 핵심 목적은 DNS 시스템 사이에서 event correlation을 위한 trace identifier를 전달하는 EDNS option을 정의하는 것이다.

```text
This document defines a new EDNS Option named TRACEPARENT that is used to communicate an identifier for correlating events between DNS systems.
```

중요한 점은 이 draft가 DNS message 안에 OpenTelemetry payload 전체를 넣자는 제안이 아니라는 것이다. W3C Trace Context의 `traceparent`에 해당하는 최소 식별자만 EDNS option으로 전달한다.

## 3. EDNS TRACEPARENT wire format

draft의 version 0 format은 W3C Trace Context `traceparent`와 같은 핵심 필드를 사용한다.

| 필드          | 크기     | 의미                                          |
| ------------- | -------- | --------------------------------------------- |
| `version`     | 1 byte   | `TRACEPARENT` option format version           |
| `trace-id`    | 16 bytes | distributed trace 전체를 식별하는 ID          |
| `parent-id`   | 8 bytes  | 이 DNS hop 직전 span 또는 parent operation ID |
| `trace-flags` | 1 byte   | sampled flag 등 trace 처리 flag               |

presentation format은 HTTP `traceparent` header와 유사하다.

```text
TRACEPARENT=[version]-[trace-id]-[parent-id]-[trace-flags]
```

이 구조가 채택되면 DNS query 자체가 trace context carrier가 될 수 있다. 예를 들어 application runtime 또는 stub resolver가 DNS query에 EDNS `TRACEPARENT`를 넣고, resolver/CoreDNS/upstream DNS가 이를 읽어 trace span의 parent 또는 link로 사용할 수 있다.

## 4. 처리 규칙과 제약

draft는 `TRACEPARENT`를 일반 인터넷 전체에 무조건 흘리는 기능으로 보기보다는, 운영자 간 합의된 환경에서 사용하는 것을 권장한다.

```text
TRACEPARENT SHOULD only be used after mutual agreement between upstream and downstream server operators.
```

또 trace context가 DNS query 처리 결과에 영향을 주면 안 된다고 본다.

```text
Performing tracing SHOULD NOT impact DNS query processing.
```

실무적으로 중요한 제약은 다음과 같다.

| 항목               | 의미                                                                                       |
| ------------------ | ------------------------------------------------------------------------------------------ |
| malformed option   | DNS 처리 실패로 이어지기보다 tracing metadata를 무시하는 쪽에 가깝다.                      |
| response 포함 여부 | draft는 `TRACEPARENT`를 DNS response에 넣는 것을 금지하는 방향이다.                        |
| access control     | 무분별한 trace injection을 피하기 위해 ACL 또는 운영자 간 합의가 필요하다.                 |
| hop-by-hop 성격    | EDNS option은 DNS hop마다 처리 방식이 달라질 수 있으므로 end-to-end 보장으로 보면 안 된다. |

## 5. 현재 AKS/CoreDNS 실험과의 관계

현재 실험 경로는 다음과 같다.

```text
otel-dns-client application
  -> libc / runtime resolver
  -> Kubernetes DNS Service
  -> AKS CoreDNS UDP/TCP :53
  -> upstream DNS
```

이 경로에서 HTTP `traceparent` header는 DNS packet 안에 들어가지 않는다. 따라서 `04` 실습에서 HTTP 요청에 `traceparent`를 직접 넣어도 application trace만 해당 trace ID를 사용하고, CoreDNS `servedns` trace는 별도의 root trace로 생성됐다.

CoreDNS `trace` plugin의 context extraction도 AKS 기본 DNS 경로와는 다르다. CoreDNS code에는 DoH처럼 HTTP request context가 있는 경로에서 header 기반 tracing context를 읽을 수 있는 흐름이 있지만, 일반 UDP/TCP DNS query에는 HTTP header carrier가 없다.

EDNS `TRACEPARENT`가 실제로 채택되고 CoreDNS가 이를 지원한다면 구조는 다음처럼 바뀔 수 있다.

```text
application span
  -> resolver emits DNS query with EDNS TRACEPARENT
CoreDNS
  -> extracts trace-id / parent-id / trace-flags
  -> creates DNS span as child or linked span
  -> optionally forwards updated TRACEPARENT to upstream DNS
```

하지만 현재 AKS managed CoreDNS에서는 이 흐름을 사용할 수 있다고 보기 어렵다.

필요한 지원은 다음과 같다.

| 계층                              | 필요한 변화                                                                             |
| --------------------------------- | --------------------------------------------------------------------------------------- |
| application/runtime/stub resolver | 현재 active trace context를 DNS query의 EDNS `TRACEPARENT` option으로 넣어야 한다.      |
| CoreDNS                           | EDNS `TRACEPARENT` option을 parse하고 CoreDNS trace span의 parent/link로 연결해야 한다. |
| forwarder/upstream DNS            | 필요하면 `TRACEPARENT`를 다음 DNS hop으로 전달하거나 새 parent-id로 갱신해야 한다.      |
| trace backend                     | DNS span과 application span을 같은 trace 또는 연결된 trace로 해석해야 한다.             |

## 6. PowerDNS 구현 사례의 의미

PowerDNS는 AKS CoreDNS를 대체하기 위한 실용적인 예시로 보기는 어렵다. 그러나 EDNS `TRACEPARENT` draft가 단순 아이디어에만 머무르지 않고 실제 DNS 구현체에서 실험되고 있다는 증거로는 의미가 있다.

관련 구현 PR 예시는 다음과 같다.

- https://github.com/PowerDNS/pdns/pull/16786
- https://github.com/PowerDNS/pdns/pull/16870

해석은 다음처럼 분리한다.

| 관점            | 해석                                                                                                    |
| --------------- | ------------------------------------------------------------------------------------------------------- |
| AKS 운영 대체안 | 적합하지 않다. AKS의 kube-dns 경로는 managed CoreDNS가 기본이다.                                        |
| 표준화 가능성   | 의미가 있다. EDNS `TRACEPARENT` draft를 실제 DNS software에 구현하는 흐름이다.                          |
| PoC 확장 방향   | AKS CoreDNS 대체가 아니라 별도 DNS proxy/resolver lab에서 protocol behavior를 검증하는 방향이 적절하다. |

## 7. 비슷하지만 다른 접근

다음은 DNS protocol adoption과 구분해야 한다.

| 접근                           | 설명                                                                             | DNS protocol-level adoption 여부                                                        |
| ------------------------------ | -------------------------------------------------------------------------------- | --------------------------------------------------------------------------------------- |
| application runtime의 DNS span | 언어별 instrumentation이 `getaddrinfo` 또는 DNS lookup 시간을 span으로 기록한다. | 아니다. DNS packet에 trace context가 실리는 것은 아니다.                                |
| eBPF/zero-code tracing         | 네트워크 또는 syscall 수준에서 DNS query를 관측해 span/metric을 만든다.          | 아니다. 관측은 가능하지만 DNS peer로 trace context를 전달하지 않는다.                   |
| CoreDNS 내부 trace plugin      | CoreDNS plugin chain을 trace로 수집한다.                                         | 부분적이다. DNS server 내부 trace이며 application trace context를 자동 수신하지 않는다. |
| EDNS `TRACEPARENT`             | DNS query 안에 trace context 식별자를 싣는다.                                    | 맞다. 이 문서의 protocol-level 후보에 해당한다.                                         |

## 8. 재확인용 명령

draft text를 빠르게 확인한다.

```bash
curl -L -s 'https://powerdns.github.io/draft-edns-otel-trace-ids/draft-edns-otel-trace-ids.txt' \
  | sed -n '1,120p'
```

wire format과 processing section을 확인한다.

```bash
curl -L -s 'https://powerdns.github.io/draft-edns-otel-trace-ids/draft-edns-otel-trace-ids.txt' \
  | grep -n -i -E 'wire format|trace-id|parent-id|trace-flags|processing|mutual agreement|SHOULD NOT impact' \
  | head -40
```

IANA EDNS0 Option Codes registry에서 `TRACEPARENT`가 보이는지 확인한다.

```bash
curl -L -s 'https://www.iana.org/assignments/dns-parameters/dns-parameters.xhtml' \
  | grep -i 'TRACEPARENT' || true
```

실행 결과 기록:

```text
draft-edns-otel-trace-ids:

IANA TRACEPARENT registry check:

```

## 9. 최종 판단

현재 PoC의 운영적 결론은 metadata correlation이다.

```text
현재 AKS CoreDNS trace plugin만으로는 application trace와 DNS trace를 같은 trace tree로 자동 연결할 수 없다.

CoreDNS trace와 application trace를 같은 Collector/backend로 모으는 것은 가능하지만, trace ID는 별도로 생성된다.

따라서 timestamp, query name, client Pod IP, namespace/workload metadata를 기준으로 correlation하는 방식이 현실적이다.
```

다만 장기적인 표준화 관점에서는 EDNS `TRACEPARENT`가 가장 직접적인 후보이다.

```text
DNS protocol itself has an active trace context adoption attempt via EDNS TRACEPARENT, but it is not yet a finalized RFC or a generally available AKS/CoreDNS feature.
```

## 참고

- EDNS `TRACEPARENT` draft repository: https://github.com/PowerDNS/draft-edns-otel-trace-ids
- EDNS `TRACEPARENT` rendered draft: https://powerdns.github.io/draft-edns-otel-trace-ids/draft-edns-otel-trace-ids.txt
- IETF datatracker entry: https://datatracker.ietf.org/doc/draft-edns-otel-trace-ids/
- IANA DNS Parameters: https://www.iana.org/assignments/dns-parameters/dns-parameters.xhtml
- RFC 6891, Extension Mechanisms for DNS: https://www.rfc-editor.org/rfc/rfc6891
- RFC 9499, DNS Terminology: https://www.rfc-editor.org/rfc/rfc9499
- W3C Trace Context: https://www.w3.org/TR/trace-context/
- PowerDNS implementation PR example 1: https://github.com/PowerDNS/pdns/pull/16786
- PowerDNS implementation PR example 2: https://github.com/PowerDNS/pdns/pull/16870

다음 단계: [06-cleanup-and-result-summary.md](06-cleanup-and-result-summary.md)
