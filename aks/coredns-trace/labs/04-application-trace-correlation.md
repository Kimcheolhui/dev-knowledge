# 04. Application trace correlation

이 실습은 CoreDNS trace와 application OpenTelemetry trace를 같은 OpenTelemetry Collector debug log로 모아 trace ID가 이어지는지 비교한다.

## 목표

- OpenTelemetry Collector를 배포한다.
- CoreDNS `trace` endpoint를 Collector Zipkin receiver로 변경한다.
- 샘플 애플리케이션이 OTLP로 application trace를 Collector에 전송하게 한다.
- 같은 요청 시점의 application trace와 CoreDNS trace ID를 비교한다.

## 구조

```text
CoreDNS trace plugin
  -> Zipkin protocol
OpenTelemetry Collector zipkin receiver
  -> debug exporter logs

otel-dns-client sample app
  -> OTLP/HTTP
OpenTelemetry Collector otlp receiver
  -> debug exporter logs
```

이 구조는 “같은 collector/backend로 모을 수 있는지”와 “같은 trace tree로 이어지는지”를 분리해서 확인하기 위한 것이다.

## 0. 변수 확인

```bash
cd /home/cheolhuikim/studyspace/dev-knowledge/aks/coredns-trace/labs

export LAB_NS=trace-lab
export LAB_ARTIFACT_DIR='<01 단계에서 만든 artifacts 디렉터리 경로>'
export TRACE_EVERY=1
```

`TRACE_EVERY=1`은 짧은 테스트 구간에서만 사용한다. 공유 클러스터에서는 `10` 또는 `1000` 이상으로 조정한다.

실행 결과 기록:

```text

```

## 1. OpenTelemetry Collector 배포

```bash
kubectl apply -f spec/04-otel-collector.yaml
kubectl -n "$LAB_NS" rollout status deployment/otel-collector --timeout=5m
kubectl -n "$LAB_NS" get pods,svc -l app=otel-collector -o wide
```

실행 결과 기록:

```text
NAME                                 READY   STATUS    RESTARTS   AGE   IP           NODE                               NOMINATED NODE   READINESS GATES
pod/otel-collector-5868b886d-fq4vc   1/1     Running   0          10s   10.244.2.5   aks-userpool-12452904-vmss000001   <none>           <none>

NAME                     TYPE        CLUSTER-IP    EXTERNAL-IP   PORT(S)                      AGE   SELECTOR
service/otel-collector   ClusterIP   10.1.222.28   <none>        9411/TCP,4317/TCP,4318/TCP   9s    app=otel-collector
```

## 2. CoreDNS trace endpoint를 Collector로 변경

Collector Service의 ClusterIP를 사용한다.

```bash
export OTEL_COLLECTOR_CLUSTER_IP=$(kubectl -n "$LAB_NS" get service otel-collector -o jsonpath='{.spec.clusterIP}')
export ZIPKIN_ENDPOINT="http://${OTEL_COLLECTOR_CLUSTER_IP}:9411/api/v2/spans"

echo "$ZIPKIN_ENDPOINT"

envsubst < spec/02-coredns-custom-trace.patch.json.tmpl \
  | tee "$LAB_ARTIFACT_DIR/coredns-custom-trace-collector.patch.json" >/dev/null

kubectl -n kube-system patch configmap coredns-custom \
  --type merge \
  --patch-file "$LAB_ARTIFACT_DIR/coredns-custom-trace-collector.patch.json"

kubectl -n kube-system rollout restart deployment/coredns
kubectl -n kube-system rollout status deployment/coredns --timeout=5m
```

## 3. 샘플 애플리케이션 배포

이 샘플 앱은 요청을 받으면 지정한 hostname을 resolve하고 HTTPS 요청을 보낸다. Python package를 컨테이너 시작 시 설치하므로 첫 기동에 시간이 걸릴 수 있다.

```bash
kubectl apply -f spec/05-otel-dns-client.yaml
kubectl -n "$LAB_NS" rollout status deployment/otel-dns-client --timeout=10m
kubectl -n "$LAB_NS" get pods,svc -l app=otel-dns-client -o wide
```

실행 결과 기록:

```text
NAME                                   READY   STATUS    RESTARTS   AGE   IP             NODE                               NOMINATED NODE   READINESS GATES
pod/otel-dns-client-6558895854-8pt9z   1/1     Running   0          29s   10.244.3.105   aks-userpool-12452904-vmss000002   <none>           <none>

NAME                      TYPE        CLUSTER-IP    EXTERNAL-IP   PORT(S)    AGE   SELECTOR
service/otel-dns-client   ClusterIP   10.1.135.64   <none>        8080/TCP   30s   app=otel-dns-client
```

## 4. 샘플 앱 호출

별도 터미널에서 port-forward를 실행한다.

```bash
kubectl -n "$LAB_NS" port-forward service/otel-dns-client 18080:8080
```

다른 터미널에서 호출한다.

```bash
curl -s 'http://127.0.0.1:18080/resolve-and-call?host=www.microsoft.com' \
  | tee "$LAB_ARTIFACT_DIR/otel-dns-client-response.json"
```

`jq`가 있으면 보기 좋게 확인한다.

```bash
jq . "$LAB_ARTIFACT_DIR/otel-dns-client-response.json"
```

실행 결과 기록:

```text
{
  "host": "www.microsoft.com",
  "addresses": [
    "203.235.96.229",
    "2600:1410:8000:38c::356e",
    "2600:1410:8000:38e::356e"
  ],
  "status_code": 200,
  "elapsed_ms": 382.06
}
```

## 5. Collector log 수집

Collector `debug` exporter 로그는 매우 길다. 원본은 artifact 파일로 저장하고, 문서에는 핵심 필드만 추린 compact summary를 기록한다.

```bash
kubectl -n "$LAB_NS" logs deployment/otel-collector --since=10m \
  > "$LAB_ARTIFACT_DIR/otel-collector-debug.log"

export COLLECTOR_LOG="$LAB_ARTIFACT_DIR/otel-collector-debug.log"
export COLLECTOR_SUMMARY="$LAB_ARTIFACT_DIR/otel-collector-compact-summary.txt"

awk 'BEGIN{RS="ResourceSpans #"; ORS="\n---\n"} /service.name: Str\(otel-dns-client\)|coredns.io\/name: Str\(www.microsoft.com/ {print "ResourceSpans #" $0}' "$COLLECTOR_LOG" \
  | grep -E '^[[:space:]]*(-> service\.name|Trace ID|Parent ID|Name           :|Start time|-> coredns\.io/(name|remote|type|proto|rcode)|-> http\.(method|url|status_code|target|route|host|server_name|scheme)|-> url\.full|-> server\.address)' \
  | sed -E 's/^[[:space:]]+//' \
  | head -200 \
  | tee "$COLLECTOR_SUMMARY"

wc -l "$COLLECTOR_LOG" "$COLLECTOR_SUMMARY"
```

요약 파일만 미리 보려면 다음을 사용한다.

```bash
sed -n '1,120p' "$COLLECTOR_SUMMARY"
```

실행 결과 기록:

```text
원본 로그: artifacts/20260612-101725/otel-collector-debug.log, 8054 lines
요약 로그: artifacts/20260612-101725/otel-collector-compact-summary.txt, 97 lines

CoreDNS DNS trace 예시:
- service.name: aks-coredns
- trace ID: 000000000000000002aee372c92259d5
- span name: servedns
- query: www.microsoft.com.svc.cluster.local.
- client IP: 10.244.3.105
- rcode: NXDOMAIN

Application trace 예시:
- service.name: otel-dns-client
- trace ID: 5f5bf280cad577cf47b7db599f46fc33
- span name: GET /resolve-and-call
- outbound HTTP span: GET https://www.microsoft.com/
- status code: 200
```

## 6. trace ID 비교

Collector log에서 `service.name: aks-coredns` 또는 CoreDNS span으로 보이는 trace와 `service.name: otel-dns-client` trace를 찾아 비교한다.

| 항목                | application trace                                                                                                         | CoreDNS trace                                                                            |
| ------------------- | ------------------------------------------------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------- |
| service name        | `otel-dns-client`                                                                                                         | `aks-coredns`                                                                            |
| trace ID            | `5f5bf280cad577cf47b7db599f46fc33`                                                                                        | `000000000000000002aee372c92259d5`, `00000000000000003f5dd264151d0f1f`                   |
| span name           | `GET /resolve-and-call`, `GET`                                                                                            | `servedns`                                                                               |
| parent ID           | root span은 비어 있음, outbound `GET` span은 `7025309f0283360f`                                                           | root `servedns` span은 비어 있음                                                         |
| timestamp           | `2026-06-12 05:58:28.992308944 +0000 UTC`부터 `05:58:29.005550355 +0000 UTC` 부근                                         | `2026-06-12 05:58:29.000027 +0000 UTC`, `05:58:29.007661 +0000 UTC`                      |
| hostname/query name | request URL: `http://127.0.0.1:18080/resolve-and-call?host=www.microsoft.com`, outbound URL: `https://www.microsoft.com/` | `www.microsoft.com.svc.cluster.local.`, `www.microsoft.com.trace-lab.svc.cluster.local.` |
| client Pod IP       | `otel-dns-client` Pod IP: `10.244.3.105`                                                                                  | `coredns.io/remote=10.244.3.105`                                                         |

판단:

| 질문                                                      | 답                                                                                                                        |
| --------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------- |
| application trace와 CoreDNS trace의 trace ID가 같은가?    | 아니다. application trace ID와 CoreDNS trace ID가 서로 다르다.                                                            |
| CoreDNS span이 application span의 child로 보이는가?       | 아니다. CoreDNS `servedns` span은 `Parent ID`가 비어 있는 root span으로 생성된다.                                         |
| 같은 collector/backend로는 수집 가능한가?                 | 가능하다. application trace는 OTLP receiver로, CoreDNS trace는 Zipkin receiver로 같은 OpenTelemetry Collector에 수집됐다. |
| timestamp + hostname/query name으로 correlation 가능한가? | 가능하다. application request와 CoreDNS query가 `05:58:29` 부근에 겹치고, query name에 `www.microsoft.com`이 포함된다.    |
| client Pod IP로 workload까지 연결 가능한가?               | 가능하다. CoreDNS trace의 `coredns.io/remote=10.244.3.105`가 `otel-dns-client` Pod IP와 일치한다.                         |

## 7. 추가 확인: traceparent 직접 주입

HTTP 요청에는 `traceparent`를 넣을 수 있지만, 일반 UDP/TCP DNS query에는 이 header가 실리지 않는다. 그래도 app trace 쪽 parent가 바뀌는지 확인하려면 다음을 실행한다.

```bash
curl -s \
  -H 'traceparent: 00-11111111111111111111111111111111-2222222222222222-01' \
  'http://127.0.0.1:18080/resolve-and-call?host=www.microsoft.com' \
  | tee "$LAB_ARTIFACT_DIR/otel-dns-client-traceparent-response.json"

kubectl -n "$LAB_NS" logs deployment/otel-collector --since=5m \
  | tee "$LAB_ARTIFACT_DIR/otel-collector-after-traceparent.log"
```

확인 포인트:

- application trace가 주입한 trace ID를 사용하는지 확인한다.
- CoreDNS trace가 같은 trace ID를 사용하는지 확인한다.

실행 결과 기록:

```text
HTTP traceparent 주입 요청 결과:
{"host":"www.microsoft.com","addresses":["203.235.96.229","2600:1410:8000:38c::356e","2600:1410:8000:38e::356e"],"status_code":200,"elapsed_ms":172.9}

Application trace:
- service.name: otel-dns-client
- trace ID: 11111111111111111111111111111111
- root span: GET /resolve-and-call
- root parent ID: 2222222222222222
- outbound span: GET https://www.microsoft.com/
- outbound parent ID: b54c82d798a3a829

CoreDNS trace:
- service.name: aks-coredns
- trace ID: 00000000000000003f464dc72582b90e
- span name: servedns
- parent ID: empty
- query name: www.microsoft.com.
- client IP: 10.244.3.105
- rcode: NOERROR

판단:
- HTTP 요청으로 주입한 traceparent는 application trace에는 반영됐다.
- 같은 요청 시점에 발생한 CoreDNS trace는 주입한 trace ID를 사용하지 않았다.
- CoreDNS servedns span은 여전히 별도 root trace로 생성됐다.

```

## 중간 결론 기록

```text
Application trace와 CoreDNS trace의 trace ID 연결 여부:
연결되지 않는다. Application trace ID와 CoreDNS trace ID가 서로 다르고, CoreDNS servedns span은 Parent ID가 비어 있는 별도 root span으로 생성된다.

같은 collector/backend 수집 가능 여부:
가능하다. Application trace는 OTLP receiver로, CoreDNS trace는 Zipkin receiver로 같은 OpenTelemetry Collector에 수집할 수 있다. 다만 같은 collector에 들어온다는 것이 같은 trace tree로 합쳐진다는 의미는 아니다.

현실적인 correlation key:
timestamp, client Pod IP, query name, Kubernetes workload metadata가 현실적인 correlation key다. 이번 실험에서는 CoreDNS trace의 coredns.io/remote=10.244.3.105가 otel-dns-client Pod IP와 일치했고, coredns.io/name에 www.microsoft.com 관련 DNS query가 남았다.

추가로 확인할 점:
운영 수준에서는 k8sattributesprocessor로 Pod IP를 namespace/pod/deployment metadata로 enrichment하고, backend에서 time window + workload metadata + query name 기준으로 자동 correlation query/dashboard를 구성하는 방식을 검토한다. 단일 요청 단위의 정확한 매칭이 필요하면 짧은 구간에서 every 1 sampling 또는 application 내부 DNS lookup span 추가를 검토한다.
```

## 8. 자동 trace tree correlation 판단

현재 구성 그대로는 application trace와 CoreDNS trace가 자동으로 같은 trace tree로 correlation되지는 않는다.

실험에서 확인한 trace ID는 다음과 같이 서로 다르다.

```text
Application trace ID:
5f5bf280cad577cf47b7db599f46fc33

CoreDNS trace ID:
000000000000000002aee372c92259d5
00000000000000003f5dd264151d0f1f
```

또한 CoreDNS `servedns` span은 `Parent ID`가 비어 있는 root span으로 생성됐다. 즉 CoreDNS span이 application span의 child로 붙은 흔적은 없다.

이유는 trace context carrier가 다르기 때문이다. Application trace는 W3C Trace Context 기준으로 `traceparent` 같은 HTTP header를 통해 trace ID를 전파한다. 반면 AKS Pod의 일반 DNS 요청은 UDP/TCP DNS packet으로 CoreDNS에 전달되며, 이 DNS packet에는 HTTP header carrier가 없다. 그래서 application span context가 CoreDNS trace plugin까지 자동으로 전달되지 않는다.

CoreDNS trace plugin 코드상으로도 Zipkin 경로에서는 DoH 요청일 때만 `dnsserver.HTTPRequestKey{}`에서 원본 HTTP request를 꺼내고, 그 HTTP header에서 OpenTracing context를 extract한다. `HTTPRequestKey`도 DNS-over-HTTPS 처리 시 HTTP request를 context에 넣기 위한 key다. AKS 기본 kube-dns 경로는 DoH가 아니라 일반 UDP/TCP DNS이므로 이 경로를 타지 않는다.

따라서 이 실험의 결론은 다음과 같다.

```text
CoreDNS trace plugin과 application OpenTelemetry trace는 AKS 기본 UDP/TCP DNS 경로에서 자동으로 같은 trace tree로 이어지지 않는다.

자동화 가능한 것은 trace ID propagation이 아니라 timestamp + client Pod IP + query name + Kubernetes metadata 기반의 correlation view다.
```

다음 단계: [05-dns-protocol-trace-context-adoption.md](05-dns-protocol-trace-context-adoption.md)
