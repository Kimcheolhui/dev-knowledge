# 02. Verify ndots behavior

이 실습은 같은 Service FQDN을 세 가지 방식으로 조회하고, CoreDNS log와 필요 시 Zipkin trace에서 query 이름 차이를 확인한다.

## 목표

1. 기본 `ndots:5` client에서 trailing dot 없이 조회하면 search suffix query가 생성되는지 확인한다.
2. trailing dot을 붙이면 search suffix query가 사라지는지 확인한다.
3. `ndots:1` client에서 trailing dot 없이 조회해도 먼저 절대 이름으로 조회되는지 확인한다.

## 0. 변수 설정

```bash
cd /home/cheolhuikim/studyspace/dev-knowledge/aks/coredns-lab/ndots/labs

export LAB_NS=ndots-lab
export LAB_RUN_ID=${LAB_RUN_ID:-$(date +%Y%m%d-%H%M%S)}
export LAB_ARTIFACT_DIR="$PWD/artifacts/$LAB_RUN_ID"

export COREDNS_NS=kube-system
export COREDNS_LABEL='k8s-app=kube-dns'

export TARGET_NAME="ndots-target.${LAB_NS}.svc.cluster.local"
export TARGET_URL="http://${TARGET_NAME}/"
export TARGET_URL_DOT="http://${TARGET_NAME}./"

export ZIPKIN_NS=trace-lab
export ZIPKIN_SERVICE=zipkin
export ZIPKIN_LOCAL_PORT=9411
export COREDNS_TRACE_SERVICE=aks-coredns

mkdir -p "$LAB_ARTIFACT_DIR"
echo "$LAB_ARTIFACT_DIR"
```

실행 결과 기록:

```text

```

## 1. Case 1 - 기본 ndots에서 trailing dot 없이 조회

기본 client의 `/etc/resolv.conf`가 `ndots:5`라면, 점이 4개인 `ndots-target.ndots-lab.svc.cluster.local`도 먼저 search suffix가 붙은 이름으로 조회된다.

```bash
export CASE1_START_UTC=$(date -u +%Y-%m-%dT%H:%M:%SZ)
echo "$CASE1_START_UTC" | tee "$LAB_ARTIFACT_DIR/case1-start-utc.txt"

kubectl -n "$LAB_NS" exec deployment/dns-client-default -- \
  curl -4 -sS --connect-timeout 3 --max-time 5 -o /dev/null \
  -w 'case1 http_code=%{http_code} remote_ip=%{remote_ip}\n' \
  "$TARGET_URL" \
  | tee "$LAB_ARTIFACT_DIR/case1-curl.txt"

kubectl -n "$COREDNS_NS" logs -l "$COREDNS_LABEL" --since-time="$CASE1_START_UTC" --prefix=true \
  | grep -F "$TARGET_NAME" \
  | tee "$LAB_ARTIFACT_DIR/case1-coredns.log" \
  || true

awk -F'"' 'NF > 1 {print $2}' "$LAB_ARTIFACT_DIR/case1-coredns.log" \
  | awk '{print $3}' \
  | sort \
  | uniq -c \
  | tee "$LAB_ARTIFACT_DIR/case1-query-summary.txt"
```

실행 결과 기록:

```text
      1 ndots-target.ndots-lab.svc.cluster.local.
      1 ndots-target.ndots-lab.svc.cluster.local.4bbzk525ohhuvj2r35l3z53jpc.syx.internal.cloudapp.net.
      1 ndots-target.ndots-lab.svc.cluster.local.cluster.local.
      1 ndots-target.ndots-lab.svc.cluster.local.ndots-lab.svc.cluster.local.
      1 ndots-target.ndots-lab.svc.cluster.local.svc.cluster.local.
```

판단 기준:

```text
아래와 비슷한 search suffix query가 보이면 ndots 이슈가 실제로 발생한 것이다.

ndots-target.ndots-lab.svc.cluster.local.ndots-lab.svc.cluster.local.
ndots-target.ndots-lab.svc.cluster.local.svc.cluster.local.
ndots-target.ndots-lab.svc.cluster.local.cluster.local.
ndots-target.ndots-lab.svc.cluster.local.
```

## 2. Case 2 - 기본 ndots에서 trailing dot을 붙여 조회

같은 client에서 이름 끝에 `.`을 붙인다. trailing dot은 이 이름이 절대 DNS 이름이라는 뜻이므로 search suffix 확장이 없어야 한다.

```bash
export CASE2_START_UTC=$(date -u +%Y-%m-%dT%H:%M:%SZ)
echo "$CASE2_START_UTC" | tee "$LAB_ARTIFACT_DIR/case2-start-utc.txt"

kubectl -n "$LAB_NS" exec deployment/dns-client-default -- \
  curl -4 -sS --connect-timeout 3 --max-time 5 -o /dev/null \
  -w 'case2 http_code=%{http_code} remote_ip=%{remote_ip}\n' \
  "$TARGET_URL_DOT" \
  | tee "$LAB_ARTIFACT_DIR/case2-curl.txt"

kubectl -n "$COREDNS_NS" logs -l "$COREDNS_LABEL" --since-time="$CASE2_START_UTC" --prefix=true \
  | grep -F "$TARGET_NAME" \
  | tee "$LAB_ARTIFACT_DIR/case2-coredns.log" \
  || true

awk -F'"' 'NF > 1 {print $2}' "$LAB_ARTIFACT_DIR/case2-coredns.log" \
  | awk '{print $3}' \
  | sort \
  | uniq -c \
  | tee "$LAB_ARTIFACT_DIR/case2-query-summary.txt"
```

실행 결과 기록:

```text
      1 ndots-target.ndots-lab.svc.cluster.local.
```

판단 기준:

```text
query summary에 아래 이름만 보이면 trailing dot으로 ndots search 확장이 제거된 것이다.

ndots-target.ndots-lab.svc.cluster.local.
```

## 3. Case 3 - ndots 값을 낮춘 Pod에서 trailing dot 없이 조회

이번에는 `dnsConfig.options.ndots: "1"`로 만든 client에서 trailing dot 없이 같은 URL을 조회한다. 이름에 점이 이미 4개 있으므로 `ndots:1` 기준에서는 먼저 절대 이름으로 조회해야 한다.

```bash
kubectl -n "$LAB_NS" exec deployment/dns-client-ndots1 -- cat /etc/resolv.conf \
  | tee "$LAB_ARTIFACT_DIR/case3-resolv-ndots1.txt"

export CASE3_START_UTC=$(date -u +%Y-%m-%dT%H:%M:%SZ)
echo "$CASE3_START_UTC" | tee "$LAB_ARTIFACT_DIR/case3-start-utc.txt"

kubectl -n "$LAB_NS" exec deployment/dns-client-ndots1 -- \
  curl -4 -sS --connect-timeout 3 --max-time 5 -o /dev/null \
  -w 'case3 http_code=%{http_code} remote_ip=%{remote_ip}\n' \
  "$TARGET_URL" \
  | tee "$LAB_ARTIFACT_DIR/case3-curl.txt"

kubectl -n "$COREDNS_NS" logs -l "$COREDNS_LABEL" --since-time="$CASE3_START_UTC" --prefix=true \
  | grep -F "$TARGET_NAME" \
  | tee "$LAB_ARTIFACT_DIR/case3-coredns.log" \
  || true

awk -F'"' 'NF > 1 {print $2}' "$LAB_ARTIFACT_DIR/case3-coredns.log" \
  | awk '{print $3}' \
  | sort \
  | uniq -c \
  | tee "$LAB_ARTIFACT_DIR/case3-query-summary.txt"
```

실행 결과 기록:

```text
      1 ndots-target.ndots-lab.svc.cluster.local.
```

판단 기준:

```text
/etc/resolv.conf에 options ndots:1이 보이고,
query summary에는 아래 이름만 보이면 ndots 설정값이 실제 resolver 동작에 반영된 것이다.

ndots-target.ndots-lab.svc.cluster.local.
```

## 4. 세 case 결과 한 번에 비교

```bash
printf '\n## case1 default ndots, no trailing dot\n'
cat "$LAB_ARTIFACT_DIR/case1-query-summary.txt"

printf '\n## case2 default ndots, with trailing dot\n'
cat "$LAB_ARTIFACT_DIR/case2-query-summary.txt"

printf '\n## case3 ndots:1, no trailing dot\n'
cat "$LAB_ARTIFACT_DIR/case3-query-summary.txt"
```

실행 결과 기록:

```text
## case1 default ndots, no trailing dot
      1 ndots-target.ndots-lab.svc.cluster.local.
      1 ndots-target.ndots-lab.svc.cluster.local.4bbzk525ohhuvj2r35l3z53jpc.syx.internal.cloudapp.net.
      1 ndots-target.ndots-lab.svc.cluster.local.cluster.local.
      1 ndots-target.ndots-lab.svc.cluster.local.ndots-lab.svc.cluster.local.
      1 ndots-target.ndots-lab.svc.cluster.local.svc.cluster.local.

## case2 default ndots, with trailing dot
      1 ndots-target.ndots-lab.svc.cluster.local.

## case3 ndots:1, no trailing dot
      1 ndots-target.ndots-lab.svc.cluster.local.
```

최종 판단 기록:

```text
(1) 실제로 ndots 이슈가 발생하는가?


(2) trailing dot을 붙였을 때 ndots 이슈가 해결되는가?


(3) ndots 설정값을 줄였을 때 trailing dot 없이도 실제로 반영되는가?


```

## 5. Zipkin trace에서 세 조건을 바로 확인

CoreDNS `trace` 플러그인과 Zipkin이 [../../trace](../../trace) lab으로 이미 준비되어 있다면, CoreDNS log에서 본 query 이름을 trace에서도 확인할 수 있다.

앞의 Case 1/2/3 실행과 시간이 벌어지면 Zipkin에서 찾기 어려우므로, 이 단계에서는 같은 세 조건을 Zipkin 확인용으로 즉시 한 번씩 다시 실행하고 바로 trace를 조회한다.

> 참고: CoreDNS `trace` 플러그인의 sampling이 `every 1`이 아니면 일부 DNS query가 Zipkin에 안 잡힐 수 있다. 이 경우 CoreDNS log 결과를 기준으로 판단하고, trace까지 정확히 보고 싶으면 trace lab에서 짧은 시간 동안 `every 1`로 낮춘 뒤 이 단계를 다시 실행한다.

### 5.1 Zipkin API 연결 확인

아래 명령은 로컬 `9411` 포트에서 Zipkin이 이미 보이면 그대로 사용하고, 없으면 현재 터미널에서 Zipkin port-forward를 background로 실행한다.

```bash
kubectl -n "$ZIPKIN_NS" get service "$ZIPKIN_SERVICE"

if curl -fsS "http://127.0.0.1:${ZIPKIN_LOCAL_PORT}/api/v2/services" >/dev/null 2>&1; then
  echo "Zipkin is already reachable on 127.0.0.1:${ZIPKIN_LOCAL_PORT}"
else
  kubectl -n "$ZIPKIN_NS" port-forward "service/$ZIPKIN_SERVICE" "${ZIPKIN_LOCAL_PORT}:9411" \
    > "$LAB_ARTIFACT_DIR/zipkin-port-forward.log" 2>&1 &
  export ZIPKIN_PF_PID=$!
  echo "$ZIPKIN_PF_PID" | tee "$LAB_ARTIFACT_DIR/zipkin-port-forward.pid"
fi

curl -sS --retry 10 --retry-delay 1 --retry-connrefused \
  "http://127.0.0.1:${ZIPKIN_LOCAL_PORT}/api/v2/services" \
  | tee "$LAB_ARTIFACT_DIR/zipkin-services.json"
```

실행 결과 기록:

```text

```

### 5.2 Zipkin 확인용 query 3개 즉시 실행

세 조건을 다시 한 번씩 실행하고, 바로 뒤에서 사용할 조회 시간 범위를 함께 저장한다.

```bash
export DEFAULT_CLIENT_IP=$(kubectl -n "$LAB_NS" get pod -l app=dns-client-default -o jsonpath='{.items[0].status.podIP}')
export NDOTS1_CLIENT_IP=$(kubectl -n "$LAB_NS" get pod -l app=dns-client-ndots1 -o jsonpath='{.items[0].status.podIP}')
export ZIPKIN_CASE_START_MS=$(date +%s%3N)
export ZIPKIN_CASE1_SEARCH_NAME="${TARGET_NAME}.${LAB_NS}.svc.cluster.local."
export ZIPKIN_TARGET_ABSOLUTE_NAME="${TARGET_NAME}."

printf 'default_client_ip=%s\nndots1_client_ip=%s\nzipkin_case_start_ms=%s\ncase1_search_name=%s\ntarget_absolute_name=%s\n' \
  "$DEFAULT_CLIENT_IP" "$NDOTS1_CLIENT_IP" "$ZIPKIN_CASE_START_MS" "$ZIPKIN_CASE1_SEARCH_NAME" "$ZIPKIN_TARGET_ABSOLUTE_NAME" \
  | tee "$LAB_ARTIFACT_DIR/zipkin-case-context.txt"

kubectl -n "$LAB_NS" exec deployment/dns-client-default -- \
  curl -4 -sS --connect-timeout 3 --max-time 5 -o /dev/null \
  -w 'zipkin-case1 default ndots, no trailing dot: http_code=%{http_code} remote_ip=%{remote_ip}\n' \
  "$TARGET_URL" \
  | tee "$LAB_ARTIFACT_DIR/zipkin-case1-curl.txt"

kubectl -n "$LAB_NS" exec deployment/dns-client-default -- \
  curl -4 -sS --connect-timeout 3 --max-time 5 -o /dev/null \
  -w 'zipkin-case2 default ndots, with trailing dot: http_code=%{http_code} remote_ip=%{remote_ip}\n' \
  "$TARGET_URL_DOT" \
  | tee "$LAB_ARTIFACT_DIR/zipkin-case2-curl.txt"

kubectl -n "$LAB_NS" exec deployment/dns-client-ndots1 -- \
  curl -4 -sS --connect-timeout 3 --max-time 5 -o /dev/null \
  -w 'zipkin-case3 ndots:1, no trailing dot: http_code=%{http_code} remote_ip=%{remote_ip}\n' \
  "$TARGET_URL" \
  | tee "$LAB_ARTIFACT_DIR/zipkin-case3-curl.txt"

export ZIPKIN_CASE_END_MS=$(date +%s%3N)
export ZIPKIN_LOOKBACK_MS=$((ZIPKIN_CASE_END_MS - ZIPKIN_CASE_START_MS + 120000))
export ZIPKIN_END_MS=$((ZIPKIN_CASE_END_MS + 60000))

printf 'zipkin_case_end_ms=%s\nzipkin_end_ms=%s\nzipkin_lookback_ms=%s\n' \
  "$ZIPKIN_CASE_END_MS" "$ZIPKIN_END_MS" "$ZIPKIN_LOOKBACK_MS" \
  | tee -a "$LAB_ARTIFACT_DIR/zipkin-case-context.txt"
```

실행 결과 기록:

```text
zipkin_case_end_ms=1782268243396
zipkin_end_ms=1782268303396
zipkin_lookback_ms=122948
```

### 5.3 Zipkin API에서 방금 query trace 확인

방금 실행한 시간대만 넉넉하게 조회하고, `ndots-target`이 들어간 CoreDNS `servedns` span만 요약한다.

```bash
curl -sS \
  "http://127.0.0.1:${ZIPKIN_LOCAL_PORT}/api/v2/traces?serviceName=${COREDNS_TRACE_SERVICE}&endTs=${ZIPKIN_END_MS}&lookback=${ZIPKIN_LOOKBACK_MS}&limit=200" \
  | tee "$LAB_ARTIFACT_DIR/zipkin-coredns-traces.json"

grep -o 'ndots-target[^" ,}]*' "$LAB_ARTIFACT_DIR/zipkin-coredns-traces.json" \
  | sort \
  | uniq -c \
  | tee "$LAB_ARTIFACT_DIR/zipkin-ndots-query-summary.txt" \
  || true

if [[ ! -s "$LAB_ARTIFACT_DIR/zipkin-ndots-query-summary.txt" ]]; then
  echo "NO_NDOTS_QUERY_STRING_FOUND: trace sampling 또는 조회 시간 범위 때문에 이번 query가 Zipkin 결과에 없을 수 있다." \
    | tee "$LAB_ARTIFACT_DIR/zipkin-ndots-query-summary.txt"
fi
```

실행 결과 기록:

```text

```

`jq`가 있으면 span 단위로 case를 추정해 더 보기 좋게 확인한다.

```bash
if command -v jq >/dev/null 2>&1; then
  jq -r \
    --arg target "$TARGET_NAME." \
    --arg default_ip "$DEFAULT_CLIENT_IP" \
    --arg ndots1_ip "$NDOTS1_CLIENT_IP" '
      [
        .[][]
        | select(.name == "servedns")
        | select((.tags["coredns.io/name"] // "") | contains("ndots-target"))
        | . as $span
        | ($span.tags["coredns.io/name"] // "-") as $query
        | ($span.tags["coredns.io/remote"] // "-") as $remote
        | {
            case: (if $remote == $default_ip and $query != $target then "case1-search-default"
                   elif $remote == $default_ip and $query == $target then "case1-final-or-case2-default"
                   elif $remote == $ndots1_ip and $query == $target then "case3-ndots1"
                   else "unknown"
                   end),
            traceId: ($span.traceId // "-"),
            spanId: ($span.id // "-"),
            query: $query,
            type: ($span.tags["coredns.io/type"] // "-"),
            rcode: ($span.tags["coredns.io/rcode"] // "-"),
            remote: $remote
          }
      ] as $rows
      | if ($rows | length) == 0 then
          "NO_NDOTS_TRACE_FOUND\ttrace sampling 또는 조회 시간 범위 때문에 이번 query가 Zipkin 결과에 없을 수 있다. CoreDNS log 결과를 기준으로 판단한다."
        else
          (["case", "traceId", "spanId", "query", "type", "rcode", "remote"] | @tsv),
          ($rows[] | [.case, .traceId, .spanId, .query, .type, .rcode, .remote] | @tsv)
        end
    ' "$LAB_ARTIFACT_DIR/zipkin-coredns-traces.json" \
    | tee "$LAB_ARTIFACT_DIR/zipkin-ndots-spans.txt"
else
  echo "jq not found. Use $LAB_ARTIFACT_DIR/zipkin-coredns-traces.json and grep output instead."
fi
```

실행 결과 기록:

```text
case    traceId spanId  query   type    rcode   remote
case1-final-or-case2-default    4c90a9383e8052e2        4c90a9383e8052e2        ndots-target.ndots-lab.svc.cluster.local.       A       NOERROR 10.244.3.198
```

판단 기준:

```text
case1-search-default가 보이면 ndots:5 search suffix query가 Zipkin trace에도 잡힌 것이다.
case1-final-or-case2-default는 기본 Pod에서 실제 Service FQDN으로 끝난 query다. case1의 마지막 query와 case2의 trailing dot query가 같은 이름이므로 trace 이름만으로는 둘을 완전히 분리하기 어렵다.
case3-ndots1이 보이면 ndots:1 Pod에서 trailing dot 없이도 실제 Service FQDN으로 바로 조회한 trace다.
```

### 5.4 Zipkin 결과가 비어 있을 때

Zipkin 결과가 비어 있어도 CoreDNS log 결과가 있으면 이 lab의 세 가지 결론은 판단할 수 있다. Zipkin은 보조 확인 수단으로 본다.

비어 있는 대표 원인은 다음과 같다.

- CoreDNS `trace` 플러그인의 sampling 때문에 해당 DNS query가 trace로 선택되지 않았다.
- `endTs`와 `lookback` 범위 밖의 trace를 조회했다.
- Zipkin 수집 또는 저장 지연 때문에 바로 조회한 결과에 아직 반영되지 않았다.

이 경우에는 `case1-query-summary.txt`, `case2-query-summary.txt`, `case3-query-summary.txt`를 기준으로 판단한다.

```bash
printf '\n## CoreDNS log summary\n'
printf '\ncase1: default ndots, no trailing dot\n'
cat "$LAB_ARTIFACT_DIR/case1-query-summary.txt"

printf '\ncase2: default ndots, with trailing dot\n'
cat "$LAB_ARTIFACT_DIR/case2-query-summary.txt"

printf '\ncase3: ndots:1, no trailing dot\n'
cat "$LAB_ARTIFACT_DIR/case3-query-summary.txt"
```

실행 결과 기록:

```text
## CoreDNS log summary

case1: default ndots, no trailing dot
      1 ndots-target.ndots-lab.svc.cluster.local.
      1 ndots-target.ndots-lab.svc.cluster.local.4bbzk525ohhuvj2r35l3z53jpc.syx.internal.cloudapp.net.
      1 ndots-target.ndots-lab.svc.cluster.local.cluster.local.
      1 ndots-target.ndots-lab.svc.cluster.local.ndots-lab.svc.cluster.local.
      1 ndots-target.ndots-lab.svc.cluster.local.svc.cluster.local.

case2: default ndots, with trailing dot
      1 ndots-target.ndots-lab.svc.cluster.local.

case3: ndots:1, no trailing dot
      1 ndots-target.ndots-lab.svc.cluster.local.
```

정리할 때는 [03-cleanup.md](03-cleanup.md)의 port-forward 종료 명령을 실행한다.
