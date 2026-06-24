# 01. Prepare ndots lab resources

이 실습은 lab 전용 namespace, 조회 대상 Service, 기본 DNS client, `ndots:1` DNS client를 배포한다.

## 목표

- lab 리소스를 배포한다.
- 기본 Pod와 `ndots:1` Pod의 `/etc/resolv.conf` 차이를 확인한다.
- CoreDNS log 플러그인이 query log를 출력하는지 확인한다.

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

## 1. 현재 kube context 확인

```bash
kubectl config current-context | tee "$LAB_ARTIFACT_DIR/kube-context.txt"
kubectl cluster-info | tee "$LAB_ARTIFACT_DIR/cluster-info.txt"
```

실행 결과 기록:

```text

```

## 2. Lab 리소스 배포

```bash
kubectl apply -f spec/01-ndots-lab.yaml

kubectl -n "$LAB_NS" rollout status deployment/ndots-target --timeout=5m
kubectl -n "$LAB_NS" rollout status deployment/dns-client-default --timeout=5m
kubectl -n "$LAB_NS" rollout status deployment/dns-client-ndots1 --timeout=5m

kubectl -n "$LAB_NS" get pods,svc -o wide | tee "$LAB_ARTIFACT_DIR/lab-resources.txt"
```

실행 결과 기록:

```text
NAME                                    READY   STATUS    RESTARTS   AGE   IP             NODE                                NOMINATED NODE   READINESS GATES
pod/dns-client-default-fc9cbfc7-p67p8   1/1     Running   0          13s   10.244.3.198   aks-userpool-12452904-vmss000002    <none>           <none>
pod/dns-client-ndots1-d745697df-6mwhs   1/1     Running   0          12s   10.244.1.253   aks-agentpool-12452904-vmss000002   <none>           <none>
pod/ndots-target-75b5cbf774-5ll7c       1/1     Running   0          13s   10.244.2.170   aks-userpool-12452904-vmss000001    <none>           <none>

NAME                   TYPE        CLUSTER-IP   EXTERNAL-IP   PORT(S)   AGE   SELECTOR
service/ndots-target   ClusterIP   10.1.57.90   <none>        80/TCP    13s   app=ndots-target
```

## 3. Pod DNS 설정 확인

기본 client는 클러스터 기본값을 그대로 사용한다. AKS 기본값이면 `options ndots:5`가 보여야 한다.

```bash
kubectl -n "$LAB_NS" exec deployment/dns-client-default -- cat /etc/resolv.conf \
  | tee "$LAB_ARTIFACT_DIR/resolv-default.txt"
```

실행 결과 기록:

```text
search ndots-lab.svc.cluster.local svc.cluster.local cluster.local 4bbzk525ohhuvj2r35l3z53jpc.syx.internal.cloudapp.net
nameserver 10.1.0.10
options ndots:5
```

`ndots:1` client는 Pod spec의 `dnsConfig.options`로 값을 낮춘 Pod다.

```bash
kubectl -n "$LAB_NS" exec deployment/dns-client-ndots1 -- cat /etc/resolv.conf \
  | tee "$LAB_ARTIFACT_DIR/resolv-ndots1.txt"
```

실행 결과 기록:

```text
search ndots-lab.svc.cluster.local svc.cluster.local cluster.local 4bbzk525ohhuvj2r35l3z53jpc.syx.internal.cloudapp.net
nameserver 10.1.0.10
options ndots:1
```

판단 기준:

```text
dns-client-default  : options ndots:5 확인
dns-client-ndots1   : options ndots:1 확인
```

## 4. CoreDNS log 확인

이 lab은 CoreDNS `log` 플러그인이 이미 활성화되어 있다고 가정한다. 아래 명령에서 최근 query log가 보이면 준비가 된 상태다.

```bash
kubectl -n "$COREDNS_NS" get pods -l "$COREDNS_LABEL" -o wide \
  | tee "$LAB_ARTIFACT_DIR/coredns-pods.txt"

kubectl -n "$COREDNS_NS" logs -l "$COREDNS_LABEL" --tail=20 --prefix=true \
  | tee "$LAB_ARTIFACT_DIR/coredns-log-tail.txt"
```

실행 결과 기록:

```text
[pod/coredns-7fbc4ff6f5-sxkrx/coredns] [INFO] 10.244.2.86:49120 - 3248 "AAAA IN 6c2a70a7-48e7-4a30-8e28-316cafb3b53e.ods.opinsights.azure.com.cluster.local. udp 93 false 512" NXDOMAIN qr,aa,rd 186 0.000091129s
[pod/coredns-7fbc4ff6f5-sxkrx/coredns] [INFO] 10.244.2.86:49120 - 63155 "A IN 6c2a70a7-48e7-4a30-8e28-316cafb3b53e.ods.opinsights.azure.com.cluster.local. udp 93 false 512" NXDOMAIN qr,aa,rd 186 0.000171586s
[pod/coredns-7fbc4ff6f5-sxkrx/coredns] [INFO] 10.244.2.86:38161 - 29869 "A IN 6c2a70a7-48e7-4a30-8e28-316cafb3b53e.ods.opinsights.azure.com.4bbzk525ohhuvj2r35l3z53jpc.syx.internal.cloudapp.net. udp 132 false 512" NXDOMAIN qr,aa,rd 132 0.000135392s
[pod/coredns-7fbc4ff6f5-sxkrx/coredns] [INFO] 10.244.2.86:38161 - 48040 "AAAA IN 6c2a70a7-48e7-4a30-8e28-316cafb3b53e.ods.opinsights.azure.com.4bbzk525ohhuvj2r35l3z53jpc.syx.internal.cloudapp.net. udp 132 false 512" NXDOMAIN qr,aa,rd 132 0.000207845s
[pod/coredns-7fbc4ff6f5-sxkrx/coredns] [INFO] 10.244.2.86:58156 - 34831 "AAAA IN 6c2a70a7-48e7-4a30-8e28-316cafb3b53e.ods.opinsights.azure.com. udp 79 false 512" NOERROR qr,aa,rd,ra 384 0.000096319s
[pod/coredns-7fbc4ff6f5-sxkrx/coredns] [INFO] 10.244.2.86:58156 - 54541 "A IN 6c2a70a7-48e7-4a30-8e28-316cafb3b53e.ods.opinsights.azure.com. udp 79 false 512" NOERROR qr,aa,rd,ra 346 0.000140652s
[pod/coredns-7fbc4ff6f5-sxkrx/coredns] [INFO] 10.244.4.195:35649 - 58923 "A IN 6c2a70a7-48e7-4a30-8e28-316cafb3b53e.ods.opinsights.azure.com. udp 79 false 512" NOERROR qr,rd,ra 346 0.002556493s
[pod/coredns-7fbc4ff6f5-sxkrx/coredns] [INFO] 10.244.4.195:35649 - 26409 "AAAA IN 6c2a70a7-48e7-4a30-8e28-316cafb3b53e.ods.opinsights.azure.com. udp 79 false 512" NOERROR qr,rd,ra 384 0.007160946s
```

확인 포인트:

```text
CoreDNS log에 "A IN ..." 또는 "AAAA IN ..." 형태의 DNS query line이 보이는가?
```

## 5. Target Service 기본 통신 확인

```bash
kubectl -n "$LAB_NS" exec deployment/dns-client-default -- \
  curl -4 -sS --connect-timeout 3 --max-time 5 -o /dev/null \
  -w 'http_code=%{http_code} remote_ip=%{remote_ip}\n' \
  "$TARGET_URL" \
  | tee "$LAB_ARTIFACT_DIR/target-curl-default.txt"
```

실행 결과 기록:

```text
http_code=200 remote_ip=10.1.57.90
```

판단 기준:

```text
http_code=200 이면 lab target Service와 client 통신이 정상이다.
```
