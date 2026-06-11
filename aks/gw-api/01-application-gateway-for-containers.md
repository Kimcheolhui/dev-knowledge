# Application Gateway for Containers on AKS

작성일: 2026-06-04

Azure Application Gateway for Containers(AGC)는 AKS/Kubernetes 워크로드 앞단에 두는 Azure 관리형 L7 애플리케이션 로드밸런서다. Kubernetes 안에는 ALB(Application Load Balancer) Controller가 동작하고, 실제 L7 데이터 플레인은 AKS 클러스터 밖 Azure 리소스로 존재한다. 사용자는 `Gateway`, `HTTPRoute` 같은 Gateway API 리소스를 선언하고, ALB Controller가 이를 Application Gateway for Containers 구성으로 반영한다.

공식 개요는 [What is Application Gateway for Containers?](https://learn.microsoft.com/en-us/azure/application-gateway/for-containers/overview), 구성 요소 설명은 [Application Gateway for Containers components](https://learn.microsoft.com/en-us/azure/application-gateway/for-containers/application-gateway-for-containers-components)를 기준으로 한다.

## 결론 요약

AGC는 AKS에서 Azure 네이티브 L7 ingress를 Gateway API 방식으로 운영하고 싶을 때 가장 먼저 검토할 만한 선택지다. 특히 WAF, TLS termination, end-to-end TLS, frontend/backend mTLS, weighted traffic splitting, gRPC, HTTP/2, WebSocket, URL/header rewrite 같은 Azure L7 기능이 필요하고, 프록시 데이터 플레인을 AKS 노드 위에서 직접 운영하고 싶지 않을 때 잘 맞는다.

다만 모든 환경에 바로 맞는 기본값은 아니다. 공식 문서 기준 frontend는 80/443 포트 중심이고, private IP frontend는 현재 지원되지 않는다고 설명되어 있다. 또한 Kubenet은 지원하지 않고 Azure CNI 또는 Azure CNI Overlay가 필요하다. 인증서는 Gateway API listener에서 Kubernetes Secret으로 참조해야 하며, 공식 SSL offloading 문서는 Secrets Store CSI driver를 통한 외부 볼륨 마운트 방식은 지원되지 않는다고 명시한다.

## 언제 선택할까

AGC를 우선 검토할 상황:

- Azure 관리형 L7 ingress와 Gateway API를 함께 쓰고 싶다.
- WAF, mTLS, TLS 정책, URL/header rewrite, traffic splitting 같은 L7 기능이 필요하다.
- ingress 프록시 데이터 플레인이 AKS 노드 CPU/메모리를 쓰지 않게 하고 싶다.
- AGIC(Application Gateway Ingress Controller)의 Ingress/annotation 중심 모델에서 Gateway API로 이동하고 싶다.
- 플랫폼 팀이 `Gateway`를 관리하고 애플리케이션 팀이 `HTTPRoute`를 관리하는 역할 분리를 도입하고 싶다.
- Azure 리소스, managed identity, subnet delegation, Azure Monitor 기반 운영 모델을 받아들일 수 있다.

AGC를 신중히 볼 상황:

- internal/private-only frontend가 필수다. 공식 components 문서 기준 frontend private IP는 현재 지원되지 않는다.
- 80/443 이외의 custom frontend port가 필요하다.
- Kubenet 기반 AKS 클러스터다.
- 인증서를 Azure Key Vault에서 직접 참조하는 모델을 기대한다. AGC Gateway API 예제는 Kubernetes Secret 참조를 기준으로 한다.
- Azure 리소스 비용과 lifecycle을 Kubernetes 리소스와 함께 추적하기 어렵다.

## 아키텍처

AGC는 크게 네 부분으로 이해하면 쉽다.

| 구성 요소                                   | 위치                 | 역할                                                                                                              |
| ------------------------------------------- | -------------------- | ----------------------------------------------------------------------------------------------------------------- |
| Application Gateway for Containers resource | Azure                | AGC의 parent resource이며 control plane 배포 단위다.                                                              |
| Frontend                                    | Azure child resource | 클라이언트가 접근하는 entry point다. 각 frontend는 Azure가 생성한 FQDN을 제공한다.                                |
| Association                                 | Azure child resource | AGC를 VNet의 delegated subnet에 연결하는 1:1 connection point다.                                                  |
| ALB Controller                              | AKS                  | Kubernetes `Gateway`, `HTTPRoute`, `Ingress`, `ApplicationLoadBalancer` 등 리소스를 감시하고 AGC 구성을 반영한다. |

공식 components 문서에 따르면 ALB Controller는 Kubernetes Deployment이며, Kubernetes custom resources와 `Ingress`, `Gateway`, `ApplicationLoadBalancer` 같은 리소스를 watch한다. 그리고 ARM API와 Application Gateway for Containers configuration API를 사용해 Azure 쪽 AGC 배포에 구성을 전파한다.

요청 흐름은 다음과 같다.

1. 클라이언트가 AGC frontend의 FQDN 또는 그 FQDN을 가리키는 CNAME으로 접근한다.
2. AGC frontend가 HTTP/HTTPS 요청을 받는다.
3. Gateway listener와 연결된 HTTPRoute 규칙이 hostname, path, header, query, method 조건 등을 평가한다.
4. AGC가 선택된 backend target으로 요청을 proxy한다.
5. backend는 AKS 내부 Service/Pod 뒤의 애플리케이션이다.

AGC는 요청을 backend로 보낼 때 `x-forwarded-for`, `x-forwarded-proto`, `x-request-id` 헤더를 추가한다. `x-request-id`는 access log의 tracking id와 연계해 디버깅에 사용할 수 있다. 자세한 요청 처리 모델은 [How Application Gateway for Containers accepts a request](https://learn.microsoft.com/en-us/azure/application-gateway/for-containers/application-gateway-for-containers-components#how-application-gateway-for-containers-accepts-a-request)를 참고한다.

## Gateway API 지원 범위

공식 overview 기준 ALB Controller는 Gateway API v1을 구현한다. 지원 리소스는 다음과 같다.

| 리소스           | 지원 여부 | 메모                                                                               |
| ---------------- | --------- | ---------------------------------------------------------------------------------- |
| `GatewayClass`   | 지원      | AKS add-on 설치 시 `azure-alb-external` GatewayClass를 확인할 수 있다.             |
| `Gateway`        | 지원      | HTTP/HTTPS listener를 지원한다. listener port는 80/443만 허용된다.                 |
| `HTTPRoute`      | 지원      | host/path/header/query/method 기반 L7 routing과 weighted backend를 구성할 수 있다. |
| `ReferenceGrant` | 지원      | 공식 overview는 현재 `v1alpha1` 지원이라고 설명한다.                               |
| `Ingress`        | 지원      | Gateway API뿐 아니라 기존 Ingress API도 지원한다.                                  |

지원 범위는 버전과 지역, add-on 상태에 따라 달라질 수 있으므로 실습 전에 [Implementation of Gateway API](https://learn.microsoft.com/en-us/azure/application-gateway/for-containers/overview#implementation-of-gateway-api)를 다시 확인한다.

## 배포 전략

AGC에는 두 가지 deployment strategy가 있다. 핵심 차이는 Azure 리소스 lifecycle을 누가 관리하느냐다.

### Managed by ALB Controller

Kubernetes의 `ApplicationLoadBalancer` custom resource가 Application Gateway for Containers resource와 association 생명주기를 결정한다. `Gateway`가 해당 `ApplicationLoadBalancer`를 참조하면 ALB Controller가 frontend를 만들고 Gateway lifecycle에 맞춰 관리한다.

이 방식은 Kubernetes 중심 운영에 가깝다. 다만 subnet, identity, role assignment, region 지원 조건은 여전히 Azure 쪽 전제 조건이다. 공식 가이드는 [Create Application Gateway for Containers managed by ALB Controller](https://learn.microsoft.com/en-us/azure/application-gateway/for-containers/quickstart-create-application-gateway-for-containers-managed-by-alb-controller)를 참고한다.

### Bring your own(BYO)

Azure Portal, CLI, PowerShell, Terraform 등으로 Application Gateway for Containers resource, frontend, association을 미리 만들고, Kubernetes `Gateway`에서 이를 참조한다. 이 경우 Azure resource lifecycle은 Kubernetes 리소스와 독립적으로 관리된다.

조직 내 네트워크/보안 팀이 Azure 리소스를 별도로 통제해야 하거나, frontend 이름과 배치 방식을 명시적으로 관리해야 할 때 적합하다. 공식 가이드는 [Create Application Gateway for Containers - bring your own deployment](https://learn.microsoft.com/en-us/azure/application-gateway/for-containers/quickstart-create-application-gateway-for-containers-byo-deployment)를 참고한다.

## AKS 전제 조건

공식 AKS add-on quickstart 기준 주요 조건은 다음과 같다.

- AGC가 제공되는 Azure region이어야 한다. 공식 overview에는 Korea Central을 포함한 supported region 목록이 있다.
- AKS network plugin은 Azure CNI 또는 Azure CNI Overlay여야 한다.
- Workload Identity가 필요하다.
- 지원되는 AKS Kubernetes version이어야 한다.
- AGC association subnet은 `Microsoft.ServiceNetworking/trafficControllers` delegation이 필요하다.
- association subnet은 최소 /24 또는 약 250~256개 이상의 사용 가능한 IP를 확보하는 방향으로 설계한다.
- Kubenet은 지원되지 않는다.

이 문서의 실습은 BYO VNet/subnet을 전제로 한다.

## 설치 가이드

AGC 설치는 크게 세 단계로 나뉜다.

1. AKS 클러스터에 ALB Controller와 Gateway API CRD를 준비한다.
2. AGC가 사용할 delegated subnet과 권한을 준비한다.
3. `Managed by ALB Controller` 또는 `Bring your own(BYO)` 방식 중 하나로 AGC Azure 리소스와 `Gateway`를 연결한다.

공식 문서는 다음 세 개를 함께 봐야 한다.

- [Deploy Application Gateway for Containers ALB Controller using AKS Add-on](https://learn.microsoft.com/en-us/azure/application-gateway/for-containers/quickstart-deploy-application-gateway-for-containers-alb-controller-addon)
- [Create Application Gateway for Containers managed by ALB Controller](https://learn.microsoft.com/en-us/azure/application-gateway/for-containers/quickstart-create-application-gateway-for-containers-managed-by-alb-controller)
- [Create Application Gateway for Containers - bring your own deployment](https://learn.microsoft.com/en-us/azure/application-gateway/for-containers/quickstart-create-application-gateway-for-containers-byo-deployment?tabs=existing-vnet-subnet)

### 0. 공통 환경 변수와 Azure 준비

먼저 subscription, resource provider, CLI extension을 준비한다. 2026-06 기준 공식 add-on quickstart에는 preview feature registration 단계가 포함되어 있으므로 실제 subscription에서 이미 등록되어 있는지 확인한다.

```bash
SUBSCRIPTION_ID='<your subscription id>'
AKS_NAME='<your cluster name>'
RESOURCE_GROUP='<your AKS resource group name>'
LOCATION='<Azure region>'

az login
az account set --subscription $SUBSCRIPTION_ID

az provider register --namespace Microsoft.ContainerService
az provider register --namespace Microsoft.Network
az provider register --namespace Microsoft.NetworkFunction
az provider register --namespace Microsoft.ServiceNetworking

az extension add --name alb
az extension add --name aks-preview

az feature register --namespace Microsoft.ContainerService --name ManagedGatewayAPIPreview
az feature register --namespace Microsoft.ContainerService --name ApplicationLoadBalancerPreview
```

Feature registration은 시간이 걸릴 수 있다. 등록 상태는 다음처럼 확인한다.

```bash
az feature show \
  --namespace Microsoft.ContainerService \
  --name ManagedGatewayAPIPreview \
  --query properties.state -o tsv

az feature show \
  --namespace Microsoft.ContainerService \
  --name ApplicationLoadBalancerPreview \
  --query properties.state -o tsv
```

### 1. ALB Controller add-on 활성화

기존 AKS 클러스터에서는 Workload Identity를 활성화한 뒤 Gateway API add-on과 Application Gateway for Containers add-on을 활성화한다. AGC add-on은 Gateway API add-on을 전제로 한다.

```bash
az aks update \
  --resource-group $RESOURCE_GROUP \
  --name $AKS_NAME \
  --enable-oidc-issuer \
  --enable-workload-identity \
  --no-wait

az aks update \
  --resource-group $RESOURCE_GROUP \
  --name $AKS_NAME \
  --enable-gateway-api \
  --enable-application-load-balancer
```

설치 후에는 다음을 확인한다.

```bash
kubectl get pods -n kube-system | grep alb-controller
kubectl get gatewayclass azure-alb-external -o yaml
```

`GatewayClass`의 `controllerName`은 `alb.networking.azure.io/alb-controller`이며, Accepted condition이 true여야 한다. 공식 절차는 [Deploy ALB Controller using AKS Add-on](https://learn.microsoft.com/en-us/azure/application-gateway/for-containers/quickstart-deploy-application-gateway-for-containers-alb-controller-addon)을 따른다.

이후 단계는 BYO VNet/subnet을 명시적으로 준비하는 흐름만 설명한다.

### 2. BYO subnet 준비

AGC association은 delegated subnet에 붙는다. 공식 components 문서 기준 association 하나당 최소 256개 주소를 가정하므로, 실습 subnet은 `/24` 이상으로 잡는 것이 안전하다. subnet 이름은 `GatewaySubnet`, `AzureFirewallSubnet`, `AzureBastionSubnet` 같은 예약 이름을 쓰면 안 된다.

#### 2.1 BYO VNet의 기존 subnet을 사용하는 경우

이미 준비된 subnet을 사용할 때는 delegation을 추가하고 subnet ID를 가져온다.

```bash
VNET_NAME='<name of the virtual network to use>'
VNET_RESOURCE_GROUP='<resource group of the virtual network>'
ALB_SUBNET_NAME='subnet-alb'

az network vnet subnet update \
  --resource-group $VNET_RESOURCE_GROUP \
  --vnet-name $VNET_NAME \
  --name $ALB_SUBNET_NAME \
  --delegations Microsoft.ServiceNetworking/trafficControllers

ALB_SUBNET_ID=$(az network vnet subnet list \
  --resource-group $VNET_RESOURCE_GROUP \
  --vnet-name $VNET_NAME \
  --query "[?name=='$ALB_SUBNET_NAME'].id" -o tsv)

echo $ALB_SUBNET_ID
```

#### 2.2 새 BYO VNet과 subnet을 만드는 경우

AKS VNet과 별도 VNet을 만들 수도 있다. 이 경우 AGC subnet과 AKS node/pod 네트워크 사이에 실제 통신 경로가 필요하므로 VNet peering, route table, firewall 경로를 별도로 설계해야 한다.

```bash
VNET_NAME='<name of the virtual network to use>'
VNET_RESOURCE_GROUP='<resource group of the virtual network>'
VNET_ADDRESS_PREFIX='<VNet address prefix>'
SUBNET_ADDRESS_PREFIX='<subnet address prefix, /24 or larger>'
ALB_SUBNET_NAME='subnet-alb'

az network vnet create \
  --resource-group $VNET_RESOURCE_GROUP \
  --name $VNET_NAME \
  --address-prefix $VNET_ADDRESS_PREFIX \
  --subnet-name $ALB_SUBNET_NAME \
  --subnet-prefixes $SUBNET_ADDRESS_PREFIX

az network vnet subnet update \
  --resource-group $VNET_RESOURCE_GROUP \
  --vnet-name $VNET_NAME \
  --name $ALB_SUBNET_NAME \
  --delegations Microsoft.ServiceNetworking/trafficControllers

ALB_SUBNET_ID=$(az network vnet subnet show \
  --resource-group $VNET_RESOURCE_GROUP \
  --vnet-name $VNET_NAME \
  --name $ALB_SUBNET_NAME \
  --query id -o tsv)
```

### 3. 공통 managed identity 권한 확인

ALB Controller가 AGC 리소스를 만들거나 수정하고, association subnet에 join하려면 권한이 필요하다.

BYO VNet을 쓰면 AKS cluster resource group, AKS node resource group, AGC resource group, VNet resource group이 서로 다를 수 있다. 따라서 role assignment의 대상 scope를 먼저 분리해서 잡는다.

```bash
AKS_RESOURCE_GROUP=$RESOURCE_GROUP

MC_RESOURCE_GROUP=$(az aks show \
  --name $AKS_NAME \
  --resource-group $AKS_RESOURCE_GROUP \
  --query nodeResourceGroup -o tsv | tr -d '\r')

# BYO VNet/subnet이 있는 resource group. 2번 단계에서 이미 설정했다면 재사용한다.
VNET_RESOURCE_GROUP='<resource group of the BYO virtual network>'

# BYO 배포에서 AGC parent/frontend/association을 만들 resource group.
# AKS resource group과 같게 둘 수도 있지만, 네트워크/플랫폼 팀 소유 RG로 분리하는 경우가 많다.
AGC_RESOURCE_GROUP='<resource group for Application Gateway for Containers resources>'
```

역할 scope는 다음처럼 나뉜다.

| 배포 방식                 | Role                                               | Scope                                                          | 이유                                                                                       |
| ------------------------- | -------------------------------------------------- | -------------------------------------------------------------- | ------------------------------------------------------------------------------------------ |
| Managed by ALB Controller | `AppGw for Containers Configuration Manager`       | AKS managed cluster resource group, 보통 `MC_*` resource group | `ApplicationLoadBalancer` CR을 기준으로 ALB Controller가 AGC Azure 리소스를 생성/관리한다. |
| Managed by ALB Controller | `Network Contributor` 또는 subnet join custom role | BYO association subnet ID                                      | AGC association이 delegated subnet에 join해야 한다.                                        |
| BYO                       | `AppGw for Containers Configuration Manager`       | AGC resource group                                             | 미리 만든 AGC parent/frontend/association을 ALB Controller가 참조하고 구성해야 한다.       |
| BYO                       | `Network Contributor` 또는 subnet join custom role | BYO association subnet ID                                      | BYO association 생성 및 subnet join에 필요하다.                                            |

AKS add-on 방식에서는 `applicationloadbalancer-<cluster-name>` user-assigned managed identity가 node resource group에 생성되고, 공식 quickstart 기준으로 MC resource group에 필요한 기본 role assignment가 구성된다. Helm 방식 문서 예제에서는 사용자가 만든 `azure-alb-identity` 이름을 사용한다. 먼저 현재 클러스터의 node resource group에 생성된 identity를 확인한다.

```bash
az identity list \
  --resource-group $MC_RESOURCE_GROUP \
  --query "[?starts_with(name, 'applicationloadbalancer')].[name, principalId]" \
  -o table
```

확인한 identity 이름을 기준으로 아래 값을 맞춘다.

```bash
IDENTITY_RESOURCE_GROUP=$MC_RESOURCE_GROUP
IDENTITY_RESOURCE_NAME="applicationloadbalancer-${AKS_NAME}"

principalId=$(az identity show \
  --resource-group $IDENTITY_RESOURCE_GROUP \
  --name $IDENTITY_RESOURCE_NAME \
  --query principalId -o tsv)
```

#### 3.1 Managed by ALB Controller 방식 권한

이 방식에서는 `ApplicationLoadBalancer` CR을 기준으로 ALB Controller가 AGC Azure 리소스를 생성한다. 공식 quickstart는 `AppGw for Containers Configuration Manager`를 AKS managed cluster resource group, 즉 `MC_*` resource group에 부여한다. BYO VNet을 쓰는 경우에도 association subnet은 별도 VNet resource group에 있을 수 있으므로 subnet scope 권한은 반드시 별도로 확인한다.

```bash
mcResourceGroupId=$(az group show \
  --name $MC_RESOURCE_GROUP \
  --query id -o tsv)

# AppGw for Containers Configuration Manager on the resource group where ALB Controller creates AGC resources
az role assignment create \
  --assignee-object-id $principalId \
  --assignee-principal-type ServicePrincipal \
  --scope $mcResourceGroupId \
  --role "fbc52c3f-28ad-4303-a892-8a056630b8f1"

# Network Contributor on the association subnet
az role assignment create \
  --assignee-object-id $principalId \
  --assignee-principal-type ServicePrincipal \
  --scope $ALB_SUBNET_ID \
  --role "4d97b98b-1d4f-4787-a291-c67834d212e7"
```

#### 3.2 BYO 방식 권한

BYO 방식에서는 AGC parent resource, frontend, association을 Azure에서 먼저 만든다. 이 경우 ALB Controller가 AGC resource group의 기존 리소스를 참조하고 구성하므로 `AppGw for Containers Configuration Manager` scope는 `AGC_RESOURCE_GROUP`이어야 한다. association subnet이 다른 resource group 또는 다른 subscription에 있다면 `ALB_SUBNET_ID` scope에 subnet join 권한도 별도로 부여한다.

```bash
resourceGroupId=$(az group show \
  --name $AGC_RESOURCE_GROUP \
  --query id -o tsv)

# AppGw for Containers Configuration Manager on AGC resource group
az role assignment create \
  --assignee-object-id $principalId \
  --assignee-principal-type ServicePrincipal \
  --scope $resourceGroupId \
  --role "fbc52c3f-28ad-4303-a892-8a056630b8f1"

# Network Contributor on BYO association subnet
az role assignment create \
  --assignee-object-id $principalId \
  --assignee-principal-type ServicePrincipal \
  --scope $ALB_SUBNET_ID \
  --role "4d97b98b-1d4f-4787-a291-c67834d212e7"
```

#### 3.3 BYO VNet 네트워크 체크

권한과 별개로 AGC association subnet에서 AKS backend로 도달 가능한 네트워크 경로가 있어야 한다. BYO VNet이 AKS node/pod VNet과 다르면 다음을 별도로 확인한다.

- AGC association VNet과 AKS VNet 사이 VNet peering 또는 동등한 routing 경로가 있다.
- NSG outbound rule이 AGC association subnet에서 AKS backend로 가는 트래픽을 막지 않는다.
- UDR이 public frontend 응답 경로를 appliance로 비대칭 라우팅하지 않는다.
- Azure Firewall/NVA를 경유하는 경우 return path가 대칭인지 확인한다.
- Azure CNI Overlay를 쓰는 경우 AGC가 실제 backend에 도달하는 방식과 required route를 공식 networking 문서 기준으로 검증한다.

> 참고: `fbc52c3f-28ad-4303-a892-8a056630b8f1`는 `AppGw for Containers Configuration Manager`, `4d97b98b-1d4f-4787-a291-c67834d212e7`는 `Network Contributor` 역할 ID다.

### 4. Managed by ALB Controller 방식

이 방식에서는 Kubernetes `ApplicationLoadBalancer` 리소스가 AGC parent resource와 association 생명주기를 결정한다. Azure 리소스 이름은 ALB Controller가 생성하므로 명시적인 Azure 리소스 이름 통제가 필요하면 BYO 방식을 쓴다.

#### 4.1 ApplicationLoadBalancer 생성

Managed by ALB Controller 방식에서는 `ApplicationLoadBalancer` custom resource가 AGC resource와 association 생명주기를 결정한다. subnet ID는 AGC association이 연결될 delegated subnet이다.

```bash
kubectl apply -f - <<EOF
apiVersion: v1
kind: Namespace
metadata:
  name: alb-test-infra
EOF

kubectl apply -f - <<EOF
apiVersion: alb.networking.azure.io/v1
kind: ApplicationLoadBalancer
metadata:
  name: alb-test
  namespace: alb-test-infra
spec:
  associations:
  - $ALB_SUBNET_ID
EOF
```

프로비저닝이 끝나면 status condition이 `Accepted=True`, `Deployment=True`로 전환되는지 확인한다. 공식 문서는 리소스 생성에 약 5~6분이 걸릴 수 있다고 설명한다.

```bash
kubectl get applicationloadbalancer alb-test -n alb-test-infra -o yaml -w
```

정상 예시에서는 다음 상태를 확인한다.

```yaml
status:
  conditions:
    - reason: Accepted
      status: "True"
      type: Accepted
    - reason: Ready
      status: "True"
      type: Deployment
```

#### 4.2 Gateway와 HTTPRoute 작성

Managed 방식에서 `Gateway`는 `ApplicationLoadBalancer` 리소스를 annotation으로 참조한다. AGC의 기본 GatewayClass는 `azure-alb-external`이다.

```bash
kubectl apply -f https://raw.githubusercontent.com/MicrosoftDocs/azure-docs/refs/heads/main/articles/application-gateway/for-containers/examples/traffic-split-scenario/deployment.yaml

kubectl apply -f - <<EOF
apiVersion: gateway.networking.k8s.io/v1
kind: Gateway
metadata:
  name: gateway-01
  namespace: test-infra
  annotations:
    alb.networking.azure.io/alb-namespace: alb-test-infra
    alb.networking.azure.io/alb-name: alb-test
spec:
  gatewayClassName: azure-alb-external
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
  name: route-01
  namespace: test-infra
spec:
  parentRefs:
  - name: gateway-01
  rules:
  - backendRefs:
    - name: backend-v1
      port: 8080
EOF
```

정상 반영 여부는 `Gateway`와 `HTTPRoute`의 status conditions에서 확인한다. 공식 예제에서는 `Accepted=True`, `Programmed=True`, `ResolvedRefs=True`를 확인한다.

```bash
kubectl get gateway gateway-01 -n test-infra -o yaml
kubectl get httproute route-01 -n test-infra -o yaml
```

### 5. Bring your own(BYO) 방식

BYO 방식에서는 AGC Azure 리소스, frontend, association을 Azure 쪽에서 먼저 만들고, Kubernetes `Gateway`에서 해당 리소스를 참조한다. Azure 리소스 이름과 lifecycle을 네트워크/플랫폼 팀이 직접 통제해야 할 때 적합하다.

#### 5.1 AGC parent resource 생성

```bash
AGFC_NAME='alb-test'

az network alb create \
  --resource-group $AGC_RESOURCE_GROUP \
  --name $AGFC_NAME
```

#### 5.2 Frontend 생성

Frontend는 클라이언트 entry point이며 Azure가 FQDN을 제공한다. BYO 방식에서는 `Gateway.spec.addresses`에서 이 frontend 이름을 참조한다.

```bash
FRONTEND_NAME='frontend'

az network alb frontend create \
  --resource-group $AGC_RESOURCE_GROUP \
  --alb-name $AGFC_NAME \
  --name $FRONTEND_NAME
```

#### 5.3 Association 생성

AGC가 backend로 proxy할 수 있도록 delegated subnet에 association을 만든다. 생성에는 5~6분 정도 걸릴 수 있다.

```bash
ASSOCIATION_NAME='association-test'

az network alb association create \
  --resource-group $AGC_RESOURCE_GROUP \
  --alb-name $AGFC_NAME \
  --name $ASSOCIATION_NAME \
  --subnet $ALB_SUBNET_ID
```

생성 상태는 다음처럼 확인한다.

```bash
az network alb association show \
  --resource-group $AGC_RESOURCE_GROUP \
  --alb-name $AGFC_NAME \
  --name $ASSOCIATION_NAME \
  -o table
```

#### 5.4 Gateway에서 BYO AGC와 frontend 참조

BYO 방식에서는 `alb.networking.azure.io/alb-id` annotation으로 AGC resource ID를 지정하고, `spec.addresses`에서 frontend 이름을 지정한다.

```bash
kubectl apply -f https://raw.githubusercontent.com/MicrosoftDocs/azure-docs/refs/heads/main/articles/application-gateway/for-containers/examples/traffic-split-scenario/deployment.yaml

RESOURCE_ID=$(az network alb show \
  --resource-group $AGC_RESOURCE_GROUP \
  --name $AGFC_NAME \
  --query id -o tsv)

kubectl apply -f - <<EOF
apiVersion: gateway.networking.k8s.io/v1
kind: Gateway
metadata:
  name: gateway-01
  namespace: test-infra
  annotations:
    alb.networking.azure.io/alb-id: $RESOURCE_ID
spec:
  gatewayClassName: azure-alb-external
  listeners:
  - name: http
    port: 80
    protocol: HTTP
    allowedRoutes:
      namespaces:
        from: Same
  addresses:
  - type: alb.networking.azure.io/alb-frontend
    value: $FRONTEND_NAME
---
apiVersion: gateway.networking.k8s.io/v1
kind: HTTPRoute
metadata:
  name: route-01
  namespace: test-infra
spec:
  parentRefs:
  - name: gateway-01
  rules:
  - backendRefs:
    - name: backend-v1
      port: 8080
EOF
```

상태 확인은 managed 방식과 동일하다.

```bash
kubectl get gateway gateway-01 -n test-infra -o yaml
kubectl get httproute route-01 -n test-infra -o yaml
```

Gateway status의 `status.addresses[0].value`에는 AGC frontend FQDN이 들어간다.

```bash
FQDN=$(kubectl get gateway gateway-01 -n test-infra -o jsonpath='{.status.addresses[0].value}')
echo $FQDN
```

### 6. 샘플 애플리케이션과 호출 테스트

AGC Gateway API 예제들은 보통 `test-infra` namespace의 sample app을 사용한다. 위 `Gateway`/`HTTPRoute` 예제에서는 공식 traffic split sample의 `backend-v1` 서비스를 backend로 사용했다. 아직 sample app을 배포하지 않았다면 다음 manifest를 적용한다.

```bash
kubectl apply -f https://raw.githubusercontent.com/MicrosoftDocs/azure-docs/refs/heads/main/articles/application-gateway/for-containers/examples/traffic-split-scenario/deployment.yaml
kubectl get pods,svc -n test-infra
```

HTTP listener라면 FQDN으로 바로 호출할 수 있다.

```bash
FQDN=$(kubectl get gateway gateway-01 -n test-infra -o jsonpath='{.status.addresses[0].value}')
curl -i http://$FQDN
```

hostname match를 쓰는 `HTTPRoute`라면 frontend FQDN으로 resolve되는 IP에 Host header를 맞춰 호출한다.

```bash
FQDN_IP=$(dig +short $FQDN | head -n 1)
curl -i --resolve contoso.com:80:$FQDN_IP http://contoso.com/
```

### 7. 삭제 순서

Managed 방식에서는 Kubernetes `ApplicationLoadBalancer`를 삭제하면 ALB Controller가 관리하던 AGC 리소스 lifecycle도 함께 정리된다.

```bash
kubectl delete httproute route-01 -n test-infra --ignore-not-found
kubectl delete gateway gateway-01 -n test-infra --ignore-not-found
kubectl delete applicationloadbalancer alb-test -n alb-test-infra --ignore-not-found
```

BYO 방식에서는 Azure 리소스가 Kubernetes lifecycle과 독립적이므로 직접 삭제해야 한다.

```bash
kubectl delete httproute route-01 -n test-infra --ignore-not-found
kubectl delete gateway gateway-01 -n test-infra --ignore-not-found

az network alb association delete \
  --resource-group $AGC_RESOURCE_GROUP \
  --alb-name $AGFC_NAME \
  --name $ASSOCIATION_NAME \
  --yes

az network alb frontend delete \
  --resource-group $AGC_RESOURCE_GROUP \
  --alb-name $AGFC_NAME \
  --name $FRONTEND_NAME \
  --yes

az network alb delete \
  --resource-group $AGC_RESOURCE_GROUP \
  --name $AGFC_NAME \
  --yes
```

## 주요 기능

공식 overview에서 확인되는 주요 L7 기능은 다음과 같다.

실제 기능 검증은 [01-application-gateway-for-containers-labs](01-application-gateway-for-containers-labs/) 아래의 실습 문서와 spec YAML을 사용한다. 기본 HTTP routing, hostname/path routing, weighted traffic splitting, URL rewrite, HTTPS termination, cert-manager, WAF policy, observability를 분리된 튜토리얼로 정리했다.

- Automatic retries
- Autoscaling
- Availability zone resiliency
- Custom/default health probes
- ECDSA/RSA certificates
- Flexible load balancing strategies: Least Request, Load Aware Routing, Ring Hash, Round Robin, Weighted Round Robin
- gRPC
- Header rewrite
- HTTP/2
- HTTPS traffic management: SSL termination, end-to-end SSL
- Ingress API and Gateway API support
- Hostname, path, header, query string, method, port 기반 L7 routing
- Frontend, backend, end-to-end mTLS
- SSE, WebSocket
- TLS policies
- URL redirect/rewrite
- WAF

Weighted traffic splitting은 `HTTPRoute`의 `backendRefs[].weight`로 구성한다. 공식 예제는 [Traffic splitting with Application Gateway for Containers - Gateway API](https://learn.microsoft.com/en-us/azure/application-gateway/for-containers/how-to-traffic-splitting-gateway-api)를 참고한다.

## 보안 모델

### TLS termination

AGC는 Gateway listener에서 HTTPS termination을 지원한다. `Gateway.spec.listeners[].tls.certificateRefs`로 Kubernetes Secret을 참조한다. 공식 SSL offloading 문서는 AGC 인증서가 Kubernetes Secret에 있어야 하며, Secrets Store CSI driver를 통해 외부 볼륨에서 직접 마운트하는 방식은 지원되지 않는다고 설명한다. 자동 인증서 관리는 cert-manager 연계를 검토한다.

참고: [SSL offloading with Application Gateway for Containers - Gateway API](https://learn.microsoft.com/en-us/azure/application-gateway/for-containers/how-to-ssl-offloading-gateway-api)

### Frontend mTLS

클라이언트 인증서 검증은 `FrontendTLSPolicy`로 구성한다. 유효하지 않거나 폐기된 클라이언트 인증서는 backend로 proxy되지 않는다.

참고: [Frontend MTLS with Application Gateway for Containers - Gateway API](https://learn.microsoft.com/en-us/azure/application-gateway/for-containers/how-to-frontend-mtls-gateway-api)

### Backend mTLS

Backend로 향하는 연결에 client certificate와 CA 검증을 적용하려면 `BackendTLSPolicy`를 사용한다. backend service가 신뢰하는 인증서를 기준으로 AGC와 backend 사이의 mutual TLS를 구성할 수 있다.

참고: [Backend MTLS with Application Gateway for Containers - Gateway API](https://learn.microsoft.com/en-us/azure/application-gateway/for-containers/how-to-backend-mtls-gateway-api)

### WAF

AGC는 security policy를 통해 WAF를 연결한다. components 문서 기준 security policy type으로 `waf`가 제공되며, WAF policy와 연결된다. WAF 로그는 diagnostic logs의 `TrafficControllerFirewallLog`로 확인한다.

## 관측성 및 디버깅

AGC 운영 시 봐야 할 신호는 Azure 리소스, ALB Controller, Kubernetes status conditions 세 군데다.

Azure Monitor:

- Activity log는 Resource Manager 작업 추적에 사용한다.
- Access log는 client IP, request URI, response latency, status code, bytes in/out 등을 확인한다.
- Firewall log는 WAF detect/block 이벤트를 확인한다.
- Diagnostic settings를 활성화해야 access/firewall log와 metrics를 수집할 수 있다. 공식 문서상 최초 활성화 후 로그가 보이기까지 최대 1시간이 걸릴 수 있다.

Kubernetes:

- `Gateway` status에서 `Accepted`, `Programmed`, listener `ResolvedRefs`를 확인한다.
- `HTTPRoute` status에서 route `Accepted`, `ResolvedRefs`, `Programmed`를 확인한다.
- `ApplicationLoadBalancer` status에서 Azure resource provisioning 상태를 확인한다.
- ALB Controller pod 로그에서 Azure API 호출 실패, 권한 문제, 리소스 reconcile 문제를 확인한다.

ALB Controller 내부 endpoint:

- components 문서 기준 ClusterIP Service로 backend health endpoint `/backendHealth`가 TCP 8000에 노출된다.
- Prometheus metrics endpoint `/metrics`가 TCP 8001에 노출된다.

참고: [Diagnostic logs for Application Gateway for Containers](https://learn.microsoft.com/en-us/azure/application-gateway/for-containers/diagnostics)

## 운영 가이드

### 고가용성

AGC는 Azure region이 availability zone을 지원하면 underlying components를 zone에 분산해 resiliency를 높인다. zone 미지원 region에서는 fault domain과 update domain으로 계획/비계획 장애 영향을 줄인다. ALB Controller는 최소 두 replica의 active/passive 구성을 사용하며, 사용자 정의 replica count는 지원되지 않는다.

참고: [Application Gateway for Containers FAQ](https://learn.microsoft.com/en-us/azure/application-gateway/for-containers/faq)

### 업그레이드와 유지보수

AKS managed add-on을 쓰면 ALB Controller 업데이트, identity 구성, subnet 구성 같은 부분을 AKS가 관리한다. FAQ 기준 routine maintenance와 update는 고객 개입 없이 service-impacting하지 않도록 설계되어 있으며, breaking change나 기능 변화가 있는 경우 Azure Service Health를 통해 알림이 제공된다.

Helm 기반으로 ALB Controller를 직접 운영하면 chart/update lifecycle은 사용자가 더 많이 책임진다. AKS Automatic cluster에서는 add-on deployment가 필요하고 Helm deployment는 지원되지 않는다.

### 네트워크와 subnet

Association은 delegated subnet에 연결된다. 현재 association 수는 Application Gateway for Containers resource당 1개로 제한된다고 components 문서가 설명한다. 각 association은 최소 256개 주소를 가정하므로 /24 subnet을 기본 설계 단위로 잡는 것이 좋다. NSG와 UDR은 지원되지만, 잘못된 UDR은 asymmetric routing을 만들 수 있으므로 인터넷 ingress return path를 특히 주의한다.

### 요청 timeout

components 문서 기준 기본 timeout은 다음과 같다.

| 항목                     | 기본값 |
| ------------------------ | ------ |
| Request Timeout          | 60초   |
| HTTP Idle Timeout        | 5분    |
| Stream Idle Timeout      | 5분    |
| Upstream Connect Timeout | 5초    |

대용량 다운로드나 장시간 응답이 있는 서비스는 request timeout 정책을 별도로 검토한다.

## 비용

AGC 비용은 최신 Azure pricing page를 기준으로 확인해야 한다. 2026-06 기준 pricing page에는 Application Gateway for Containers 항목으로 fixed gateway-hour와 capacity unit-hour가 표시된다. 또한 outbound data transfer는 표준 data transfer 요금이 적용된다. 실제 금액은 region, currency, 계약 조건, WAF 사용 여부, 처리량에 따라 달라질 수 있으므로 [Application Gateway pricing](https://azure.microsoft.com/pricing/details/application-gateway/)과 Azure Pricing Calculator를 함께 확인한다.

비용 검토 포인트:

- Gateway-hour 고정 비용
- Capacity Unit-hour 비용
- Outbound data transfer
- WAF policy 및 log 저장 비용
- Azure Monitor 로그 저장/쿼리 비용
- Public DNS, certificate automation, supporting resource 비용

## 제약 및 주의사항

- Frontend는 AGC가 생성한 FQDN을 제공한다. components 문서는 frontend가 80/443만 listen한다고 설명한다.
- components 문서 기준 frontend private IP address는 현재 지원되지 않는다.
- Kubenet은 지원하지 않는다. Azure CNI 또는 Azure CNI Overlay를 사용한다.
- 동일 frontend resource를 여러 `Gateway` 또는 `Ingress`가 공유하는 방식은 지원되지 않는다.
- 여러 ALB Controller를 같은 클러스터에 설치하는 것은 가능하더라도 권장/지원되지 않는다.
- ALB Controller replica count를 사용자가 늘리는 것은 지원되지 않는다.
- 각 ALB Controller는 고유 managed identity를 사용해야 한다.
- TLS protocol version은 사용자가 설정할 수 없고, FAQ 기준 TLS 1.2를 지원하며 SSL 2.0/3.0, TLS 1.0/1.1은 비활성화되어 있다.
- Client와 frontend 사이는 HTTP/2와 HTTP/1.1을 지원한다. AGC와 backend target 사이 통신은 gRPC를 제외하면 HTTP/1.1이다.
- Gateway API의 모든 upstream 리소스와 모든 extended feature를 지원한다고 가정하면 안 된다. 공식 지원 목록을 기준으로 검증한다.

## AGIC와 비교한 위치

AGIC는 기존 Azure Application Gateway를 Ingress API와 연결하는 controller이고, AGC는 Gateway API와 Ingress API를 모두 지원하는 새 Azure L7 load balancing 제품군이다. 공식 overview도 AGC를 AGIC의 evolution으로 설명한다.

AGC가 유리한 지점:

- Gateway API 표준 리소스 사용
- Weighted traffic splitting
- Header/query/method 기반 routing
- Frontend/backend mTLS 정책 모델
- Kubernetes 리소스 변경의 near-real-time 반영 목표
- Azure 관리형 L7 데이터 플레인을 AKS 노드 밖에서 운영

AGIC가 여전히 검토될 수 있는 지점:

- private/internal frontend가 필수인 기존 Application Gateway v2 설계
- 이미 AGIC와 Ingress annotation 기반 운영 체계가 안정화된 환경
- AGC 지원 region/기능 제약이 현재 요구사항과 맞지 않는 경우

비공식 비교 자료로는 Juan Manuel Rey의 [AGIC vs AGC: Which Ingress Solution Should You Use in AKS?](https://jreypo.io/2025/09/25/agic-vs-agc-which-ingress-solution-should-you-use-in-aks/)와 [Exposing AKS Workloads on Azure - 2025 Edition](https://jreypo.io/2025/09/10/exposing-aks-workloads-on-azure-2025-edition/)가 참고할 만하다. 단, 최종 판단은 Microsoft Learn의 최신 공식 문서와 실제 subscription/region 검증을 기준으로 한다.

## 팩트체크 메모

초안에서 수정하거나 보수적으로 바꾼 내용:

- `특정 FrontEnd IP(Public)를 할당한다`는 표현은 `frontend가 Azure 제공 FQDN을 제공하고, 해당 FQDN이 anycast IP로 resolve된다`로 정리했다. 공식 FAQ는 frontend가 anycast IP로 resolve될 수 있다고 설명한다.
- `Private IP가 preview`라는 표현은 반영하지 않았다. components 문서 기준 Application Gateway for Containers frontend는 private IP address를 현재 지원하지 않는다고 설명한다.
- `Azure Key Vault와 연계하여 인증서 관리 가능`은 Gateway API listener 인증서 관점에서는 그대로 쓰지 않았다. 공식 SSL offloading 문서는 AGC 인증서가 Kubernetes Secret에 있어야 하며 Secrets Store CSI driver를 통한 외부 볼륨 마운트는 지원되지 않는다고 설명한다.
- `Azure AD Application Gateway Auth 통합 로드맵`은 공식 AGC 문서에서 확인하지 못해 제외했다.
- `전용 HW/FPGAs 활용`은 공식 AGC 문서에서 확인하지 못해 제외했다.
- `GA` 표현은 단정하지 않았다. 공식 overview에는 supported regions, Pricing/SLA 링크가 있지만, add-on quickstart에는 preview feature registration 단계가 남아 있으므로 실제 사용 전 region/subscription 지원 상태를 확인해야 한다.
- `Frontend 수 기반 과금`은 pricing page에서 핵심 과금 항목으로 확인하지 못해 비용 설명에서는 gateway-hour와 capacity unit-hour 중심으로 정리했다.

## 레퍼런스

- [What is Application Gateway for Containers?](https://learn.microsoft.com/en-us/azure/application-gateway/for-containers/overview)
- [Application Gateway for Containers components](https://learn.microsoft.com/en-us/azure/application-gateway/for-containers/application-gateway-for-containers-components)
- [Deploy Application Gateway for Containers ALB Controller using AKS Add-on](https://learn.microsoft.com/en-us/azure/application-gateway/for-containers/quickstart-deploy-application-gateway-for-containers-alb-controller-addon)
- [Create Application Gateway for Containers managed by ALB Controller](https://learn.microsoft.com/en-us/azure/application-gateway/for-containers/quickstart-create-application-gateway-for-containers-managed-by-alb-controller)
- [Create Application Gateway for Containers - bring your own deployment](https://learn.microsoft.com/en-us/azure/application-gateway/for-containers/quickstart-create-application-gateway-for-containers-byo-deployment)
- [SSL offloading with Application Gateway for Containers - Gateway API](https://learn.microsoft.com/en-us/azure/application-gateway/for-containers/how-to-ssl-offloading-gateway-api)
- [Frontend MTLS with Application Gateway for Containers - Gateway API](https://learn.microsoft.com/en-us/azure/application-gateway/for-containers/how-to-frontend-mtls-gateway-api)
- [Backend MTLS with Application Gateway for Containers - Gateway API](https://learn.microsoft.com/en-us/azure/application-gateway/for-containers/how-to-backend-mtls-gateway-api)
- [Traffic splitting with Application Gateway for Containers - Gateway API](https://learn.microsoft.com/en-us/azure/application-gateway/for-containers/how-to-traffic-splitting-gateway-api)
- [Diagnostic logs for Application Gateway for Containers](https://learn.microsoft.com/en-us/azure/application-gateway/for-containers/diagnostics)
- [Frequently asked questions about Application Gateway for Containers](https://learn.microsoft.com/en-us/azure/application-gateway/for-containers/faq)
- [Application Gateway pricing](https://azure.microsoft.com/pricing/details/application-gateway/)
