# AKS CoreDNS ndots Labs

작성일: 2026-06-24

이 폴더는 Kubernetes Pod의 `ndots` 설정이 DNS query 생성 방식에 어떤 영향을 주는지 확인하기 위한 실행형 lab 문서 모음이다.

## 확인할 것

1. `ndots:5` 환경에서 trailing dot이 없는 이름 조회가 실제로 search suffix query를 만든다.
2. 같은 이름에 trailing dot을 붙이면 search suffix query가 사라진다.
3. Pod의 `ndots` 값을 낮추면 trailing dot 없이도 먼저 절대 이름으로 조회한다.

## 실습 흐름

| 순서 | 문서                                                       | 확인 내용                                                                |
| ---- | ---------------------------------------------------------- | ------------------------------------------------------------------------ |
| 1    | [01-prepare-lab-resources.md](01-prepare-lab-resources.md) | namespace, target Service, DNS client Pod 준비와 `/etc/resolv.conf` 확인 |
| 2    | [02-verify-ndots-behavior.md](02-verify-ndots-behavior.md) | 기본 `ndots`, trailing dot, `ndots:1`의 query 차이 확인                  |
| 3    | [03-cleanup.md](03-cleanup.md)                             | lab 리소스와 선택적으로 실행한 Zipkin port-forward 정리                  |
| 4    | [04-result-summary.md](04-result-summary.md)               | lab 결과와 최종 결론                                                     |

## 공통 전제

- 현재 kube context가 테스트 대상 AKS 클러스터를 가리킨다.
- `kubectl` 사용 권한이 있다.
- CoreDNS `log` 플러그인이 이미 활성화되어 있다.
- CoreDNS `trace` 플러그인과 Zipkin은 [../../trace](../../trace) lab에서 이미 준비되어 있으면 함께 참고한다.
- AKS 기본 CoreDNS Pod label은 `k8s-app=kube-dns`라고 가정한다.
- `jq`는 선택 사항이다. 없으면 `grep` 기반 명령으로도 확인할 수 있다.

## 공통 변수

각 문서의 첫 번째 명령 블록에 같은 변수를 다시 넣어두었다. 문서를 순서대로 실행하지 않아도 해당 문서 안의 명령만 복사해 실행할 수 있다.

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

## 관찰 대상 이름

이 lab은 외부 인터넷 도메인 대신 lab 내부 Service FQDN을 사용한다. 엄밀히는 trailing dot이 없는 이름이므로 resolver 입장에서는 아직 절대 이름으로 고정된 상태가 아니다.

```text
ndots-target.ndots-lab.svc.cluster.local
```

이 이름에는 점이 4개 있다. Pod 기본값이 `ndots:5`라면 resolver는 이 이름을 곧바로 절대 이름으로 보지 않고, search suffix를 먼저 붙여 조회한다. 그래서 다음과 같은 허수 query가 CoreDNS log에 보일 수 있다.

```text
ndots-target.ndots-lab.svc.cluster.local.ndots-lab.svc.cluster.local.
ndots-target.ndots-lab.svc.cluster.local.svc.cluster.local.
ndots-target.ndots-lab.svc.cluster.local.cluster.local.
ndots-target.ndots-lab.svc.cluster.local.
```

마지막 query만 실제 Service 이름이고, 앞의 query들은 `ndots:5`와 search suffix 때문에 만들어진 query다.
