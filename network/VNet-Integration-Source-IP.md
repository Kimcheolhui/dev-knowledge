# VNet Integration에서 Source IP가 delegated subnet 대역으로 보이는 이유

작성일: 2026-10-16

## 핵심 결론

**서비스가 delegated subnet의 주소를 할당받아 VNet 측 연결을 구성하는 형태의 VNet Integration에서는, 해당 연동 경로로 나오는 트래픽의 Source IP가 그 subnet 대역의 사설 IP로 보인다.**

이는 서비스가 Microsoft 관리 인프라에서 실행되더라도 마찬가지다. 서비스의 실행 위치와 고객 VNet에서 사용하는 출발지 주소는 구분해야 한다.

이 문서에서 말하는 Source IP는 **고객 VNet 측에서 관측하는 주소이며, 이후 Firewall 등의 추가 SNAT이 적용되기 전 주소**다. SRE Agent를 실측 예시로 사용하지만, 설명하려는 핵심은 특정 제품이 아니라 delegated subnet 기반 VNet Integration의 주소 사용 방식이다. 모든 Azure 서비스의 네트워크 연동 기능이 같은 구현이라는 뜻은 아니다.

## 1. 단순히 subnet을 경유하는 것과 무엇이 다른가

Subnet delegation과 VNet Integration의 역할을 구분하면 이해하기 쉽다.

| 개념 | 역할 |
|---|---|
| Subnet delegation | 특정 Azure 서비스가 subnet을 사용하도록 위임하고, 서비스에 필요한 네트워크 구성 조건을 적용할 수 있게 한다. |
| Delegated subnet 기반 VNet Integration | 서비스가 해당 subnet의 주소를 사용해 고객 VNet으로 통신할 수 있는 연결을 구성한다. 실제 구현은 서비스마다 다르다. |
| 라우팅 | 패킷을 어느 경로로 전달할지 결정한다. 경로를 바꾼다는 이유만으로 Source IP가 바뀌지는 않는다. |
| SNAT | 패킷의 Source IP를 다른 주소로 변환한다. Delegation 자체와는 별개다. |

따라서 다음 두 설명은 다르다.

- **부정확한 설명:** “트래픽이 delegated subnet을 지나가므로 Source IP가 자동으로 그 대역으로 변환된다.”
- **정확한 설명:** “VNet Integration이 해당 subnet의 주소를 서비스의 VNet 측 출발지 주소로 사용하도록 연결한다.”

이런 형태의 Integration에서는 사용자가 별도의 SNAT 규칙을 만들지 않아도, 플랫폼이 구성한 연동을 통해 subnet 대역의 사설 IP가 Source IP로 관측된다. 다만 이것만으로 내부 구현이 주소 변환인지, 해당 주소를 사용하는 인터페이스나 연결 생성인지까지 단정할 수는 없다.

[Subnet delegation 공식 문서](https://learn.microsoft.com/azure/virtual-network/subnet-delegation-overview)도 각 Azure 서비스가 자신의 배포 모델과 subnet 요구 사항을 정의한다고 설명한다. Delegation 설정 자체가 모든 서비스에 공통된 Source IP 변환 규칙을 제공하는 것은 아니다.

## 2. 공식 문서가 설명하는 구체적인 사례: App Service

SRE Agent와 별개로, App Service는 VNet Integration의 구현을 다음과 같이 설명한다.

> “Virtual network integration works by mounting virtual interfaces to the worker roles with addresses in the delegated subnet.”

즉, App Service의 실행 환경에 **delegated subnet의 주소를 가진 가상 인터페이스를 연결**하는 방식이다. 같은 문서는 integration VNet이나 peered VNet의 VM 또는 Private Endpoint로 연결할 때 integration subnet의 주소를 사용한다고 명시한다.

출처: [App Service — How virtual network integration works](https://learn.microsoft.com/azure/app-service/overview-vnet-integration#how-virtual-network-integration-works)

이 설명에서 중요한 점은 서비스가 고객 subnet을 단순한 통과 구간으로만 사용하는 것이 아니라, **그 subnet의 주소를 자신의 VNet 측 통신에 사용한다**는 것이다.

App Service는 이를 가상 인터페이스로 설명하지만, 다른 서비스도 내부적으로 동일한 인터페이스나 NIC 구조를 사용한다고 일반화해서는 안 된다. 일반화할 수 있는 범위는 해당 서비스의 문서가 설명하는 주소 할당 방식과 실제 관측 결과까지다.

## 3. SRE Agent를 이용한 실측

### 실험 구성

| 항목 | 설정 |
|---|---|
| 서비스 | Azure SRE Agent, Azure VNet 모드 |
| VNet | `10.42.0.0/16` |
| Agent integration subnet | `10.42.1.0/26` |
| Subnet delegation | `Microsoft.App/environments` |
| Firewall subnet | `10.42.0.0/26` |
| Firewall Private IP | `10.42.0.4` |
| Agent subnet 기본 경로 | `0.0.0.0/0`을 Firewall Private IP로 전달 |
| 허용 정책 | Agent subnet에서 `example.com`으로 HTTPS/443 허용, 나머지는 기본 차단 |
| 관측 지점 | 고객 Azure Firewall의 Application rule 로그 |

SRE Agent의 공식 문서는 Azure VNet 모드에서 기본적으로 non-platform 아웃바운드 트래픽이 고객 VNet의 delegated subnet을 통과하며, 고객의 NSG·Firewall 정책·DNS가 적용된다고 설명한다.

출처: [Azure SRE Agent — Network integration](https://learn.microsoft.com/azure/sre-agent/network-integration#how-azure-vnet-mode-works)

### 관측 결과

Agent를 VNet에 연결한 뒤, 샌드박스에서 두 인터넷 목적지에 HTTPS 요청을 실행했다. Source IP로 미리 필터링하지 않고 로그를 조회했으며, 각 로그의 `_ResourceId`가 실험용 Firewall과 일치하는지도 확인했다.

2026-10-16 **11:27:51 KST**에 기록된 결과는 다음과 같다.

| 목적지 | Firewall 처리 | 관측된 Source IP | 로그 수 |
|---|---|---|---:|
| `example.com:443` | Allow | **`10.42.1.53`** | 1 |
| `example.org:443` | Deny — 기본 차단 | **`10.42.1.53`** | 3 |

```text
SRE Agent 샌드박스
        |
        | VNet Integration
        v
Delegated subnet: 10.42.1.0/26
        |
        | 관측된 HTTPS Source IP: 10.42.1.53
        v
고객 Azure Firewall: 10.42.0.4
        |
        +-- example.com:443  -> Allow
        +-- example.org:443  -> Deny
```

**허용·차단 양쪽의 HTTPS 로그 모두 Source IP가 `10.42.1.53`이었으며, 이는 delegated subnet `10.42.1.0/26`에 포함된다.** 따라서 이 실험에서는 서비스의 VNet 경유 트래픽이 고객 Firewall에 도착할 때 해당 subnet 대역의 사설 IP를 출발지 주소로 사용한다는 점을 확인했다.

이 결과가 SRE Agent 내부에서 어떤 방식으로 주소를 구성하거나 변환하는지까지 입증하는 것은 아니다. 또한 Firewall의 Allow 로그는 HTTP 200 응답 자체를 증명하지 않으며, 로그 수와 개별 HTTP 요청 횟수의 대응은 별도로 확인해야 한다. 여기서 검증한 대상은 **Firewall에서 실제로 관측한 Source IP**다.

실험 자료:

- [환경 구성 및 실험 절차](./README.md)
- [HTTPS Application 로그 원본](./artifacts/test-application.json)
- [관측 결과 요약과 검증 항목](./artifacts/traffic-verification.json)
- [로그 조회용 KQL](./queries.kql)

## 4. 이 결론을 적용할 때의 범위

### VNet Integration으로 실제 라우팅되는 트래픽에 한정한다

서비스가 발생시키는 모든 트래픽이 항상 integration 경로를 사용하는 것은 아니다. 예를 들어 SRE Agent에는 플랫폼 서비스·커넥터 등 고객 VNet을 경유하지 않는 경로가 있다. App Service도 라우팅 설정에 따라 인터넷행 트래픽이 VNet을 경유하지 않을 수 있다.

따라서 **“VNet Integration을 켰으니 모든 통신의 Source IP가 subnet 대역이다”**가 아니라, **“해당 integration 경로로 고객 VNet에 나오는 트래픽의 Source IP가 subnet 대역이다”**라고 표현해야 한다.

### 관측 지점 이후의 SNAT은 별개다

고객 Firewall에서 관측한 integration subnet의 사설 IP와, Firewall을 지나 인터넷 목적지에서 관측하는 주소는 다를 수 있다.

Azure Firewall을 통한 일반적인 인터넷 egress에서는 Firewall의 공인 IP가 사용되며, Firewall subnet에 NAT Gateway를 연동했다면 NAT Gateway의 공인 IP가 사용될 수 있다. 이는 VNet Integration의 사설 출발지 주소와 이후 egress 구간의 주소 변환을 구분해야 한다는 뜻이다.

출처: [Azure Firewall SNAT](https://learn.microsoft.com/azure/firewall/snat-private-range), [Firewall의 Public IP 및 NAT Gateway 연동](https://learn.microsoft.com/azure/virtual-network/ip-services/configure-public-ip-firewall#advanced-configuration)

### 단일 고정 IP를 의미하지 않는다

“Subnet 대역의 IP를 사용한다”와 “항상 같은 IP 하나를 사용한다”는 다른 주장이다. 이번에 관측한 `10.42.1.53`이 재시작이나 확장 이후에도 유지된다는 보장은 이 실험으로 확인하지 않았다.

서비스별 주소 할당·변경 조건은 해당 서비스 문서를 확인해야 한다. 예를 들어 App Service는 integration subnet에서 할당된 `WEBSITE_PRIVATE_IP` 값이 변경될 수 있다고 명시한다.

출처: [App Service — Manage virtual network integration](https://learn.microsoft.com/azure/app-service/overview-vnet-integration#manage-virtual-network-integration)

## 요약

> **Delegated subnet의 주소를 사용하는 VNet Integration에서는 서비스가 그 subnet 대역의 사설 IP를 VNet 측 출발지 주소로 사용한다. 이는 단순히 subnet을 경유해서 주소가 바뀌는 현상이 아니라, 서비스의 VNet 연동이 구성하는 통신 방식이다. SRE Agent 실험에서도 고객 Firewall에 도착한 HTTPS 트래픽의 Source IP가 delegated subnet 내 주소인 `10.42.1.53`으로 확인됐다.**
