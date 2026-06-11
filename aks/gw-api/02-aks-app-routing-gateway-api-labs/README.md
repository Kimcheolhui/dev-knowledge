# AKS Application Routing Gateway API Labs

작성일: 2026-06-07

이 폴더는 AKS application routing Gateway API implementation을 운영 관점에서 실습하기 위한 시나리오 모음이다. 기본 Gateway API 라우팅 기능은 `01-application-gateway-for-containers-labs`에서 이미 다뤘으므로, 여기서는 `approuting-istio`가 클러스터 안에 어떤 리소스를 만들고, 그 리소스를 어떻게 관찰/조정/정리해야 하는지에 집중한다.

## 시나리오 구성

| 문서                                                                 | 포함 시나리오                                                                  |
| -------------------------------------------------------------------- | ------------------------------------------------------------------------------ |
| [01-install-and-control-plane.md](01-install-and-control-plane.md)   | Managed Gateway API CRD, app routing Istio control plane, GatewayClass 확인    |
| [02-generated-gateway-resources.md](02-generated-gateway-resources.md) | Gateway 생성 후 Deployment, Service, HPA, PDB가 자동 생성되는 방식 확인        |
| [03-customization-and-scaling.md](03-customization-and-scaling.md)   | internal LoadBalancer, Gateway-level ConfigMap, HPA/PDB customization 확인     |
| [04-observability-and-cleanup.md](04-observability-and-cleanup.md)   | Gateway/Route condition, generated resource event, gateway pod log, cleanup 확인 |

## 공통 전제

- Azure CLI `2.86.0` 이상
- 대상 AKS cluster에 Managed Gateway API CRD 활성화 가능
- 대상 AKS cluster에 application routing Gateway API implementation 활성화 가능
- AKS Istio service mesh add-on이 동시에 활성화되어 있지 않아야 함
- `kubectl` context가 실습 대상 AKS cluster를 가리켜야 함

현재 context를 확인한다.

```bash
kubectl config current-context
kubectl get nodes
```

Gateway API와 application routing 상태를 확인한다.

```bash
kubectl get gatewayclass
kubectl get pods -n aks-istio-system
kubectl get cm istio-gateway-class-defaults -n aks-istio-system -o yaml
```

`GatewayClass` 목록에 `approuting-istio`가 없으면 [01-install-and-control-plane.md](01-install-and-control-plane.md)를 먼저 진행한다.

## 공통 준비

실습 manifest는 `approuting-lab` namespace와 `apr-lab-gateway` Gateway 이름을 기본으로 사용한다.

`spec/` 폴더에는 같은 Gateway를 external, internal, customized 상태로 바꾸는 대체 manifest가 함께 들어 있다. 전체 폴더를 한 번에 apply하지 말고, 각 실습 문서의 순서대로 개별 파일을 적용한다.

```bash
cd /home/cheolhuikim/studyspace/dev-knowledge/aks/gw-api/02-aks-app-routing-gateway-api-labs

kubectl apply -f spec/00-namespace-and-apps.yaml
kubectl apply -f spec/01-gateway.yaml
kubectl apply -f spec/02-httproute.yaml
```

Gateway가 Programmed 상태가 될 때까지 기다린다.

```bash
kubectl wait \
  --for=condition=programmed \
  gateways.gateway.networking.k8s.io apr-lab-gateway \
  -n approuting-lab \
  --timeout=10m
```

## 공통 변수

실습 중 자주 쓰는 값은 다음처럼 잡아둔다.

```bash
export LAB_NS=approuting-lab
export GATEWAY_NAME=apr-lab-gateway
export GENERATED_NAME=${GATEWAY_NAME}-approuting-istio
export INGRESS_HOST=$(kubectl get gateway $GATEWAY_NAME -n $LAB_NS -o jsonpath='{.status.addresses[0].value}')

echo $LAB_NS
echo $GATEWAY_NAME
echo $GENERATED_NAME
echo $INGRESS_HOST
```

기본 호출을 확인한다.

```bash
curl -i -H 'Host: app.example.com' "http://$INGRESS_HOST/"
curl -i -H 'Host: app.example.com' "http://$INGRESS_HOST/api"
```

응답 JSON의 `app` 값이 각각 `web-v1`, `api-v1`로 나오면 route와 backend Service 연결이 정상이다.

## Cleanup

실습 리소스를 삭제한다.

```bash
kubectl delete -f spec/05-gateway-with-options.yaml --ignore-not-found
kubectl delete -f spec/04-gateway-options-configmap.yaml --ignore-not-found
kubectl delete -f spec/03-gateway-internal-lb.yaml --ignore-not-found
kubectl delete -f spec/02-httproute.yaml --ignore-not-found
kubectl delete -f spec/01-gateway.yaml --ignore-not-found
kubectl delete -f spec/00-namespace-and-apps.yaml --ignore-not-found
```

`istiod` HPA를 실습 중 조정했다면 기본값으로 되돌린다.

```bash
kubectl patch hpa istiod -n aks-istio-system --type merge --patch '{"spec": {"minReplicas": 2, "maxReplicas": 5}}'
```

더 이상 application routing Gateway API implementation을 쓰지 않는 실습 cluster라면 add-on을 비활성화한다.

```bash
export CLUSTER='<cluster-name>'
export RESOURCE_GROUP='<resource-group-name>'

az aks update \
  --resource-group $RESOURCE_GROUP \
  --name $CLUSTER \
  --disable-app-routing-istio
```

Managed Gateway API CRD는 다른 Gateway API implementation도 공유할 수 있으므로, cluster에서 더 이상 Gateway API를 쓰지 않을 때만 비활성화한다.

```bash
az aks update \
  --resource-group $RESOURCE_GROUP \
  --name $CLUSTER \
  --disable-gateway-api
```