# 03. Customization And Scaling

이 실습은 application routing Gateway API implementation에서 gateway workload를 어느 범위까지 조정할 수 있는지 확인한다. 핵심은 generated resource를 직접 손으로 수정하는 것이 아니라, `Gateway.spec.infrastructure.annotations`, Gateway-level ConfigMap, control plane HPA 같은 지원 경로를 사용하는 것이다.

## 목표

- Gateway `spec.infrastructure.annotations`로 internal LoadBalancer를 만든다.
- Gateway-level ConfigMap으로 generated `HPA`와 `Deployment` label을 조정한다.
- allow list 기반 customization의 한계를 확인한다.
- `istiod` control plane HPA와 gateway data plane HPA를 구분한다.

## 0. 기본 상태 확인

```bash
cd /home/cheolhuikim/studyspace/dev-knowledge/aks/gw-api/02-aks-app-routing-gateway-api-labs

export LAB_NS=approuting-lab
export GATEWAY_NAME=apr-lab-gateway
export GENERATED_NAME=${GATEWAY_NAME}-approuting-istio

kubectl get gateway $GATEWAY_NAME -n $LAB_NS
kubectl get service $GENERATED_NAME -n $LAB_NS -o wide
kubectl get hpa $GENERATED_NAME -n $LAB_NS
kubectl get pdb $GENERATED_NAME -n $LAB_NS
```

기본 리소스가 없다면 먼저 공통 준비를 실행한다.

```bash
kubectl apply -f spec/00-namespace-and-apps.yaml
kubectl apply -f spec/01-gateway.yaml
kubectl apply -f spec/02-httproute.yaml
```

## 1. internal LoadBalancer로 전환

`spec/03-gateway-internal-lb.yaml`은 같은 Gateway에 internal LoadBalancer annotation을 추가한다.

```bash
kubectl apply -f spec/03-gateway-internal-lb.yaml
kubectl describe gateway $GATEWAY_NAME -n $LAB_NS
```

Service annotation이 generated Service로 반영되는지 확인한다.

```bash
kubectl get service $GENERATED_NAME -n $LAB_NS -o yaml | grep -A8 annotations:
kubectl get service $GENERATED_NAME -n $LAB_NS -o wide
```

내부 LoadBalancer는 private IP를 받는다. IP 할당이 늦으면 Service event를 본다.

```bash
kubectl describe service $GENERATED_NAME -n $LAB_NS
```

특정 subnet에 붙이고 싶으면 Gateway annotation에 subnet 이름을 추가한다.

```bash
kubectl patch gateway $GATEWAY_NAME -n $LAB_NS --type merge --patch '{"spec": {"infrastructure": {"annotations": {"service.beta.kubernetes.io/azure-load-balancer-internal-subnet": "<subnet-name>"}}}}'
```

이 단계는 AGC의 frontend/subnet association을 Azure 리소스로 보는 것과 다르다. 여기서는 Kubernetes Service annotation이 Azure Load Balancer 동작을 간접 제어한다.

## 2. Gateway-level ConfigMap 적용

기본 HPA/PDB 설정은 `aks-istio-system`의 `istio-gateway-class-defaults` ConfigMap에서 온다. 실습에서는 Gateway 하나에만 영향을 주도록 Gateway-level ConfigMap을 사용한다.

```bash
kubectl apply -f spec/04-gateway-options-configmap.yaml
kubectl apply -f spec/05-gateway-with-options.yaml
```

HPA min/max가 Gateway-level ConfigMap 값으로 바뀌는지 확인한다.

```bash
kubectl get hpa $GENERATED_NAME -n $LAB_NS
kubectl get hpa $GENERATED_NAME -n $LAB_NS -o jsonpath='{.spec.minReplicas}{"\t"}{.spec.maxReplicas}{"\n"}'
```

Deployment label이 반영되는지 확인한다.

```bash
kubectl get deployment $GENERATED_NAME -n $LAB_NS -o jsonpath='{.metadata.labels.lab\.gw-api\.azure\/config}{"\n"}'
```

기대값은 `per-gateway`다.

## 3. allow list 감각 잡기

Gateway generated resource customization은 모든 Kubernetes 필드를 자유롭게 열어주는 기능이 아니다. AKS add-on managed webhook이 allow list 밖 필드를 차단한다.

허용되는 예시는 다음과 같다.

| 리소스 | 예시 필드 |
| ------ | --------- |
| Deployment | `metadata.labels`, `metadata.annotations`, `spec.template.spec.containers.resources.requests`, `spec.template.spec.tolerations` |
| Service | `metadata.annotations`, `spec.type`, `spec.loadBalancerSourceRanges`, `spec.externalTrafficPolicy` |
| HPA | `spec.minReplicas`, `spec.maxReplicas`, `spec.metrics`, scale up/down behavior |
| PDB | `spec.minAvailable`, `spec.unhealthyPodEvictionPolicy` |

운영에서는 generated `Deployment`나 `HPA`를 직접 patch하기보다 ConfigMap과 Gateway spec을 source of truth로 둔다. 직접 patch한 값은 control plane reconciliation으로 되돌아가거나 upgrade 중 예상과 다르게 동작할 수 있다.

## 4. control plane HPA와 data plane HPA 구분

gateway data plane HPA는 Gateway namespace에 생성된다.

```bash
kubectl get hpa $GENERATED_NAME -n $LAB_NS
```

application routing Istio control plane HPA는 `aks-istio-system` namespace에 있다.

```bash
kubectl get hpa istiod -n aks-istio-system
```

control plane HPA는 직접 patch할 수 있다. `minReplicas`는 기본값 2보다 낮추지 않는다.

```bash
kubectl patch hpa istiod -n aks-istio-system --type merge --patch '{"spec": {"minReplicas": 3, "maxReplicas": 6}}'
kubectl get hpa istiod -n aks-istio-system
```

실습 후 기본값으로 되돌린다.

```bash
kubectl patch hpa istiod -n aks-istio-system --type merge --patch '{"spec": {"minReplicas": 2, "maxReplicas": 5}}'
```

## 5. external LoadBalancer로 되돌리기

internal LoadBalancer annotation을 제거하려면 기본 Gateway manifest를 다시 적용한다.

```bash
kubectl apply -f spec/01-gateway.yaml
kubectl get service $GENERATED_NAME -n $LAB_NS -o wide
```

만약 patch로 추가한 subnet annotation이 남아 있으면 `infrastructure` 필드를 명시적으로 제거한 뒤 기본 manifest를 다시 적용한다.

```bash
kubectl patch gateway $GATEWAY_NAME -n $LAB_NS --type json -p='[{"op":"remove","path":"/spec/infrastructure"}]'
kubectl apply -f spec/01-gateway.yaml
```

Gateway-level ConfigMap까지 유지하려면 `spec/05-gateway-with-options.yaml`을 다시 적용한다. 이 manifest는 external LoadBalancer 상태에서 per-Gateway HPA/Deployment customization만 유지한다.

```bash
kubectl apply -f spec/05-gateway-with-options.yaml
```