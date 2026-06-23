# 03. Generate DNS queries and inspect CoreDNS traces

이 실습은 테스트 Pod에서 DNS query를 발생시키고, Zipkin에서 CoreDNS `trace` 플러그인이 만든 span의 실제 field를 확인한다.

## 목표

- DNS query를 반복 발생시킨다.
- Zipkin API로 `aks-coredns` service trace를 조회한다.
- trace/span/tag에 어떤 값이 들어오는지 기록한다.

## 0. 변수 확인

```bash
cd /home/cheolhuikim/studyspace/dev-knowledge/aks/coredns-trace/labs

export LAB_NS=trace-lab
export LAB_ARTIFACT_DIR='<01 단계에서 만든 artifacts 디렉터리 경로>'
```

실행 결과 기록:

```text

```

## 1. DNS tools Pod 배포

```bash
kubectl apply -f spec/03-dns-tools.yaml
kubectl -n "$LAB_NS" rollout status deployment/dns-tools --timeout=5m
kubectl -n "$LAB_NS" get pods -l app=dns-tools -o wide
```

실행 결과 기록:

```text
NAME                         READY   STATUS    RESTARTS   AGE   IP             NODE                               NOMINATED NODE   READINESS GATES
dns-tools-59488687b5-jd24n   1/1     Running   0          13s   10.244.3.121   aks-userpool-12452904-vmss000002   <none>           <none>
```

## 2. DNS query 발생

```bash
kubectl -n "$LAB_NS" exec deployment/dns-tools -- sh -c '
for i in $(seq 1 30); do
  dig +short kubernetes.default.svc.cluster.local
  dig +short www.microsoft.com
  dig +short api.github.com
done
'
```

실행 결과 기록:

```text
10.1.0.1
www.microsoft.com-c-3.edgekey.net.
e13678.dscb.akamaiedge.net.
203.235.96.229
20.200.245.245
10.1.0.1
www.microsoft.com-c-3.edgekey.net.
e13678.dscb.akamaiedge.net.
203.235.96.229
20.200.245.245
10.1.0.1
www.microsoft.com-c-3.edgekey.net.
e13678.dscb.akamaiedge.net.
203.235.96.229
20.200.245.245
10.1.0.1
www.microsoft.com-c-3.edgekey.net.
e13678.dscb.akamaiedge.net.
203.235.96.229
20.200.245.245
10.1.0.1
www.microsoft.com-c-3.edgekey.net.
e13678.dscb.akamaiedge.net.
203.235.96.229
20.200.245.245
10.1.0.1
www.microsoft.com-c-3.edgekey.net.
e13678.dscb.akamaiedge.net.
203.235.96.229
20.200.245.245
10.1.0.1
www.microsoft.com-c-3.edgekey.net.
e13678.dscb.akamaiedge.net.
203.235.96.229
20.200.245.245
10.1.0.1
www.microsoft.com-c-3.edgekey.net.
e13678.dscb.akamaiedge.net.
203.235.96.229
20.200.245.245
10.1.0.1
www.microsoft.com-c-3.edgekey.net.
e13678.dscb.akamaiedge.net.
203.235.96.229
20.200.245.245
10.1.0.1
www.microsoft.com-c-3.edgekey.net.
e13678.dscb.akamaiedge.net.
203.235.96.229
20.200.245.245
10.1.0.1
www.microsoft.com-c-3.edgekey.net.
e13678.dscb.akamaiedge.net.
203.235.96.229
20.200.245.245
10.1.0.1
www.microsoft.com-c-3.edgekey.net.
e13678.dscb.akamaiedge.net.
203.235.96.229
20.200.245.245
10.1.0.1
www.microsoft.com-c-3.edgekey.net.
e13678.dscb.akamaiedge.net.
203.235.96.229
20.200.245.245
10.1.0.1
www.microsoft.com-c-3.edgekey.net.
e13678.dscb.akamaiedge.net.
203.235.96.229
20.200.245.245
10.1.0.1
www.microsoft.com-c-3.edgekey.net.
e13678.dscb.akamaiedge.net.
203.235.96.229
20.200.245.245
10.1.0.1
www.microsoft.com-c-3.edgekey.net.
e13678.dscb.akamaiedge.net.
203.235.96.229
20.200.245.245
10.1.0.1
www.microsoft.com-c-3.edgekey.net.
e13678.dscb.akamaiedge.net.
203.235.96.229
20.200.245.245
10.1.0.1
www.microsoft.com-c-3.edgekey.net.
e13678.dscb.akamaiedge.net.
203.235.96.229
20.200.245.245
10.1.0.1
www.microsoft.com-c-3.edgekey.net.
e13678.dscb.akamaiedge.net.
203.235.96.229
20.200.245.245
10.1.0.1
www.microsoft.com-c-3.edgekey.net.
e13678.dscb.akamaiedge.net.
203.235.96.229
20.200.245.245
10.1.0.1
www.microsoft.com-c-3.edgekey.net.
e13678.dscb.akamaiedge.net.
203.235.96.229
20.200.245.245
10.1.0.1
www.microsoft.com-c-3.edgekey.net.
e13678.dscb.akamaiedge.net.
203.235.96.229
20.200.245.245
10.1.0.1
www.microsoft.com-c-3.edgekey.net.
e13678.dscb.akamaiedge.net.
203.235.96.229
20.200.245.245
10.1.0.1
www.microsoft.com-c-3.edgekey.net.
e13678.dscb.akamaiedge.net.
203.235.96.229
20.200.245.245
10.1.0.1
www.microsoft.com-c-3.edgekey.net.
e13678.dscb.akamaiedge.net.
203.235.96.229
20.200.245.245
10.1.0.1
www.microsoft.com-c-3.edgekey.net.
e13678.dscb.akamaiedge.net.
203.235.96.229
20.200.245.245
10.1.0.1
www.microsoft.com-c-3.edgekey.net.
e13678.dscb.akamaiedge.net.
203.235.96.229
20.200.245.245
10.1.0.1
www.microsoft.com-c-3.edgekey.net.
e13678.dscb.akamaiedge.net.
203.235.96.229
20.200.245.245
10.1.0.1
www.microsoft.com-c-3.edgekey.net.
e13678.dscb.akamaiedge.net.
203.235.96.229
20.200.245.245
10.1.0.1
www.microsoft.com-c-3.edgekey.net.
e13678.dscb.akamaiedge.net.
203.235.96.229
20.200.245.245
```

## 3. Zipkin service 목록 확인

`02` 단계의 port-forward가 살아 있어야 한다. 없다면 별도 터미널에서 다시 실행한다.

```bash
kubectl -n "$LAB_NS" port-forward service/zipkin 9411:9411
```

다른 터미널에서 다음을 실행한다.

```bash
curl -s http://127.0.0.1:9411/api/v2/services \
  | tee "$LAB_ARTIFACT_DIR/zipkin-services.json"
```

`jq`가 있으면 보기 좋게 확인한다.

```bash
jq . "$LAB_ARTIFACT_DIR/zipkin-services.json"
```

실행 결과 기록:

```text
["aks-coredns"]
```

## 4. CoreDNS trace 조회

```bash
curl -s 'http://127.0.0.1:9411/api/v2/traces?serviceName=aks-coredns&limit=10' \
  | tee "$LAB_ARTIFACT_DIR/zipkin-aks-coredns-traces.json"
```

`jq`가 있으면 첫 번째 span의 핵심 필드를 확인한다.

```bash
jq '.[0][0] | {traceId, id, parentId, name, kind, timestamp, duration, localEndpoint, remoteEndpoint, tags}' \
  "$LAB_ARTIFACT_DIR/zipkin-aks-coredns-traces.json"
```

실행 결과 기록:

```text
{
  "traceId": "5257cc7a926f75ff",
  "id": "4f0c6312704ac753",
  "parentId": "7330c02c3ebc1062",
  "name": "connect",
  "kind": null,
  "timestamp": 1781229372319531,
  "duration": 1478,
  "localEndpoint": {
    "serviceName": "aks-coredns"
  },
  "remoteEndpoint": null,
  "tags": {
    "peer.address": "168.63.129.16:53"
  }
}
```

## 5. DNS query 관련 tag 확인

| 항목                           | 확인 값                                                            |
| ------------------------------ | ------------------------------------------------------------------ |
| service name                   | `aks-coredns`                                                      |
| span name                      | `servedns`                                                         |
| trace ID 예시                  | `241ac4b4ee0b6d68`                                                 |
| span ID 예시                   | `241ac4b4ee0b6d68`                                                 |
| parent span 존재 여부          | root `servedns` span 기준 `parentId=null`; 하위 plugin span은 존재 |
| query name tag key/value       | `coredns.io/name=api.github.com.`                                  |
| query type tag key/value       | `coredns.io/type=A`                                                |
| protocol tag key/value         | `coredns.io/proto=udp`                                             |
| remote/client IP tag key/value | `coredns.io/remote=10.244.3.121`                                   |
| response code tag key/value    | `coredns.io/rcode=NOERROR`                                         |
| duration 단위/값               | `220` microseconds                                                 |
| error tag 존재 여부            | 없음                                                               |

### CoreDNS trace 해석

CoreDNS `trace` 플러그인으로 보는 trace는 application trace가 아니라 CoreDNS 내부 plugin chain을 DNS query가 어떻게 통과했는지 보여주는 trace다.

대표적으로 다음과 같은 span이 보인다.

```text
servedns
  -> prometheus
  -> errors
  -> loadbalance
  -> cache
  -> template
  -> kubernetes
  -> loop
  -> forward
  -> connect
```

각 span의 의미는 다음과 같이 볼 수 있다.

| span                                                                                        | 의미                                                                                                                                                       |
| ------------------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `servedns`                                                                                  | CoreDNS가 DNS 요청 하나를 받은 root span. DNS query의 name/type/proto/client/rcode tag가 여기에 붙는다.                                                    |
| `prometheus`, `errors`, `loadbalance`, `cache`, `template`, `kubernetes`, `loop`, `forward` | Corefile에 설정된 CoreDNS plugin chain을 요청이 통과한 흔적. 요청 종류와 처리 경로에 따라 보이는 plugin span은 달라질 수 있다.                             |
| `connect`                                                                                   | `forward` plugin이 upstream DNS 서버로 질의를 전달할 때 생기는 하위 span. 예를 들어 `peer.address=168.63.129.16:53`이면 Azure DNS 쪽으로 forward된 것이다. |

따라서 이 trace는 “애플리케이션의 span tree”라기보다 “CoreDNS 입장에서 DNS query가 어떤 plugin을 거쳐 처리됐는지”를 보여준다. 예를 들어 cache에서 처리됐는지, Kubernetes service discovery plugin을 탔는지, 외부 upstream으로 forward됐는지, upstream 연결이 오래 걸렸는지 확인하는 데 유용하다.

## 6. client Pod IP와 trace tag 비교

```bash
kubectl -n "$LAB_NS" get pod -l app=dns-tools -o wide
```

Zipkin span의 remote/client IP가 `dns-tools` Pod IP와 맞는지 비교한다.

실행 결과 기록:

```text
NAME                         READY   STATUS    RESTARTS   AGE     IP             NODE                               NOMINATED NODE   READINESS GATES
dns-tools-59488687b5-jd24n   1/1     Running   0          3h28m   10.244.3.121   aks-userpool-12452904-vmss000002   <none>           <none>
```

## 7. 중간 결론 기록

| 질문                                                         | 답                                                                                                                                                                                                                                                                                  |
| ------------------------------------------------------------ | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| CoreDNS trace가 Zipkin에 수집되는가?                         | 예. Zipkin service 목록에 `aks-coredns`가 보이고, `/api/v2/traces?serviceName=aks-coredns` 조회로 trace가 수집됨을 확인했다.                                                                                                                                                        |
| DNS query 분석에 필요한 field가 충분한가?                    | 부분적으로 충분하다. root `servedns` span에서 `coredns.io/name`, `coredns.io/type`, `coredns.io/proto`, `coredns.io/remote`, `coredns.io/rcode`, `duration`을 확인할 수 있다. 다만 하위 plugin span에는 대부분 tag가 없고, `connect` span은 upstream DNS `peer.address`만 보여준다. |
| client Pod IP를 확인할 수 있는가?                            | 가능하다. `servedns` span의 `coredns.io/remote=10.244.3.121`이 `dns-tools` Pod IP와 일치한다. 따라서 CoreDNS trace에서 client Pod IP를 확인할 수 있다.                                                                                                                              |
| query name과 application hostname을 연결할 수 있어 보이는가? | 가능하다. 최신 trace에서 `coredns.io/name=api.github.com.`, `coredns.io/name=www.microsoft.com.`, `coredns.io/name=kubernetes.default.svc.cluster.local.`처럼 테스트로 발생시킨 query name이 확인됐다.                                                                              |
| 부하/노이즈 관점에서 sampling 조정이 필요한가?               | 상황에 따라 필요하다. 반복 query를 발생시키면 `every 10`에서도 테스트 질의를 확인할 수 있었다. 단일 요청 단위의 정확한 correlation을 보려면 짧은 시간 동안 `every 1`로 낮추거나 client IP/query name/time range로 필터링하는 것이 좋다.                                             |

다음 단계: [03-generate-query-and-inspect-trace-02.md](03-generate-query-and-inspect-trace-02.md)
