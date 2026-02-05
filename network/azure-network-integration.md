# Azure 리소스의 네트워크 통합 방식

## 개요

Azure에서 PaaS(Platform as a Service) 리소스와 VNet(Virtual Network)을 통합하는 방법은 크게 세 가지가 있음: Private Endpoint, VNet Integration, VNet Injection. 각각은 네트워크 트래픽의 방향, 보안 요구사항, 서비스 배치 위치에 따라 사용 목적이 다름.

## Private Endpoint

### 정의

Private Endpoint는 Azure PaaS 서비스(Storage, SQL Database, App Service 등)에 대한 인바운드 연결을 VNet 내부 사설 IP 주소로 제공하는 네트워크 인터페이스임. 서비스 자체는 Azure 관리 영역에 존재하지만, VNet 내부에 네트워크 인터페이스를 생성하여 사설 IP를 통해 접근 가능하게 함.

### 사용 목적

- **인바운드 트래픽 제어**: 외부(인터넷)에서 PaaS 서비스로의 접근을 차단하고, VNet 내부에서만 접근 가능하게 함
- **데이터 보안 강화**: 민감한 데이터를 다루는 서비스에 대한 접근을 VNet 내부로 제한
- **규정 준수**: 데이터가 퍼블릭 인터넷을 거치지 않아야 하는 규제 요구사항 충족

### 작동 방식

1. VNet의 서브넷에 네트워크 인터페이스(NIC) 생성
2. 해당 NIC에 사설 IP 주소 할당
3. PaaS 서비스의 FQDN이 사설 IP로 해석되도록 DNS 구성
4. 트래픽은 Microsoft 백본 네트워크만을 통해 전송됨

### DNS 구성

Private Endpoint를 정상적으로 사용하려면 DNS 설정이 필수적임. 서비스의 FQDN(예: `mystorageaccount.blob.core.windows.net`)이 Private Endpoint의 사설 IP로 해석되어야 함.

#### Azure Private DNS Zone 사용

```
1. Private Endpoint 생성 시 Private DNS Zone 생성
   예: privatelink.blob.core.windows.net
   
2. Private DNS Zone에 A 레코드 자동 등록
   mystorageaccount.blob.core.windows.net -> 10.0.1.5
   
3. VNet과 Private DNS Zone 연결 (Virtual Network Link)
   VNet 내 모든 리소스가 사설 IP로 해석
```

#### DNS 해석 흐름

```
클라이언트 쿼리: mystorageaccount.blob.core.windows.net
         ↓
Azure DNS (168.63.129.16)
         ↓
Private DNS Zone 조회
         ↓
Private Endpoint 사설 IP 반환 (10.0.1.5)
```

#### 온프레미스 연동

온프레미스 네트워크에서도 Private Endpoint에 접근해야 하는 경우, DNS 전달 구성이 필요함:

1. **Azure DNS Private Resolver 사용** (권장)
   - Inbound Endpoint를 VNet에 생성
   - 온프레미스 DNS 서버에 조건부 전달자(Conditional Forwarder) 설정
   - Private DNS Zone 도메인 쿼리를 Azure DNS Resolver로 전달

2. **DNS 포워더 VM 사용** (레거시)
   - VNet에 DNS 포워더 역할의 VM 배치
   - 온프레미스 DNS 서버가 해당 VM으로 쿼리 전달

### 사용 예시

```
시나리오: VNet 내 VM에서 Azure SQL Database에 안전하게 접근

[VM (10.0.0.4)] --VNet--> [Private Endpoint (10.0.1.10)] --Azure Backbone--> [Azure SQL Database]

- SQL Database의 공용 엔드포인트 비활성화
- Private Endpoint를 통해서만 접근 가능
- 트래픽이 인터넷을 거치지 않음
```

### 특징

- **트래픽 방향**: 인바운드 (VNet → PaaS 서비스)
- **서비스 위치**: Azure 관리 영역 (VNet 외부)
- **IP 할당**: VNet의 사설 IP 주소 공간에서 할당
- **다중 VNet 지원**: 여러 VNet에 각각 Private Endpoint 생성 가능
- **DNS 필수**: Private DNS Zone 구성 필요
- **추가 비용**: Private Endpoint 및 데이터 처리 비용 발생

### 지원 서비스

- Azure Storage (Blob, File, Queue, Table)
- Azure SQL Database
- Azure Cosmos DB
- Azure Key Vault
- Azure App Service
- Azure Container Registry
- Azure Cognitive Services
- 기타 대부분의 Azure PaaS 서비스

## VNet Integration

### 정의

VNet Integration은 Azure PaaS 서비스가 VNet 내부의 리소스로 아웃바운드 연결을 할 수 있도록 하는 기능임. 주로 App Service, Function App, Logic App 등이 VNet 내부 리소스(VM, 데이터베이스 등)에 접근해야 할 때 사용함.

### 사용 목적

- **아웃바운드 트래픽 제어**: PaaS 서비스에서 VNet 내부 리소스로의 연결
- **온프레미스 연결**: ExpressRoute나 VPN을 통해 온프레미스 리소스 접근
- **네트워크 격리**: 특정 네트워크 경로를 통해서만 외부 통신

### 두 가지 방식

#### 1. Regional VNet Integration (권장)

**특징:**
- App Service와 같은 리전의 VNet에 연결
- VNet Gateway 불필요
- 더 나은 성능과 낮은 지연시간
- 서브넷 위임(Delegation) 필요

**서브넷 위임 설정:**
```
1. Azure Portal > Virtual Network > Subnets 이동
2. 새 서브넷 생성 또는 기존 서브넷 편집
3. "Subnet delegation" 항목에서 "Microsoft.Web/serverFarms" 선택
4. 저장

주의: 위임된 서브넷은 App Service 전용으로 사용됨
다른 리소스(VM 등)와 공유 불가
```

**구성 예시:**
```
Azure Portal에서 App Service 설정:
1. App Service > Networking > VNet Integration
2. "Add VNet Integration" 클릭
3. VNet 및 위임된 서브넷 선택
4. 연결 완료

이제 App Service의 아웃바운드 트래픽이 VNet을 통해 전송됨
```

#### 2. Gateway-required VNet Integration (레거시)

**특징:**
- 다른 리전의 VNet 연결 가능
- VPN Gateway 필요 (추가 비용)
- Point-to-Site VPN 구성 필요
- 2027년 폐지 예정

**사용 권장하지 않음**: 새로운 배포는 Regional VNet Integration 사용

### 작동 방식

```
App Service (아웃바운드 요청)
         ↓
위임된 서브넷 (10.0.2.0/24)
         ↓
VNet 라우팅 테이블 확인
         ↓
VNet 내부 리소스 (예: VM 10.0.1.10) 도달
```

### 사용 예시

```
시나리오: App Service에서 VNet 내부 PostgreSQL 서버에 접근

[App Service] --VNet Integration--> [위임된 서브넷] --VNet--> [PostgreSQL VM (10.0.1.20)]

애플리케이션 연결 문자열:
postgresql://10.0.1.20:5432/mydb

- 퍼블릭 IP 불필요
- 내부 네트워크 통신만 사용
- NSG로 트래픽 제어 가능
```

### 네트워크 기능

VNet Integration을 활용하여 다음 네트워크 기능 사용 가능:

1. **Network Security Groups (NSG)**
   - 아웃바운드 트래픽 규칙 적용
   - 특정 IP/포트로의 접근 제어

2. **User Defined Routes (UDR)**
   - 트래픽을 방화벽 또는 NVA로 라우팅
   - 강제 터널링(Forced Tunneling)

3. **Service Endpoints**
   - VNet Integration과 함께 사용하여 Azure 서비스 접근 최적화

4. **NAT Gateway**
   - 아웃바운드 트래픽에 고정 Public IP 할당
   - 외부 API 호출 시 IP 화이트리스트에 유용

### 특징

- **트래픽 방향**: 아웃바운드 (PaaS 서비스 → VNet)
- **서비스 위치**: Azure 관리 영역 (VNet 외부)
- **단일 VNet**: 하나의 App Service는 하나의 VNet에만 연결 가능
- **서브넷 크기**: 최소 /28 (16개 IP), 권장 /26 이상 (앱 스케일링 고려)
- **DNS**: VNet의 DNS 설정 자동 적용
- **추가 비용**: VNet Integration 자체는 무료 (NAT Gateway나 VPN Gateway는 별도 비용)

### 지원 서비스

- Azure App Service (Web Apps, API Apps)
- Azure Functions (Premium Plan, App Service Plan)
- Azure Logic Apps (Standard)
- Azure Container Apps (일부 시나리오)

## VNet Injection

### 정의

VNet Injection은 Azure 서비스 자체를 VNet의 서브넷 내에 직접 배포하는 방식임. 서비스가 VNet의 일부가 되어 완전한 네트워크 격리와 제어를 제공함.

### 사용 목적

- **완전한 네트워크 격리**: 서비스를 완전히 사설 네트워크에 배치
- **세밀한 트래픽 제어**: 인바운드/아웃바운드 모두 제어 가능
- **규정 준수**: 데이터와 서비스가 외부에 노출되지 않아야 하는 요구사항
- **온프레미스 완전 통합**: 서비스가 온프레미스 네트워크의 일부처럼 작동

### 작동 방식

```
VNet 서브넷 (10.0.3.0/24)
    ├── VM (10.0.3.4)
    ├── VM (10.0.3.5)
    └── Azure Service (10.0.3.10)  ← VNet에 직접 배포됨

서비스가 VNet의 네이티브 리소스로 존재
모든 네트워크 정책 적용 가능 (NSG, UDR, 방화벽 등)
```

### 사용 예시

#### 1. Azure Database for PostgreSQL Flexible Server

```
시나리오: 완전 사설 데이터베이스 구성

[VNet 서브넷 (10.0.5.0/24)]
    └── PostgreSQL Flexible Server (10.0.5.10)

구성:
1. PostgreSQL Flexible Server 생성 시 "Private access (VNet Integration)" 선택
2. VNet 및 서브넷 지정
3. 서버가 해당 서브넷에 배치됨
4. 공용 엔드포인트 없음, VNet 내부에서만 접근 가능

연결:
- VNet 내부: postgresql://10.0.5.10:5432/mydb
- 외부: 접근 불가 (완전 격리)
```

#### 2. Azure Kubernetes Service (AKS)

```
시나리오: AKS 클러스터를 VNet에 배포

[VNet (10.0.0.0/16)]
    ├── AKS 노드 서브넷 (10.0.10.0/24)
    │    ├── Node 1 (10.0.10.4)
    │    ├── Node 2 (10.0.10.5)
    │    └── Node 3 (10.0.10.6)
    └── AKS 포드 서브넷 (10.0.11.0/24)
         ├── Pod 1 (10.0.11.10)
         └── Pod 2 (10.0.11.11)

특징:
- 노드와 포드가 VNet IP 주소 사용
- NSG로 트래픽 제어
- UDR로 라우팅 제어
- VNet 피어링으로 다른 VNet과 통신
```

#### 3. Azure API Management (Internal Mode)

```
시나리오: API Gateway를 내부 네트워크에만 노출

[VNet 서브넷 (10.0.4.0/24)]
    └── APIM (10.0.4.5)

구성:
- Internal VNet Mode 선택
- APIM이 사설 IP만 사용
- 외부에서 직접 접근 불가
- Application Gateway나 방화벽을 통해 선택적 노출 가능
```

### 지원 서비스

VNet Injection을 지원하는 주요 서비스:

- **컴퓨팅**
  - Azure Kubernetes Service (AKS)
  - Azure Container Instances (전용 서브넷)
  - Azure Batch

- **데이터베이스**
  - Azure Database for PostgreSQL Flexible Server
  - Azure Database for MySQL Flexible Server
  - Azure SQL Managed Instance

- **통합 및 API**
  - Azure API Management (Internal Mode)
  - Azure Logic Apps (Integration Service Environment - ISE)
  - Azure Data Factory (Managed VNet)

- **AI 및 분석**
  - Azure Machine Learning (Compute Instance/Cluster)
  - Azure Databricks (VNet Injection)
  - Azure HDInsight

- **보안**
  - Azure Firewall
  - Azure Bastion

### 서브넷 요구사항

VNet Injection 사용 시 서브넷 크기를 충분히 확보해야 함:

```
서비스별 최소 서브넷 크기:

- Azure SQL Managed Instance: /27 이상
- AKS: 노드 수 × 최대 포드 수 고려
- APIM Developer/Premium: /29 이상
- Azure Databricks: /26 이상 (Private/Public 서브넷 각각)
- Logic Apps ISE: /27 이상
```

### 특징

- **트래픽 방향**: 인바운드 + 아웃바운드 (양방향)
- **서비스 위치**: VNet 내부 (서브넷에 직접 배치)
- **완전한 제어**: NSG, UDR, 방화벽 등 모든 네트워크 정책 적용
- **격리 수준**: 가장 높은 수준의 네트워크 격리
- **IP 소비**: 서브넷의 IP 주소를 직접 사용
- **복잡도**: 구성 및 관리가 가장 복잡함
- **추가 비용**: 서비스별로 다름 (일부는 Premium 티어 필요)

### 네트워크 고려사항

#### 1. 서브넷 전용 사용

많은 경우 VNet Injection된 서비스는 전용 서브넷 필요:

```
[VNet 10.0.0.0/16]
    ├── App 서브넷 (10.0.1.0/24) - VM, 일반 리소스
    ├── Data 서브넷 (10.0.2.0/24) - SQL Managed Instance 전용
    └── AKS 서브넷 (10.0.3.0/24) - AKS 노드 전용
```

#### 2. 네트워크 정책 적용

VNet Injection된 리소스에 NSG 적용 예시:

```
NSG 규칙 예시 (PostgreSQL Flexible Server):

인바운드 규칙:
1. Allow: VNet 내부 서브넷 → PostgreSQL:5432
2. Deny: 기타 모든 인바운드 트래픽

아웃바운드 규칙:
1. Allow: PostgreSQL → Azure Storage (백업)
2. Allow: PostgreSQL → Azure Monitor (모니터링)
3. Deny: 기타 모든 아웃바운드 트래픽
```

#### 3. UDR로 트래픽 라우팅

```
시나리오: AKS 아웃바운드 트래픽을 방화벽 경유

Route Table:
- 0.0.0.0/0 → Azure Firewall (10.0.100.4)
- 168.63.129.16/32 → Internet (Azure 메타데이터 서비스)

AKS 노드의 모든 인터넷 트래픽이 방화벽을 경유하여
중앙 집중식 로깅 및 보안 정책 적용 가능
```

## 세 가지 방식 비교

### 비교표

| 항목 | Private Endpoint | VNet Integration | VNet Injection |
|------|-----------------|------------------|----------------|
| **트래픽 방향** | 인바운드 | 아웃바운드 | 양방향 |
| **서비스 위치** | Azure 관리 영역 | Azure 관리 영역 | VNet 서브넷 내부 |
| **네트워크 격리** | 중간 | 낮음 | 높음 |
| **구성 복잡도** | 중간 | 낮음 | 높음 |
| **DNS 구성** | 필수 | 자동 | 자동 |
| **IP 소비** | 서브넷당 1개 | 서브넷 전체 | 서비스 크기에 따라 다름 |
| **NSG 적용** | 가능 | 가능 | 완전히 가능 |
| **UDR 적용** | 제한적 | 가능 | 완전히 가능 |
| **다중 VNet** | 가능 | 불가 (1:1) | 불가 (1:1) |
| **주요 사용 사례** | PaaS 보안 접근 | PaaS의 VNet 리소스 접근 | 완전 격리된 PaaS |
| **비용** | Private Endpoint + 데이터 | 무료 (Gateway는 유료) | 서비스별 상이 |

### 사용 시나리오별 선택 가이드

#### 시나리오 1: 외부에서 PaaS 서비스로의 접근을 차단하고 싶음

```
선택: Private Endpoint

예시:
- Azure SQL Database를 VNet 내부에서만 접근
- Storage Account를 내부 애플리케이션 전용으로 사용
```

#### 시나리오 2: App Service가 VNet 내부 데이터베이스에 접근해야 함

```
선택: VNet Integration

예시:
- Web App이 VNet 내부 PostgreSQL VM에 연결
- Function App이 VNet 내부 Redis Cache에 연결
- App Service가 온프레미스 API 호출 (ExpressRoute 경유)
```

#### 시나리오 3: 데이터베이스를 완전히 사설 네트워크에 격리해야 함

```
선택: VNet Injection

예시:
- PostgreSQL Flexible Server를 VNet에 배포
- 공용 엔드포인트 완전 비활성화
- 모든 접근이 VNet 내부에서만 가능
```

#### 시나리오 4: AKS 클러스터의 네트워크를 완전 제어하고 싶음

```
선택: VNet Injection

예시:
- AKS 노드를 VNet에 배포
- NSG로 포드 트래픽 제어
- UDR로 아웃바운드 트래픽을 방화벽 경유
```

## 복합 시나리오

실제 프로덕션 환경에서는 여러 방식을 조합하여 사용함.

### 시나리오 1: 3계층 웹 애플리케이션

```
아키텍처:

[인터넷]
    ↓
[Application Gateway (WAF 활성화)]
    ↓
[App Service (VNet Integration 설정)]
    ↓ (Private Endpoint 경유)
[Azure SQL Database]
    ↓ (Private Endpoint 경유)
[Azure Storage]

설명:
1. Application Gateway: 인터넷에서 유입되는 트래픽 처리
2. App Service: VNet Integration으로 내부 리소스 접근
3. SQL Database: Private Endpoint로 VNet 내부에서만 접근
4. Storage: Private Endpoint로 보안 강화

네트워크 흐름:
- 인바운드: 인터넷 → App Service (Application Gateway 경유)
- 아웃바운드: App Service → SQL/Storage (VNet Integration → Private Endpoint)
```

### 시나리오 2: 하이브리드 클라우드 환경

```
아키텍처:

[온프레미스 데이터센터]
    ↓ (ExpressRoute)
[Azure VNet Hub]
    ├── [AKS (VNet Injection)]
    │    ↓
    ├── [SQL Managed Instance (VNet Injection)]
    │    
    └── [Spoke VNet]
         ├── [App Service (VNet Integration)]
         └── [Storage (Private Endpoint)]

설명:
1. Hub-Spoke 토폴로지로 VNet 구성
2. ExpressRoute로 온프레미스와 Azure 연결
3. AKS와 SQL MI는 VNet Injection으로 완전 제어
4. App Service는 VNet Integration으로 내부 통신
5. Storage는 Private Endpoint로 보안 접근

네트워크 흐름:
- 온프레미스 → ExpressRoute → Hub VNet → 모든 Azure 리소스 접근
- AKS 포드 → SQL MI (VNet 내부 통신)
- App Service → Storage (VNet Integration → Private Endpoint)
```

### 시나리오 3: 마이크로서비스 아키텍처

```
아키텍처:

[VNet 10.0.0.0/16]
    ├── [AKS 서브넷 (VNet Injection)]
    │    ├── Frontend Service
    │    ├── Backend Service
    │    └── API Gateway Service
    │
    ├── [Data 서브넷]
    │    ├── PostgreSQL Flexible Server (VNet Injection)
    │    └── Redis Cache (Private Endpoint)
    │
    ├── [Integration 서브넷]
    │    └── App Service for Admin (VNet Integration)
    │
    └── [External 서브넷]
         ├── Azure Firewall
         └── Application Gateway

설명:
1. AKS: 모든 마이크로서비스 호스팅 (VNet Injection)
2. PostgreSQL: 완전 격리된 데이터베이스 (VNet Injection)
3. Redis: Private Endpoint로 캐시 접근
4. Admin App: VNet Integration으로 내부 리소스 관리
5. Firewall: 모든 아웃바운드 트래픽 제어
6. App Gateway: 인바운드 트래픽 라우팅 및 WAF

트래픽 제어:
- AKS 아웃바운드 트래픽 → UDR → Azure Firewall
- AKS → PostgreSQL (VNet 내부 통신, NSG 제어)
- AKS → Redis (Private Endpoint, 사설 IP)
- Admin App → AKS (VNet Integration → VNet 내부)
```

## 구성 모범 사례

### 1. Private Endpoint 사용 시

```
권장사항:

✓ Private DNS Zone을 중앙 집중식으로 관리 (Hub VNet에 배치)
✓ 모든 Spoke VNet을 동일한 Private DNS Zone에 연결
✓ 각 서비스마다 적절한 Private DNS Zone 이름 사용
  예: privatelink.blob.core.windows.net, privatelink.database.windows.net
✓ 온프레미스 연동 시 Azure DNS Private Resolver 사용
✓ Private Endpoint와 Public Endpoint를 함께 사용하는 경우 방화벽 규칙 주의

주의사항:

✗ 동일 Private DNS Zone에 서로 다른 종류의 서비스 연결하지 않기
✗ Private Endpoint 삭제 시 DNS 레코드도 함께 정리
✗ Public 접근이 필요한 경우 Private Endpoint만으로는 부족 (Application Gateway 등 필요)
```

### 2. VNet Integration 사용 시

```
권장사항:

✓ Regional VNet Integration 사용 (Gateway 방식은 레거시)
✓ 서브넷 크기를 충분히 확보 (/26 이상 권장)
✓ 위임된 서브넷은 App Service 전용으로 사용
✓ NSG와 UDR을 활용하여 트래픽 제어
✓ NAT Gateway 연결하여 아웃바운드 IP 고정 (필요 시)
✓ App Service의 "Route All" 설정 활성화하여 모든 트래픽을 VNet 경유

주의사항:

✗ 서브넷이 너무 작으면 스케일 아웃 시 IP 부족 문제 발생
✗ 위임되지 않은 서브넷에는 연결 불가
✗ 하나의 App Service는 하나의 VNet에만 연결 가능
✗ 크로스 리전 VNet Integration은 Gateway 방식만 가능 (2027년 폐지 예정)
```

### 3. VNet Injection 사용 시

```
권장사항:

✓ 서비스별 최소 서브넷 크기 요구사항 확인
✓ 전용 서브넷 사용 (다른 리소스와 혼용 금지)
✓ 서비스 운영에 필요한 아웃바운드 규칙 허용 (백업, 모니터링 등)
✓ UDR 사용 시 Azure 서비스 통신 경로 고려
✓ 서비스별 네트워킹 문서 철저히 확인
✓ 고가용성 구성 시 IP 주소 여유 확보

주의사항:

✗ 필수 아웃바운드 포트를 차단하지 않기 (서비스 동작 불가)
✗ 서브넷 크기를 최소값으로 설정하지 않기 (확장 불가)
✗ NSG 규칙이 Azure 관리 트래픽을 차단하지 않도록 주의
✗ 서비스 삭제 후에도 서브넷이 "InUse" 상태로 남을 수 있음 (시간 필요)
```

## 네트워크 보안 계층

세 가지 방식을 사용할 때 적용할 수 있는 보안 계층:

### 1. 네트워크 수준

```
- Network Security Groups (NSG)
  · 서브넷 또는 NIC 수준의 트래픽 필터링
  · Allow/Deny 규칙으로 인바운드/아웃바운드 제어
  
- Azure Firewall / NVA
  · 중앙 집중식 트래픽 검사 및 필터링
  · 위협 인텔리전스 기반 차단
  · 애플리케이션 수준 필터링
  
- User Defined Routes (UDR)
  · 트래픽 경로 제어
  · 특정 경로를 방화벽 또는 NVA 경유
```

### 2. 서비스 수준

```
- Private Endpoint
  · 퍼블릭 엔드포인트 비활성화
  · VNet 내부 접근만 허용
  
- Service Endpoints
  · Azure 서비스에 대한 최적화된 경로
  · 서비스 방화벽과 결합하여 접근 제어
  
- IP 방화벽
  · 서비스 수준에서 IP 주소 기반 접근 제어
```

### 3. 애플리케이션 수준

```
- Web Application Firewall (WAF)
  · Application Gateway 또는 Front Door에서 제공
  · OWASP 규칙 기반 공격 차단
  · SQL 인젝션, XSS 등 방어
  
- 인증 및 권한 부여
  · Azure AD 통합
  · Managed Identity 사용
  · RBAC 적용
```

### 방어 심층화(Defense in Depth) 예시

```
[인터넷]
    ↓
[DDoS Protection] ← 1계층: 네트워크 공격 방어
    ↓
[Azure Firewall] ← 2계층: 트래픽 필터링 및 검사
    ↓
[Application Gateway + WAF] ← 3계층: 애플리케이션 공격 방어
    ↓
[NSG] ← 4계층: 서브넷 수준 필터링
    ↓
[App Service (VNet Integration)] ← 5계층: 네트워크 격리
    ↓
[Private Endpoint] ← 6계층: 사설 연결
    ↓
[Azure SQL (Private Endpoint)] ← 7계층: 데이터 계층 격리
    +
[Azure AD + Managed Identity] ← 8계층: 인증 및 권한 부여
    +
[Encryption (TLS, TDE)] ← 9계층: 데이터 암호화
```

## 비용 고려사항

### Private Endpoint

```
비용 구성:
1. Private Endpoint 자체: $0.01/시간 (약 $7.20/월)
2. 데이터 처리: $0.01/GB (인바운드/아웃바운드)

예시 (월간):
- Private Endpoint 1개: $7.20
- 데이터 전송 100GB: $1.00
- 총: $8.20/월

다중 VNet 환경:
- VNet당 Private Endpoint 필요
- 3개 VNet = $21.60/월 (Private Endpoint만)
```

### VNet Integration

```
비용 구성:
1. Regional VNet Integration: 무료
2. Gateway-required VNet Integration:
   - VPN Gateway 비용: $26~$2,900/월 (SKU에 따라)
   - 데이터 전송 비용

NAT Gateway (선택적):
- Gateway 자체: $32.85/월
- 데이터 처리: $0.045/GB

예시 (Regional, NAT Gateway 사용):
- VNet Integration: $0
- NAT Gateway: $32.85
- 데이터 전송 100GB: $4.50
- 총: $37.35/월
```

### VNet Injection

```
비용은 서비스별로 상이:

Azure SQL Managed Instance:
- General Purpose 4 vCore: ~$700/월
- Business Critical 4 vCore: ~$1,300/월
- VNet Injection 자체 비용 없음 (서비스 비용에 포함)

PostgreSQL Flexible Server:
- Burstable B1ms: ~$12/월
- General Purpose D2s_v3: ~$110/월
- VNet 배포 시 추가 비용 없음

AKS:
- 노드 VM 비용만 부과
- 컨트롤 플레인은 무료
- VNet Injection 자체 비용 없음
```

### 비용 최적화 팁

```
1. Private Endpoint 최적화
   - 필요한 서비스에만 적용
   - Private DNS Zone은 공유 (Hub VNet)
   
2. VNet Integration 최적화
   - Regional 방식 사용 (Gateway 비용 절감)
   - NAT Gateway는 필요할 때만
   
3. VNet Injection 최적화
   - 서브넷 크기를 적절히 설정 (과도한 IP 예약 방지)
   - 스케일링 정책 최적화
```

## 트러블슈팅

### Private Endpoint 문제

#### 문제 1: DNS가 사설 IP로 해석되지 않음

```
증상:
- nslookup mystorageaccount.blob.core.windows.net
- 결과: 공용 IP 반환

원인:
- Private DNS Zone이 VNet에 연결되지 않음
- DNS 서버 설정 문제

해결:
1. Private DNS Zone의 Virtual Network Link 확인
   Azure Portal > Private DNS Zone > Virtual network links
   
2. VNet DNS 설정 확인
   Azure Portal > VNet > DNS servers > Default (Azure-provided)
   
3. VM에서 DNS 서버 확인
   cat /etc/resolv.conf
   # nameserver 168.63.129.16 (Azure DNS) 확인
```

#### 문제 2: Private Endpoint로 연결 실패

```
증상:
- Connection timeout 또는 Connection refused

원인:
- NSG가 트래픽 차단
- 서비스 방화벽 설정 문제
- 서브넷 라우팅 문제

해결:
1. NSG 규칙 확인
   - Private Endpoint 서브넷의 인바운드 규칙
   - 소스 서브넷의 아웃바운드 규칙
   
2. 서비스 방화벽 확인
   - Azure Portal > 서비스 > Networking
   - "Allow access from" 설정 확인
   - Private Endpoint 사용 시 "Selected networks" 선택
   
3. 효과적인 라우트 확인
   Azure Portal > NIC > Effective routes
```

### VNet Integration 문제

#### 문제 1: VNet Integration 연결 실패

```
증상:
- "Failed to join virtual network" 오류

원인:
- 서브넷 위임이 설정되지 않음
- 서브넷 IP 부족
- 리전 불일치

해결:
1. 서브넷 위임 확인
   Azure Portal > VNet > Subnets > Subnet delegation
   "Microsoft.Web/serverFarms" 확인
   
2. 서브넷 IP 가용성 확인
   사용 가능한 IP 주소 충분한지 확인 (최소 4개 이상)
   
3. App Service와 VNet 리전 확인
   Regional VNet Integration은 같은 리전만 가능
```

#### 문제 2: VNet 리소스에 연결되지 않음

```
증상:
- App Service에서 VNet 내부 IP 연결 실패

원인:
- Route All 설정 비활성화
- NSG 차단
- DNS 문제

해결:
1. Route All 활성화
   Azure Portal > App Service > Networking > VNet Integration
   "Route All" 체크박스 활성화
   
2. NSG 확인
   위임된 서브넷의 아웃바운드 규칙 확인
   
3. DNS 확인
   App Service가 VNet의 Custom DNS 사용하는지 확인
```

### VNet Injection 문제

#### 문제 1: 서비스 생성 실패

```
증상:
- "The subnet is not valid for deployment" 오류

원인:
- 서브넷 크기 부족
- 서브넷에 다른 리소스 존재
- 네트워크 정책 충돌

해결:
1. 서비스별 최소 서브넷 크기 확인
   SQL MI: /27, APIM: /29, AKS: 상황에 따라
   
2. 서브넷 비우기
   VNet Injection 전용 서브넷 사용
   
3. 서브넷 설정 확인
   - Private endpoint network policies: Disabled (일부 서비스)
   - Private link service network policies: Disabled (일부 서비스)
```

#### 문제 2: 서비스 작동 불가 또는 연결 실패

```
증상:
- 서비스가 배포되었지만 작동하지 않음
- 관리 작업 실패

원인:
- 필수 아웃바운드 포트 차단
- Azure 관리 트래픽 차단
- UDR이 Azure 서비스 통신 방해

해결:
1. 서비스별 필수 아웃바운드 요구사항 확인
   예: AKS - Azure API, Container Registry 등
   
2. NSG 규칙 추가
   서비스 태그(Service Tag) 사용하여 Azure 트래픽 허용
   예: AzureCloud, AzureMonitor, Storage 등
   
3. UDR 예외 추가
   Azure 관리 트래픽은 Internet으로 직접 라우팅
   예: Next hop type = Internet for service tags
```

## 요약

### 핵심 개념 정리

```
Private Endpoint:
- 목적: PaaS 서비스로의 안전한 인바운드 접근
- 방향: 인바운드 (VNet → PaaS)
- 위치: VNet에 NIC 생성, 서비스는 Azure 관리 영역
- 특징: DNS 구성 필수, 다중 VNet 지원

VNet Integration:
- 목적: PaaS 서비스의 VNet 리소스 접근
- 방향: 아웃바운드 (PaaS → VNet)
- 위치: 서비스는 Azure 관리 영역, VNet 연결
- 특징: 서브넷 위임 필요, 단일 VNet만 가능

VNet Injection:
- 목적: 완전한 네트워크 격리 및 제어
- 방향: 양방향 (인바운드 + 아웃바운드)
- 위치: VNet 서브넷 내부에 직접 배포
- 특징: 전용 서브넷 필요, 모든 네트워크 정책 적용 가능
```

### 선택 기준

```
Private Endpoint를 선택하는 경우:
✓ PaaS 서비스 접근을 VNet 내부로 제한하고 싶을 때
✓ 데이터 보안 및 규정 준수가 중요할 때
✓ 여러 VNet에서 동일 서비스 접근이 필요할 때

VNet Integration을 선택하는 경우:
✓ App Service/Function이 VNet 내부 리소스에 접근해야 할 때
✓ 온프레미스 리소스에 연결이 필요할 때
✓ 아웃바운드 IP를 고정하고 싶을 때

VNet Injection을 선택하는 경우:
✓ 서비스를 완전히 사설 네트워크에 격리해야 할 때
✓ 모든 네트워크 트래픽을 세밀하게 제어하고 싶을 때
✓ 가장 높은 수준의 보안이 요구될 때
```

### 실전 체크리스트

```
네트워크 설계 시 고려사항:

1. 트래픽 방향 파악
   - 인바운드만? → Private Endpoint
   - 아웃바운드만? → VNet Integration
   - 양방향? → VNet Injection

2. 보안 요구사항
   - 데이터 분류 수준
   - 규정 준수 요구사항
   - 네트워크 격리 수준

3. 아키텍처 복잡도
   - 관리 가능한 복잡도인가?
   - 운영 팀의 네트워크 전문성
   - 자동화 및 IaC 가능성

4. 비용
   - Private Endpoint 비용 (다중 VNet)
   - Gateway 비용 (레거시 VNet Integration)
   - Premium 티어 필요 여부 (일부 VNet Injection)

5. 확장성
   - 서브넷 IP 주소 충분한가?
   - 스케일 아웃 계획
   - 다른 환경으로 확장 가능성
```
