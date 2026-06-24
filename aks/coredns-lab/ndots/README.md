# Kubernetes ndots DNS 이슈

Kubernetes Pod의 `/etc/resolv.conf`에는 일반적으로 다음과 같은 DNS 설정이 들어간다.

```text
search <namespace>.svc.cluster.local svc.cluster.local cluster.local
nameserver <CoreDNS Service ClusterIP>
options ndots:5
```

여기서 핵심은 `options ndots:5`이다. Linux resolver는 조회하려는 이름에 포함된 점(`.`)의 개수가 `ndots` 값보다 적으면, 그 이름을 바로 절대 이름처럼 조회하지 않고 `search` suffix를 붙여가며 먼저 조회한다.

예를 들어 Pod가 `default` namespace에 있고 애플리케이션이 `api.github.com`을 조회한다고 가정한다. `api.github.com`에는 점이 2개뿐이므로 `ndots:5` 기준에서는 아직 절대 이름으로 우선 처리되지 않는다. resolver는 대략 다음과 같은 순서로 질의할 수 있다.

```text
api.github.com.default.svc.cluster.local
api.github.com.svc.cluster.local
api.github.com.cluster.local
api.github.com
```

환경에 따라 노드 또는 클라우드에서 추가한 search domain이 더 붙어 있으면 중간 질의가 더 늘어날 수 있다. 즉 애플리케이션 입장에서는 `api.github.com` 하나만 조회했지만, 실제로는 여러 개의 DNS query가 CoreDNS로 전달될 수 있다.

## 왜 Kubernetes는 ndots 값을 크게 쓰는가

Kubernetes 내부 서비스 이름을 짧게 조회하기 위해서다.

예를 들어 같은 namespace의 Service를 `backend`라는 짧은 이름으로 호출하면 resolver는 다음과 같이 search suffix를 붙여 `backend.default.svc.cluster.local`을 만들 수 있다.

```text
backend.default.svc.cluster.local
```

이 방식 덕분에 애플리케이션은 매번 `backend.default.svc.cluster.local` 같은 긴 FQDN을 쓰지 않아도 된다. Kubernetes 서비스 디스커버리에는 편리하지만, 외부 도메인 조회가 많은 워크로드에서는 불필요한 DNS query가 늘어나는 부작용이 생긴다.

## 누가 여러 DNS query를 만드는가

`ndots`로 인해 여러 query가 생길 때, CoreDNS가 이름을 바꿔가며 recursive하게 다시 질의하는 것이 아니다. 먼저 Pod 안의 DNS client resolver가 `/etc/resolv.conf`의 `search` list와 `ndots` 값을 보고 후보 이름을 여러 개 만든 뒤, 이를 CoreDNS에 순차적으로 질의한다.

흐름은 대략 다음과 같다.

```text
application
	-> libc / resolver
	-> /etc/resolv.conf 확인
	-> search suffix 후보 이름 생성
	-> CoreDNS에 후보 query를 하나씩 전송
	-> NXDOMAIN이면 다음 후보 query 전송
```

즉 CoreDNS log에 여러 줄이 보인다면, CoreDNS 입장에서는 서로 다른 DNS query를 여러 개 받은 것이다. 이 현상은 **client-side search expansion**에 가깝다.

다만 recursive resolver라는 표현은 별도의 의미로 쓰인다. CoreDNS가 자신이 authoritative하게 처리하지 않는 외부 도메인을 `forward` plugin을 통해 upstream resolver로 넘기고, upstream resolver가 실제 인터넷 DNS 계층을 따라가며 이름을 푸는 것이 일반적인 recursive resolution이다.

따라서 ndots 이슈는 다음처럼 구분해서 보는 것이 좋다.

- Pod resolver: search suffix를 붙인 여러 query를 CoreDNS에 보낸다.
- CoreDNS: Kubernetes zone은 직접 응답하고, cluster domain 밖의 query는 설정에 따라 upstream으로 forward할 수 있다.
- Upstream recursive resolver: forwarded query에 대해 실제 recursive resolution을 수행한다.

## 무엇이 문제가 되는가

이 현상은 보통 다음 문제로 이어질 수 있다.

- 하나의 외부 도메인 조회가 여러 DNS query로 확대된다.
- 존재하지 않는 `*.svc.cluster.local`, `*.cluster.local` 형태의 NXDOMAIN 응답이 증가한다.
- CoreDNS의 query volume, CPU 사용량, cache miss가 늘어날 수 있다.
- cluster domain 밖의 search query나 최종 외부 도메인 query는 CoreDNS의 `forward` plugin을 통해 upstream recursive resolver로 전달될 수 있다.
- 외부 API 호출이 많은 애플리케이션에서는 DNS lookup latency가 증가하고, 짧은 timeout 또는 높은 QPS 상황에서 장애처럼 보일 수 있다.

즉 문제의 본질은 `ndots:5` 자체가 항상 나쁘다는 것이 아니라, 짧은 Kubernetes 서비스 이름 조회를 최적화한 기본값이 외부 도메인 조회 패턴과 만나면서 DNS query amplification을 만들 수 있다는 점이다.

## FQDN과 trailing dot

DNS에서 완전한 절대 이름은 엄밀히 말하면 마지막에 점이 붙은 형태다.

```text
api.github.com.
```

이렇게 trailing dot을 붙이면 search suffix 확장을 건너뛰고 절대 이름으로 조회하게 만들 수 있다. 다만 애플리케이션, 라이브러리, HTTP client, TLS hostname 검증 방식에 따라 trailing dot 사용이 자연스럽지 않거나 문제가 될 수 있으므로 운영 대응책으로 무조건 적용하기는 어렵다.

## 대표적인 완화 방향

상황에 따라 다음 방식을 검토할 수 있다.

- 외부 도메인을 많이 조회하는 Pod에 `dnsConfig.options.ndots`를 낮게 설정한다.
- 가능하면 내부 서비스 호출에는 명확한 Kubernetes DNS 이름을 사용하고, 외부 도메인 조회 패턴을 분리해서 본다.
- CoreDNS cache hit ratio, NXDOMAIN 비율, upstream forward latency를 관찰한다.
- NodeLocal DNSCache 또는 CoreDNS autoscaling 같은 DNS 경로 최적화를 함께 검토한다.
- 애플리케이션 레벨 DNS cache, connection reuse, keep-alive 설정을 확인한다.

## Lab에서 확인할 내용

이 lab에서는 다음 내용을 실제로 관찰한다.

- Pod의 `/etc/resolv.conf`에서 `search`와 `ndots` 확인
- `ndots-target.ndots-lab.svc.cluster.local` 조회 시 생성되는 실제 query 순서 확인
- CoreDNS log 또는 metrics에서 NXDOMAIN/query 증가 확인
- `ndots:5`와 낮은 `ndots` 값의 query 수 차이 비교
- FQDN trailing dot 사용 시 search query가 줄어드는지 확인

## Lab 문서

실제 실행 절차는 [labs](labs) 폴더에 분리했다.

| 문서                                                                 | 목적                                                   |
| -------------------------------------------------------------------- | ------------------------------------------------------ |
| [labs/README.md](labs/README.md)                                     | 전체 lab 흐름과 공통 변수                              |
| [labs/01-prepare-lab-resources.md](labs/01-prepare-lab-resources.md) | lab 리소스 배포와 Pod DNS 설정 확인                    |
| [labs/02-verify-ndots-behavior.md](labs/02-verify-ndots-behavior.md) | ndots 기본 동작, trailing dot, ndots 값 변경 효과 검증 |
| [labs/03-cleanup.md](labs/03-cleanup.md)                             | lab 리소스와 Zipkin port-forward 정리                  |
