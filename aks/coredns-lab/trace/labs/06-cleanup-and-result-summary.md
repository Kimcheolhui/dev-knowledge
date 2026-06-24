# 06. Cleanup and result summary

이 실습은 CoreDNS `trace.override`를 제거하고 lab 리소스를 삭제한 뒤, 최종 결론을 기록한다.

## 목표

- `coredns-custom`에서 `trace.override`를 제거한다.
- CoreDNS를 rolling restart한다.
- Zipkin, OpenTelemetry Collector, 테스트 Pod, 샘플 앱을 삭제한다.
- PoC 결과를 보고용 문장으로 정리한다.

## 0. 변수 확인

```bash
cd /home/cheolhuikim/studyspace/dev-knowledge/aks/coredns-trace/labs

export LAB_NS=trace-lab
export LAB_ARTIFACT_DIR='<01 단계에서 만든 artifacts 디렉터리 경로>'
```

실행 결과 기록:

```text

```

## 1. trace.override 제거

```bash
kubectl -n kube-system patch configmap coredns-custom \
  --type json \
  -p='[{"op":"remove","path":"/data/trace.override"}]' \
  || true

kubectl -n kube-system get configmap coredns-custom -o yaml \
  | tee "$LAB_ARTIFACT_DIR/coredns-custom-after-cleanup.yaml"
```

실행 결과 기록:

```text

```

## 2. CoreDNS rolling restart와 DNS 확인

```bash
kubectl -n kube-system rollout restart deployment/coredns
kubectl -n kube-system rollout status deployment/coredns --timeout=5m

kubectl run coredns-trace-cleanup-smoke \
  --rm -i --restart=Never \
  --image=busybox:1.36 \
  -- nslookup kubernetes.default.svc.cluster.local
```

실행 결과 기록:

```text

```

## 3. lab 리소스 삭제

```bash
kubectl delete -f spec/05-otel-dns-client.yaml --ignore-not-found
kubectl delete -f spec/04-otel-collector.yaml --ignore-not-found
kubectl delete -f spec/03-dns-tools.yaml --ignore-not-found
kubectl delete -f spec/01-zipkin.yaml --ignore-not-found
```

실행 결과 기록:

```text

```

## 4. coredns-custom 원복 여부 확인

`01` 단계에서 `coredns-custom not found`였고 지금 ConfigMap이 비어 있다면 삭제해도 된다. 기존에 다른 key가 있었다면 삭제하지 않는다.

```bash
cat "$LAB_ARTIFACT_DIR/coredns-custom-existence.txt"
kubectl -n kube-system get configmap coredns-custom -o yaml || true
```

필요한 경우만 실행한다.

```bash
kubectl -n kube-system delete configmap coredns-custom
kubectl -n kube-system rollout restart deployment/coredns
kubectl -n kube-system rollout status deployment/coredns --timeout=5m
```

실행 결과 기록:

```text

```

## 5. 최종 결과 요약

| 질문                                                                          | 결과 |
| ----------------------------------------------------------------------------- | ---- |
| AKS CoreDNS에 `trace` 설정 적용이 가능했는가?                                 |      |
| CoreDNS rollout 후 DNS resolution은 정상인가?                                 |      |
| Zipkin에 CoreDNS trace가 수집되었는가?                                        |      |
| CoreDNS span에서 query name을 확인할 수 있었는가?                             |      |
| CoreDNS span에서 query type을 확인할 수 있었는가?                             |      |
| CoreDNS span에서 client Pod IP를 확인할 수 있었는가?                          |      |
| CoreDNS span에서 response code를 확인할 수 있었는가?                          |      |
| application trace와 CoreDNS trace ID가 같았는가?                              |      |
| 같은 Collector/backend로 app trace와 CoreDNS trace를 함께 수집할 수 있었는가? |      |
| metadata correlation이 가능해 보이는가?                                       |      |

## 6. 보고용 결론 초안

아래 문장을 실제 결과에 맞게 수정한다.

```text
AKS CoreDNS의 trace plugin은 coredns-custom의 trace.override를 통해 활성화할 수 있었다/없었다.

Zipkin endpoint를 지정한 뒤 CoreDNS를 rolling restart하면 DNS query trace가 Zipkin에 수집되었다/수집되지 않았다.

수집된 CoreDNS span에는 <query name>, <query type>, <protocol>, <client IP>, <rcode>, <duration>을 확인할 수 있었다/없었다.

애플리케이션 OpenTelemetry trace와 CoreDNS trace를 같은 OpenTelemetry Collector로 수집하는 것은 가능했다/불가능했다.

일반 Pod -> CoreDNS UDP/TCP DNS 경로에서는 application trace ID와 CoreDNS trace ID가 동일했다/달랐다.

따라서 application trace와 CoreDNS trace는 하나의 parent-child trace tree로 자동 통합된다고 보기 어렵다/가능하다.

현실적인 분석 방식은 timestamp, query name, client Pod IP, namespace/workload metadata를 기준으로 correlation하는 것이다.
```

## 7. 남은 질문

```text
추가로 확인할 backend:

Application Insights로 보낼 때 필요한 구성:

Azure Managed Grafana에서 보여줄 dashboard 후보:

운영 적용 시 sampling 값 후보:

운영 적용하지 않는다면 대체 관측 방식:
```
