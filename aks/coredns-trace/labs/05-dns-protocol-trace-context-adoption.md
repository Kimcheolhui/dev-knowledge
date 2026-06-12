# 05. DNS protocol-level trace context adoption

이 문서는 `04` 실습에서 확인한 “application trace와 CoreDNS trace가 같은 trace tree로 자동 연결되지 않는다”는 결과를 바탕으로, DNS 프로토콜 레벨에서 trace context를 전달하는 것이 가능한지와 CoreDNS/OpenTelemetry 진영에서 어떤 방향의 논의가 있었는지를 정리한다.

## 목표

- DNS 프로토콜에 HTTP header와 유사한 trace context carrier가 있는지 확인한다.
- EDNS option을 이용해 W3C Trace Context의 `traceparent` 값을 전달하는 접근이 이론적으로 가능한지 판단한다.
- CoreDNS trace plugin을 수정하면 EDNS 기반 trace context extraction이 가능한지 코드 관점에서 해석한다.
- CoreDNS/OpenTelemetry 진영에서 실제로 논의된 방향을 확인하고, 현재 PoC의 현실적인 결론을 정리한다.

## 1. 결론 요약

| 질문                                                            | 판단                                                                                                                                      |
| --------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------- |
| DNS에 trace context를 넣을 확장 지점이 있는가?                  | 있다. HTTP header 같은 범용 header는 없지만, Additional section의 EDNS(0) OPT pseudo-RR option을 carrier로 사용할 수 있다.                 |
| EDNS option에 W3C `traceparent`와 동등한 값을 실을 수 있는가?    | 기술적으로 가능하다. `trace-id`, `parent-id`, `trace-flags`를 option data로 encode하면 된다.                                              |
| CoreDNS trace code를 수정하면 그 값을 parent context로 쓸 수 있는가? | 가능하다. CoreDNS는 `dns.Msg`의 EDNS option을 읽을 수 있으므로, trace plugin에서 option을 parse해 span parent 또는 link로 사용할 수 있다. |
| 현재 AKS/CoreDNS 기본 경로에서 바로 쓸 수 있는가?               | 어렵다. client resolver가 EDNS trace context를 넣지 않고, AKS managed CoreDNS의 trace plugin 코드도 수정할 수 없다.                       |
| CoreDNS/OpenTelemetry 본류에서 이 방향이 주류로 논의됐는가?     | 아니다. 확인된 논의는 OpenTelemetry plugin 도입, app-side DNS span, eBPF/OBI 기반 DNS/network correlation 쪽에 가깝다.                   |

따라서 현재 PoC의 결론은 다음처럼 정리한다.

```text
DNS 프로토콜에 trace context를 실을 수 있는 확장 지점은 EDNS option 형태로 존재한다.

그러나 일반 AKS Pod -> CoreDNS UDP/TCP DNS 경로에서는 application trace context가 EDNS option으로 자동 전파되지 않는다.

직접 구현하려면 application/resolver 쪽과 CoreDNS trace 처리 로직을 함께 수정해야 하며, AKS managed CoreDNS에서는 적용성이 제한된다.
```

## 2. DNS에서 trace context carrier가 될 수 있는 위치

DNS에는 HTTP의 `traceparent` header처럼 임의 key-value metadata를 넣는 범용 header 영역이 없다. DNS message는 대략 다음 구조를 가진다.

```text
DNS Message
  Header
  Question
  Answer
  Authority
  Additional
    OPT pseudo-RR
      OPTION-CODE
      OPTION-LENGTH
      OPTION-DATA
```

이 중 trace context carrier 후보는 EDNS(0)의 `OPT` pseudo-RR이다. `OPT` record는 DNS Additional section에 들어가며, 하나 이상의 EDNS option을 담을 수 있다.

즉 HTTP에서는 다음처럼 header가 carrier가 된다.

```http
traceparent: 00-<trace-id>-<parent-id>-01
```

DNS에서는 같은 정보를 다음처럼 EDNS option data에 encode하는 구조가 된다.

```text
Additional section:
  OPT pseudo-RR:
    TRACEPARENT option:
      version
      trace-id
      parent-id
      trace-flags
```

따라서 “DNS에는 trace context를 실을 방법이 전혀 없다”가 아니라, “HTTP header와는 다른 carrier를 별도로 정의하고 양쪽 구현체가 그 carrier를 이해해야 한다”가 정확하다.

## 3. EDNS TRACEPARENT draft의 의미

DNS protocol-level trace context adoption의 가장 직접적인 후보는 EDNS `TRACEPARENT` Internet-Draft다.

- Datatracker: https://datatracker.ietf.org/doc/draft-edns-otel-trace-ids/
- Draft source repository: https://github.com/PowerDNS/draft-edns-otel-trace-ids
- Rendered draft text: https://powerdns.github.io/draft-edns-otel-trace-ids/draft-edns-otel-trace-ids.txt

이 draft의 제목은 다음과 같다.

```text
Communicating Distributed Trace IDs in EDNS
```

핵심 목적은 DNS system 사이에서 event correlation을 위해 trace identifier를 전달하는 EDNS option을 정의하는 것이다. 즉 OpenTelemetry payload 전체를 DNS packet에 넣자는 제안이 아니라, W3C Trace Context의 `traceparent`에 해당하는 최소 식별자만 DNS option으로 전달하는 접근이다.

Version 0 기준 data field는 다음 세 값을 담는다.

| 필드          | 크기     | 의미                                |
| ------------- | -------- | ----------------------------------- |
| `trace-id`    | 16 bytes | distributed trace 전체 식별자       |
| `parent-id`   | 8 bytes  | 직전 span 또는 parent operation ID  |
| `trace-flags` | 1 byte   | sampled flag 등 trace 처리 flag     |

presentation format은 W3C Trace Context의 HTTP header와 유사하다.

```text
TRACEPARENT=[version]-[trace-id]-[parent-id]-[trace-flags]
```

다만 이 draft는 아직 현재 운영 환경에서 바로 기대할 수 있는 표준 기능으로 보기는 어렵다.

| 항목                  | 현재 판단                                                                                                                           |
| --------------------- | ------------------------------------------------------------------------------------------------------------------------------------ |
| RFC 여부              | 아니다. Internet-Draft 단계다.                                                                                                       |
| IANA option code 여부 | draft text에서는 option code가 `TBD1`로 남아 있고, IANA EDNS0 Option Codes registry에 `TRACEPARENT` 항목은 확인되지 않는다.          |
| AKS/CoreDNS 적용성    | 기본 AKS CoreDNS와 일반 Pod resolver 경로에서는 지원된다고 보기 어렵다. client와 DNS server 양쪽 구현이 필요하다.                  |
| 운영 사용 범위        | draft도 upstream/downstream server operator 간 상호 합의 후 사용하는 방향을 전제한다. 무분별한 public DNS 전파 기능으로 보기 어렵다. |

## 4. CoreDNS code 관점에서 가능한 수정 방향

CoreDNS는 DNS query를 `github.com/miekg/dns`의 `dns.Msg`로 처리한다. 따라서 CoreDNS plugin 코드에서는 request message의 EDNS option을 읽을 수 있다.

개념적으로는 다음 흐름이 가능하다.

```text
CoreDNS trace plugin
  -> r.IsEdns0()로 OPT record 확인
  -> option list에서 TRACEPARENT option code 탐색
  -> option data에서 trace-id / parent-id / trace-flags parse
  -> CoreDNS servedns span의 parent context 또는 link로 사용
```

현재 CoreDNS `trace` plugin에는 이미 HTTP request context가 있는 경우 header에서 tracing context를 추출하는 흐름이 있다.

```go
if val := ctx.Value(dnsserver.HTTPRequestKey{}); val != nil {
    if httpReq, ok := val.(*http.Request); ok {
        spanCtx, _ = t.Tracer().Extract(ot.HTTPHeaders, ot.HTTPHeadersCarrier(httpReq.Header))
    }
}

span = t.Tracer().StartSpan(defaultTopLevelSpanName, otext.RPCServerOption(spanCtx))
```

이 로직은 DoH처럼 HTTP request가 CoreDNS context에 들어오는 경로에서는 의미가 있다. 하지만 일반 UDP/TCP DNS query에서는 HTTP header carrier가 없으므로 이 경로를 타지 않는다.

EDNS 기반 구현을 한다면 대략 다음 방향이 된다.

```go
spanCtx := extractTraceparentFromEDNS(r)
span = t.Tracer().StartSpan(defaultTopLevelSpanName, otext.RPCServerOption(spanCtx))
```

다만 현재 `trace` plugin은 OpenTracing/Zipkin bridge 중심으로 구현되어 있다. EDNS TRACEPARENT draft는 W3C Trace Context 형식이므로, 단순히 HTTP carrier에 `traceparent` 문자열을 넣는 것만으로 기존 Zipkin OpenTracing extractor가 이해한다고 보기는 어렵다. 구현 방향은 둘 중 하나다.

| 방향                                   | 설명                                                                                           |
| -------------------------------------- | ---------------------------------------------------------------------------------------------- |
| 기존 trace plugin에 직접 mapping 추가 | EDNS option에서 읽은 W3C trace-id/parent-id를 Zipkin/OpenTracing span context로 직접 변환한다.   |
| OpenTelemetry 기반 plugin으로 재작성   | CoreDNS tracing을 OpenTelemetry SDK 기반으로 바꾸고 W3C Trace Context propagator를 활용한다.     |

기술적으로는 가능하지만, 이것은 설정 변경이 아니라 CoreDNS tracing implementation 변경이다.

## 5. application/resolver 쪽에서 필요한 변화

CoreDNS만 수정해서는 trace tree가 이어지지 않는다. application 쪽 DNS query가 EDNS TRACEPARENT option을 실제로 넣어줘야 한다.

필요한 흐름은 다음과 같다.

```text
application active span
  -> resolver가 current trace context를 조회
  -> DNS query에 EDNS TRACEPARENT option 추가
  -> CoreDNS가 해당 option을 parse
  -> CoreDNS DNS span을 application trace의 child 또는 linked span으로 생성
```

일반적인 HTTP client instrumentation은 HTTP request header에 `traceparent`를 넣어준다. 반면 일반 `getaddrinfo()`, libc resolver, 언어 runtime resolver는 현재 OpenTelemetry context를 EDNS option으로 넣지 않는다.

가능한 구현 방식은 다음과 같다.

| 방식                                    | 가능성 | 한계                                                                                     |
| --------------------------------------- | ------ | ---------------------------------------------------------------------------------------- |
| 앱에서 custom DNS client 사용           | 가능   | 일반 DNS resolution 경로를 우회해야 하며 앱 변경 폭이 크다.                              |
| 언어 runtime 또는 resolver library 수정 | 가능   | Go/Java/Python/libc/c-ares 등 런타임별 구현이 필요하고 범용 운영 적용이 어렵다.           |
| node-local DNS proxy에서 주입           | 제한적 | proxy가 application의 in-process current span context를 알기 어렵다. 정확한 parent 연결이 어렵다. |
| eBPF 기반 관측/correlation              | 현실적 | protocol propagation은 아니지만, DNS latency/error/query를 trace와 correlation할 수 있다. |

따라서 직접 구현 PoC는 가능하지만, 운영 적용은 application/resolver 표준 지원 없이는 제한적이다.

## 6. CoreDNS/OpenTelemetry 진영에서 확인된 논의

CoreDNS와 OpenTelemetry 쪽에서 확인한 논의는 EDNS TRACEPARENT 직접 지원보다는 다음 방향에 가깝다.

### 6.1 CoreDNS OpenTelemetry plugin 논의

CoreDNS에는 OpenTelemetry plugin을 추가하자는 이슈와 PR이 있었다.

- Issue: https://github.com/coredns/coredns/issues/5530
- PR: https://github.com/coredns/coredns/pull/5777

이 논의의 배경은 기존 CoreDNS `trace` plugin이 OpenTracing 기반이고, OpenTracing이 deprecated 되었기 때문에 OpenTelemetry 기반 tracing plugin으로 옮기자는 것이었다.

주요 논점은 다음과 같다.

| 논점              | 내용                                                                                 |
| ----------------- | ------------------------------------------------------------------------------------ |
| 필요성            | OpenTracing 기반 `trace` plugin을 OpenTelemetry 기반으로 대체하거나 보완한다.         |
| 장점              | OpenTelemetry Collector/Zipkin 등 더 넓은 backend 연계 가능성을 제공한다.             |
| 반대/우려         | OpenTelemetry SDK dependency가 CoreDNS에 비해 무겁고, 외부 plugin이 더 적절할 수 있다. |
| 결과              | PR은 merge되지 않았다. CoreDNS 본류에 별도 `opentelemetry` plugin이 들어가지는 않았다. |
| EDNS TRACEPARENT와의 관계 | DNS packet의 EDNS option에서 traceparent를 extract하는 논의는 아니다.                 |

즉 CoreDNS 진영에서는 “tracing implementation을 OpenTelemetry로 현대화하자”는 논의는 있었지만, “EDNS option을 trace context carrier로 삼자”는 흐름은 확인되지 않았다.

### 6.2 OpenTelemetry app-side DNS instrumentation

OpenTelemetry 쪽에서는 DNS를 protocol carrier로 다루기보다, application 내부 operation으로 span을 만드는 논의가 확인된다.

Node.js DNS instrumentation:

- Package: https://github.com/open-telemetry/opentelemetry-js-contrib/tree/main/packages/instrumentation-dns
- Related issue: https://github.com/open-telemetry/opentelemetry-js-contrib/issues/2846

Python aiohttp DNS resolution span 논의:

- Issue: https://github.com/open-telemetry/opentelemetry-python-contrib/issues/3198

이 방향은 DNS query를 CoreDNS trace와 같은 trace tree로 이어붙이는 protocol propagation이 아니다. 대신 application trace 안에 `dns.lookup` 또는 `dns.resolve`에 해당하는 span을 만들고, DNS resolution latency와 error를 application 관점에서 관측하는 방식이다.

### 6.3 OpenTelemetry eBPF/OBI 기반 DNS observability

OpenTelemetry eBPF Instrumentation, 즉 OBI 쪽에서는 DNS observability 논의가 더 직접적으로 확인된다.

- DNS observability in OBI: https://github.com/open-telemetry/opentelemetry-ebpf-instrumentation/issues/608
- Trace-correlated L3/L4 network flow spans: https://github.com/open-telemetry/opentelemetry-ebpf-instrumentation/issues/1659
- Initial TCP-only network flow span proposal: https://github.com/open-telemetry/opentelemetry-ebpf-instrumentation/issues/1781

`DNS observability in OBI` 이슈는 DNS latency, rcode, resolver usage, qname 등을 metrics/traces로 관측하자는 내용이며, trace 쪽 목표로 “active span이 있으면 `dns.resolve` child span을 만든다”는 방향을 제시한다.

`trace-correlated network flow spans` 논의는 DNS보다 더 넓은 TCP/UDP/ICMP flow를 기존 trace와 correlation해서 span으로 만들자는 제안이다. 여기서는 flow와 trace가 서로 다른 abstraction layer라서 many-to-many 관계가 생길 수 있고, span links나 별도 network trace 모델도 논의된다.

이 흐름은 EDNS TRACEPARENT를 packet에 주입하는 방식이 아니라, eBPF/agent가 network/DNS event를 관측하고 가능한 경우 application trace와 correlation하는 방식이다.

## 7. 현재 AKS/CoreDNS PoC와의 관계

현재 실험 경로는 다음과 같다.

```text
otel-dns-client application
  -> libc / runtime resolver
  -> Kubernetes DNS Service
  -> AKS CoreDNS UDP/TCP :53
  -> upstream DNS
```

이 경로에서 HTTP `traceparent` header는 DNS packet 안에 들어가지 않는다. 따라서 `04` 실습에서 HTTP 요청에 `traceparent`를 직접 넣어도 application trace만 해당 trace ID를 사용하고, CoreDNS `servedns` trace는 별도의 root trace로 생성됐다.

EDNS TRACEPARENT 방식이 적용되려면 구조가 다음처럼 바뀌어야 한다.

```text
application span
  -> resolver emits DNS query with EDNS TRACEPARENT
CoreDNS
  -> extracts trace-id / parent-id / trace-flags
  -> creates DNS span as child or linked span
```

그러나 현재 AKS managed CoreDNS 기준으로는 다음 제약이 있다.

| 계층                              | 제약                                                                                              |
| --------------------------------- | ------------------------------------------------------------------------------------------------- |
| application/runtime/stub resolver | current OpenTelemetry context를 DNS EDNS option으로 넣지 않는다.                                  |
| CoreDNS                           | managed CoreDNS의 `trace` plugin 코드를 수정할 수 없고, `coredns-custom`은 Corefile 설정만 바꾼다. |
| trace backend                     | 같은 Collector/backend로 모을 수 있어도 trace ID가 다르면 하나의 trace tree로 자동 병합되지 않는다. |
| 표준화 상태                       | EDNS TRACEPARENT는 아직 널리 배포된 표준 기능이 아니다.                                           |

따라서 AKS 기본 경로에서 현실적인 접근은 여전히 metadata correlation이다.

```text
현재 AKS CoreDNS trace plugin만으로는 application trace와 DNS trace를 같은 trace tree로 자동 연결할 수 없다.

CoreDNS trace와 application trace를 같은 Collector/backend로 모으는 것은 가능하지만, trace ID는 별도로 생성된다.

따라서 timestamp, query name, client Pod IP, namespace/workload metadata를 기준으로 correlation하는 방식이 현실적이다.
```

## 8. 추가 PoC를 한다면 가능한 방향

직접 구현 가능성을 검증하려면 AKS managed CoreDNS가 아니라 별도 실험 환경에서 시작하는 것이 적절하다.

```text
custom DNS client
  -> EDNS TRACEPARENT option 주입
custom CoreDNS 또는 CoreDNS fork
  -> EDNS option parse
  -> CoreDNS DNS span parent/link 설정
Zipkin 또는 OpenTelemetry backend
  -> app span과 DNS span 관계 확인
```

검증 포인트는 다음과 같다.

| 검증 항목                       | 확인 내용                                                                 |
| ------------------------------- | ------------------------------------------------------------------------- |
| EDNS option encode/decode       | client가 넣은 trace-id/parent-id/flags를 CoreDNS에서 정확히 읽는가.        |
| parent-child 또는 link 생성     | CoreDNS DNS span이 application span의 child 또는 linked span으로 보이는가. |
| sampling/부하                   | DNS query마다 trace context를 싣는 것이 부하와 데이터량을 과도하게 늘리지 않는가. |
| cache/forward behavior          | CoreDNS cache hit, upstream forward, NXDOMAIN 등 처리 경로별 span이 안정적인가. |
| 보안/신뢰 경계                  | 외부에서 임의 trace ID를 주입하는 것을 허용할지, ACL을 둘지 판단한다.      |

운영 적용까지 고려한다면, CoreDNS fork보다 OpenTelemetry OBI의 DNS/network observability 또는 application-side DNS instrumentation 쪽이 더 현실적인 대안일 수 있다.

## 9. 현실적인 대안: application DNS span과 eBPF/OBI correlation

EDNS TRACEPARENT 기반 구현은 protocol-level로는 가능하지만, application/resolver/CoreDNS를 모두 바꿔야 한다. 따라서 현재 운영 환경에서는 다음 두 접근이 더 현실적이다.

```text
application 내부 DNS span
= 애플리케이션 프로세스 안에서 DNS lookup 호출 구간을 span으로 기록한다.

eBPF/OBI 기반 DNS/network observability
= 커널/네트워크 레벨에서 실제 DNS packet 또는 flow를 관측하고, 가능한 경우 application trace와 correlation한다.
```

### 9.1 Application 내부 DNS span

Application DNS span은 DNS query packet에 trace context를 싣는 방식이 아니다. 애플리케이션이 DNS resolution을 수행하는 코드 구간을 현재 active span의 child span으로 기록하는 방식이다.

예를 들어 application 요청 하나가 외부 hostname resolve와 HTTP call을 수행하면 trace는 다음처럼 구성될 수 있다.

```text
Trace ID: <application-trace-id>
GET /resolve-and-call
  -> dns.resolve www.microsoft.com
  -> HTTP GET https://www.microsoft.com/
```

이 방식의 장점은 application trace tree와 자연스럽게 이어진다는 점이다. DNS lookup span은 application process 안에서 생성되므로 현재 active span context를 그대로 parent로 사용할 수 있다.

| 장점                                  | 설명                                                                                  |
| ------------------------------------- | ------------------------------------------------------------------------------------- |
| request 단위 원인 분석이 쉽다         | 특정 API 요청에서 DNS lookup 시간이 얼마나 걸렸는지 바로 볼 수 있다.                  |
| CoreDNS 수정이 필요 없다              | application instrumentation 또는 runtime/library hook만으로 시작할 수 있다.            |
| HTTP outbound span과 함께 보기 좋다   | 외부 호출 전 DNS resolution 지연과 HTTP 지연을 같은 trace에서 비교할 수 있다.          |
| parent-child 관계가 명확하다          | span이 application 내부에서 생성되므로 trace context propagation 문제가 상대적으로 작다. |

한계도 명확하다.

| 한계                           | 설명                                                                                           |
| ------------------------------ | ---------------------------------------------------------------------------------------------- |
| CoreDNS 내부 처리는 보이지 않는다 | CoreDNS cache hit/miss, plugin chain, upstream forward 여부는 알 수 없다.                       |
| runtime/library 의존성이 있다   | 언어별 DNS resolver hook이나 instrumentation 지원이 필요하다.                                   |
| 실제 packet 발생 여부가 애매할 수 있다 | OS/runtime cache에서 처리된 lookup과 실제 DNS packet이 나간 lookup을 구분하기 어려울 수 있다. |
| qname privacy/cardinality 관리가 필요하다 | query name은 민감 정보이거나 high-cardinality attribute가 될 수 있다.                          |

따라서 application DNS span은 “CoreDNS가 어떻게 처리했는가”보다 “이 application request 안에서 DNS lookup이 병목이었는가”를 확인하는 데 적합하다.

### 9.2 eBPF/OBI 기반 DNS/network observability

OBI, 즉 OpenTelemetry eBPF Instrumentation 방향은 애플리케이션 코드가 아니라 노드 커널/네트워크 레벨에서 DNS packet 또는 socket flow를 관측하는 접근이다.

```text
Application
  -> DNS query packet
Kernel / eBPF
  -> DNS request/response 관측
  -> qname / qtype / rcode / latency 추출
  -> source workload, destination resolver, network tuple과 연결
  -> 가능한 경우 application trace와 correlation
```

이 접근은 실제 네트워크에서 발생한 DNS request/response를 본다. 따라서 application 내부 DNS span보다 cluster/workload 관점의 DNS 품질 분석에 강하다.

관측 가능한 정보의 예시는 다음과 같다.

| 정보                  | 의미                                      |
| --------------------- | ----------------------------------------- |
| query name / query type | 어떤 이름과 record type을 조회했는지 확인한다. |
| response code         | `NOERROR`, `NXDOMAIN`, `SERVFAIL` 등 실패 유형을 본다. |
| resolver/server address | 어떤 resolver 또는 CoreDNS endpoint로 질의했는지 본다. |
| latency               | DNS request와 response 사이의 시간을 본다. |
| source workload       | 어떤 pod/workload가 DNS query를 발생시켰는지 본다. |
| transport/flow        | UDP/TCP, socket/flow 수준의 네트워크 정보를 본다. |

다만 eBPF/OBI도 trace 관계를 항상 정확한 parent-child로 복원할 수 있는 것은 아니다. DNS packet 자체에는 trace context가 없기 때문이다. 따라서 correlation은 보통 다음 단서들을 조합한다.

```text
known trace context
+ process/thread/socket 정보
+ source pod/workload
+ destination resolver
+ timestamp window
+ DNS transaction id 또는 5-tuple
+ qname
=> 이 DNS event가 이 trace와 관련 있어 보인다고 연결
```

OBI의 trace-correlated network flow 논의에서도 이 문제가 드러난다. network flow와 application trace는 서로 다른 abstraction layer이므로 항상 1:1 관계가 아니다.

| 관계 예시              | 의미                                                                 |
| ---------------------- | -------------------------------------------------------------------- |
| 하나의 trace -> 여러 DNS query | 한 요청이 여러 hostname resolve, retry, reconnect를 만들 수 있다.       |
| 하나의 flow -> 여러 trace      | long-lived connection이나 shared resolver flow는 여러 요청이 공유할 수 있다. |
| 여러 trace -> 하나의 network view | network 관점에서는 하나의 resolver/workload edge로 집계될 수 있다.        |

그래서 eBPF/OBI 방식에서는 상황에 따라 세 모델을 구분해야 한다.

| 모델                         | 설명                                                                                  |
| ---------------------------- | ------------------------------------------------------------------------------------- |
| application trace 안에 child span 추가 | correlation이 충분히 명확하면 `dns.resolve` 또는 network span을 기존 trace에 붙인다.       |
| Span Link 사용               | parent-child로 단정하기 어렵지만 관련성은 있을 때 link로 연결한다.                    |
| metrics/log/event 기반 correlation | trace에 직접 붙이지 않고 dashboard/query에서 workload, qname, time window로 연결한다. |

즉 eBPF/OBI는 protocol propagation을 대체하는 것이 아니라, 실제 packet/flow evidence를 기반으로 DNS/network 문제를 application trace와 최대한 연결해 보는 접근이다.

### 9.3 CoreDNS trace와의 역할 분리

세 접근은 대체재라기보다 서로 다른 계층을 본다.

| 접근                         | 보는 위치                    | 강한 질문                                                       | 약한 질문                                                              |
| ---------------------------- | ---------------------------- | --------------------------------------------------------------- | ---------------------------------------------------------------------- |
| Application DNS span         | application process 내부      | “이 요청에서 DNS lookup이 느렸는가?”                            | “CoreDNS가 cache/plugin/upstream 중 어디서 처리했는가?”                 |
| eBPF/OBI DNS/network 관측    | node/kernel/network level      | “어떤 workload가 어떤 DNS error/latency/flow를 만들었는가?”      | “정확히 어떤 span의 child인가?”를 항상 보장하기 어렵다.                 |
| CoreDNS trace plugin         | CoreDNS plugin chain 내부      | “CoreDNS가 query를 어떤 plugin chain과 upstream 경로로 처리했는가?” | “이 DNS query가 어떤 application trace의 일부인가?”를 자동으로 알기 어렵다. |

따라서 이상적인 운영 관측 모델은 다음처럼 볼 수 있다.

```text
Application trace
  GET /api
    -> dns.resolve api.github.com          # application-side DNS span
    -> HTTP GET https://api.github.com

Node / eBPF / OBI
  DNS event
    workload=<source-workload>
    qname=api.github.com
    rcode=NOERROR
    server=<resolver-address>
    latency=12ms
    correlated_trace_id=<best-effort>

CoreDNS trace
  servedns
    -> cache / kubernetes / forward / connect
```

Application DNS span은 request causality를 보여주고, eBPF/OBI는 실제 packet-level evidence를 보강하며, CoreDNS trace는 DNS server 내부 처리 경로를 설명한다.

### 9.4 AKS 운영 관점의 우선순위

AKS 운영 관점에서는 다음 순서가 현실적이다.

| 우선순위 | 접근                          | 이유                                                                                  |
| -------- | ----------------------------- | ------------------------------------------------------------------------------------- |
| 1        | Application 내부 DNS span      | trace tree에 가장 자연스럽게 붙고, application latency 원인 분석에 바로 유용하다.       |
| 2        | eBPF/OBI 기반 DNS/network 관측 | workload/cluster 전체 DNS 품질, error, resolver latency를 보는 데 유리하다.             |
| 3        | CoreDNS trace plugin           | CoreDNS 내부 plugin chain 진단에는 유용하지만, 상시 운영은 sampling/부하/노이즈 검토가 필요하다. |
| 4        | EDNS TRACEPARENT custom 구현   | 기술적으로 흥미로운 PoC지만, application/resolver/CoreDNS를 모두 바꿔야 해 운영 적용성이 낮다. |

결론적으로, application trace와 DNS를 “같은 trace tree”로 붙이는 목적이라면 application 내부 DNS span이 가장 현실적이다. 반면 cluster/workload 관점에서 DNS 문제를 탐지하고 싶다면 eBPF/OBI 기반 DNS observability가 더 적합하다. CoreDNS trace plugin은 CoreDNS 내부 처리 경로를 설명하는 진단 도구로 남기는 것이 자연스럽다.

## 10. 최종 판단

이번 AKS CoreDNS trace PoC에서 중요한 결론은 다음이다.

```text
EDNS option을 이용하면 DNS protocol-level trace context carrier를 정의하는 것은 가능하다.

그러나 현재 AKS/CoreDNS 기본 UDP/TCP DNS 경로에서는 application trace context가 CoreDNS trace plugin까지 자동 전파되지 않는다.

직접 구현하려면 application/resolver와 CoreDNS trace logic을 함께 수정해야 하며, AKS managed CoreDNS에서는 바로 적용하기 어렵다.

CoreDNS/OpenTelemetry 진영의 실제 논의도 EDNS TRACEPARENT 직접 적용보다는 OpenTelemetry plugin, app-side DNS span, eBPF/OBI 기반 DNS/network correlation 쪽에 가깝다.

Application trace와 DNS를 같은 trace tree 안에서 보고 싶다면 application 내부 DNS span이 가장 현실적이다.

Cluster/workload 관점에서 실제 DNS packet, resolver latency, rcode, network flow를 보고 싶다면 eBPF/OBI 기반 DNS/network observability가 더 적합하다.

CoreDNS trace plugin은 application trace propagation 수단이라기보다 CoreDNS 내부 plugin chain과 upstream 처리 경로를 설명하는 진단 도구로 보는 것이 자연스럽다.

따라서 현재 AKS CoreDNS trace PoC의 운영 결론은 protocol-level same trace tree propagation이 아니라, application-side span 또는 eBPF/OBI 관측을 보완적으로 사용하고 CoreDNS trace는 timestamp + query name + client Pod IP + Kubernetes metadata 기준으로 correlation하는 것이다.
```

## 참고

- RFC 6891, Extension Mechanisms for DNS: https://www.rfc-editor.org/rfc/rfc6891
- IANA DNS Parameters: https://www.iana.org/assignments/dns-parameters/dns-parameters.xhtml
- W3C Trace Context: https://www.w3.org/TR/trace-context/
- EDNS `TRACEPARENT` draft repository: https://github.com/PowerDNS/draft-edns-otel-trace-ids
- EDNS `TRACEPARENT` rendered draft: https://powerdns.github.io/draft-edns-otel-trace-ids/draft-edns-otel-trace-ids.txt
- IETF datatracker entry: https://datatracker.ietf.org/doc/draft-edns-otel-trace-ids/
- CoreDNS `trace` plugin source: https://github.com/coredns/coredns/blob/master/plugin/trace/trace.go
- CoreDNS OpenTelemetry plugin issue: https://github.com/coredns/coredns/issues/5530
- CoreDNS OpenTelemetry plugin PR: https://github.com/coredns/coredns/pull/5777
- OpenTelemetry context propagation: https://opentelemetry.io/docs/concepts/context-propagation/
- OpenTelemetry propagators spec: https://opentelemetry.io/docs/specs/otel/context/api-propagators/
- OpenTelemetry JS DNS instrumentation: https://github.com/open-telemetry/opentelemetry-js-contrib/tree/main/packages/instrumentation-dns
- OpenTelemetry JS DNS span relationship issue: https://github.com/open-telemetry/opentelemetry-js-contrib/issues/2846
- OpenTelemetry Python aiohttp DNS resolution span issue: https://github.com/open-telemetry/opentelemetry-python-contrib/issues/3198
- OpenTelemetry OBI DNS observability issue: https://github.com/open-telemetry/opentelemetry-ebpf-instrumentation/issues/608
- OpenTelemetry OBI trace-correlated network flow issue: https://github.com/open-telemetry/opentelemetry-ebpf-instrumentation/issues/1659
- OpenTelemetry OBI TCP network flow span issue: https://github.com/open-telemetry/opentelemetry-ebpf-instrumentation/issues/1781

다음 단계: [06-cleanup-and-result-summary.md](06-cleanup-and-result-summary.md)
