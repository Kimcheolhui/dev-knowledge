# CoreDNS

## Overview

1. CoreDNS가 Kubernetes에서 어떤 역할을 하는가
   - Kubernetes DNS
   - Service와 Pod에 대한 DNS Record를 만들고, kubelet이 각 Pod의 /etc/resolv.conf를 구성
   - Record 생성 경로에 대해서 설명
2. CoreDNS 구조와 특성
   - Go로 작성된 DNS 서버. Go의 특징.
   - 거의 모든 기능을 Plugin으로 구성 → Plugin-chain 기반 구조
   - 기타 특징
3. ## 주요 plugin 설명
4. K8s 내부 DNS query flow
   - Pod → /etc/resolv.conf → kube-dns Service IP → CoreDNS Pod → plugin chain → kubernetes plugin or upstream forward 순서로 설명
   - Application 자체의 DNS? Container나 VM 수준의 DNS가 존재하는지, 개입하는지?
   - Linux OS 자체의 DNS 서버가 개입하나?
5. Trace, metrics, log에 대해서
   - 각각을 어떻게 노출하고 있는지?
   - 어떤 metric이 노출되는지?
   - trace
     - 해보니까 Application Trace와 correlation이 안됨
     - eBPF trace, bpftrace로는 가능한가?
6. 성능, 운영 이슈
   - 성능 저하가 발생되는 조건
     - scaling과 연계해서.
   - LocalDNS, ndots, conntrack, CoreDNS scaling, cache hit/miss, upstream DNS 장애
7. 발전 방향, 대체재, kube-dns 전환 이유
   - CoreDNS 최신 흐름, kube-dns에서 전환된 이유
   - 실질적 대체재는 거의 없다는 결론

## 1. Kubernetes에서 CoreDNS의 역할

Kubernetes 클러스터 내에서 DNS resolver 역할을 수행.

- kube-dns라는 service 이름을 가지고 있고, 일반적으로 별도의 노드에 2개(scaling 가능)의 replicas를 가짐.

모든 Pod가 시작할 때, kubelet이 Pod의 /etc/resolv.conf 파일에 다음과 같은 정보를 넣음.

```yaml
search <namespace>.svc.cluster.local svc.cluster.local cluster.local
nameserver <CoreDNS Service ClusterIP>
options ndots:5
```

그래서 Pod가 이 정보를 통해 CoreDNS SVC ClusterIP로 DNS Query를 날리는 것.

**CoreDNS의 3가지 역할**

1. (방금 얘기했던) Kubernetes Service name(또는 FQDN)을 ClusterIP로 resolving하는 것
   - CoreDNS는 API server를 watching함으로써 Service, EndpointSlice, Namespace, Pod에 대해서 지속적으로 동기화함.
   - 예를 들어서, 새로운 Service가 생성되면 CoreDNS가 그걸 수초 내에 확인해서 해당하는 DNS record를 생성한다.
2. Cluster Resource를 위해 Reverse DNS를 서빙하는 것.
   - Pod IP나 Service ClusterIP를 넣었을 때, CoreDNS가 그 IP에 대응되는 Kubernetes DNS name을 PTR record로 돌려주는 것
   - 언제 쓰는데?
     - 네트워크 디버깅
       - `connection from 10.96.20.30` 이런 로그가 찍혔다고 했을 때
       - `dig -x 10.96.20.30`을 실행해서 `api.default.svc.cluster.local`를 알아낼 수 있음
3. Non-cluster DNS Query를 Upstream Resolvers로 Forwarding하는 것.
   - 뒤에 언급할 Corefile에는 kubernetes zone을 벗어나고 cache hit가 안되는 fqdn에 대해서는 upstream DNS로 forwarding을 수행함.

## 2. CoreDNS 구조와 특성

### (1) Plugin-chain 기반 구조

CoreDNS는 여러 Plugin이 chain처럼 엮어서 동작하는 구조를 가지고 있음.

→ `CoreDNS is powered by plugins`

- 예를 들어, metrics이나 cache plugins이 존재하고, kubernetes와 통신하는 Kubernetes plugin도 존재
- default로 30개의 plugins이 포함되는데, functionality를 확장하기 위한 external plugin들도 다수 존재
  - file이나 db를 백엔드로 사용한다거나
- 플러그인을 작성하는 것 자체도 어렵지는 않다고 하는데, Go언어를 알아야 하고 DNS의 특성을 잘 알아야함

### (2) Go의 Concurrency(동시성) 모델

![e1769566fa.png](./img/./img/e1769566fa.png)

- (요약) CoreDNS는 Go 언어로 작성되었고, Go 언어은 동시성 모델(goroutine)이 내장되어 있어 I/O가 많은 DNS 트래픽 처리에 좋은 성능을 보여준다.
- goroutine: Go 런타임이 관리하는 가벼운 실행 단위
  - OS thread와 비슷해 보이지만 훨씬 가볍다
  - Go 프로그램은 수천, 수만 개의 goroutine을 만들 수 있고, Go 런타임이 이 goroutine들을 실제 OS thread 위에 효율적으로 스케줄링한다.
  - CoreDNS가 DNS 요청을 받을 때마다 무거운 OS thread를 새로 만드는 구조가 아님
- 하나의 DNS 요청은 대략 이런 흐름을 탄다.

  ```markdown
  Pod
  ↓ DNS Query
  CoreDNS
  ↓
  plugin chain 실행
  ↓
  kubernetes plugin / cache plugin / forward plugin 등
  ↓
  DNS Response 반환
  ```

  - 각 요청 하나하나는 CPU보다는 I/O 성격이 강함
    - 메모리 조회, 캐시 조회, upstream DNS 질의 등
  - Go의 goroutine은 이런 workload에 적합
  - 각 goroutine은 독립적으로 plugin chain을 따라가며 DNS response를 만들 수 있고, 하나의 요청이 I/O 작업으로 대기 중인 동안 다른 요청들이 계속 처리될 수 있다.

- DNS 요청은 I/O 중심인 경우가 많기 때문에 I/O block 상황에서도 goroutine을 통해 다른 요청을 계속해서 처리할 수 있어 K8s 클러스터 내부의 대량 DNS 트래픽 처리에 유리하다.
- 동시에 다중 요청을 처리할 수 있으며, 한 플러그인 인스턴스가 여러 고루틴에 의해 동시에 호출될 수 있으므로, 플러그인 코드가 thread-safe해야 한다.
  - 그래서 각 plugin들은 동시에 호출될 수 있다는 가정 하에 plugin 코드들이 작성됨
- 코어 자체는 Event Loop 없이 고루틴으로 요청을 처리하므로, 요청이 많을 경우 CPU 코어 수에 따라 병렬로 처리된다.

## 3. Corefile과 주요 plugin들

### (1) 관여하는 파일들

- CoreDNS는 일반적으로 kube-system 네임스페이스의 `coredns` ConfigMap에 Corefile 구성을 저장
- CoreDNS deployment의 spec을 보면, Pod filesystem의 `/etc/coredns`와 `/etc/coredns/custom`에 각각 ConfigMap `coredns`와 `coredns-custom`가 volumeMount된 것을 확인할 수 있음.
- AKS에서는 이 ConfigMap `coredns-custom`를 통해 default Corefile을 overwrite한다.
  - 여기서 demo

### (2) 기본 구조와 예시

어떤 DNS 요청을 이 서버 블록이 처리할지를 정의하는 구조

```yaml
[SCHEME://]ZONE [:PORT] {
    PLUGIN [ARGUMENTS]
}
```

- `ZONE`
  - 이 서버 블록이 담당할 DNS 이름 영역

    ```yaml
    # 예시 1
    example.org {
        whoami
    }

    # 예시 2
    . {
    		...
    }
    ```

  - 예시 1) CoreDNS가 `example.org` Zone에 대한 DNS 요청을 처리한다는 뜻
  - 예시 2) Zone이 “.”인 경우, DNS root zone을 의미한다.
    - DNS 이름 체계에서 모든 도메인은 사실 마지막에 “.”이 붙어 있음
      - `microsoft.com.`
    - 사실상 모든 DNS 질의를 처리하는 서버 블록

- `SCHEME`
  - 어떤 프로토콜로 DNS 요청을 받을지를 의미
  - 기본값(생략시)은 UDP/TCP 기반 DNS

    ```yaml
    # 예시 1
    dns://.:53{
    		...
    }

    # 예시 2
    .:53 {
        ...
    }

    # 예시 3: DNS-over-HTTP
    https://.:443 {
        ...
    }
    ```

- `PORT`
  - CoreDNS가 listen할 포트 넘버
  - 기본값(생략시)은 53인데, 보통 명시함

```yaml
# AKS의 Default CoreDNS Corefile
.:53 { # 53번 포트로 수신하는 모든 DNS 질의를 처리
        errors
        ready
        health {
          lameduck 5s
        }
        # kubernetes 플러그인이 authoritative하게 처리할 DNS zone을 정의
        kubernetes cluster.local in-addr.arpa ip6.arpa {
          pods insecure
          fallthrough in-addr.arpa ip6.arpa
          ttl 30
        }
        prometheus :9153
        forward . /etc/resolv.conf  # 노드의 기본 /etc/resolv.conf 내 상위 DNS 주소를 읽어와 사용한다는 의미
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

- AKS에서는 CoreDNS Corefile을 직접 수정하는 대신, 전용 ConfigMap으로 기본 설정을 Overwrite하는 방식을 사용
  - AKS가 CoreDNS의 업그레이드 및 가용성을 관리
    - 기본적으로 다른 노드에 스케쥴되어 이중화
    - AKS 클러스터 업그레이드 시 CoreDNS도 함께 최신 버전으로 관리
  - Built-in 플러그인 외에 External 플러그인 사용은 제한
    ![image.png](./img/image.png)

### (3) 주요 플러그인

1. kubernetes
   - Kubernetes 서비스 검색 지원
   - cluster.local 및 클러스터 도메인에 대한 Authoritative DNS 데이터 제공
   - Kubernetes API를 watch하여 Service, EndpointSliace, Pod, Namespace 리소스를 캐시에 유지하고 DNS 레코드로 응답
2. forward
   - 클러스터 외부 도메인의 이름을 상위 DNS 서버에 recursive query하여 non-authoritative 응답을 반환하는 Proxy/Forwarding 플러그인.
   - UDP, TCP, DNS-over-TLS 지원
3. cache
   - 응답 캐싱을 수행하는 플러그인
   - 기본 설정에서는 약 9984개 엔트리까지 메모리 캐시 유지 및 최대 30초 동안 결과 저장
4. loop
   - DNS Forwarding Loop 감지 및 서버 정지를 수행하는 플러그인
     - CoreDNS → systemd-resolved → back to CoreDNS
   - CoreDNS가 자신을 참조하는 무한 루프가 감지될 경우 프로세스를 종료하여 루프 현상 차단
5. reload
   - Corefile 변경사항 감지 시 자동 재적용(Hot-reload)하는 플러그인
   - 약 30초마다 ConfigMap(Corefile)의 SHA512 해시를 점검하여 변경이 있으면 코어 서버를 재시작하지 않고 새로운 플러그인 체인을 로드하여 설정을 적용
6. health, ready
   - health: 상태 확인(liveness)을 위해 HTTP 8080 포트에서 `/health` 엔드포인트를 제공하여 CoreDNS 프로세스의 전체적인 정상 동작 상태 확인
   - ready: 준비 상태 체크용 플러그인. HTTP 8181 포트에서 `/ready` 엔드포인트 제공하여 플러그인이 모두 준비된 상태가 되면 HTTP 200 OK 응답. 하나라도 준비가 안되면 503 반환하면서 준비가 되지 않은 플러그인 노출
7. prometheus
   - CoreDNS 및 플러그인의 metric을 HTTP 9153 포트 `/metrics`로 Prometheus 형식으로 노출
   - coredns_requests_total, coredns_request_duration_seconds, coredns_cache_hits_total 등의 메트릭을 제공
8. errors
   - error response 로그를 stdout로 출력
9. log
   - Query logging 플러그인
   - 쿼리명을 비롯해 응답 코드, 응답 시간 등을 stdout으로 기록
   - 설정을 통해 출력 형식이나 필터링 제어 가능
   - 쿼리 로그 활성화 시 성능 오버헤드가 발생하므로, 디버깅 목적 외에는 상시 활성화 비권장
10. hosts
    - 정적 Hosts 파일 기반 DNS 제공
    - Linux의 /etc/hosts와 동일한 형식의 고정 매핑을 CoreDNS를 통해 클러스터 차원에서 서비스할 수 있음
    - 지정된 hosts 파일을 5초마다 모니터링하여 변경 시 자동으로 업데이트된 IP-Domain 매핑을 제공

전체 플러그인 리스트

```bash
kubectl -n kube-system exec deployment/coredns -c coredns -- \
  coredns -plugins | tr ' ' '\n' | sort
# 출력
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

### (4) 실행 순서

- `Corefile` 상에서 플러그인 나열 순서는 실행 순서에 영향을 주지 않는다.
- CoreDNS `plugin.cgf` 파일에 순서가 정의되어 컴파일 시 고정된다.
  - [plugin.cfg](https://github.com/coredns/coredns/blob/master/plugin.cfg)
- 각 plugin인은 response를 생성해서 chain을 멈추거나 다음 plugin을 호출할 수 있음
  - 근데 response 생성 없이 끝까지 가면 `SERVFAIL`이 반환됨

## 4. CoreDNS의 Metric, Log, Trace

### Metric

- prometheus 플러그인이 존재하여, prometheus format의 metrics을 9153 포트로 노출
  ```yaml
  .:53 {
  ...
  prometheus :9153
  ...
  }
  ```
- 다만, 기본적으로는 Azure Managed Prometheus에서 이걸 scraping을 안한다.
- 직접 enable 설정을 적용해줘야함. 적절한 CongfigMap 배포가 필요하다.
  - [https://learn.microsoft.com/ko-kr/azure/azure-monitor/containers/prometheus-metrics-scrape-configuration](https://learn.microsoft.com/ko-kr/azure/azure-monitor/containers/prometheus-metrics-scrape-configuration)
  - [https://github.com/Azure/prometheus-collector/blob/main/otelcollector/configmaps/ama-metrics-settings-configmap.yaml](https://github.com/Azure/prometheus-collector/blob/main/otelcollector/configmaps/ama-metrics-settings-configmap.yaml)
  - 아래 스크린샷을 보면, Depoyment `ama-metrics`에는 `ama-metrics-settings-configmap`라는 이름의 ConfigMap이 Volume mount 설정되어 있음
    ![image.png](./img/image%201.png)
  ```yaml
  apiVersion: v1
  kind: ConfigMap
  metadata:
    name: ama-metrics-settings-configmap
    namespace: kube-system
  data:
    cluster-metrics: |-
      default-targets-scrape-enabled: |-
        coredns = true
      minimal-ingestion-profile: |-
        enabled = true
    config-version: ver1
    controlplane-metrics: |-
      minimal-ingestion-profile: |-
        enabled = true
    prometheus-collector-settings: |-
      cluster_alias = ""
      debug-mode = false
      https_config = true
      secrets_access_namespaces = ""
    schema-version: v2
  ```
- 각 플러그인 별로 생성하는 metrics이 여러 개 있고, 이것들은 prometheus를 통해 노출되는 방식
  - 다만, Azure Monitor managed service for Prometheus의 기본 scrape target에서 `coredns`가 disabled 상태이다.
  - Azure Monitor managed Prometheus는 기본적으로 minimal ingestion profile이 켜져 있고, 이 경우 default target에서 수집하는 metric을 문서에 정의된 목록으로 제한한다.
    - [https://learn.microsoft.com/ko-kr/azure/azure-monitor/containers/prometheus-metrics-scrape-default#targets-scraped-by-default](https://learn.microsoft.com/ko-kr/azure/azure-monitor/containers/prometheus-metrics-scrape-default#targets-scraped-by-default)
- Metrics 종류 (minimal ingestion profile에 의해서 모든 metrics을 수집하지는 않음)
  - `coredns_build_info`
  - `coredns_panics_total`
  - `coredns_dns_responses_total`
  - `coredns_forward_responses_total`
  - `coredns_dns_request_duration_seconds` `coredns_dns_request_duration_seconds_bucket` `coredns_dns_request_duration_seconds_sum` `coredns_dns_request_duration_seconds_count`
  - `coredns_forward_request_duration_seconds` `coredns_forward_request_duration_seconds_bucket` `coredns_forward_request_duration_seconds_sum` `coredns_forward_request_duration_seconds_count`
  - `coredns_dns_requests_total`
  - `coredns_forward_requests_total`
  - `coredns_cache_hits_total`
  - `coredns_cache_misses_total`
  - `coredns_cache_entries`
  - `coredns_plugin_enabled`
  - `coredns_dns_request_size_bytes` `coredns_dns_request_size_bytes_bucket` `coredns_dns_request_size_bytes_sum` `coredns_dns_request_size_bytes_count`
  - `coredns_dns_response_size_bytes` `coredns_dns_response_size_bytes_bucket` `coredns_dns_response_size_bytes_sum` `coredns_dns_response_size_bytes_count`
  - `coredns_dns_response_size_bytes` `coredns_dns_response_size_bytes_bucket` `coredns_dns_response_size_bytes_sum` `coredns_dns_response_size_bytes_count`
  - `process_resident_memory_bytes`
  - `process_cpu_seconds_total`
  - `go_goroutines`
  - `kubernetes_build_info`
- Azure Portal Built-in Grafana에서 CoreDNS를 위한 Community Dashboard를 Import 해줘야 해당 metrics을 시각화 할 수 있음.

### Log

- log, error 플러그인이 존재하고, 각 plugin에서 발생시키는 로그도 존재함
- DNS 트래픽 및 오류 상태를 로깅
- 기본적으로는 log 플러그인이 비활성화되어 있음
  - ConfigMap `coredns`를 확인해보면 log 플러그인이 빠져있음
  - ConfigMap `coredns-custom`에 아래 내용을 추가하고 restart하면 정상적으로 Log 출력 시작
    ```yaml
    data:
    	log.override: |
    		log
    ```
- 다만 여기까지 해도 Container Insight가 활성화 되어있더라도 LAW에 로그가 수집되지는 않는다.
  - 대신 Live Logs는 볼 수 있음
- Container Insight를 켜도 default 세팅으로는 CoreDNS의 log가 LAW쪽으로 수집되지 않음.
  - Azure Monitor Container Insights가 기본적으로 kube-system 같은 system namespace의 container logs를 제외하기 때문
  - Log Analytics 비용 절감을 위함
  - 활성화 방법
    - [https://learn.microsoft.com/ko-kr/azure/azure-monitor/containers/kubernetes-data-collection-configmap](https://learn.microsoft.com/ko-kr/azure/azure-monitor/containers/kubernetes-data-collection-configmap)
    - 별도의 ConfigMap `container-azm-ms-agentconfig`를 배포해야함.
    - 아래 스크린샷을 보면, Depoyment `ama-logs-rs`에는 `container-azm-ms-agentconfig`라는 이름의 ConfigMap이 이미 Volume mount 설정되어 있음
      ![image.png](./img/image%202.png)
    - 아래와 같이 ConfigMap 배포

      ```yaml
      apiVersion: v1
      kind: ConfigMap
      metadata:
        name: container-azm-ms-agentconfig
        namespace: kube-system
      data:
        schema-version: "v1"
        config-version: "1.0.0"
        log-data-collection-settings: |-
          [log_collection_settings]
            [log_collection_settings.stdout]
              enabled = true
              collect_system_pod_logs = ["kube-system:coredns"]

            [log_collection_settings.stderr]
              enabled = true
              collect_system_pod_logs = ["kube-system:coredns"]
      ```

    - 배포 후 몇 분이 지나면 ama-log pod가 rollout restart됨.
      - restart가 안될 경우 직접 restart 수행
        ![image.png](./img/image%203.png)

### Trace

- AKS CoreDNS 바이너리에 trace 플러그인이 이미 존재하지만 기본 설정에는 활성화되어 있지 않다.
- trace 플러그인
  - ConfigMap `coredns-custom`을 통해서 직접 trace 플러그인을 설정해주어야 한다.
    - [https://coredns.io/plugins/trace/](https://coredns.io/plugins/trace/)
  - trace telemetry에 대한 Endpoint-type은 `zipkin`과 `datadog`만 지원한다
  - 또한 OpenTelemetry가 아닌 OpenTracing 기반 tracing이다.
    - OpenTelemetry의 propagator는 W3C TraceContext 헤더(traceparent)를 사용한다
    - OpenTracing은 propagator에 강제 사항이 없으며, parent context를 extract하려는 쪽에서 traceparent를 추출할 수 있어야 OpenTelemetry와 OpenTracing의 correlation이 가능하다.
- trace 시도
  1. ZipKin 배포
  2. ZipKin endpoint와 함께 trace 플러그인 활성화 (ConfigMap `coredns-custom` 수정)
  3. 테스트 DNS query 생성

     ```bash
     kubectl apply -f spec/03-dns-tools.yaml
     kubectl -n trace-lab rollout status deployment/dns-tools --timeout=5m

     kubectl -n trace-lab exec deployment/dns-tools -- sh -c '
     for i in $(seq 1 30); do
       dig +short kubernetes.default.svc.cluster.local
       dig +short www.microsoft.com
       dig +short api.github.com
     done
     '
     ```

  4. 결과

     ```bash
     kubectl -n "$LAB_NS" port-forward service/zipkin 9411:9411
     ```

     ![image.png](./img/image%204.png)

- Q. Application Tracing과 CoreDNS Tracing을 하나의 trace로 correlation이 가능한가?
  - CoreDNS의 trace 플러그인에 HTTP header에서 parent context를 extract하려는 코드는 있지만, 그 구현체가 Zipkin OpenTracing wrapper라서 기본 propagation은 W3C의 traceparent가 아님.
  - 결론적으로는 trace의 correlation은 불가
  - 또한 DNS 프로토콜의 경우 OpenTelemetry의 HTTP header를 통한 trace의 propagation와 같은 동작에 대한 표준이 없기 때문에 프로토콜 자체도 한계가 있다.
  - OpenTelemetry를 도입하려는 시도
    - [https://github.com/coredns/coredns/pull/5777](https://github.com/coredns/coredns/pull/5777) (2022말~2023초)
    - opentelemtry 전용 플러그인 PR이 올라왔으나, maintainer의 반대로 무산
    - 이 논의의 배경은 기존 CoreDNS의 trace plugin이 OpenTracing 기반이고, OpenTracing이 deprecated 되었기 때문에 OpenTelemetry 기반 tracing plugin으로 옮기자는 것
  - OpenTelemetry eBPF Instrumentation
    - Application proces / socket / DNS packet을 eBPF로 관측
    - 해당 DNS lookup을 현재 application span과 runtime으로 correlation
      - socket/PID/trace key 기반으로 기반 client request trace를 찾을 수 있다는 조건 하에
    - application trace 안에 dns.resolve span이 추가됨
    - [https://github.com/open-telemetry/opentelemetry-ebpf-instrumentation/pull/793](https://github.com/open-telemetry/opentelemetry-ebpf-instrumentation/pull/793)
      - 이 PR에서 추가됨
    - (참고) packet이 propagation될 떄 trace context를 packet에 주입하는 방식은 아님.
      - 때문에 W3C Trace Context 표준(traceparent를 carrier를 통해서 전파하는)도 아니고, OBI 자체가 아직 발전 단계.

## 5. 트러블슈팅/시나리오 기반 설정

### 1. 회사 내부 도메인을 별도 DNS 서버로 포워딩

### 2. CoreDNS가 CrashLoopBackOff 상태로 빠지는 경우

- Forwarding Loop가 감지되어 Pod가 CrashLoopBackOff 상태로 빠진 것
- CoreDNS의 Forward 상위 서버가 다시 CoreDNS 자신을 가리키는 잘못된 구성 등에서 발생
- Loop 플러그인이 해당 상황을 FATAL 로그와 함께 감지하여 CoreDNS 프로세스를 중단
- /etc/resolv.conf의 상위 DNS 설정이 클러스터 DNS 자신을 참조하지 않도록 설정해야함.

### 3. DNS 응답 지연 또는 Timeout 현상

- 과도한 QPS로 인한 CPU 과부하 또는 상위 DNS 응답 지연으로 발생
- CoreDNS Pod의 CPU 자원을 늘리거나 레플리카 수를 늘려 수평 확장
- Prometheus 메트릭을 통해 QPS 및 응답 지연을 모니터링하여 병목 원인을 파악
- 필요하다면 NodeLocal DNSCache나 LocalDNS 같은 DNS 캐시를 도입하여 CoreDNS 부하를 줄이고 DNS 응답 시간을 개선

### 4. TTL 만료 시 upstream resolution으로 생기는 latency를 줄이고 싶다.

- cache 플러그인의 prefetch 기능을 활용
  - [https://coredns.io/plugins/cache/](https://coredns.io/plugins/cache/)
- 인기 쿼리에 대한 캐시 만료 전 선조회(prefetch)를 활성화하면 캐시 효율을 높일 수 있다.
    <aside>
    
    `prefetch` will prefetch popular items when they are about to be expunged from the cache. Popular means **AMOUNT** queries have been seen with no gaps of **DURATION** or more between them. **DURATION** defaults to 1m. Prefetching will happen when the TTL drops below **PERCENTAGE**, which defaults to `10%`, or latest 1 second before TTL expiration. Values should be in the range `[10%, 90%]`. Note the percent sign is mandatory. **PERCENTAGE** is treated as an `int`.
    
    </aside>

## 6. 기타

### DNS-over-HTTP란?
