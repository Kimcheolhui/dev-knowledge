# Azure Application Gateway와 Load Balancer

## 개요

Azure Application Gateway와 Load Balancer는 Azure에서 제공하는 부하 분산 서비스임. 두 서비스는 모두 트래픽을 여러 백엔드 리소스로 분산하는 역할을 하지만, 동작 계층(L4 vs L7), 내부 구조, 비용 모델, 그리고 제공하는 기능에서 큰 차이가 있음.

이 문서에서는 두 서비스의 네트워크 모델(VNet Integration vs VNet Injection), 내부 아키텍처, 기능 차이, 비용 구조를 상세히 다룸.

## VNet Integration vs VNet Injection

Azure 리소스와 VNet의 관계를 이해하는 것이 Application Gateway와 Load Balancer의 동작 방식을 이해하는 핵심임.

### 용어 정의

#### VNet Integration (VNet 연결)

- 리소스는 Azure 관리 네트워크(Microsoft 네트워크)에 존재함
- VNet에 직접 배치되지 않고, VNet으로 나가는 아웃바운드 연결만 설정됨
- 리소스가 VNet 내부의 NIC나 Private IP를 갖지 않음
- 주로 아웃바운드 트래픽을 VNet을 통해 전송하는 용도

**대표 예시:**
- Azure App Service
- Azure Functions

**특징:**
- UDR(User Defined Route) 적용 불가
- NSG(Network Security Group) 적용 불가
- 인바운드 트래픽은 여전히 공용 엔드포인트를 통해서만 가능
- VNet 내부 리소스처럼 동작하지 않음

#### VNet Injection (VNet 배치)

- 리소스가 VNet 내부의 서브넷에 직접 배치됨
- 서브넷 내에 NIC(Network Interface Card)와 Private IP를 가짐
- 리소스가 VNet의 일부로서 실제로 존재함
- 인바운드와 아웃바운드 모두 VNet 내부에서 처리

**대표 예시:**
- Azure Application Gateway
- Azure Kubernetes Service (AKS Node Pool)
- Azure Virtual Machines

**특징:**
- UDR 적용 가능
- NSG 적용 가능
- VNet Peering을 통한 Hub-Spoke 아키텍처 구성 가능
- Private IP를 통한 내부 통신 가능
- Azure Firewall 등을 통한 트래픽 제어 가능

**참고: AKS의 네트워크 모델**
- AKS는 여러 구성 요소로 이루어져 있으며, 각 구성 요소의 네트워크 모델이 다름
- **Node Pool (Worker Nodes)**: VNet Injection - 노드들이 VNet의 서브넷에 직접 배치되며 Private IP를 가짐
- **API Server**: VNet Injection도 Integration도 아님 - Private Endpoint를 통해 VNet에서 접근 가능 (Private AKS 클러스터의 경우)
- 따라서 "AKS는 VNet Injection"이라는 표현은 정확히는 Node Pool에 대한 설명임

### 비교표

| 구분 | VNet Integration | VNet Injection |
|------|------------------|----------------|
| **리소스 위치** | VNet 외부 (Microsoft 네트워크) | VNet 내부 (고객 VNet) |
| **NIC / Private IP** | 없음 | 있음 |
| **전용 Subnet 필요** | 불필요 | 필수 |
| **UDR 적용** | 불가능 | 가능 |
| **NSG 적용** | 불가능 | 가능 |
| **Private Backend 통신** | 제한적 | 직접 가능 |
| **트래픽 방향** | 주로 Outbound | Inbound & Outbound |
| **예시** | App Service, Functions | Application Gateway, AKS Node Pool, VM |

### 실무 중요성

Hub-Spoke 네트워크 아키텍처에서 Azure Firewall을 통한 트래픽 제어, Private AKS 연동, UDR 기반 라우팅 등을 구현할 때 VNet Injection 여부가 핵심적인 차이를 만듦.

**VNet Injection인 경우 가능한 것들:**
- Application Gateway Subnet에 UDR을 설정하여 트래픽을 Azure Firewall로 우회
- Private AKS를 Private IP로 직접 Backend Pool에 등록
- VNet Peering을 통해 Spoke VNet의 리소스를 Backend로 등록
- Application Gateway → Firewall → Internet 같은 복잡한 라우팅 구성

## Azure Application Gateway

### 네트워크 모델: VNet Injection

Azure Application Gateway는 **VNet Injection 모델**임. VNet Integration이 아님.

#### 배치 특성

- **전용 Subnet 필수**: Application Gateway 생성 시 반드시 VNet의 전용 Subnet이 필요함
- **Subnet 명명**: 전용 서브넷은 다른 리소스와 공유할 수 없으며, Application Gateway만을 위해 사용되어야 함
- **NIC와 Private IP**: Application Gateway 인스턴스들이 해당 Subnet에 NIC와 Private IP를 직접 가짐
- **네트워크 관점**: PaaS처럼 보이지만 네트워크 관점에서는 거의 NVA(Network Virtual Appliance) 수준의 네트워크 장비임

#### VNet Injection이므로 가능한 것들

1. **UDR 적용**: Application Gateway Subnet에 사용자 정의 경로를 적용하여 트래픽 라우팅 제어 가능
2. **NSG 적용**: Network Security Group을 통한 보안 규칙 적용 가능 (단, Application Gateway 동작에 필요한 특정 포트는 열어야 함)
3. **VNet Peering 지원**: Hub-Spoke 아키텍처에서 Peering을 통해 다른 VNet의 리소스와 통신 가능
4. **Private Frontend**: Private IP를 Frontend로 사용하여 내부 전용 Application Gateway 구성 가능
5. **Private Backend**: Backend Pool에 Private IP를 직접 등록 (AKS, VM, Internal Load Balancer 등)

### 내부 구조

Application Gateway는 L7(애플리케이션 계층) 프록시로 동작하며, 관리형 게이트웨이 인스턴스들로 구성됨.

#### 인스턴스 기반 구조

- Application Gateway는 내부적으로 여러 **게이트웨이 인스턴스**로 구성됨
- 각 인스턴스는 L7 프록시 엔진을 실행하며, HTTP/HTTPS 트래픽을 처리함
- 오토스케일링 시 인스턴스가 자동으로 추가되거나 제거됨
- 장애 발생 시 Azure가 자동으로 새 인스턴스를 생성하여 교체함
- 고객이 직접 VM이나 인스턴스를 관리하지는 않지만, 서비스 내부적으로는 컴퓨팅 리소스가 필요함

#### L7 처리를 위한 필요성

Application Gateway는 다음과 같은 고급 기능을 제공하기 위해 실제 컴퓨팅 리소스가 필요함:
- HTTP/HTTPS 프로토콜 파싱
- Host header 기반 라우팅
- Path 기반 라우팅
- TLS/SSL 종료 (암호화/복호화)
- 인증서 관리 및 SNI(Server Name Indication) 처리
- WAF(Web Application Firewall) 규칙 검사
- 요청/응답 본문 검사
- URL Rewrite 및 Redirect
- Cookie 기반 세션 어피니티

이러한 작업들은 단순한 패킷 포워딩이 아니라, 애플리케이션 계층에서의 복잡한 처리를 요구하므로 CPU와 메모리가 필요함.

### 주요 기능

#### 기본 기능
- **SSL/TLS 종료**: 백엔드 서버의 부하를 줄이기 위해 Application Gateway에서 SSL을 종료
- **엔드투엔드 SSL**: 백엔드까지 암호화된 연결 유지
- **자동 크기 조정**: 트래픽에 따라 자동으로 인스턴스 수 조정
- **영역 중복성**: 가용성 영역 간 분산 배치로 고가용성 보장
- **세션 어피니티**: Cookie 기반으로 동일한 사용자를 동일한 백엔드 서버로 라우팅

#### 고급 라우팅
- **호스트 기반 라우팅**: Host header를 기반으로 다른 백엔드 풀로 분산
- **경로 기반 라우팅**: URL 경로에 따라 다른 백엔드 풀로 분산
- **다중 사이트 호스팅**: 단일 Application Gateway로 여러 웹 사이트 호스팅
- **URL Rewrite**: 요청/응답 URL 및 헤더 수정
- **리디렉션**: HTTP를 HTTPS로 자동 리디렉션

#### 보안 기능
- **WAF (Web Application Firewall)**: OWASP Core Rule Set 기반 웹 공격 방어
- **사용자 지정 WAF 규칙**: 특정 패턴에 대한 맞춤형 보안 규칙
- **상호 TLS 인증**: 클라이언트 인증서 검증

### 비용 구조

Application Gateway는 인스턴스 기반 구조이므로 다음과 같은 비용이 발생함:

1. **고정 비용 (시간당)**: 인스턴스가 실행되는 시간에 비례
2. **용량 단위 비용**: 컴퓨팅 파워, 연결 수, 처리량에 따라 부과
3. **데이터 처리 비용**: 처리되는 데이터 양(GB)에 따라 부과

오토스케일링을 사용하지 않더라도 최소 인스턴스 수만큼 시간당 비용이 발생함.

## Azure Load Balancer

### 네트워크 모델: SDN 기반 L4 분산 기능

Azure Load Balancer는 엄밀히 말하면 VNet Integration도 VNet Injection도 아님. **Azure SDN(Software Defined Networking) 데이터플레인에 프로그래밍되는 L4 분산 기능**임.

#### 구조적 특징

- **VM/NIC 없음**: Application Gateway와 달리 별도의 VM이나 인스턴스가 존재하지 않음
- **Subnet 배치 없음**: 특정 Subnet에 NIC가 생성되지 않음
- **SDN 레벨 동작**: Azure 호스트(하이퍼바이저) 레벨의 SDN 스택에서 부하 분산 규칙이 프로그래밍됨
- **분산 구조**: 각 VM/노드가 올라가 있는 물리 호스트의 SDN Agent가 부하 분산을 처리함

#### 트래픽 흐름

```
클라이언트 → Azure SDN Fabric → Host SDN Agent → Backend NIC
```

중간에 별도의 프록시 VM이나 네트워크 장비가 개입하지 않음. 이는 매우 낮은 지연 시간과 높은 처리량을 가능하게 함.

### VNet과의 관계

Azure Load Balancer는 다음과 같은 특성으로 인해 VNet 내부 리소스처럼 동작함:

#### Frontend IP 구성
- **Public Load Balancer**: 공용 IP 주소를 Frontend로 사용
- **Internal Load Balancer (ILB)**: VNet의 Subnet 내에서 Private IP를 Frontend로 사용

#### Backend Pool 제약
- Backend Pool의 리소스는 Load Balancer의 Frontend IP와 **동일한 VNet 내**에 있어야 함
- 이는 Azure SDN 데이터플레인 라우팅의 제약 사항임

#### 네트워크 제어 영향
- **UDR 영향**: Backend Pool로의 트래픽은 UDR의 영향을 받음
- **NSG 영향**: Backend 리소스의 NSG는 적용됨
- **VNet Peering**: Peering을 통해 다른 VNet의 Backend 리소스 연결 가능

### 내부 동작 원리

#### L4 분산 메커니즘

Azure Load Balancer는 다음 정보를 기반으로 트래픽을 분산함:
- **5-tuple 해시**: 소스 IP, 소스 포트, 대상 IP, 대상 포트, 프로토콜
- **세션 어피니티**: 2-tuple(소스 IP, 대상 IP) 또는 3-tuple(소스 IP, 대상 IP, 프로토콜) 옵션 지원

#### NAT 기능
- **Inbound NAT Rules**: 특정 포트를 특정 Backend 인스턴스로 매핑
- **Outbound Rules**: Backend 리소스의 아웃바운드 트래픽에 대한 SNAT 구성

#### 고성능의 이유

Load Balancer가 초고성능(수십 Gbps)을 제공할 수 있는 이유:
1. **VM을 거치지 않음**: 별도의 프록시 VM이 없으므로 병목 지점이 없음
2. **분산 구조**: 각 물리 호스트에서 독립적으로 부하 분산 처리
3. **하드웨어 가속**: Azure SDN은 하드웨어 오프로드를 활용
4. **장애 포인트 없음**: 단일 실패 지점이 없는 분산 아키텍처

### 주요 기능

#### 기본 기능
- **TCP/UDP 부하 분산**: L4 계층에서의 트래픽 분산
- **상태 모니터링**: Health Probe를 통한 Backend 상태 확인
- **고가용성**: 영역 중복 Frontend IP 지원
- **자동 재구성**: Backend 리소스 추가/제거 시 자동 반영

#### 고급 기능 (Standard SKU)
- **HA Ports**: 모든 포트에 대한 부하 분산 (0~65535)
- **여러 Frontend**: 단일 Load Balancer에 여러 공용/사설 IP 구성
- **Outbound 연결**: Backend 리소스의 아웃바운드 인터넷 연결 제공
- **SLA 보장**: 99.99% 가용성 SLA

#### 제약 사항 (L4이므로 불가능한 것들)
- **HTTP/HTTPS 이해 불가**: HTTP 프로토콜을 파싱하지 못함
- **TLS 종료 불가**: SSL/TLS 암호화/복호화 불가능
- **Header 기반 라우팅 불가**: Host나 Path 기반 라우팅 불가능
- **Cookie 세션 불가**: HTTP Cookie를 인식하지 못함
- **WAF 불가**: 애플리케이션 계층 공격 방어 불가능
- **Content 기반 처리 불가**: URL Rewrite, Redirect 등 불가능

### 비용 구조

Azure Load Balancer는 독특한 비용 구조를 가짐:

#### Basic SKU
- **완전 무료**: Load Balancer 자체 비용이 없음
- 이유: Azure VNet의 기본 네트워크 기능으로 제공되므로 별도 리소스 비용이 없음

#### Standard SKU
- **규칙 비용**: Load Balancing 규칙 및 NAT 규칙 수에 따라 시간당 소액의 비용
- **데이터 처리 비용**: 처리되는 데이터 양(GB)에 따라 부과
- **인스턴스 비용 없음**: Application Gateway와 달리 시간당 인스턴스 비용은 없음

#### 왜 비용이 낮은가?

Load Balancer는 다음과 같은 이유로 비용이 낮음:
1. **VM이 없음**: 별도의 컴퓨팅 리소스를 유지할 필요가 없음
2. **SDN 기능**: 이미 존재하는 Azure 네트워크 인프라에 규칙만 추가하는 형태
3. **추가 유지비용 없음**: Azure 입장에서 추가로 유지해야 할 컴퓨팅 리소스가 없음

Load Balancer의 Standard SKU 비용은 주로 **Azure 네트워크 데이터플레인 사용량**에 대한 과금임.

## Application Gateway vs Load Balancer 비교

### 계층 및 구조 비교

| 항목 | Application Gateway | Load Balancer |
|------|---------------------|---------------|
| **OSI 계층** | L7 (Application Layer) | L4 (Transport Layer) |
| **내부 구조** | 관리형 게이트웨이 인스턴스 | Azure SDN 분산 규칙 엔진 |
| **VM 존재 여부** | 있음 (관리형) | 없음 |
| **Subnet 필요** | 필수 (전용 Subnet) | Frontend IP만 필요 |
| **NIC 생성** | 있음 | 없음 |
| **네트워크 모델** | VNet Injection | SDN 데이터플레인 기능 |

### 기능 비교

| 기능 | Application Gateway | Load Balancer |
|------|---------------------|---------------|
| **프로토콜** | HTTP, HTTPS, WebSocket | TCP, UDP |
| **SSL/TLS 종료** | ✅ 가능 | ❌ 불가능 |
| **Host 기반 라우팅** | ✅ 가능 | ❌ 불가능 |
| **Path 기반 라우팅** | ✅ 가능 | ❌ 불가능 |
| **URL Rewrite** | ✅ 가능 | ❌ 불가능 |
| **Redirect** | ✅ 가능 | ❌ 불가능 |
| **WAF** | ✅ 가능 | ❌ 불가능 |
| **Cookie 세션 어피니티** | ✅ 가능 | ❌ 불가능 |
| **WebSocket** | ✅ 지원 | ❌ 불가능 |
| **mTLS** | ✅ 가능 | ❌ 불가능 |
| **5-tuple 해시 분산** | ❌ (HTTP 기반) | ✅ 가능 |
| **HA Ports** | ❌ | ✅ 가능 |
| **초고성능 처리량** | 중간 수준 | 매우 높음 (수십 Gbps) |

### 네트워크 제어 비교

| 항목 | Application Gateway | Load Balancer |
|------|---------------------|---------------|
| **UDR 적용** | ✅ Subnet에 적용 가능 | ✅ Backend로의 라우팅 영향 |
| **NSG 적용** | ✅ Subnet에 적용 가능 | ✅ Backend 리소스에 적용 |
| **VNet Peering** | ✅ 가능 | ✅ 가능 |
| **Private Frontend** | ✅ 가능 | ✅ 가능 (ILB) |
| **Private Backend** | ✅ 직접 연결 | ✅ 직접 연결 |
| **Azure Firewall 경유** | ✅ UDR로 가능 | ✅ UDR로 가능 |

### 비용 비교

| 항목 | Application Gateway | Load Balancer |
|------|---------------------|---------------|
| **시간당 인스턴스 비용** | ✅ 있음 | ❌ 없음 |
| **데이터 처리 비용** | ✅ 있음 | ✅ 있음 (Standard) |
| **용량 단위 비용** | ✅ 있음 | ❌ 없음 |
| **최소 비용** | 높음 (항상 인스턴스 실행) | 낮음 (규칙 비용만) |
| **비용 발생 이유** | VM 기반 프록시 | 네트워크 사용량 |

### 사용 사례 비교

#### Application Gateway 적합한 경우

1. **웹 애플리케이션 부하 분산**
   - HTTP/HTTPS 트래픽을 여러 웹 서버로 분산
   - Host/Path 기반으로 마이크로서비스 라우팅

2. **SSL/TLS 오프로딩**
   - Backend 서버의 SSL 부하 감소
   - 중앙화된 인증서 관리

3. **보안이 중요한 웹 서비스**
   - WAF를 통한 웹 공격 방어 필요
   - OWASP Top 10 공격 방어

4. **복잡한 라우팅 요구사항**
   - URL Rewrite/Redirect 필요
   - 다중 사이트 호스팅

5. **AKS Ingress Controller 대체**
   - AKS 클러스터 앞단의 L7 부하 분산
   - Azure 네이티브 솔루션으로 통합 관리

#### Load Balancer 적합한 경우

1. **비-HTTP 프로토콜 부하 분산**
   - 데이터베이스 연결 (SQL, MySQL, PostgreSQL)
   - 커스텀 TCP/UDP 애플리케이션
   - RDP, SSH 등 관리 프로토콜

2. **초고성능 요구사항**
   - 수십 Gbps 처리량 필요
   - 매우 낮은 지연 시간 필요

3. **비용 최적화**
   - 단순 L4 부하 분산만 필요
   - HTTP 고급 기능 불필요

4. **VM/VMSS 부하 분산**
   - 여러 VM 간 트래픽 분산
   - VMSS Auto-scaling과 연동

5. **AKS Service type=LoadBalancer**
   - Kubernetes Service의 외부 노출
   - 단순 TCP/UDP 포트 노출

6. **Outbound 인터넷 연결**
   - Backend 리소스의 아웃바운드 SNAT
   - 고정된 공용 IP로 아웃바운드 연결

### 함께 사용하는 경우

실무에서는 두 서비스를 함께 사용하는 경우가 많음:

#### 패턴 1: Application Gateway → Load Balancer → VM

```
Internet → Application Gateway (L7, WAF, TLS 종료)
             ↓
         Internal Load Balancer (L4 분산)
             ↓
         VM Scale Set
```

- Application Gateway: 웹 공격 방어, SSL 종료, Host/Path 라우팅
- Load Balancer: VM 간 고성능 TCP 분산

#### 패턴 2: Application Gateway → AKS (LoadBalancer Service)

```
Internet → Application Gateway (L7)
             ↓
         AKS Service type=LoadBalancer (내부적으로 Load Balancer 생성)
             ↓
         Pod
```

- Application Gateway: 외부 인터넷 → AKS 진입점, WAF
- Load Balancer: AKS 노드 간 분산

#### 패턴 3: Load Balancer → Application Gateway → Backend

```
Internet → Public Load Balancer (L4, IP 분산)
             ↓
         Application Gateway (L7, 도메인별 라우팅)
             ↓
         Backend Services
```

- 특수한 경우에만 사용
- 여러 지역/IP 기반 분산이 필요한 경우

## 자주 하는 오해

### 오해 1: "Application Gateway도 리소스 비용이 없을 것이다"

**틀렸음.** Application Gateway는 내부적으로 관리형 인스턴스를 실행하므로 항상 시간당 비용이 발생함. Load Balancer와 달리 VM 기반 구조이므로 비용이 높음.

### 오해 2: "Load Balancer도 VNet Injection이다"

**부정확함.** Load Balancer는 VNet Injection도 Integration도 아닌, Azure SDN의 네트워크 기능에 가까움. 별도의 VM이나 NIC가 생성되지 않음.

### 오해 3: "Application Gateway가 더 비싸니까 모든 면에서 더 좋다"

**틀렸음.** Application Gateway는 L7 기능만 제공하며, L4 수준의 초고성능이나 비-HTTP 프로토콜은 Load Balancer가 더 적합함. 용도가 다름.

### 오해 4: "Load Balancer는 무료이므로 성능이 떨어질 것이다"

**틀렸음.** Load Balancer는 Azure SDN에서 직접 처리되므로 오히려 Application Gateway보다 훨씬 높은 처리량(수십 Gbps)을 제공함. 무료인 이유는 별도 VM이 필요 없기 때문임.

### 오해 5: "Application Gateway는 WAF가 있으니 Load Balancer를 대체할 수 있다"

**틀렸음.** Application Gateway는 HTTP/HTTPS만 지원하므로 TCP/UDP 프로토콜이 필요한 경우 Load Balancer를 사용해야 함.

## 아키텍처 설계 가이드

### Hub-Spoke 아키텍처에서의 활용

#### Application Gateway 배치 권장사항

**Hub VNet 배치:**
```
Hub VNet
  ├─ AzureFirewallSubnet (Azure Firewall)
  ├─ ApplicationGatewaySubnet (Application Gateway)
  └─ Peering → Spoke VNet (AKS, VM)
```

**장점:**
- 중앙화된 인그레스 제어
- Firewall을 통한 아웃바운드 제어
- Spoke의 여러 Backend 서비스를 하나의 Application Gateway로 관리

**UDR 구성 예시:**
```
ApplicationGatewaySubnet UDR:
  0.0.0.0/0 → Azure Firewall
  (Application Gateway 관리 트래픽은 예외 처리 필수)
```

#### Load Balancer 배치 권장사항

**Spoke VNet 배치:**
```
Spoke VNet
  ├─ VM Subnet (Internal Load Balancer Frontend)
  ├─ AKS Subnet (Service type=LoadBalancer)
  └─ Peering → Hub VNet
```

**장점:**
- Spoke 내부의 고성능 분산
- 비-HTTP 프로토콜 지원
- 비용 효율적

### 보안 고려사항

#### Application Gateway NSG 규칙

Application Gateway Subnet의 NSG는 다음 규칙을 허용해야 함:

**필수 인바운드 규칙:**
- **포트 65200-65535**: Azure 인프라 통신 (GatewayManager service tag)
- **포트 80, 443**: 실제 클라이언트 트래픽
- **Health Probe 포트**: Backend에 대한 Health Probe

**필수 아웃바운드 규칙:**
- **Backend Pool 포트**: Backend 서버로의 연결
- **포트 443**: Azure 서비스 통신 (인증서, 진단 등)

#### Load Balancer 보안

Load Balancer 자체는 NSG를 가지지 않지만, Backend 리소스의 NSG를 설정해야 함:

**Backend NSG 규칙:**
- **Load Balancer Health Probe**: AzureLoadBalancer service tag 허용
- **실제 서비스 포트**: 필요한 포트만 선택적 허용

### 고가용성 설계

#### Application Gateway
- **영역 중복**: 여러 가용성 영역에 인스턴스 분산
- **최소 인스턴스 수**: 최소 2개 이상 권장
- **오토스케일링**: 트래픽 패턴에 따라 동적 확장

#### Load Balancer
- **영역 중복 Frontend**: 표준 SKU에서 지역 중복 IP 사용
- **여러 Backend**: Health Probe로 정상 Backend만 트래픽 전송
- **크로스 존 부하 분산**: 가용성 영역 간 자동 분산

### 모니터링 및 진단

#### Application Gateway
- **메트릭**: 처리량, 응답 시간, 실패한 요청, Backend 상태
- **로그**: 액세스 로그, 성능 로그, 방화벽 로그 (WAF 사용 시)
- **NSG Flow 로그**: Subnet 수준 트래픽 분석

#### Load Balancer
- **메트릭**: 데이터 처리량, SNAT 포트 사용률, Health Probe 상태
- **진단 로그**: Load Balancing 규칙, Health Probe 이벤트
- **연결 모니터**: Backend 연결 상태 확인

## 주요 제약사항 및 제한

### Application Gateway 제한

- **Backend Pool 크기**: SKU에 따라 최대 100~125개
- **리스너 수**: 최대 100개
- **규칙 수**: 최대 100개
- **WAF**: v2 SKU만 지원
- **WebSocket**: v2 SKU에서만 지원
- **Private Link**: v2 SKU에서만 지원
- **동시 연결**: SKU 및 인스턴스 수에 따라 제한

### Load Balancer 제한

- **Frontend IP**: 최대 600개 (Public + Private 합계)
- **Backend Pool 크기**: 표준 SKU에서 최대 1000개
- **Load Balancing 규칙**: 최대 1000개
- **Inbound NAT 규칙**: 최대 1000개
- **HA Ports**: 내부 Load Balancer에서만 사용 가능
- **Cross-region 부하 분산**: 글로벌 Load Balancer 계층 필요

## 참고 자료

### Application Gateway 공식 문서

- [Application Gateway 인프라 구성 (Subnet/NSG/UDR 등)](https://learn.microsoft.com/azure/application-gateway/configuration-infrastructure)
- [Application Gateway FAQ](https://learn.microsoft.com/azure/application-gateway/application-gateway-faq)
- [Application Gateway v2 오토스케일 및 영역 중복](https://learn.microsoft.com/azure/application-gateway/application-gateway-autoscaling-zone-redundant)
- [Application Gateway 작동 방식](https://learn.microsoft.com/azure/application-gateway/how-application-gateway-works)

### Load Balancer 공식 문서

- [Azure Load Balancer 개요](https://learn.microsoft.com/azure/load-balancer/load-balancer-overview)
- [Load Balancer SKU 비교](https://learn.microsoft.com/azure/load-balancer/skus)
- [Load Balancer 가격](https://azure.microsoft.com/pricing/details/load-balancer/)

### VNet 통합 관련

- [Azure VNet 서비스 엔드포인트](https://learn.microsoft.com/azure/virtual-network/virtual-network-service-endpoints-overview)
- [Private Link 및 Private Endpoint](https://learn.microsoft.com/azure/private-link/private-link-overview)

### 아키텍처 참조

- [Hub-Spoke 네트워크 토폴로지](https://learn.microsoft.com/azure/architecture/reference-architectures/hybrid-networking/hub-spoke)
- [Azure Application Gateway를 사용한 웹 애플리케이션 방화벽](https://learn.microsoft.com/azure/architecture/example-scenario/gateway/application-gateway-before-azure-firewall)

## 요약

### 핵심 차이점

1. **계층**: Application Gateway는 L7, Load Balancer는 L4
2. **구조**: Application Gateway는 관리형 인스턴스 기반, Load Balancer는 Azure SDN 기능
3. **기능**: Application Gateway는 HTTP 고급 기능 제공, Load Balancer는 초고성능 TCP/UDP 분산
4. **비용**: Application Gateway는 인스턴스 비용 발생, Load Balancer는 주로 데이터 사용량 비용

### 선택 가이드

**Application Gateway를 선택해야 하는 경우:**
- HTTP/HTTPS 트래픽 처리
- WAF가 필요
- Host/Path 기반 라우팅 필요
- SSL 종료 필요
- URL Rewrite/Redirect 필요

**Load Balancer를 선택해야 하는 경우:**
- 비-HTTP 프로토콜 (TCP/UDP)
- 초고성능 요구사항 (수십 Gbps)
- 단순 L4 부하 분산
- 비용 최적화가 중요
- Outbound SNAT 필요

**둘 다 사용하는 경우:**
- Application Gateway로 L7 처리 + Load Balancer로 Backend L4 분산
- 복잡한 엔터프라이즈 아키텍처
- 다층 보안 및 라우팅 요구사항

Azure 네트워크 설계 시 각 서비스의 특성과 제약사항을 정확히 이해하고, 요구사항에 맞는 서비스를 선택하는 것이 중요함.
