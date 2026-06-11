# AKS Application Routing Gateway API Implementation

작성일: 2026-06-06

AKS application routing Gateway API implementation은 AKS application routing add-on의 Gateway API 기반 ingress 구현체다. 기존 managed NGINX application routing add-on이 legacy `Ingress` API 중심이었다면, 이 구현체는 Kubernetes Gateway API의 `GatewayClass`, `Gateway`, `HTTPRoute`를 사용해 ingress 트래픽을 관리한다. 내부적으로 Istio control plane을 배포하지만, 전체 service mesh를 제공하는 AKS Istio service mesh add-on과는 목적과 지원 범위가 다르다.

공식 문서는 [Configure ingress with the Kubernetes Gateway API via the application routing add-on](https://learn.microsoft.com/en-us/azure/aks/app-routing-gateway-api), Gateway API CRD 관리는 [Install Managed Gateway API CRDs on AKS](https://learn.microsoft.com/en-us/azure/aks/managed-gateway-api), TLS 구성은 [Secure ingress traffic with the application routing Gateway API implementation](https://learn.microsoft.com/en-us/azure/aks/app-routing-gateway-api-tls)를 기준으로 한다.

## 결론 요약

AKS application routing Gateway API implementation은 AKS에서 가장 “AKS 관리형 ingress add-on”에 가까운 Gateway API 선택지다. `gatewayClassName: approuting-istio`를 사용하며, `Gateway`를 만들면 AKS가 관리하는 Istio control plane이 gateway `Deployment`, `Service`, `HorizontalPodAutoscaler`, `PodDisruptionBudget` 같은 Kubernetes 리소스를 자동으로 만든다.

이 구현체는 managed NGINX application routing add-on의 장기 대체 경로로 보기 좋다. 다만 전체 Istio service mesh가 아니며, sidecar injection, Istio CRD 기반 mesh traffic management, egress traffic management는 지원하지 않는다. 또한 Azure DNS와 TLS 인증서 자동 관리 기능은 Gateway API 경로에서 기존 NGINX application routing add-on과 동일하게 제공되지 않는다. TLS termination은 Azure Key Vault + Secrets Store CSI Driver로 Kubernetes TLS Secret을 동기화한 뒤 Gateway에서 참조하는 방식으로 구성한다.

## 언제 선택할까

우선 검토할 상황:

- AKS 공식 관리형 경로로 Gateway API ingress를 사용하고 싶다.
- managed NGINX application routing add-on에서 Gateway API로 이전할 계획이 있다.
- AGC(Application Gateway for Containers)처럼 Azure 외부 L7 데이터 플레인을 쓰기보다, 클러스터 안의 gateway workload와 Azure Load Balancer Service 조합을 선호한다.
- platform team이 `Gateway`를 관리하고 application team이 `HTTPRoute`를 붙이는 Gateway API 운영 모델을 도입하고 싶다.
- Istio 전체 mesh는 필요 없고 north-south ingress만 Gateway API로 관리하고 싶다.
- AKS가 control plane lifecycle과 기본 gateway HPA/PDB 구성을 관리해주는 방식을 선호한다.

신중히 볼 상황:

- WAF, frontend/backend mTLS, Azure L7 managed data plane 같은 AGC 기능이 필요하다.
- 전체 service mesh, sidecar injection, Istio CRD, east-west traffic management가 필요하다. 이 경우 AKS Istio service mesh add-on을 검토한다.
- Gateway API egress traffic management가 필요하다.
- `TLSRoute` 기반 SNI passthrough가 지금 당장 필요하다. 공식 문서 기준 `asm-1-29`에서는 지원되지 않고, `asm-1-30` 이후 지원 예정이다.
- Azure DNS와 TLS 인증서 자동 관리를 managed NGINX application routing add-on처럼 기대한다.
- `Gateway`로 생성되는 Deployment/Service/HPA/PDB를 자유롭게 모두 커스터마이징해야 한다. 커스터마이징은 allow list 안에서만 지원된다.

## 아키텍처

이 구현체는 이름 때문에 헷갈리기 쉽다. 핵심은 “application routing add-on이 Istio control plane을 사용해 Gateway API ingress용 인프라를 관리한다”는 것이다.

| 구성 요소                               | 위치                           | 역할                                                                                                              |
| --------------------------------------- | ------------------------------ | ----------------------------------------------------------------------------------------------------------------- |
| Managed Gateway API CRDs                | AKS cluster                    | `GatewayClass`, `Gateway`, `HTTPRoute`, `ReferenceGrant` 등 Gateway API CRD를 AKS가 관리한다.                     |
| Application routing Istio control plane | `aks-istio-system` namespace   | Gateway API 리소스를 reconcile하고 gateway workload를 생성/관리한다.                                              |
| `GatewayClass`                          | cluster-scoped                 | `approuting-istio` class가 application routing Gateway API implementation을 가리킨다.                             |
| `Gateway`                               | application/platform namespace | listener, protocol, route attachment 정책을 선언한다.                                                             |
| Generated gateway resources             | Gateway namespace              | Gateway별 `Deployment`, `Service`, `HPA`, `PDB`가 생성된다. 기본 이름은 `<gateway-name>-approuting-istio` 형태다. |
| `HTTPRoute`                             | application namespace          | Gateway에 붙는 L7 routing rule이다.                                                                               |

요청 흐름은 다음과 같다.

1. 사용자가 `gatewayClassName: approuting-istio`인 `Gateway`를 만든다.
2. AKS application routing Istio control plane이 해당 Gateway를 reconcile한다.
3. Gateway에 대응하는 gateway `Deployment`, `Service`, `HPA`, `PDB`가 생성된다.
4. `Service`는 기본적으로 external `LoadBalancer` 형태로 생성되어 Azure Load Balancer frontend IP를 받는다.
5. `HTTPRoute`가 Gateway listener에 attach되고, Envoy/Istio gateway workload에 routing config가 반영된다.
6. 외부 클라이언트는 Azure Load Balancer IP로 들어오고, gateway pod가 HTTP routing을 수행한 뒤 backend Service로 전달한다.

## Gateway API 지원 범위

공식 문서 기준 이 구현체는 Kubernetes Gateway API를 ingress traffic management 용도로 사용한다.

| 리소스             | 상태                           | 메모                                                                                                       |
| ------------------ | ------------------------------ | ---------------------------------------------------------------------------------------------------------- |
| `GatewayClass`     | 지원                           | class 이름은 `approuting-istio`다.                                                                         |
| `Gateway`          | 지원                           | HTTP/HTTPS listener와 Gateway resource customization을 지원한다.                                           |
| `HTTPRoute`        | 지원                           | path/hostname 기반 routing, backend reference를 사용한다.                                                  |
| `ReferenceGrant`   | Managed Gateway API CRD에 포함 | cross-namespace reference를 쓸 때 Gateway API 표준 권한 모델을 따른다. 실제 지원 범위는 실습으로 확인한다. |
| `TLSRoute`         | 제한적/버전 의존               | 공식 문서 기준 SNI passthrough는 `asm-1-29`에서 미지원이고 `asm-1-30` 이후 지원 예정이다.                  |
| egress Gateway API | 미지원                         | application routing Gateway API implementation은 egress traffic management를 지원하지 않는다.              |

Managed Gateway API CRD bundle version은 AKS Kubernetes minor version에 따라 달라진다. 예를 들어 공식 Managed Gateway API 문서 기준 `v1.35.x`는 Gateway API bundle `v1.4.1`, `v1.36.0+`는 `v1.5.1`과 매핑된다. AKS cluster upgrade 시 Managed Gateway API CRD도 호환되는 bundle version으로 자동 업그레이드될 수 있다.

## AKS Istio service mesh add-on과의 차이

둘 다 Istio를 사용하지만 목적이 다르다.

| 항목                      | Application routing Gateway API implementation | AKS Istio service mesh add-on                                       |
| ------------------------- | ---------------------------------------------- | ------------------------------------------------------------------- |
| 주 목적                   | Gateway API ingress infrastructure 관리        | 전체 service mesh 제공                                              |
| GatewayClass              | `approuting-istio`                             | `istio`                                                             |
| Sidecar injection         | 지원하지 않음                                  | 지원                                                                |
| Istio CRD                 | 지원하지 않음                                  | `VirtualService`, `DestinationRule`, `AuthorizationPolicy` 등 지원  |
| Revision model            | revisioned 방식 아님, in-place upgrade         | revision 기반, minor upgrade는 canary upgrade 가능                  |
| egress traffic management | 미지원                                         | Istio add-on 기능으로 별도 지원                                     |
| 동시 사용                 | Istio service mesh add-on과 동시에 enable 불가 | application routing Gateway API implementation과 동시에 enable 불가 |

공식 문서에 따르면 두 add-on은 동시에 활성화할 수 없다. Istio service mesh add-on에서 application routing Gateway API implementation으로 전환할 때는 Istio add-on을 비활성화한 뒤 남아 있는 Istio CRD와 `GatewayClass istio`를 정리해야 할 수 있다. 단, 기존 `VirtualService`, `DestinationRule` 같은 Istio custom resource가 있다면 CRD 삭제와 함께 해당 리소스도 삭제되므로 주의해야 한다.

## 배포 전략

이 구현체의 배포 전략은 단순하다. AGC처럼 BYO Azure data plane과 ALB Controller managed deployment를 나누지 않는다.

- AKS cluster에 Managed Gateway API CRD를 활성화한다.
- application routing Gateway API implementation을 활성화한다.
- `approuting-istio` GatewayClass를 사용하는 `Gateway`와 `HTTPRoute`를 작성한다.
- Gateway별로 생성되는 Kubernetes `Deployment`, `Service`, `HPA`, `PDB`를 Kubernetes 관점에서 운영한다.

즉, 데이터 플레인은 Azure 외부 L7 service가 아니라 클러스터 안의 Istio/Envoy gateway workload다. 외부 노출은 일반적으로 Kubernetes `Service` type `LoadBalancer`를 통해 Azure Load Balancer가 담당한다.

## AKS 전제 조건

공식 문서 기준 주요 전제 조건은 다음과 같다.

- Azure CLI `2.86.0` 이상이 필요하다.
- Managed Gateway API CRD를 사용해야 한다. self-managed Gateway API CRD와 함께 쓰는 방식은 지원되지 않는다.
- application routing Gateway API implementation과 AKS Istio service mesh add-on은 동시에 활성화할 수 없다.
- 기존 Istio add-on 또는 self-managed Istio의 CRD가 남아 있으면 application routing Gateway API control plane이 시작하지 못할 수 있다.
- TLS termination을 위해 Azure Key Vault를 사용할 경우 Azure Key Vault provider for Secrets Store CSI Driver add-on과 Key Vault 접근 권한이 필요하다.
- 내부 LoadBalancer, Service annotation, Gateway generated resource customization은 allow list와 Azure Load Balancer annotation 제약을 따른다.

## 설치 가이드

### 0. 공통 환경 변수

```bash
export CLUSTER='<cluster-name>'
export RESOURCE_GROUP='<resource-group-name>'
export LOCATION='<location>'
```

Azure CLI 버전을 확인한다.

```bash
az --version
```

`azure-cli`가 `2.86.0`보다 낮으면 업그레이드한다.

```bash
az upgrade
```

### 1. 기존 Gateway API CRD 상태 확인

Managed Gateway API를 활성화하기 전에 기존 self-managed Gateway API CRD가 있는지 확인한다.

```bash
kubectl get crd | grep 'gateway.networking.k8s.io' || true
```

기존 CRD가 있다면 standard channel인지, experimental CRD가 섞여 있는지 확인한다. Managed Gateway API 문서 기준 experimental channel CRD는 허용되지 않는다.

```bash
kubectl get crd gateways.gateway.networking.k8s.io -o jsonpath='{.metadata.annotations.gateway\.networking\.k8s\.io/channel}'
```

### 2. Managed Gateway API CRD 활성화

기존 클러스터에서 활성화한다.

```bash
az aks update \
  --resource-group $RESOURCE_GROUP \
  --name $CLUSTER \
  --enable-gateway-api
```

CRD 설치를 확인한다.

```bash
kubectl get crds | grep 'gateway.networking.k8s.io'
kubectl get crd gateways.gateway.networking.k8s.io -ojsonpath='{.metadata.annotations}' | jq
```

`app.kubernetes.io/managed-by: aks`, `gateway.networking.k8s.io/channel: standard`, `gateway.networking.k8s.io/bundle-version`을 확인한다.

### 3. application routing Gateway API implementation 활성화

기존 클러스터에 활성화한다.

```bash
az aks update \
  --resource-group $RESOURCE_GROUP \
  --name $CLUSTER \
  --enable-app-routing-istio
```

새 클러스터 생성 시 함께 활성화할 수도 있다.

```bash
az aks create \
  --resource-group $RESOURCE_GROUP \
  --name $CLUSTER \
  --enable-gateway-api \
  --enable-app-routing-istio
```

### 4. control plane 확인

`aks-istio-system` namespace의 `istiod` pod를 확인한다.

```bash
kubectl get pods -n aks-istio-system
```

ValidatingWebhookConfiguration도 확인한다.

```bash
kubectl get validatingwebhookconfiguration | grep azure-service-mesh || true
```

Managed Gateway API CRD와 함께 활성화된 경우 `istio-gateway-class-defaults` ConfigMap이 생성된다.

```bash
kubectl get cm -n aks-istio-system
kubectl get cm istio-gateway-class-defaults -n aks-istio-system -o yaml
```

GatewayClass를 확인한다.

```bash
kubectl get gatewayclass
kubectl get gatewayclass approuting-istio -o yaml
```

### 5. 샘플 애플리케이션 배포

공식 문서는 Istio `httpbin` sample을 사용한다.

```bash
export ISTIO_RELEASE='release-1.27'
kubectl apply -f https://raw.githubusercontent.com/istio/istio/$ISTIO_RELEASE/samples/httpbin/httpbin.yaml
kubectl get pods,svc
```

### 6. Gateway와 HTTPRoute 생성

`gatewayClassName`은 `approuting-istio`를 사용한다.

```bash
kubectl apply -f - <<'EOF'
apiVersion: gateway.networking.k8s.io/v1
kind: Gateway
metadata:
  name: httpbin-gateway
spec:
  gatewayClassName: approuting-istio
  listeners:
  - name: http
    port: 80
    protocol: HTTP
    allowedRoutes:
      namespaces:
        from: Same
---
apiVersion: gateway.networking.k8s.io/v1
kind: HTTPRoute
metadata:
  name: httpbin
spec:
  parentRefs:
  - name: httpbin-gateway
  hostnames:
  - httpbin.example.com
  rules:
  - matches:
    - path:
        type: PathPrefix
        value: /get
    backendRefs:
    - name: httpbin
      port: 8000
EOF
```

생성된 gateway resources를 확인한다.

```bash
kubectl get gateway httpbin-gateway -o yaml
kubectl get deployment httpbin-gateway-approuting-istio
kubectl get service httpbin-gateway-approuting-istio
kubectl get hpa httpbin-gateway-approuting-istio
kubectl get pdb httpbin-gateway-approuting-istio
```

공식 예제 기준 기본으로 `Deployment`, `Service`, `HPA`, `PDB`가 만들어진다. `Service`는 external `LoadBalancer`로 생성되며, 필요하면 Gateway의 `spec.infrastructure.annotations`로 internal Load Balancer annotation을 추가할 수 있다.

### 7. 호출 테스트

```bash
kubectl wait --for=condition=programmed gateways.gateway.networking.k8s.io httpbin-gateway

export INGRESS_HOST=$(kubectl get gateways.gateway.networking.k8s.io httpbin-gateway -ojsonpath='{.status.addresses[0].value}')

curl -s -I -HHost:httpbin.example.com "http://$INGRESS_HOST/get"
```

`HTTP/1.1 200 OK` 또는 이에 준하는 200 응답이 나오면 정상이다.

## TLS 구성

Gateway API 기반 application routing은 기존 NGINX application routing add-on의 Azure DNS/TLS certificate management 경로를 그대로 지원하지 않는다. 공식 TLS 문서는 Azure Key Vault와 Secrets Store CSI Driver add-on을 사용해 TLS Secret을 cluster에 동기화하고, Gateway listener가 해당 Secret을 참조하는 흐름을 사용한다.

구성 흐름은 다음과 같다.

1. Azure Key Vault 생성 또는 기존 Key Vault 사용
2. Azure Key Vault provider for Secrets Store CSI Driver add-on 활성화
3. CSI Driver add-on managed identity에 Key Vault secret 접근 권한 부여
4. 인증서 private key와 certificate를 Key Vault secret 또는 certificate로 저장
5. `SecretProviderClass` 작성
6. Secret sync용 pod 배포
7. Kubernetes TLS Secret 생성 확인
8. HTTPS listener가 있는 Gateway 작성
9. HTTPS `HTTPRoute` 작성 및 호출 검증

Gateway 예시는 다음과 같다.

```yaml
apiVersion: gateway.networking.k8s.io/v1
kind: Gateway
metadata:
  name: httpbin-gateway
spec:
  gatewayClassName: approuting-istio
  listeners:
    - name: https
      hostname: httpbin.example.com
      port: 443
      protocol: HTTPS
      tls:
        mode: Terminate
        certificateRefs:
          - name: httpbin-credential
      allowedRoutes:
        namespaces:
          from: Selector
          selector:
            matchLabels:
              kubernetes.io/metadata.name: default
```

TLS 세부 실습은 [Secure ingress traffic with the application routing Gateway API implementation](https://learn.microsoft.com/en-us/azure/aks/app-routing-gateway-api-tls)를 따른다.

## 주요 기능

- AKS 관리형 Gateway API ingress 구현체
- `approuting-istio` GatewayClass
- `Gateway` 기반 automated gateway deployment
- Gateway별 `Deployment`, `Service`, `HPA`, `PDB` 자동 생성
- HTTP/HTTPS ingress traffic management
- Azure Load Balancer Service annotation을 통한 internal/external LoadBalancer 구성
- GatewayClass-level 및 Gateway-level ConfigMap customization
- Control plane HPA customization
- TLS termination with Kubernetes Secret
- Azure Key Vault + Secrets Store CSI Driver를 통한 TLS secret sync

운영 모델 중심 실습은 [02-aks-app-routing-gateway-api-labs/README.md](02-aks-app-routing-gateway-api-labs/README.md)에 정리했다. 기본 라우팅 기능 반복보다 generated gateway resources, HPA/PDB, internal LoadBalancer, ConfigMap customization, 로그/cleanup 차이를 확인하는 흐름이다.

## 제약 및 주의사항

- AKS Istio service mesh add-on과 동시에 활성화할 수 없다.
- self-managed Gateway API CRD와 함께 쓰는 방식은 지원되지 않는다.
- sidecar injection과 Istio CRD는 지원하지 않는다.
- egress traffic management는 지원하지 않는다.
- Azure DNS와 TLS certificate management는 Gateway API 경로에서 현재 지원되지 않는다.
- `TLSRoute` 기반 SNI passthrough는 Istio 1.30 지원 전까지 제한된다.
- Gateway generated resource customization은 allow list 안에서만 가능하다.
- `istio-gateway-class-defaults` ConfigMap은 AKS가 관리하므로 기존 self-managed ConfigMap과 충돌하지 않게 해야 한다.
- in-place upgrade 방식이므로 upgrade 중 traffic disruption 가능성을 고려한다.

## 관측성 및 디버깅

우선 Gateway API status condition을 본다.

```bash
kubectl get gateway -A
kubectl describe gateway httpbin-gateway
kubectl describe httproute httpbin
```

중요 condition:

- `Accepted`: Gateway 또는 Route가 controller에 의해 수락되었는지
- `Programmed`: 실제 gateway workload/config에 반영되었는지
- `ResolvedRefs`: backend Service, Secret, ReferenceGrant 등 참조가 유효한지

생성된 gateway workload를 확인한다.

```bash
kubectl get deployment,service,hpa,pdb | grep httpbin-gateway
kubectl logs deployment/httpbin-gateway-approuting-istio --tail=100
```

Control plane 상태를 확인한다.

```bash
kubectl get pods -n aks-istio-system
kubectl logs -n aks-istio-system deployment/istiod --tail=200
```

요청 단위 access log가 필요하면 먼저 Gateway pod 로그와 cluster-level container log 수집 경로를 확인한다. AKS Istio service mesh add-on 문서에는 `Telemetry` API를 사용하는 Gateway access log 예제가 있지만, application routing Gateway API implementation은 공식 문서 기준 sidecar injection과 Istio CRD support를 제공하지 않으므로 `Telemetry` 리소스를 이 구현체의 기본 관측 경로로 전제하지 않는다.

## 운영 가이드

### 업그레이드

application routing Gateway API implementation의 Istio control plane은 AKS cluster Kubernetes version에 맞는 최대 supported Istio minor version을 기준으로 배포/업그레이드된다. patch version upgrade는 AKS release 일부로 자동 적용된다. minor version upgrade는 AKS cluster upgrade 또는 새 Istio version rollout에 따라 in-place로 진행된다.

공식 문서는 upgrade 중 traffic disruption 가능성을 언급하며, 이를 줄이기 위해 각 Gateway에 기본 HPA와 PDB를 둔다. 기본값은 다음과 같이 이해할 수 있다.

- Gateway `HPA`: min replicas 2, max replicas 5, CPU 80% 기준
- Gateway `PDB`: min available 1
- Control plane `istiod` HPA: min replicas 2, max replicas 5, CPU 80% 기준

### Control plane HPA 조정

`istiod` HPA는 직접 patch할 수 있다. 단, PDB와 충돌하지 않도록 `minReplicas`를 기본값 2 아래로 낮출 수 없다.

```bash
kubectl patch hpa istiod -n aks-istio-system --type merge --patch '{"spec": {"minReplicas": 3, "maxReplicas": 6}}'
```

### Gateway resource customization

Gateway가 생성하는 `Deployment`, `Service`, `HPA`, `PDB`는 annotation과 ConfigMap으로 커스터마이징할 수 있다. 다만 AKS add-on managed webhook이 allow list 밖 필드를 차단한다.

GatewayClass-level 기본 ConfigMap은 `aks-istio-system` namespace의 `istio-gateway-class-defaults`다.

```bash
kubectl get cm istio-gateway-class-defaults -n aks-istio-system -o yaml
```

Gateway별 ConfigMap을 사용하려면 `Gateway.spec.infrastructure.parametersRef`로 ConfigMap을 참조한다.

```yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: gw-options
data:
  horizontalPodAutoscaler: |
    spec:
      minReplicas: 2
      maxReplicas: 4
  deployment: |
    metadata:
      labels:
        example.com/gateway-config: per-gateway
---
apiVersion: gateway.networking.k8s.io/v1
kind: Gateway
metadata:
  name: httpbin-gateway
spec:
  infrastructure:
    parametersRef:
      group: ""
      kind: ConfigMap
      name: gw-options
  gatewayClassName: approuting-istio
  listeners:
    - name: http
      port: 80
      protocol: HTTP
```

### Internal LoadBalancer

Gateway의 `spec.infrastructure.annotations`에 Azure Load Balancer annotation을 추가해 internal Load Balancer를 만들 수 있다.

```yaml
spec:
  infrastructure:
    annotations:
      service.beta.kubernetes.io/azure-load-balancer-internal: "true"
      service.beta.kubernetes.io/azure-load-balancer-internal-subnet: "my-subnet"
```

## 비용

이 구현체는 AGC처럼 별도의 Application Gateway for Containers Azure L7 resource 비용을 발생시키는 모델이 아니다. 다만 다음 비용은 고려해야 한다.

- Gateway pod가 사용하는 AKS node compute resource
- Gateway `Service` type `LoadBalancer`로 생성되는 Azure Load Balancer/Public IP 관련 비용
- Azure Key Vault, Secrets Store CSI Driver, DNS, Log Analytics/Managed Prometheus 등 부가 리소스 비용
- 트래픽 egress 비용

실제 비용은 cluster SKU, node pool sizing, public IP/LB 사용, log 수집량에 따라 달라진다.

## 삭제

실습 리소스를 먼저 삭제한다.

```bash
kubectl delete gateways.gateway.networking.k8s.io httpbin-gateway --ignore-not-found
kubectl delete httproute httpbin --ignore-not-found
kubectl delete configmap gw-options --ignore-not-found
```

TLS 실습을 했다면 SecretProviderClass, sync pod, Secret도 삭제한다.

```bash
kubectl delete secret httpbin-credential --ignore-not-found
kubectl delete pod secrets-store-sync-httpbin --ignore-not-found
kubectl delete secretproviderclass httpbin-credential-spc --ignore-not-found
```

application routing Gateway API implementation을 비활성화한다.

```bash
az aks update \
  --resource-group $RESOURCE_GROUP \
  --name $CLUSTER \
  --disable-app-routing-istio
```

Managed Gateway API CRD도 더 이상 필요 없으면 비활성화한다. 다른 Gateway API implementation이 같은 CRD를 쓰고 있다면 삭제하면 안 된다.

```bash
az aks update \
  --resource-group $RESOURCE_GROUP \
  --name $CLUSTER \
  --disable-gateway-api
```

## AGC와 비교한 위치

| 항목                  | Application routing Gateway API                    | Application Gateway for Containers          |
| --------------------- | -------------------------------------------------- | ------------------------------------------- |
| 데이터 플레인         | AKS cluster 내부 Istio/Envoy gateway pod           | Azure managed L7 data plane                 |
| 노출 방식             | Kubernetes `Service` type `LoadBalancer`           | AGC frontend/association                    |
| GatewayClass          | `approuting-istio`                                 | `azure-alb-external`                        |
| Azure WAF             | 기본 기능 아님                                     | 지원                                        |
| Frontend/backend mTLS | 기본 기능 아님                                     | 지원                                        |
| 운영 복잡도           | AKS add-on 중심, Kubernetes workload 운영 필요     | Azure L7 resource lifecycle도 함께 관리     |
| 적합한 상황           | AKS 관리형 Gateway API ingress, managed NGINX 대체 | Azure L7/WAF/mTLS/AGC 기능이 필요한 ingress |

요약하면, application routing Gateway API implementation은 AKS ingress add-on의 Gateway API 경로이고, AGC는 Azure L7 load balancing 제품군의 Gateway API 경로다.

## 팩트체크 메모

- `AKS Istio service mesh add-on`과 동시에 사용할 수 없다.
- `application routing Gateway API implementation`은 내부적으로 Istio control plane을 쓰지만 sidecar injection과 Istio CRD를 지원하지 않는다.
- 공식 AKS release notes 기준 Gateway API-based ingress for application routing add-on은 GA로 공지되었다. 다만 각 지역/클러스터 버전의 rollout 상태는 AKS release tracker와 `az` 명령으로 확인한다.
- 예전 `istio-about` 문서에는 Gateway API가 아직 지원되지 않는다는 제한 문구가 남아 있을 수 있다. 최신 Gateway API 문서는 `istio-gateway-api`와 `app-routing-gateway-api`를 기준으로 본다.
- TLS 자동화는 managed NGINX application routing add-on과 동일한 Azure DNS/TLS 자동 관리 경로가 아니라, Key Vault + CSI sync + Kubernetes Secret 참조 흐름이다.

## 레퍼런스

- [Configure ingress with the Kubernetes Gateway API via the application routing add-on](https://learn.microsoft.com/en-us/azure/aks/app-routing-gateway-api)
- [Install Managed Gateway API CRDs on AKS](https://learn.microsoft.com/en-us/azure/aks/managed-gateway-api)
- [Secure ingress traffic with the application routing Gateway API implementation](https://learn.microsoft.com/en-us/azure/aks/app-routing-gateway-api-tls)
- [Configure Istio ingress with the Kubernetes Gateway API for AKS](https://learn.microsoft.com/en-us/azure/aks/istio-gateway-api)
- [Istio-based service mesh add-on for AKS](https://learn.microsoft.com/en-us/azure/aks/istio-about)
- [Support policy for Istio-based service mesh add-on for AKS](https://learn.microsoft.com/en-us/azure/aks/istio-support-policy)
- [Managed NGINX ingress with the application routing add-on](https://learn.microsoft.com/en-us/azure/aks/app-routing)
