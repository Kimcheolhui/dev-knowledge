# 01. Install And Control Plane

이 실습은 AKS application routing Gateway API implementation을 활성화하고, 실제로 어떤 control plane과 cluster-scoped 리소스가 생기는지 확인한다.

## 목표

- Managed Gateway API CRD가 AKS 관리형으로 설치됐는지 확인한다.
- `--enable-app-routing-istio`로 application routing Gateway API implementation을 활성화한다.
- `aks-istio-system` namespace, `istiod`, validating webhook, `approuting-istio` GatewayClass를 확인한다.
- AGC와 달리 별도 Azure L7 data plane이 아니라 cluster 내부 Istio/Envoy gateway workload를 관리하는 구조임을 확인한다.

## 0. 공통 변수

```bash
export CLUSTER='<cluster-name>'
export RESOURCE_GROUP='<resource-group-name>'
export LOCATION='<location>'
```

Azure CLI와 cluster context를 확인한다.

```bash
az --version
az aks show --resource-group $RESOURCE_GROUP --name $CLUSTER --query '{name:name,kubernetesVersion:kubernetesVersion,location:location}' -o table
az aks get-credentials --resource-group $RESOURCE_GROUP --name $CLUSTER --overwrite-existing
kubectl config current-context
```

## 1. 기존 충돌 가능성 확인

application routing Gateway API implementation은 AKS Istio service mesh add-on과 동시에 활성화할 수 없다.

```bash
az aks show \
  --resource-group $RESOURCE_GROUP \
  --name $CLUSTER \
  --query 'serviceMeshProfile' \
  -o json
```

기존 Istio CRD가 남아 있는지도 확인한다.

```bash
kubectl get crd -o name | grep -E 'istio\.io' || true
kubectl get gatewayclass istio --ignore-not-found
```

Istio custom resource를 더 이상 쓰지 않는 cluster에서만 CRD와 `GatewayClass istio`를 정리한다. CRD 삭제는 기존 `VirtualService`, `DestinationRule`, `AuthorizationPolicy`, `Telemetry` 같은 리소스도 함께 삭제할 수 있다. 먼저 남아 있는 custom resource와 CRD를 확인한다.

```bash
kubectl get virtualservice,destinationrule,authorizationpolicy,telemetry -A 2>/dev/null || true

ISTIO_CRDS=$(kubectl get crd -o name | grep -E 'istio\.io' || true)

if [ -n "$ISTIO_CRDS" ]; then
  printf '%s\n' "$ISTIO_CRDS"
fi
```

정말 삭제해도 되는 cluster라면 다음처럼 명시적으로 삭제한다.

```bash
if [ -n "$ISTIO_CRDS" ]; then
  printf '%s\n' "$ISTIO_CRDS" | xargs -r kubectl delete
fi

kubectl delete gatewayclass istio --ignore-not-found
```

## 2. Managed Gateway API CRD 활성화

기존 Gateway API CRD 상태를 본다.

```bash
kubectl get crd | grep 'gateway.networking.k8s.io' || true
```

Managed Gateway API를 활성화한다.

```bash
az aks update \
  --resource-group $RESOURCE_GROUP \
  --name $CLUSTER \
  --enable-gateway-api
```

CRD annotation을 확인한다.

```bash
kubectl get crd gateways.gateway.networking.k8s.io -o jsonpath='{.metadata.annotations.gateway\.networking\.k8s\.io/channel}{"\n"}'
kubectl get crd gateways.gateway.networking.k8s.io -o jsonpath='{.metadata.annotations.gateway\.networking\.k8s\.io/bundle-version}{"\n"}'
kubectl get crd gateways.gateway.networking.k8s.io -o jsonpath='{.metadata.labels.app\.kubernetes\.io/managed-by}{"\n"}'
```

기대값은 `standard`, AKS Kubernetes version에 맞는 bundle version, `aks` 관리 label이다.

## 3. application routing Gateway API implementation 활성화

```bash
az aks update \
  --resource-group $RESOURCE_GROUP \
  --name $CLUSTER \
  --enable-app-routing-istio
```

control plane pod를 확인한다.

```bash
kubectl get pods -n aks-istio-system -o wide
kubectl get deployment,hpa,pdb -n aks-istio-system
```

validating webhook을 확인한다.

```bash
kubectl get validatingwebhookconfiguration | grep azure-service-mesh || true
kubectl get mutatingwebhookconfiguration | grep azure-service-mesh || true
```

GatewayClass를 확인한다.

```bash
kubectl get gatewayclass
kubectl get gatewayclass approuting-istio -o yaml
```

`approuting-istio`가 보여야 한다.

## 4. GatewayClass 기본 ConfigMap 확인

Managed Gateway API CRD와 app routing Istio가 함께 활성화되면 AKS가 `istio-gateway-class-defaults` ConfigMap을 만든다.

```bash
kubectl get cm -n aks-istio-system
kubectl get cm istio-gateway-class-defaults -n aks-istio-system -o yaml
```

기본적으로 gateway별 HPA/PDB 설정이 들어 있다.

```bash
kubectl get cm istio-gateway-class-defaults -n aks-istio-system -o jsonpath='{.data.horizontalPodAutoscaler}{"\n"}'
kubectl get cm istio-gateway-class-defaults -n aks-istio-system -o jsonpath='{.data.podDisruptionBudget}{"\n"}'
```

이 ConfigMap은 AKS가 provision하고 reconcile한다. 전체 GatewayClass 기본값을 바꾸는 경우를 제외하면, 실습에서는 Gateway별 ConfigMap을 사용하는 편이 변경 범위를 좁히기 쉽다.

## 5. AGC와의 운영 차이 확인

AGC는 Azure 쪽 Application Gateway for Containers data plane과 ALB Controller 권한/RBAC를 함께 본다. 반면 application routing Gateway API implementation은 다음 Kubernetes 리소스를 먼저 본다.

```bash
kubectl get gatewayclass approuting-istio
kubectl get pods -n aks-istio-system
kubectl get cm istio-gateway-class-defaults -n aks-istio-system
```

아직 `Gateway`를 만들지 않았기 때문에 gateway data plane pod는 없다. 다음 실습에서 `Gateway`를 만들면 해당 namespace에 `Deployment`, `Service`, `HPA`, `PDB`가 자동 생성된다.