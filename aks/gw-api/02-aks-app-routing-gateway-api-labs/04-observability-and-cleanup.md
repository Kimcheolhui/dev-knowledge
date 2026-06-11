# 04. Observability And Cleanup

이 실습은 장애가 났을 때 어디부터 볼지 정리한다. application routing Gateway API implementation은 Kubernetes status condition, generated resource, gateway pod log, `istiod` log를 같이 봐야 한다.

## 목표

- Gateway/HTTPRoute condition을 읽는다.
- generated gateway pod 로그와 `istiod` control plane 로그를 확인한다.
- application routing Gateway API implementation에서 지원되는 관측 지점과 Istio service mesh add-on 전용 기능을 구분한다.
- 실습 리소스와 add-on cleanup 범위를 구분한다.

## 0. 공통 변수

```bash
cd /home/cheolhuikim/studyspace/dev-knowledge/aks/gw-api/02-aks-app-routing-gateway-api-labs

export LAB_NS=approuting-lab
export GATEWAY_NAME=apr-lab-gateway
export GENERATED_NAME=${GATEWAY_NAME}-approuting-istio
export INGRESS_HOST=$(kubectl get gateway $GATEWAY_NAME -n $LAB_NS -o jsonpath='{.status.addresses[0].value}')
```

## 1. Status condition 우선 확인

```bash
kubectl get gateway $GATEWAY_NAME -n $LAB_NS -o wide
kubectl describe gateway $GATEWAY_NAME -n $LAB_NS
kubectl describe httproute apr-lab-route -n $LAB_NS
```

JSON으로 condition만 보고 싶으면 다음처럼 본다.

```bash
kubectl get gateway $GATEWAY_NAME -n $LAB_NS -o jsonpath='{range .status.conditions[*]}{.type}{"\t"}{.status}{"\t"}{.reason}{"\t"}{.message}{"\n"}{end}'
kubectl get httproute apr-lab-route -n $LAB_NS -o jsonpath='{range .status.parents[*].conditions[*]}{.type}{"\t"}{.status}{"\t"}{.reason}{"\t"}{.message}{"\n"}{end}'
```

자주 보는 신호는 다음이다.

| 증상 | 먼저 볼 곳 |
| ---- | ---------- |
| `Gateway Programmed=False` | `kubectl describe gateway`, generated Deployment/Service event |
| `HTTPRoute ResolvedRefs=False` | backend Service 이름/port, cross-namespace면 `ReferenceGrant` |
| Gateway address 없음 | generated Service `EXTERNAL-IP`, Azure Load Balancer event |
| 호출 timeout | Service event, Network Security Group, internal LB 여부, pod readiness |

## 2. Gateway pod와 Service 확인

```bash
kubectl get deployment,service,hpa,pdb -n $LAB_NS | grep $GENERATED_NAME
kubectl get pods -n $LAB_NS -l gateway.networking.k8s.io/gateway-name=$GATEWAY_NAME -o wide
kubectl describe deployment $GENERATED_NAME -n $LAB_NS
kubectl describe service $GENERATED_NAME -n $LAB_NS
```

gateway pod 로그를 본다.

```bash
kubectl logs -n $LAB_NS deployment/$GENERATED_NAME --tail=100
```

## 3. Control plane 로그 확인

```bash
kubectl get pods -n aks-istio-system -o wide
kubectl logs -n aks-istio-system deployment/istiod --tail=200
```

최근 event도 같이 본다.

```bash
kubectl get events -n aks-istio-system --sort-by=.metadata.creationTimestamp | tail -n 40
kubectl get events -n $LAB_NS --sort-by=.metadata.creationTimestamp | tail -n 80
```

## 4. Access log와 지원 범위 구분

AKS Istio service mesh add-on 문서에는 `Telemetry` API를 사용한 Gateway access log 설정이 나온다. 하지만 application routing Gateway API implementation은 전체 Istio service mesh가 아니며, 공식 문서 기준 sidecar injection과 Istio CRD support를 제공하지 않는다. 따라서 이 실습에서는 `Telemetry` CRD를 새로 설치하거나 `Telemetry` 리소스를 전제로 두지 않는다.

먼저 Gateway pod의 기본 로그와 event로 문제를 좁힌다.

```bash
kubectl logs -n $LAB_NS deployment/$GENERATED_NAME --tail=200
kubectl get events -n $LAB_NS --sort-by=.metadata.creationTimestamp | tail -n 80
```

요청을 여러 번 보내고 gateway pod 로그와 backend 응답을 함께 본다.

```bash
export INGRESS_HOST=$(kubectl get gateway $GATEWAY_NAME -n $LAB_NS -o jsonpath='{.status.addresses[0].value}')

curl -i -H 'Host: app.example.com' "http://$INGRESS_HOST/"
curl -i -H 'Host: app.example.com' "http://$INGRESS_HOST/api"
kubectl logs -n $LAB_NS deployment/$GENERATED_NAME --tail=200
```

요청 단위 access log가 운영 요구사항이면, 이 구현체의 공식 지원 범위 안에서는 cluster-level container log collection, Azure Monitor Container Insights, 또는 gateway pod log 수집 정책으로 접근한다. `Telemetry` 리소스를 써야 하는 요구사항이라면 application routing Gateway API implementation이 아니라 AKS Istio service mesh add-on 쪽 설계와 비교한다.

혹시 이전 Istio service mesh add-on에서 남은 Telemetry CRD가 보이면, app-routing 전환 전 정리 대상인지 확인한다.

```bash
kubectl get crd telemetries.telemetry.istio.io --ignore-not-found
```

## 5. Cleanup 범위 구분

먼저 Gateway, Route, ConfigMap을 삭제한다. 이 단계에서는 namespace를 아직 남겨두고 generated resource가 함께 정리되는지 확인한다.

```bash
kubectl delete -f spec/05-gateway-with-options.yaml --ignore-not-found
kubectl delete -f spec/04-gateway-options-configmap.yaml --ignore-not-found
kubectl delete -f spec/03-gateway-internal-lb.yaml --ignore-not-found
kubectl delete -f spec/02-httproute.yaml --ignore-not-found
kubectl delete -f spec/01-gateway.yaml --ignore-not-found
```

삭제 후 generated resource가 남아 있는지 확인한다.

```bash
kubectl get all,hpa,pdb -n $LAB_NS
kubectl get gateway,httproute -n $LAB_NS
```

마지막으로 실습 앱과 namespace를 삭제한다.

```bash
kubectl delete -f spec/00-namespace-and-apps.yaml --ignore-not-found
```

add-on 자체를 비활성화하는 cleanup은 cluster-wide 작업이다.

```bash
export CLUSTER='<cluster-name>'
export RESOURCE_GROUP='<resource-group-name>'

az aks update \
  --resource-group $RESOURCE_GROUP \
  --name $CLUSTER \
  --disable-app-routing-istio
```

Managed Gateway API CRD는 다른 Gateway API implementation도 사용할 수 있다. cluster에서 Gateway API를 더 이상 사용하지 않을 때만 비활성화한다.

```bash
az aks update \
  --resource-group $RESOURCE_GROUP \
  --name $CLUSTER \
  --disable-gateway-api
```

## 6. AGC와 운영 관점 차이 정리

| 항목 | Application routing Gateway API | AGC |
| ---- | ------------------------------- | --- |
| Data plane 위치 | AKS node 위 gateway pod | Azure managed AGC resource |
| 외부 노출 | Kubernetes `Service` type `LoadBalancer` | AGC frontend/association |
| 기본 운영 확인 | Gateway condition, generated Deployment/Service/HPA/PDB, gateway pod log | Gateway/Route condition, ALB Controller log, AGC resource/diagnostic log |
| Scaling | Kubernetes HPA와 node capacity 영향 | Azure managed data plane capacity 모델 |
| Customization | Gateway annotation/ConfigMap allow list | AGC resource, frontend, WAF/diagnostic Azure 설정 |