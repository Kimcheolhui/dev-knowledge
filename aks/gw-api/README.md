# AKS Gateway API Implementation Options

작성일: 2026-06-04

이 문서는 AKS에서 Kubernetes Gateway API를 적용할 때 검토할 구현체 후보를 간단히 정리하는 인덱스다. AKS 관리형 후보는 공식 지원 경로로 유지하고, 오픈소스 진영은 시장에서 이미 어느 정도 검증된 후보만 남긴다. 설치 방법, 세부 장단점, 운영 가이드, 실습 기록은 구현체별 개별 문서에 작성한다.

## 범위

- 주 대상은 AKS 클러스터의 north-south ingress 트래픽이다.
- Kubernetes Gateway API의 `GatewayClass`, `Gateway`, `HTTPRoute` 기반 구성을 우선 검토한다.
- 오픈소스 후보는 Gateway API 지원 여부만으로 넣지 않는다. 기반 기술, 프로젝트/제품의 실제 운영 채택, 생태계 성숙도를 함께 본다.
- 너무 신생이거나 특정 use case 중심인 구현체는 제외 후보로 둔다.

## 먼저 알아둘 점

- Gateway API CRD와 Gateway API 구현체는 별개다. AKS에는 Managed Gateway API CRD 관리 기능이 있고, 일부 AKS 애드온은 이를 전제로 동작한다.
- 기존 `Ingress` 기반 NGINX 운영과 Gateway API 운영은 리소스 모델이 다르다. `IngressClass`와 annotation 중심 운영을 그대로 옮기는 방식보다 `GatewayClass`, `Gateway`, `HTTPRoute`, `ReferenceGrant`, policy attachment 중심으로 다시 설계해야 한다.
- AKS의 managed NGINX application routing add-on은 legacy Ingress API 기반이다. Gateway API 구현체 검토에서는 제외한다.
- Envoy, NGINX처럼 기반 기술이 성숙했더라도 해당 Gateway API 구현체 자체의 시장 검증 정도는 별도로 본다.

## 검증 후보

| 구현체                                              | 유형                              | 기본 GatewayClass          | 남기는 이유                                                                                                                                                                              | 개별 문서                                  |
| --------------------------------------------------- | --------------------------------- | -------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------ |
| Application Gateway for Containers + ALB Controller | AKS/Azure 관리형 L7 데이터 플레인 | `azure-alb-external`       | Azure 공식 Gateway API 경로다. Azure L7 load balancer, WAF, mTLS, autoscaling, Azure 리소스 통합이 필요한 경우에 우선 검토한다.                                                          | `01-application-gateway-for-containers.md` |
| AKS application routing Gateway API implementation  | AKS 관리형 애드온                 | `approuting-istio`         | AKS가 Istio control plane 기반 Gateway API ingress를 관리한다. managed NGINX add-on의 장기 대체 후보로 보기 좋다.                                                                        | `02-aks-app-routing-gateway-api.md`        |
| AKS Istio service mesh add-on                       | AKS 관리형 service mesh           | `istio`                    | AKS 공식 Istio add-on이다. 전체 service mesh가 필요하고 Gateway API ingress도 함께 검토하려는 경우에 적합하다. application routing Gateway API implementation과는 동시에 사용할 수 없다. | `03-aks-istio-service-mesh-gateway-api.md` |
| Istio self-managed                                  | 오픈소스 service mesh/gateway     | `istio`                    | CNCF Graduated 프로젝트이고 production service mesh로 채택이 많다. Gateway API ingress와 mesh traffic management를 함께 검토할 수 있다.                                                  | `04-istio-self-managed-gateway-api.md`     |
| Cilium Gateway API                                  | CNI/Service Mesh 통합형 OSS       | `cilium`                   | Cilium 자체가 CNCF Graduated이고 Kubernetes networking, security, observability 영역에서 실사용 기반이 크다. Cilium 기반 클러스터라면 Gateway API까지 같은 스택으로 묶을 수 있다.        | `05-cilium-gateway-api.md`                 |
| Kong Gateway / KIC / Gateway Operator               | API Gateway 제품군                | 구성에 따름                | Kong은 API Gateway 시장에서 오래 검증된 제품군이다. 인증, rate limiting, plugin, API 관리 요구가 있으면 Gateway API 후보로 볼 가치가 있다.                                               | `06-kong-gateway-api.md`                   |
| Traefik Proxy                                       | 오픈소스 reverse proxy            | `traefik` 또는 구성에 따름 | Kubernetes ingress/reverse proxy로 실사용이 많고 운영 모델이 비교적 단순하다. 경량 또는 중소 규모 Gateway API 후보로 검토한다.                                                           | `07-traefik-gateway-api.md`                |

## 제외 후보

| 후보                                                   | 제외 이유                                                                                                                         |
| ------------------------------------------------------ | --------------------------------------------------------------------------------------------------------------------------------- |
| Envoy Gateway                                          | Envoy 자체는 충분히 검증됐지만 Envoy Gateway 구현체 자체는 아직 주류 ingress controller 수준으로 시장 검증됐다고 보기 어렵다.     |
| NGINX Gateway Fabric                                   | NGINX 자체는 검증됐지만 Gateway Fabric은 ingress-nginx만큼 운영 사례가 쌓인 구현체는 아니다.                                      |
| Contour                                                | 오래된 Envoy 기반 ingress controller지만 신규 Gateway API 후보로는 채택 흐름이 약하고 Envoy Gateway/Istio/Cilium과 역할이 겹친다. |
| AKS managed NGINX application routing add-on           | Gateway API 구현체가 아니라 legacy Ingress 기반이다.                                                                              |
| HAProxy Ingress                                        | HAProxy 자체는 성숙하지만 AKS Gateway API 검토에서 메인 후보로 둘 만큼의 생태계 압도감은 약하다.                                  |
| Gloo Gateway / kgateway                                | 기능은 강하지만 제품군 성격이 강하다. 이미 Solo.io 생태계를 쓰는 경우에만 별도 검토한다.                                          |
| Linkerd                                                | Gateway API는 주로 mesh/GAMMA 쪽이며 north-south ingress 후보로는 우선순위가 낮다.                                                |
| Calico Gateway API                                     | Calico 네트워크 스택 채택 여부와 강하게 결합된다. Gateway API ingress 후보로는 Cilium보다 우선순위가 낮다.                        |
| Varnish Gateway, Airlock Microgateway, Agentgateway 등 | 특정 use case 또는 제품 성격이 강해서 일반적인 AKS Gateway API 검증 후보에서는 제외한다.                                          |
