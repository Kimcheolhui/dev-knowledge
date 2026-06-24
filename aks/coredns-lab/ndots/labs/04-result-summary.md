# 04. Result summary

이 lab에서는 Kubernetes Pod의 기본 `ndots:5` 설정이 실제로 search suffix query를 만들고, trailing dot 또는 낮은 `ndots` 값으로 이를 줄일 수 있음을 확인했다.

## 결론

1. `ndots:5` 환경에서 trailing dot 없이 조회하면 ndots 이슈가 발생한다.
2. trailing dot을 붙이면 search suffix 확장이 발생하지 않는다.
3. Pod의 `dnsConfig.options.ndots` 값을 `1`로 낮추면 trailing dot 없이도 먼저 절대 이름으로 조회한다.

## 관찰 결과

### Case 1 - 기본 ndots, trailing dot 없음

```text
ndots-target.ndots-lab.svc.cluster.local.ndots-lab.svc.cluster.local.
ndots-target.ndots-lab.svc.cluster.local.svc.cluster.local.
ndots-target.ndots-lab.svc.cluster.local.cluster.local.
ndots-target.ndots-lab.svc.cluster.local.4bbzk525ohhuvj2r35l3z53jpc.syx.internal.cloudapp.net.
ndots-target.ndots-lab.svc.cluster.local.
```

하나의 이름 조회가 5개의 DNS query로 확장되었다. 앞의 4개는 search suffix 때문에 만들어진 query이고, 마지막 query가 실제 Service FQDN이다.

### Case 2 - 기본 ndots, trailing dot 있음

```text
ndots-target.ndots-lab.svc.cluster.local.
```

trailing dot을 붙이자 search suffix query 없이 실제 Service FQDN만 조회되었다.

### Case 3 - ndots:1, trailing dot 없음

```text
ndots-target.ndots-lab.svc.cluster.local.
```

Pod의 `ndots` 값을 `1`로 낮추자 trailing dot 없이도 실제 Service FQDN만 조회되었다.

## 추가 확인

Pod의 search list에는 Kubernetes 기본 suffix 외에 Azure internal search domain도 포함되어 있었다.

```text
search ndots-lab.svc.cluster.local svc.cluster.local cluster.local 4bbzk525ohhuvj2r35l3z53jpc.syx.internal.cloudapp.net
```

따라서 AKS 환경에서는 Kubernetes suffix뿐 아니라 노드/클라우드에서 온 search domain까지 불필요한 DNS query를 늘릴 수 있다.

## 최종 판단

이 lab의 핵심 판단 근거는 CoreDNS log다. Zipkin trace는 sampling과 조회 시간 범위에 따라 비어 있을 수 있으므로 보조 확인 수단으로 보는 것이 적절하다.
