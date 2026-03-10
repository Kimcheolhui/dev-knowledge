# AKS에서 FQDN의 ndots 이슈

## 개요

Kubernetes 환경, 특히 Azure AKS에서 외부 API를 호출할 때 예상치 못한 지연이나 타임아웃이 발생하는 경우가 있다. 이는 흔히 "ndots issue" 또는 "Kubernetes DNS ndots problem"이라고 불리는 문제로, DNS resolution 과정에서 발생하는 성능 저하가 원인이다. 특히 Private AKS + Azure Firewall + DNS Proxy 환경에서는 실제 장애로 이어질 수 있어 주의가 필요하다.

## ndots란 무엇인가

### 기본 개념

`ndots`는 Linux DNS resolver 옵션으로, `/etc/resolv.conf`의 `options` 섹션에 설정된다.

```
options ndots:5
```

이 설정의 의미는 다음과 같다:

- **DNS 쿼리할 hostname에 dot(`.`)이 몇 개 이상 있어야 "완전한 FQDN"으로 간주할 것인가**
- dot 개수가 `ndots` 값 이상이면: 바로 FQDN으로 DNS lookup 수행
- dot 개수가 `ndots` 값 미만이면: 먼저 search domain을 붙여서 여러 번 lookup 시도

### Kubernetes의 기본 설정

Kubernetes Pod 안의 `/etc/resolv.conf`는 일반적으로 다음과 같이 구성되어 있다:

```
search default.svc.cluster.local svc.cluster.local cluster.local
nameserver 10.1.0.10
options ndots:5
```

Azure AKS의 경우 Azure Private DNS 구조 때문에 다음과 같은 형태로 나타날 수 있다:

```
search default.svc.cluster.local svc.cluster.local cluster.local zkizzqdbcnbejgheh3z4rawvyf.fx.internal.cloudapp.net
nameserver 10.1.0.10
options ndots:5
```

여기서 `zkizzqdbcnbejgheh3z4rawvyf.fx.internal.cloudapp.net`은 Azure VNet DNS suffix로, Azure DHCP가 VM/노드에 자동으로 주입하는 값이다. Azure Virtual Network 내부의 이름 해석에 사용되며, 이 4번째 search domain이 추가됨으로 인해 일반적인 Kubernetes 환경(search domain 3개)보다 실패하는 lookup 시도가 1회 더 많아진다. 즉, Azure AKS에서는 실제 FQDN lookup 전에 **4번의 불필요한 lookup**이 발생하여 다른 클라우드 프로바이더보다 ndots 문제가 더 심각하다.

## 문제가 발생하는 이유

### DNS Lookup 순서의 문제

Go 애플리케이션에서 다음과 같은 외부 API 호출을 한다고 가정하자:

```go
http.Get("https://management.azure.com")
```

hostname: `management.azure.com`의 dot 개수는 2개다.

그런데 Kubernetes의 기본 `ndots:5` 설정에 따르면:
- 2 < 5 → FQDN으로 바로 lookup하지 않음

따라서 resolver는 다음 순서로 DNS lookup을 시도한다:

1. `management.azure.com.default.svc.cluster.local`
2. `management.azure.com.svc.cluster.local`
3. `management.azure.com.cluster.local`
4. `management.azure.com.zkizzqdbcnbejgheh3z4rawvyf.fx.internal.cloudapp.net` (Azure 환경의 경우)
5. `management.azure.com` (실제 FQDN, 마지막에 시도)

즉, Azure AKS 환경에서는 **실제 FQDN lookup 전에 4번 실패**한다 (일반적인 Kubernetes 환경에서는 3번). Azure VNet DNS suffix가 search domain에 추가되어 있기 때문에 불필요한 lookup이 1회 더 발생한다.

### 외부 API 호출의 실제 예시

다음은 일반적인 외부 API endpoint들의 dot 개수다:

| 도메인 | dot 개수 | ndots:5 영향 |
|--------|---------|-------------|
| `api.openai.com` | 2 | 영향 받음 |
| `management.azure.com` | 2 | 영향 받음 |
| `login.microsoftonline.com` | 2 | 영향 받음 |
| `cosmosdb.azure.com` | 2 | 영향 받음 |
| `myacr.azurecr.io` | 2 | 영향 받음 |

대부분의 외부 endpoint가 dot 2~3개를 가지고 있어 `ndots:5` 설정의 영향을 받게 된다.

## 성능 및 안정성 영향

### DNS Timeout과 Retry

각 실패한 lookup은 다음을 유발한다:

1. DNS request 전송
2. Timeout 대기
3. Retry 시도

특히 다음 환경에서는 각 단계의 latency가 크게 증가한다:

- CoreDNS latency가 높은 환경
- Azure Firewall + DNS proxy 구조
- Private DNS + outbound 제한 환경
- NodeLocal DNSCache가 없는 환경

### 실제 증상

다음과 같은 현상이 있으면 ndots 문제일 가능성이 높다:

#### 1. 외부 API 호출 지연
- Azure ARM, OpenAI, CosmosDB 등 외부 SaaS 호출이 느림
- 특히 첫 요청만 느리고 DNS cache 이후 빨라짐

#### 2. Intermittent Timeout
- 무작위로 timeout 발생
- Retry하면 성공하는 경우

#### 3. CoreDNS 부하 증가
- 외부 호출 1번 = DNS query 최대 5번
- 예: 1000 RPS 외부 API 호출 시 → CoreDNS 5000 QPS 발생 가능

#### 4. 서비스 시작 지연
- 애플리케이션 startup 느려짐
- Readiness probe 실패
- AKS control plane connectivity 문제

### Azure AKS 환경에서 더욱 심각한 이유

Private AKS + Azure Firewall + DNS proxy 구조에서는:

```
Pod → CoreDNS → upstream DNS (Azure DNS) → Firewall → DNS filtering → Private DNS resolution
```

모든 hop을 거치기 때문에 lookup latency가 배가된다.

특히:
- Firewall rule mismatch (search domain lookup이 firewall rule과 매칭 안됨)
- DNS proxy에서 delay 발생
- Retry 증가
- Connection failure

같은 문제가 발생할 수 있다.

## 언어별 영향

### 공통점: 모든 언어가 영향을 받는다

대부분의 프로그래밍 언어는 OS resolver를 사용하므로 **ndots 문제는 Go만의 문제가 아니다**. JavaScript, Java, Python 모두 동일하게 영향을 받는다. 다만 각 런타임마다 caching 전략과 resolver 동작이 달라서 체감하는 정도가 다를 뿐이다.

### JavaScript (Node.js)

#### 동작 방식
- `dns.lookup`: OS resolver 사용 (ndots 영향 받음)
- `dns.resolve`: 직접 DNS query (ndots 영향 적음)
- 대부분의 HTTP client는 `dns.lookup` 사용

#### 특징
- Node.js는 **DNS caching이 기본적으로 없음**
- 요청마다 DNS lookup 발생 가능
- CoreDNS 부하 증가

#### 완화 방법
```javascript
// Keep-alive agent 사용으로 connection 재사용
const https = require('https');
const agent = new https.Agent({ 
  keepAlive: true,
  maxSockets: 50
});

// Custom DNS cache 구현
const cachingLookup = require('lookup-dns-cache')();
```

### Java

#### 동작 방식
- JVM이 OS resolver 사용
- 하지만 **JVM DNS cache 존재**

#### 특징
- 기본값: cache forever (보안 설정에 따라 다름)
- 처음 lookup만 느리고 이후 빠름
- TTL 무시하는 경우 stale cache 문제 가능

#### 설정
```properties
# JVM 옵션으로 TTL 조정
networkaddress.cache.ttl=30
networkaddress.cache.negative.ttl=10
```

#### 영향도
- 초기 lookup latency 증가
- CoreDNS 부하 증가
- 하지만 Node나 Go보다는 덜 체감됨

### Python

#### 동작 방식
- OS resolver 사용 (ndots 영향 그대로 받음)
- HTTP client (requests 등): connection pooling과 keepalive로 반복 lookup 감소

#### 특징
```python
import requests

# Session 사용으로 connection 재사용
session = requests.Session()
response = session.get('https://api.example.com')
```

- Async 환경 (aiohttp 등)에서는 DNS lookup 빈도 증가 가능

### Go

#### 왜 Go에서 특히 많이 언급되는가

Go에서 이 문제가 크게 부각되는 이유:
- Microservice 환경에서 많이 사용
- High concurrency 지원
- DNS lookup 빈도 높음
- 기본 DNS cache 없음

#### Go DNS Resolver의 두 가지 모드

Go의 DNS resolver는 환경에 따라 다르게 동작한다:

1. **Pure Go resolver**: 자체 구현
2. **cgo 기반 resolver**: glibc 사용

```bash
# 환경 변수로 제어
GODEBUG=netdns=go    # Pure Go resolver
GODEBUG=netdns=cgo   # cgo resolver
```

두 방식 모두 Kubernetes 환경에서:
- ndots 영향을 받음
- search domain을 그대로 따름

#### 영향을 크게 받는 Go 애플리케이션
- Microservice
- HTTP client
- Agent / sidecar
- Egress checker
- 외부 API를 자주 호출하는 서비스

## 해결 방법

### 1. FQDN에 Trailing Dot 사용

가장 간단한 방법으로, hostname 끝에 `.`을 추가한다:

```go
// Before
http.Get("https://management.azure.com")

// After - trailing dot 추가
http.Get("https://management.azure.com.")
```

**동작 원리:**
- Trailing dot이 있으면 search domain을 건너뛰고 바로 FQDN lookup

**장점:**
- 즉시 적용 가능
- 코드 변경만으로 해결

**단점:**
- 코드 전체를 수정해야 함
- 라이브러리에도 영향
- 모든 endpoint를 찾아서 수정 필요

### 2. ndots 값 낮추기

Pod의 `dnsConfig`에서 ndots 값을 낮춘다:

```yaml
apiVersion: v1
kind: Pod
metadata:
  name: my-app
spec:
  dnsConfig:
    options:
    - name: ndots
      value: "2"  # 또는 "1"
  containers:
  - name: app
    image: myapp:latest
```

**효과:**
- `management.azure.com` (dot 2개) → `ndots:2` 설정으로 바로 lookup

**장점:**
- 애플리케이션 코드 수정 불필요
- 전체 Pod에 일괄 적용 가능

**단점:**
- 클러스터 내부 서비스 호출에 영향 가능
- `ndots:1` 설정 시: dot이 1개 이상인 hostname은 모두 FQDN으로 간주된다. 즉 `myservice.default` (namespace-qualified short name)를 바로 FQDN으로 lookup하므로 해석에 실패한다.
- **ndots:1에서 깨지는 일반적인 패턴:**
  - `myservice.default` — namespace를 지정한 짧은 서비스 참조
  - `myservice.default.svc` — cluster.local이 빠진 부분 FQDN
  - Helm chart에서 `{{ .Release.Name }}-redis` 같은 참조는 dot이 없어 정상 동작하지만, `redis.default` 같은 참조는 실패한다
  - Service mesh 설정에서 partial name으로 서비스를 참조하는 경우
- `ndots:2` 설정 시: `myservice.default` (dot 1개)는 search domain이 붙어 정상 동작한다. 하지만 `myservice.default.svc` (dot 2개)는 FQDN으로 간주되어 실패한다.
- **권장사항:** ndots를 낮출 경우, 모든 내부 서비스 참조를 완전한 FQDN 형식(`myservice.default.svc.cluster.local`)이나 dot이 없는 짧은 이름(`myservice`)으로 통일해야 한다.

**권장 설정:**

많은 production 환경에서 사용하는 값:

```yaml
options:
- name: ndots
  value: "1"  # 외부 API 호출이 많은 경우
```

또는

```yaml
options:
- name: ndots
  value: "2"  # 클러스터 내부 서비스도 많이 사용하는 경우
```

### 3. Deployment 레벨에서 설정

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: my-app
spec:
  template:
    spec:
      dnsConfig:
        options:
        - name: ndots
          value: "2"
      containers:
      - name: app
        image: myapp:latest
```

### 4. NodeLocal DNSCache 사용

NodeLocal DNSCache를 활성화하면 DNS 요청이 node 로컬 cache에서 처리되어 latency를 크게 줄일 수 있다.

#### AKS에서 활성화

AKS에서는 NodeLocal DNSCache가 별도의 managed addon으로 제공되지 않는다. Kubernetes 공식 가이드에 따라 DaemonSet으로 직접 배포해야 한다.

```bash
# NodeLocal DNSCache DaemonSet 배포
# Kubernetes 공식 가이드: https://kubernetes.io/docs/tasks/administer-cluster/nodelocaldns/

# 1. 클러스터의 kube-dns service IP 확인
KUBE_DNS_IP=$(kubectl get svc -n kube-system kube-dns -o jsonpath='{.spec.clusterIP}')

# 2. NodeLocal DNSCache manifest 다운로드 및 적용
curl -sL https://raw.githubusercontent.com/kubernetes/kubernetes/master/cluster/addons/dns/nodelocaldns/nodelocaldns.yaml \
  | sed "s/__PILLAR__LOCAL__DNS__/169.254.20.10/g" \
  | sed "s/__PILLAR__DNS__DOMAIN__/cluster.local/g" \
  | sed "s/__PILLAR__DNS__SERVER__/$KUBE_DNS_IP/g" \
  | kubectl apply -f -
```

Note: GKE에서는 `--addons=NodeLocalDNS` 옵션으로 클러스터 생성 시 활성화할 수 있고, EKS에서도 별도 배포가 필요하다. AKS는 현재 managed addon으로 NodeLocal DNSCache를 제공하지 않으므로 직접 배포해야 한다.

**장점:**
- DNS query latency 감소
- CoreDNS 부하 감소
- Network hop 감소
- Packet loss 영향 감소

### 5. CoreDNS Tuning

CoreDNS의 cache plugin을 튜닝한다:

```yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: coredns
  namespace: kube-system
data:
  Corefile: |
    .:53 {
        errors
        health {
           lameduck 5s
        }
        ready
        kubernetes cluster.local in-addr.arpa ip6.arpa {
           pods insecure
           fallthrough in-addr.arpa ip6.arpa
           ttl 30
        }
        prometheus :9153
        forward . /etc/resolv.conf {
           max_concurrent 1000
        }
        cache 30 {
           success 9984 30
           denial 9984 5
        }
        loop
        reload
        loadbalance
    }
```

**주요 설정:**
- `cache 30`: 30초 동안 DNS 응답 캐싱
- `success 9984 30`: 성공한 응답 최대 9984개를 30초간 캐싱
- `max_concurrent 1000`: 동시 요청 처리 수 증가

## Private AKS + Firewall 환경에서의 고려사항

### DNS 흐름 이해

Private AKS + Azure Firewall 환경의 DNS resolution 흐름:

```
Pod
  ↓
CoreDNS (클러스터 내부 DNS)
  ↓
Azure DNS (또는 Custom DNS)
  ↓
Azure Firewall (DNS Proxy 활성화된 경우)
  ↓
External DNS
```

### ndots가 이 구조에 미치는 영향

1. **불필요한 DNS 요청 증가**
   - 각 단계를 거치는 시간이 배가됨
   - search domain lookup이 firewall rule과 매칭 안됨

2. **Firewall 정책 고려**
   ```
   # 잘못된 접근
   management.azure.com.default.svc.cluster.local → Firewall rule 미매칭
   
   # 올바른 접근
   management.azure.com → Firewall rule 매칭
   ```

3. **Timeout 누적**
   - 각 실패한 lookup마다 timeout
   - Azure Firewall까지 거치면서 delay 누적

### Azure 특화 권장사항

#### 1. Azure 서비스 Endpoint 최적화

```yaml
# Azure 서비스용 ConfigMap
apiVersion: v1
kind: ConfigMap
metadata:
  name: azure-endpoints
data:
  ARM_ENDPOINT: "https://management.azure.com."
  LOGIN_ENDPOINT: "https://login.microsoftonline.com."
  ACR_ENDPOINT: "myacr.azurecr.io."
```

#### 2. Firewall Application Rule 설계

```bash
# FQDN Tag 사용
az network firewall application-rule create \
  --resource-group myResourceGroup \
  --firewall-name myFirewall \
  --collection-name "AKS-Required" \
  --name "Azure-Services" \
  --protocols Https=443 \
  --fqdn-tags AzureKubernetesService AzureResourceManager
```

#### 3. DNS Proxy 설정

Azure Firewall에서 DNS Proxy를 활성화하면 DNS 요청을 firewall을 통해 처리할 수 있다:

```bash
az network firewall update \
  --name myFirewall \
  --resource-group myResourceGroup \
  --enable-dns-proxy true
```

이 경우 ndots 문제가 더욱 중요해진다:
- 모든 DNS 요청이 firewall을 거침
- 불필요한 lookup은 firewall 부하 증가
- DNS proxy latency 추가

## Big Tech의 접근 방식

### Google (GKE)

- NodeLocal DNSCache 강력 권장
- `ndots:1` 사용 권장
- Istio/Envoy를 통한 DNS caching

### Amazon (EKS)

- CoreDNS autoscaling
- `ndots:2` 권장
- VPC DNS resolver 최적화

### Microsoft (AKS)

- NodeLocal DNSCache는 DaemonSet으로 직접 배포 필요 (managed addon 미제공)
- Azure Firewall DNS Proxy 통합
- Private DNS zone 최적화

### 공통 패턴

대부분의 production 환경에서:

1. **ndots 낮춤**: `1` 또는 `2`
2. **Local DNS cache**: 필수
3. **DNS monitoring**: Prometheus + Grafana
4. **Sidecar DNS caching**: Envoy 등 활용

## 트러블슈팅 가이드

### 1. ndots 문제 확인하기

#### Pod에서 resolv.conf 확인

```bash
kubectl exec -it <pod-name> -- cat /etc/resolv.conf
```

예상 출력:
```
search default.svc.cluster.local svc.cluster.local cluster.local
nameserver 10.1.0.10
options ndots:5
```

#### DNS lookup 직접 테스트

```bash
# Pod 내부에서
kubectl exec -it <pod-name> -- sh

# nslookup으로 테스트
nslookup management.azure.com

# dig로 상세 분석
dig management.azure.com
```

### 2. tcpdump로 DNS 트래픽 분석

```bash
# Node에서 DNS 트래픽 캡처
sudo tcpdump -i any -n port 53 -v

# 필터링해서 특정 Pod의 DNS 요청만 보기
sudo tcpdump -i any -n port 53 and host <pod-ip>
```

예상 출력에서 다음을 확인:
```
# 불필요한 search domain lookup들
management.azure.com.default.svc.cluster.local
management.azure.com.svc.cluster.local
management.azure.com.cluster.local
management.azure.com.zkizzqdbcnbejgheh3z4rawvyf.fx.internal.cloudapp.net

# 마지막에 실제 FQDN
management.azure.com
```

### 3. CoreDNS 로그 확인

```bash
# CoreDNS Pod 로그 조회
kubectl logs -n kube-system -l k8s-app=kube-dns

# 실시간 모니터링
kubectl logs -n kube-system -l k8s-app=kube-dns --follow
```

#### CoreDNS 메트릭 확인

```bash
# CoreDNS Prometheus 메트릭
kubectl port-forward -n kube-system svc/kube-dns 9153:9153

# 다른 터미널에서
curl http://localhost:9153/metrics | grep coredns_dns
```

주요 메트릭:
- `coredns_dns_request_count_total`: 총 DNS 요청 수
- `coredns_dns_request_duration_seconds`: 요청 latency
- `coredns_dns_response_rcode_count_total`: 응답 코드별 카운트

### 4. 애플리케이션 레벨 진단

#### Go 애플리케이션

```go
package main

import (
	"bufio"
	"context"
	"fmt"
	"net"
	"os"
	"strings"
	"time"
)

// resolv.conf에서 ndots와 search domain을 파싱한다
func parseResolvConf() (searchDomains []string, ndots int) {
	ndots = 5 // 기본값
	f, err := os.Open("/etc/resolv.conf")
	if err != nil {
		return nil, ndots
	}
	defer f.Close()

	scanner := bufio.NewScanner(f)
	for scanner.Scan() {
		line := strings.TrimSpace(scanner.Text())
		if strings.HasPrefix(line, "search ") {
			searchDomains = strings.Fields(line)[1:]
		}
		if strings.HasPrefix(line, "options ") {
			for _, opt := range strings.Fields(line)[1:] {
				if strings.HasPrefix(opt, "ndots:") {
					fmt.Sscanf(opt, "ndots:%d", &ndots)
				}
			}
		}
	}
	return
}

func countDots(s string) int {
	return strings.Count(s, ".")
}

// 실제 DNS lookup을 수행하면서 각 단계의 latency를 측정한다
func diagnoseDNSLookup(hostname string) {
	searchDomains, ndots := parseResolvConf()
	dots := countDots(hostname)

	fmt.Printf("=== DNS Lookup 진단: %s ===\n", hostname)
	fmt.Printf("resolv.conf: ndots=%d, search domains=%v\n", ndots, searchDomains)
	fmt.Printf("hostname dot 개수: %d\n\n", dots)

	resolver := &net.Resolver{PreferGo: true}

	if dots < ndots {
		fmt.Printf("dot(%d) < ndots(%d) → search domain을 먼저 시도한다\n\n", dots, ndots)
		for i, domain := range searchDomains {
			fqdn := hostname + "." + domain
			start := time.Now()
			addrs, err := resolver.LookupHost(context.Background(), fqdn)
			elapsed := time.Since(start)
			if err != nil {
				fmt.Printf("  [%d] %s → 실패 (%v, %v)\n", i+1, fqdn, elapsed, err)
			} else {
				fmt.Printf("  [%d] %s → 성공 (%v, %v)\n", i+1, fqdn, elapsed, addrs)
			}
		}
	} else {
		fmt.Printf("dot(%d) >= ndots(%d) → 바로 FQDN으로 lookup한다\n\n", dots, ndots)
	}

	start := time.Now()
	addrs, err := resolver.LookupHost(context.Background(), hostname)
	elapsed := time.Since(start)
	if err != nil {
		fmt.Printf("  [FQDN] %s → 실패 (%v, %v)\n", hostname, elapsed, err)
	} else {
		fmt.Printf("  [FQDN] %s → 성공 (%v, %v)\n", hostname, elapsed, addrs)
	}
}

func main() {
	targets := []string{
		"management.azure.com",
		"login.microsoftonline.com",
		"myacr.azurecr.io",
	}
	for _, t := range targets {
		diagnoseDNSLookup(t)
		fmt.Println()
	}
}
```

#### DNS lookup latency가 높을 때

50ms 이상이면 ndots 문제를 의심해볼 수 있다:

```go
if elapsed > 50*time.Millisecond {
    fmt.Println("⚠️  High DNS latency detected - check ndots configuration")
}
```

## 실전 적용 시나리오

### 시나리오 1: Microservice가 외부 API를 많이 호출

#### 상황
- Go로 작성된 microservice
- Azure OpenAI, CosmosDB 등 외부 API 호출
- 첫 요청이 느리고 intermittent timeout 발생

#### 해결책

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: api-service
spec:
  template:
    spec:
      dnsConfig:
        options:
        - name: ndots
          value: "2"
        - name: timeout
          value: "2"
        - name: attempts
          value: "2"
      containers:
      - name: api
        image: myapi:latest
        env:
        - name: GODEBUG
          value: "netdns=go"  # Pure Go resolver 사용
```

#### 효과
- DNS lookup latency 70% 감소
- Timeout 발생 빈도 90% 감소
- 첫 요청 응답 시간 개선

### 시나리오 2: Private AKS + Azure Firewall

#### 상황
- Private AKS cluster
- Azure Firewall을 통한 egress 제어
- Azure ARM, AAD 연결 지연

#### 해결책

1. **ndots 설정 최적화**
```yaml
dnsConfig:
  options:
  - name: ndots
    value: "1"
```

2. **NodeLocal DNSCache 활성화**
```bash
# Kubernetes 공식 가이드에 따라 DaemonSet으로 직접 배포
KUBE_DNS_IP=$(kubectl get svc -n kube-system kube-dns -o jsonpath='{.spec.clusterIP}')
curl -sL https://raw.githubusercontent.com/kubernetes/kubernetes/master/cluster/addons/dns/nodelocaldns/nodelocaldns.yaml \
  | sed "s/__PILLAR__LOCAL__DNS__/169.254.20.10/g" \
  | sed "s/__PILLAR__DNS__DOMAIN__/cluster.local/g" \
  | sed "s/__PILLAR__DNS__SERVER__/$KUBE_DNS_IP/g" \
  | kubectl apply -f -
```

3. **Azure Firewall DNS Proxy 활성화**
```bash
az network firewall update \
  --name myFirewall \
  --resource-group myResourceGroup \
  --enable-dns-proxy true
```

4. **CoreDNS에서 Azure DNS forwarding 설정**
```yaml
.:53 {
    forward . 168.63.129.16  # Azure DNS
    cache 60
}
```

### 시나리오 3: NodeJS 애플리케이션

#### 상황
- NodeJS API server
- 외부 webhook 호출이 많음
- DNS cache가 없어서 매 요청마다 lookup

#### 해결책

```javascript
// app.js
const dns = require('dns');
const { LookupCache } = require('lookup-dns-cache');

// DNS cache 활성화
const dnsCache = new LookupCache({
  ttl: 60,  // 60초 캐싱
  max: 1000 // 최대 1000개 엔트리
});

// HTTP agent 설정
const https = require('https');
const agent = new https.Agent({ 
  keepAlive: true,
  maxSockets: 50,
  lookup: dnsCache.lookup
});

// 사용
const axios = require('axios');
axios.defaults.httpAgent = agent;
```

추가로 Kubernetes 설정:
```yaml
dnsConfig:
  options:
  - name: ndots
    value: "2"
```

## 모니터링 및 알림

### Prometheus Metrics

```yaml
# ServiceMonitor for CoreDNS
apiVersion: monitoring.coreos.com/v1
kind: ServiceMonitor
metadata:
  name: coredns
  namespace: kube-system
spec:
  selector:
    matchLabels:
      k8s-app: kube-dns
  endpoints:
  - port: metrics
    interval: 30s
```

### Grafana Dashboard

주요 메트릭:
- DNS request rate (QPS)
- DNS request duration (P50, P95, P99)
- DNS error rate
- Cache hit ratio

### 알림 규칙

```yaml
# PrometheusRule
apiVersion: monitoring.coreos.com/v1
kind: PrometheusRule
metadata:
  name: coredns-alerts
spec:
  groups:
  - name: coredns
    interval: 30s
    rules:
    - alert: HighDNSLatency
      expr: histogram_quantile(0.99, coredns_dns_request_duration_seconds_bucket) > 0.1
      for: 5m
      labels:
        severity: warning
      annotations:
        summary: "High DNS latency detected"
        description: "P99 DNS latency is above 100ms"
    
    - alert: HighDNSErrorRate
      expr: rate(coredns_dns_response_rcode_count_total{rcode="SERVFAIL"}[5m]) > 10
      for: 5m
      labels:
        severity: critical
      annotations:
        summary: "High DNS error rate"
        description: "DNS SERVFAIL rate is high"
```

## Best Practices 요약

### 애플리케이션 설계

1. **외부 FQDN 호출 시 trailing dot 사용** (가능하면)
2. **Connection pooling과 keep-alive 활성화**
3. **DNS lookup을 가능한 한 캐싱**
4. **Circuit breaker 패턴으로 DNS failure 대응**

### Kubernetes 설정

1. **ndots를 1 또는 2로 낮추기**
   - 외부 API 호출이 많으면: `ndots:1`
   - 클러스터 내부 서비스도 많으면: `ndots:2`

2. **NodeLocal DNSCache 필수 활성화**

3. **CoreDNS tuning**
   - Cache 크기 증가
   - TTL 적절히 설정
   - Forward 설정 최적화

4. **Resource limits 적절히 설정**
```yaml
resources:
  limits:
    memory: 512Mi
    cpu: 500m
  requests:
    memory: 256Mi
    cpu: 100m
```

### Azure AKS 특화

1. **Azure Firewall DNS Proxy 활성화**
2. **Private DNS zone 설계 최적화**
3. **FQDN Tag 적극 활용**
4. **Managed Identity로 Azure 서비스 접근 최적화**

### 모니터링

1. **CoreDNS 메트릭 수집 및 시각화**
2. **DNS latency 알림 설정**
3. **정기적인 DNS 성능 테스트**
4. **Egress connectivity 테스트 자동화**

## 참고 자료

### Kubernetes 공식 문서
- [DNS for Services and Pods](https://kubernetes.io/docs/concepts/services-networking/dns-pod-service/)
- [Customizing DNS Service](https://kubernetes.io/docs/tasks/administer-cluster/dns-custom-nameservers/)
- [Using NodeLocal DNSCache](https://kubernetes.io/docs/tasks/administer-cluster/nodelocaldns/)

### Azure 문서
- [AKS Networking Concepts](https://learn.microsoft.com/en-us/azure/aks/concepts-network)
- [Azure Firewall DNS Settings](https://learn.microsoft.com/en-us/azure/firewall/dns-settings)
- [AKS DNS Configuration Best Practices](https://learn.microsoft.com/en-us/azure/aks/coredns-custom)

### 블로그 및 아티클
- [Kubernetes: An Introduction to the ndots Option](https://mrkaran.dev/posts/ndots-kubernetes/) - ndots 문제를 실제 tcpdump 예시와 함께 설명한 글
- [5 – 15s DNS lookups on Kubernetes?](https://blog.quentin-machu.fr/2018/06/24/5-15s-dns-lookups-on-kubernetes/) - ndots로 인한 DNS 지연 분석
- [Racy conntrack and DNS lookup timeouts](https://www.weave.works/blog/racy-conntrack-and-dns-lookup-timeouts) - conntrack race condition과 DNS timeout의 관계
- [Debugging DNS Resolution](https://kubernetes.io/docs/tasks/administer-cluster/dns-debugging-resolution/) - Kubernetes 공식 DNS 디버깅 가이드

### 관련 GitHub Issues
- [kubernetes/kubernetes#56903](https://github.com/kubernetes/kubernetes/issues/56903) - DNS intermittent delays of 5s
- [kubernetes/kubernetes#62628](https://github.com/kubernetes/kubernetes/issues/62628) - DNS resolution ndots:5 causes unnecessary DNS queries

## 결론

ndots 이슈는 Kubernetes 환경에서 외부 API를 호출하는 모든 애플리케이션에 영향을 미칠 수 있는 중요한 문제다. 특히 Private AKS + Azure Firewall 환경에서는 DNS lookup latency가 배가되어 실제 장애로 이어질 수 있다.

핵심은 **불필요한 search domain lookup을 최소화**하는 것이다. ndots 값을 낮추고, NodeLocal DNSCache를 활성화하며, 애플리케이션 레벨에서 DNS caching을 구현하면 대부분의 문제를 해결할 수 있다.

특히 Go, Node.js 등 DNS caching이 기본으로 없는 런타임을 사용하는 경우 이 문제에 더욱 주의를 기울여야 한다. 적절한 모니터링과 알림 설정을 통해 DNS 관련 문제를 조기에 발견하고 대응하는 것이 중요하다.
