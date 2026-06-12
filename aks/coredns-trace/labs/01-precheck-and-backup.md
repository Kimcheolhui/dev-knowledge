# 01. Precheck and Backup

이 실습은 CoreDNS `trace` 적용 전에 현재 클러스터와 CoreDNS 상태를 기록하고, 롤백에 필요한 ConfigMap을 백업한다.

## 목표

- 현재 kube context와 노드 상태를 기록한다.
- CoreDNS 이미지와 `trace` plugin 포함 여부를 기록한다.
- `coredns`, `coredns-custom`, CoreDNS deployment yaml을 백업한다.
- AKS 기본 Corefile의 plugin chain과 `custom/*.override`, `custom/*.server` import 위치를 확인한다.

## 0. 공통 변수 설정

```bash
cd /home/cheolhuikim/studyspace/dev-knowledge/aks/coredns-trace/labs

export LAB_NS=trace-lab
export LAB_RUN_ID=$(date +%Y%m%d-%H%M%S)
export LAB_ARTIFACT_DIR="$PWD/artifacts/$LAB_RUN_ID"

mkdir -p "$LAB_ARTIFACT_DIR"
echo "$LAB_ARTIFACT_DIR"
```

실행 결과 기록:

```text
/home/cheolhuikim/studyspace/dev-knowledge/aks/coredns-trace/labs/artifacts/20260612-101725
```

## 1. 클러스터 context 확인

```bash
kubectl config current-context
kubectl get nodes -o wide
```

실행 결과 기록:

```text
cheolhuikim@Cheolhui:~/studyspace/dev-knowledge/aks/coredns-trace/labs$ kubectl config current-context
aks-kc-trace-01
cheolhuikim@Cheolhui:~/studyspace/dev-knowledge/aks/coredns-trace/labs$ kubectl get nodes -o wide
NAME                                STATUS   ROLES    AGE   VERSION   INTERNAL-IP   EXTERNAL-IP   OS-IMAGE             KERNEL-VERSION     CONTAINER-RUNTIME
aks-agentpool-12452904-vmss000000   Ready    <none>   18h   v1.35.5   10.0.1.4      <none>        Ubuntu 24.04.4 LTS   6.8.0-1056-azure   containerd://2.1.7-2
aks-agentpool-12452904-vmss000001   Ready    <none>   18h   v1.35.5   10.0.1.5      <none>        Ubuntu 24.04.4 LTS   6.8.0-1056-azure   containerd://2.1.7-2
aks-agentpool-12452904-vmss000002   Ready    <none>   18h   v1.35.5   10.0.1.6      <none>        Ubuntu 24.04.4 LTS   6.8.0-1056-azure   containerd://2.1.7-2
aks-userpool-12452904-vmss000000    Ready    <none>   18h   v1.35.5   10.0.1.7      <none>        Ubuntu 24.04.4 LTS   6.8.0-1056-azure   containerd://2.1.7-2
aks-userpool-12452904-vmss000001    Ready    <none>   18h   v1.35.5   10.0.1.9      <none>        Ubuntu 24.04.4 LTS   6.8.0-1056-azure   containerd://2.1.7-2
aks-userpool-12452904-vmss000002    Ready    <none>   18h   v1.35.5   10.0.1.8      <none>        Ubuntu 24.04.4 LTS   6.8.0-1056-azure   containerd://2.1.7-2
```

## 2. CoreDNS 이미지 확인

```bash
kubectl -n kube-system get deployment coredns \
  -o jsonpath='{.spec.template.spec.containers[0].image}{"\n"}'
```

실행 결과 기록:

```text
mcr.microsoft.com/oss/v2/kubernetes/coredns:v1.13.1-9
```

## 3. CoreDNS plugin 목록에서 trace 확인

```bash
kubectl -n kube-system exec deployment/coredns -c coredns -- \
  coredns -plugins | tr ' ' '\n' | sort
```

실행 결과 기록:

```text
acl
any
auto
autopath
azure
bind
bufsize
cache
cancel
chaos
clouddns
debug
dns64
dnssec
dnstap
erratic
errors
etcd
file
forward
geoip
grpc
header
health
hosts
k8s_external
kubernetes
loadbalance
local
log
loop
metadata
minimal
multisocket
nomad
nsid
on
pprof
prometheus
quic
ready
reload
rewrite
root
route53
secondary
sign
template
timeouts
tls
trace
transfer
tsig
view
whoami
```

## 4. CoreDNS 관련 리소스 백업

```bash
kubectl -n kube-system get configmap coredns -o yaml \
  | tee "$LAB_ARTIFACT_DIR/coredns.yaml" >/dev/null

kubectl -n kube-system get deployment coredns -o yaml \
  | tee "$LAB_ARTIFACT_DIR/coredns-deployment.yaml" >/dev/null

if kubectl -n kube-system get configmap coredns-custom >/dev/null 2>&1; then
  kubectl -n kube-system get configmap coredns-custom -o yaml \
    | tee "$LAB_ARTIFACT_DIR/coredns-custom.yaml" >/dev/null
  echo "coredns-custom existed" | tee "$LAB_ARTIFACT_DIR/coredns-custom-existence.txt"
else
  echo "coredns-custom not found" | tee "$LAB_ARTIFACT_DIR/coredns-custom-existence.txt"
fi

ls -l "$LAB_ARTIFACT_DIR"
```

백업 파일 위치:

```text
cheolhuikim@Cheolhui:~/studyspace/dev-knowledge/aks/coredns-trace/labs$ ls -l "$LAB_ARTIFACT_DIR"
total 24
-rw-r--r-- 1 cheolhuikim cheolhuikim   23 Jun 12 10:24 coredns-custom-existence.txt
-rw-r--r-- 1 cheolhuikim cheolhuikim  326 Jun 12 10:24 coredns-custom.yaml
-rw-r--r-- 1 cheolhuikim cheolhuikim 9413 Jun 12 10:24 coredns-deployment.yaml
-rw-r--r-- 1 cheolhuikim cheolhuikim 1951 Jun 12 10:24 coredns.yaml
```

## 5. Corefile 전체 확인

`trace`를 활성화하기 전에 현재 Corefile에 어떤 plugin이 어떤 순서로 적용되어 있는지 기록한다.

```bash
kubectl -n kube-system get configmap coredns -o jsonpath='{.data.Corefile}' \
  | tee "$LAB_ARTIFACT_DIR/coredns-corefile.txt"
```

실행 결과 기록:

```text
.:53 {
    errors
    ready
    health {
      lameduck 5s
    }
    kubernetes cluster.local in-addr.arpa ip6.arpa {
      pods insecure
      fallthrough in-addr.arpa ip6.arpa
      ttl 30
    }
    prometheus :9153
    forward . /etc/resolv.conf
    cache 30
    loop
    reload
    loadbalance
    import custom/*.override
    template ANY ANY internal.cloudapp.net {
      match "^(?:[^.]+\.){4,}internal\.cloudapp\.net\.$"
      rcode NXDOMAIN
      fallthrough
    }
    template ANY ANY reddog.microsoft.com {
      rcode NXDOMAIN
    }
}
import custom/*.server
```

확인 포인트:

- 기본 plugin chain에는 `errors`, `ready`, `health`, `kubernetes`, `prometheus`, `forward`, `cache`, `loop`, `reload`, `loadbalance`, `template` 등이 적용되어 있다.
- `import custom/*.override`는 main server block 내부, `loadbalance` 다음에 있다.
- `import custom/*.server`는 main server block 밖에 있다.

## 6. Corefile import 지점 확인

```bash
kubectl -n kube-system get configmap coredns \
  -o jsonpath='{.data.Corefile}' \
  | grep -E 'import custom/.*(override|server)'
```

기대 결과:

- `import custom/*.override`
- `import custom/*.server`

실행 결과 기록:

```text
import custom/*.override
import custom/*.server
```

## 7. CoreDNS baseline 상태 확인

```bash
kubectl -n kube-system get pods -l k8s-app=kube-dns -o wide
kubectl -n kube-system logs deployment/coredns --tail=50 \
  | tee "$LAB_ARTIFACT_DIR/coredns-baseline.log"
```

실행 결과 기록:

```text
NAME                      READY   STATUS    RESTARTS   AGE   IP             NODE                                NOMINATED NODE   READINESS GATES
coredns-97979b585-2v5wh   1/1     Running   0          19h   10.244.5.94    aks-userpool-12452904-vmss000000    <none>           <none>
coredns-97979b585-c6pcs   1/1     Running   0          19h   10.244.0.254   aks-agentpool-12452904-vmss000001   <none>           <none>
Found 2 pods, using pod/coredns-97979b585-2v5wh
[WARNING] No files matching import glob pattern: custom/*.override
[WARNING] No files matching import glob pattern: custom/*.server
[WARNING] No files matching import glob pattern: custom/*.override
[WARNING] No files matching import glob pattern: custom/*.server
[WARNING] No files matching import glob pattern: custom/*.override
[WARNING] No files matching import glob pattern: custom/*.server
[WARNING] No files matching import glob pattern: custom/*.override
[WARNING] No files matching import glob pattern: custom/*.server
[WARNING] No files matching import glob pattern: custom/*.override
[WARNING] No files matching import glob pattern: custom/*.server
[WARNING] No files matching import glob pattern: custom/*.override
[WARNING] No files matching import glob pattern: custom/*.server
[WARNING] No files matching import glob pattern: custom/*.override
[WARNING] No files matching import glob pattern: custom/*.server
[WARNING] No files matching import glob pattern: custom/*.override
[WARNING] No files matching import glob pattern: custom/*.server
[WARNING] No files matching import glob pattern: custom/*.override
[WARNING] No files matching import glob pattern: custom/*.server
[WARNING] No files matching import glob pattern: custom/*.override
[WARNING] No files matching import glob pattern: custom/*.server
[WARNING] No files matching import glob pattern: custom/*.override
[WARNING] No files matching import glob pattern: custom/*.server
[WARNING] No files matching import glob pattern: custom/*.override
[WARNING] No files matching import glob pattern: custom/*.server
[WARNING] No files matching import glob pattern: custom/*.override
[WARNING] No files matching import glob pattern: custom/*.server
[WARNING] No files matching import glob pattern: custom/*.override
[WARNING] No files matching import glob pattern: custom/*.server
[WARNING] No files matching import glob pattern: custom/*.override
[WARNING] No files matching import glob pattern: custom/*.server
[WARNING] No files matching import glob pattern: custom/*.override
[WARNING] No files matching import glob pattern: custom/*.server
[WARNING] No files matching import glob pattern: custom/*.override
[WARNING] No files matching import glob pattern: custom/*.server
[WARNING] No files matching import glob pattern: custom/*.override
[WARNING] No files matching import glob pattern: custom/*.server
[WARNING] No files matching import glob pattern: custom/*.override
[WARNING] No files matching import glob pattern: custom/*.server
[WARNING] No files matching import glob pattern: custom/*.override
[WARNING] No files matching import glob pattern: custom/*.server
[WARNING] No files matching import glob pattern: custom/*.override
[WARNING] No files matching import glob pattern: custom/*.server
[WARNING] No files matching import glob pattern: custom/*.override
[WARNING] No files matching import glob pattern: custom/*.server
[WARNING] No files matching import glob pattern: custom/*.override
[WARNING] No files matching import glob pattern: custom/*.server
[WARNING] No files matching import glob pattern: custom/*.override
[WARNING] No files matching import glob pattern: custom/*.server
[WARNING] No files matching import glob pattern: custom/*.override
[WARNING] No files matching import glob pattern: custom/*.server
```

## 체크포인트

| 항목                                   | 결과 |
| -------------------------------------- | ---- |
| 현재 kube context 확인                 | 정상 |
| CoreDNS 이미지 확인                    | 정상 |
| `trace` plugin 확인                    | 정상 |
| `coredns` ConfigMap 백업               | 정상 |
| `coredns-custom` 백업 또는 미존재 확인 | 정상 |
| Corefile 전체 확인                     | 정상 |
| Corefile import 확인                   | 정상 |
| CoreDNS baseline 정상                  | 정상 |

다음 단계: [02-enable-trace-with-zipkin.md](02-enable-trace-with-zipkin.md)
