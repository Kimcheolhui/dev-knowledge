# 03-02. Generate DNS queries and inspect CoreDNS traces with debug logs

CoreDNS `trace` 문서에는 다음 문장이 있다.

```text
Enable the debug plugin to get logs from the trace plugin.
```

이 실습은 기존 `trace.override`에 `debug` 플러그인을 잠깐 추가하고, DNS query를 발생시킨 뒤 CoreDNS stdout log와 Zipkin trace를 같이 확인한다.

## 0. 변수 확인

```bash
cd /home/cheolhuikim/studyspace/dev-knowledge/aks/coredns-trace/labs

export LAB_NS=trace-lab
export LAB_ARTIFACT_DIR='<01 단계에서 만든 artifacts 디렉터리 경로>'
export TRACE_EVERY=1

mkdir -p "$LAB_ARTIFACT_DIR"

export ZIPKIN_CLUSTER_IP=$(kubectl -n "$LAB_NS" get service zipkin -o jsonpath='{.spec.clusterIP}')
export ZIPKIN_ENDPOINT="http://${ZIPKIN_CLUSTER_IP}:9411/api/v2/spans"

echo "$ZIPKIN_ENDPOINT"
```

## 1. debug / trace plugin 포함 여부 확인

```bash
kubectl -n kube-system exec deployment/coredns -c coredns -- \
  coredns -plugins | tr ' ' '\n' | grep -E '^(debug|trace)$'
```

기대 결과:

```text
debug
trace
```

## 2. coredns-custom에 debug + trace 적용

`debug`는 짧은 테스트 구간에서만 켠다.

```bash
kubectl -n kube-system get configmap coredns-custom >/dev/null 2>&1 \
  || kubectl -n kube-system create configmap coredns-custom

cat > "$LAB_ARTIFACT_DIR/coredns-custom-trace-debug.patch.json" <<EOF
{
  "data": {
    "trace.override": "debug\ntrace zipkin ${ZIPKIN_ENDPOINT} {\n  every ${TRACE_EVERY}\n  service aks-coredns\n}\n"
  }
}
EOF

cat "$LAB_ARTIFACT_DIR/coredns-custom-trace-debug.patch.json"

kubectl -n kube-system patch configmap coredns-custom \
  --type merge \
  --patch-file "$LAB_ARTIFACT_DIR/coredns-custom-trace-debug.patch.json"

kubectl -n kube-system get configmap coredns-custom -o yaml \
  | tee "$LAB_ARTIFACT_DIR/coredns-custom-after-trace-debug.yaml"
```

## 3. CoreDNS 재시작

```bash
kubectl -n kube-system rollout restart deployment/coredns
kubectl -n kube-system rollout status deployment/coredns --timeout=5m
kubectl -n kube-system get pods -l k8s-app=kube-dns -o wide
```

## 4. DNS query 발생

```bash
kubectl apply -f spec/03-dns-tools.yaml
kubectl -n "$LAB_NS" rollout status deployment/dns-tools --timeout=5m

kubectl -n "$LAB_NS" exec deployment/dns-tools -- sh -c '
for i in $(seq 1 30); do
  dig +short kubernetes.default.svc.cluster.local
  dig +short www.microsoft.com
  dig +short api.github.com
done
'
```

## 5. CoreDNS debug log 수집

```bash
kubectl -n kube-system logs -l k8s-app=kube-dns \
  --since=5m \
  --all-containers=true \
  --prefix=true \
  | tee "$LAB_ARTIFACT_DIR/coredns-trace-debug.log"

grep -i -E 'trace|debug|zipkin|span|servedns|connect' \
  "$LAB_ARTIFACT_DIR/coredns-trace-debug.log" \
  | tee "$LAB_ARTIFACT_DIR/coredns-trace-debug-filtered.log" \
  || true
```

## 6. Zipkin trace도 같이 확인

포트포워딩 없이 `dns-tools` Pod 안에서 Zipkin API를 호출한다.

```bash
kubectl -n "$LAB_NS" exec deployment/dns-tools -- \
  curl -s 'http://zipkin:9411/api/v2/services' \
  | tee "$LAB_ARTIFACT_DIR/zipkin-services-after-debug.json"

kubectl -n "$LAB_NS" exec deployment/dns-tools -- \
  curl -s 'http://zipkin:9411/api/v2/traces?serviceName=aks-coredns&limit=3' \
  | tee "$LAB_ARTIFACT_DIR/zipkin-aks-coredns-traces-after-debug.json"
```

## 7. debug 제거 후 trace 설정 복원

`debug`는 process-wide로 debug mode를 켜므로 확인 후 바로 제거한다.

```bash
export TRACE_EVERY=10

envsubst < spec/02-coredns-custom-trace.patch.json.tmpl \
  | tee "$LAB_ARTIFACT_DIR/coredns-custom-trace-after-debug-restore.patch.json" >/dev/null

kubectl -n kube-system patch configmap coredns-custom \
  --type merge \
  --patch-file "$LAB_ARTIFACT_DIR/coredns-custom-trace-after-debug-restore.patch.json"

kubectl -n kube-system rollout restart deployment/coredns
kubectl -n kube-system rollout status deployment/coredns --timeout=5m

kubectl -n kube-system get configmap coredns-custom -o yaml \
  | tee "$LAB_ARTIFACT_DIR/coredns-custom-after-debug-restore.yaml"
```

## 체크포인트

| 항목                                                               | 결과 |
| ------------------------------------------------------------------ | ---- |
| CoreDNS image에 `debug`, `trace` plugin이 포함되어 있는가?         |      |
| `trace.override`에 `debug`와 `trace zipkin ...`가 같이 적용됐는가? |      |
| CoreDNS rollout이 성공했는가?                                      |      |
| DNS query 후 CoreDNS log를 수집했는가?                             |      |
| Zipkin에 `aks-coredns` trace가 계속 수집되는가?                    |      |
| 확인 후 `debug`를 제거하고 trace 설정을 복원했는가?                |      |

다음 단계: [04-application-trace-correlation.md](04-application-trace-correlation.md)
