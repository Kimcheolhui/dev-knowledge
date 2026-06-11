# 02. Generated Gateway Resources

이 실습은 `Gateway` 하나가 `approuting-istio` control plane에 의해 어떤 Kubernetes 리소스로 확장되는지 확인한다. 여기서 중요한 차이는 AGC처럼 Azure managed L7 resource를 직접 보지 않고, cluster 안의 gateway workload와 Kubernetes `Service` type `LoadBalancer`를 운영한다는 점이다.

## 목표

- `Gateway`와 `HTTPRoute`를 배포한다.
- 자동 생성된 `Deployment`, `Service`, `HorizontalPodAutoscaler`, `PodDisruptionBudget`를 확인한다.
- Azure Load Balancer가 Kubernetes Service를 통해 붙는 방식을 확인한다.
- Gateway API status condition과 generated resource 상태를 같이 보는 습관을 만든다.

## 0. 실습 리소스 배포

```bash
cd /home/cheolhuikim/studyspace/dev-knowledge/aks/gw-api/02-aks-app-routing-gateway-api-labs

kubectl apply -f spec/00-namespace-and-apps.yaml
kubectl apply -f spec/01-gateway.yaml
kubectl apply -f spec/02-httproute.yaml
```

공통 변수를 설정한다.

```bash
export LAB_NS=approuting-lab
export GATEWAY_NAME=apr-lab-gateway
export GENERATED_NAME=${GATEWAY_NAME}-approuting-istio
```

Gateway가 Programmed 상태가 될 때까지 기다린다.

```bash
kubectl wait \
  --for=condition=programmed \
  gateways.gateway.networking.k8s.io $GATEWAY_NAME \
  -n $LAB_NS \
  --timeout=10m
```

## 1. Gateway와 Route condition 확인

```bash
kubectl get gateway $GATEWAY_NAME -n $LAB_NS
kubectl describe gateway $GATEWAY_NAME -n $LAB_NS
kubectl describe httproute apr-lab-route -n $LAB_NS
```

우선 볼 condition은 다음이다.

| Condition      | 확인 의미                                              |
| -------------- | ------------------------------------------------------ |
| `Accepted`     | `approuting-istio` controller가 Gateway/Route를 받았는지 |
| `Programmed`   | Envoy gateway workload/config에 반영됐는지             |
| `ResolvedRefs` | backend Service, Secret, ReferenceGrant 참조가 유효한지 |

## 2. 자동 생성 리소스 확인

공식 문서 기준 기본 이름은 `<gateway-name>-approuting-istio`다.

```bash
kubectl get deployment $GENERATED_NAME -n $LAB_NS
kubectl get service $GENERATED_NAME -n $LAB_NS
kubectl get hpa $GENERATED_NAME -n $LAB_NS
kubectl get pdb $GENERATED_NAME -n $LAB_NS
```

한 번에 보면 더 운영 관점에 가깝다.

```bash
kubectl get deployment,service,hpa,pdb -n $LAB_NS | grep $GENERATED_NAME
```

gateway pod가 실제로 cluster node 위에서 돈다는 점을 확인한다.

```bash
kubectl get pods -n $LAB_NS -l gateway.networking.k8s.io/gateway-name=$GATEWAY_NAME -o wide
kubectl get deployment $GENERATED_NAME -n $LAB_NS -o jsonpath='{.spec.template.spec.containers[*].image}{"\n"}'
```

## 3. Service LoadBalancer 확인

application routing Gateway API implementation은 외부 노출에 Kubernetes `Service` type `LoadBalancer`를 사용한다.

```bash
kubectl get service $GENERATED_NAME -n $LAB_NS -o wide
kubectl describe service $GENERATED_NAME -n $LAB_NS
```

기본 Service에는 health check port와 HTTP listener port가 같이 보인다.

```bash
kubectl get service $GENERATED_NAME -n $LAB_NS -o jsonpath='{range .spec.ports[*]}{.name}{"\t"}{.port}{"\t"}{.targetPort}{"\n"}{end}'
```

Gateway status의 address도 확인한다.

```bash
export INGRESS_HOST=$(kubectl get gateway $GATEWAY_NAME -n $LAB_NS -o jsonpath='{.status.addresses[0].value}')
echo $INGRESS_HOST
```

## 4. 호출 테스트

```bash
curl -i -H 'Host: app.example.com' "http://$INGRESS_HOST/"
curl -i -H 'Host: app.example.com' "http://$INGRESS_HOST/api"
```

응답 예시는 다음과 같은 형태다.

```json
{
  "app": "web-v1",
  "method": "GET",
  "path": "/",
  "host": "app.example.com"
}
```

## 5. 기본 HPA/PDB 확인

upgrade나 node drain 시 gateway pod가 어떻게 보호되는지 확인한다.

```bash
kubectl get hpa $GENERATED_NAME -n $LAB_NS
kubectl get hpa $GENERATED_NAME -n $LAB_NS -o jsonpath='{.spec.minReplicas}{"\t"}{.spec.maxReplicas}{"\n"}'

kubectl get pdb $GENERATED_NAME -n $LAB_NS
kubectl get pdb $GENERATED_NAME -n $LAB_NS -o jsonpath='{.spec.minAvailable}{"\n"}'
```

기본값은 HPA min replicas 2, max replicas 5, PDB min available 1로 이해하면 된다. 이 값은 다음 실습에서 Gateway-level ConfigMap으로 조정한다.

## 6. 삭제 시 owner model 확인

선택 실습이다. Gateway를 삭제하면 generated resource도 같이 사라진다.

```bash
kubectl delete gateway $GATEWAY_NAME -n $LAB_NS
kubectl get deployment,service,hpa,pdb -n $LAB_NS | grep $GATEWAY_NAME || true
```

다음 실습을 계속하려면 Gateway를 다시 만든다.

```bash
kubectl apply -f spec/01-gateway.yaml
kubectl wait \
  --for=condition=programmed \
  gateways.gateway.networking.k8s.io $GATEWAY_NAME \
  -n $LAB_NS \
  --timeout=10m
```