# Hub-and-Spoke 패턴에서 Managed Identity 인증과 Firewall 설정

## 개요

Hub-and-spoke 네트워크 패턴에서 Azure Firewall을 통해 모든 아웃바운드 트래픽을 제어하는 환경에서, System-assigned Managed Identity를 사용하는 VM이 `az login --identity` 명령을 실행할 때 실패하는 문제가 발생할 수 있음. 이는 단순히 로그인만 하는 것이 아니라, 로그인 후 Azure Resource Manager(ARM) 엔드포인트로 추가 호출을 시도하면서 발생하는 네트워크 차단 문제임.

이 문서는 해당 문제의 원인을 진단하고 해결하는 방법을 설명함.

## 문제 상황

### 시나리오

```
구성:
- Hub VNet: Azure Firewall (Private IP: 10.2.1.4)
- Spoke VNet: Private Subnet에 VM 배치
- System-assigned Managed Identity가 활성화된 VM
- Subnet에 UDR 적용: 0.0.0.0/0 → Azure Firewall (10.2.1.4)
- Azure Firewall TLS Inspection: Disabled

현상:
- az login --identity 명령 실행 시 타임아웃 또는 실패
- CA 인증서 문제는 아님
- IMDS 접근은 가능한 상태
```

### 증상

많은 경우 "Managed Identity가 막혔다"고 생각하지만, 실제로는 다음 단계에서 발생하는 네트워크 차단 문제임:

1. IMDS에서 토큰 획득 - 성공
2. 토큰으로 ARM API 호출하여 구독/테넌트 정보 조회 - 실패

## 원인 분석

Managed Identity 인증이 실패하는 원인은 크게 두 가지로 나눌 수 있음:

### 1. IMDS(169.254.169.254) 자체가 차단된 경우

System-assigned Managed Identity는 VM 내부에서 IMDS(Instance Metadata Service) 고정 IP `169.254.169.254`로 요청하여 토큰을 받음. 이 트래픽은 VM 밖으로 나가면 안 되는 성격이며, VM 내부 프록시나 라우팅 정책이 IMDS 요청을 가로채면 즉시 실패함.

#### IMDS 차단 원인

**프록시 환경변수 설정**
- VM에 `HTTP_PROXY` 또는 `HTTPS_PROXY` 환경변수가 설정되어 있으면 IMDS 호출도 프록시를 거치려고 시도함
- Microsoft 공식 문서에서도 "IMDS 호출은 웹 프록시를 우회해야 한다"고 명시함

**잘못된 UDR 설정**
- `169.254.169.254/32` 또는 `168.63.129.16/32` 같은 Azure 플랫폼 IP를 방화벽으로 라우팅하는 UDR을 잘못 추가한 경우
- IMDS 트래픽은 VM 내부에서만 처리되어야 하므로 이런 라우트를 추가하면 안 됨

#### 진단 방법

VM에서 다음 명령으로 IMDS 접근 테스트:

```bash
# Linux
curl -H "Metadata:true" "http://169.254.169.254/metadata/instance?api-version=2021-02-01"

# 성공 시: VM 메타데이터 JSON 응답
# 실패 시: 타임아웃 또는 연결 거부
```

IMDS 호출이 실패하면 `az login --identity`는 당연히 실패함.

#### 해결 방법

**프록시 예외 설정 (Linux)**

```bash
# 환경변수에 NO_PROXY 추가
export NO_PROXY=169.254.169.254,168.63.129.16,localhost,127.0.0.1

# 영구 설정 (bash)
echo 'export NO_PROXY=169.254.169.254,168.63.129.16,localhost,127.0.0.1' >> ~/.bashrc
source ~/.bashrc

# 영구 설정 (시스템 전역)
echo 'export NO_PROXY=169.254.169.254,168.63.129.16,localhost,127.0.0.1' >> /etc/environment
```

**프록시 예외 설정 (Windows)**

```powershell
# 사용자 환경변수 설정
[Environment]::SetEnvironmentVariable("NO_PROXY", "169.254.169.254,168.63.129.16,localhost,127.0.0.1", "User")

# 시스템 환경변수 설정 (관리자 권한 필요)
[Environment]::SetEnvironmentVariable("NO_PROXY", "169.254.169.254,168.63.129.16,localhost,127.0.0.1", "Machine")
```

**잘못된 UDR 제거**

Azure Portal에서 Route Table을 확인하고 IMDS IP 관련 경로가 있으면 제거:

```
제거해야 할 경로 예시:
- Address Prefix: 169.254.169.254/32, Next Hop: Virtual Appliance
- Address Prefix: 168.63.129.16/32, Next Hop: Virtual Appliance
```

**중요**: IMDS 단계가 차단된 경우 "Firewall에 FQDN 추가"로는 해결되지 않음. VM 내부 설정을 수정해야 함.

### 2. IMDS는 작동하지만 ARM 호출이 Firewall에서 차단된 경우 (가장 흔함)

이 경우가 가장 흔하게 발생하는 패턴임. `az login --identity`는 실제로 다음 두 단계를 수행함:

1. IMDS에서 토큰 받기 (성공)
2. 토큰으로 ARM에 접속하여 테넌트/구독 목록 조회 및 기본 구독 설정 (실패)

두 번째 단계에서 `management.azure.com` 등의 ARM 엔드포인트 접근이 Firewall에서 차단되면 로그인이 실패함.

#### 진단 방법

디버그 모드로 정확한 실패 지점 확인:

```bash
az login --identity --debug
```

출력에서 다음과 같은 패턴을 찾음:

```
# IMDS 토큰 요청 - 성공
Attempting to get token from IMDS...
Token acquired from IMDS

# ARM API 호출 시도 - 실패 (여기서 막힘)
Request URL: 'https://management.azure.com/subscriptions?api-version=...'
Connection timeout
또는
Connection refused
```

실패 지점이 `management.azure.com` 호출이라면 Firewall 설정 문제임.

## 해결 방법

### 최소 허용 목록

Azure Firewall Application Rule에 다음 FQDN을 허용해야 함:

```
최소 구성:
- management.azure.com:443 (HTTPS)

이유: ARM API 엔드포인트로, 구독/테넌트 정보 조회 및 대부분의 Azure 관리 작업에 필요
```

### 권장 허용 목록 (FQDN Tag 사용)

Azure Firewall은 FQDN Tag를 지원하여 Microsoft 서비스 도메인 묶음을 쉽게 허용할 수 있음:

```
권장 FQDN Tags:
1. AzureResourceManager
   - management.azure.com
   - ARM 관련 엔드포인트 포함

2. AzureActiveDirectory
   - login.microsoftonline.com
   - Entra ID 인증 및 토큰 관련 엔드포인트
   - 일부 Azure CLI 명령에서 필요할 수 있음
```

**FQDN Tag 사용의 장점**:
- Microsoft가 관리하는 엔드포인트 목록이 자동으로 업데이트됨
- 개별 FQDN을 수동으로 관리할 필요 없음
- 서비스 엔드포인트 변경에 자동 대응

### Azure Firewall Application Rule 설정

#### Azure Portal

```
1. Azure Portal → Firewall → Rules → Application Rules
2. Add application rule collection

Rule Collection 설정:
  Name: Allow-Azure-Management
  Priority: 100
  Action: Allow

Rule 추가:
  Name: Allow-ARM
  Source Type: IP Address
  Source: * (또는 특정 서브넷 CIDR)
  Protocol: https:443
  Target Type: FQDN Tag
  Target FQDNs: AzureResourceManager, AzureActiveDirectory
```

#### Azure CLI

```bash
# Application Rule Collection 생성
az network firewall application-rule create \
  --resource-group myResourceGroup \
  --firewall-name myFirewall \
  --collection-name Allow-Azure-Management \
  --priority 100 \
  --action Allow \
  --name Allow-ARM \
  --source-addresses '*' \
  --protocols Https=443 \
  --fqdn-tags AzureResourceManager AzureActiveDirectory
```

#### Terraform

```hcl
resource "azurerm_firewall_application_rule_collection" "azure_management" {
  name                = "Allow-Azure-Management"
  azure_firewall_name = azurerm_firewall.main.name
  resource_group_name = azurerm_resource_group.main.name
  priority            = 100
  action              = "Allow"

  rule {
    name = "Allow-ARM"
    source_addresses = ["*"]
    
    fqdn_tags = [
      "AzureResourceManager",
      "AzureActiveDirectory"
    ]
  }
}
```

### 특정 FQDN만 허용 (최소 권한 원칙)

FQDN Tag 대신 특정 도메인만 허용하려는 경우:

```
최소 필수 FQDN:
1. management.azure.com (필수)
2. login.microsoftonline.com (선택적, Azure CLI 일부 명령에서 필요)
3. graph.microsoft.com (선택적, Graph API 사용 시)
```

#### Azure Portal 설정

```
Rule 추가:
  Name: Allow-Specific-Management
  Source Type: IP Address
  Source: * (또는 특정 서브넷)
  Protocol: https:443
  Target Type: FQDN
  Target FQDNs:
    - management.azure.com
    - login.microsoftonline.com
```

## 빠른 진단 루틴

다음 순서로 문제를 진단하면 빠르게 원인을 파악할 수 있음:

### 1단계: IMDS 토큰 획득 테스트

```bash
# 토큰 요청
curl -H "Metadata:true" \
  "http://169.254.169.254/metadata/identity/oauth2/token?api-version=2018-02-01&resource=https://management.azure.com/" \
  | jq -r .access_token

# 성공: JWT 토큰이 출력됨
# 실패: 타임아웃 또는 에러 → 1번 원인 (IMDS 차단)
```

### 2단계: ARM API 직접 호출 테스트

```bash
# 토큰 저장
TOKEN=$(curl -s -H "Metadata:true" \
  "http://169.254.169.254/metadata/identity/oauth2/token?api-version=2018-02-01&resource=https://management.azure.com/" \
  | jq -r .access_token)

# ARM API 호출
curl -H "Authorization: Bearer $TOKEN" \
  "https://management.azure.com/subscriptions?api-version=2020-01-01"

# 성공: 구독 목록 JSON 반환
# 실패: 타임아웃 또는 연결 거부 → 2번 원인 (Firewall 차단)
```

### 3단계: Azure CLI 디버그 모드

```bash
az login --identity --debug 2>&1 | tee debug.log

# debug.log에서 확인:
# - "Token acquired from IMDS" → IMDS 성공
# - "management.azure.com" 관련 타임아웃 → Firewall 차단
```

### 진단 플로우차트

```
az login --identity 실패
        ↓
1단계: IMDS 토큰 획득 테스트
        ↓
    실패? ─────→ 프록시 설정 확인 / UDR 확인
        ↓ 성공
2단계: ARM API 직접 호출 테스트
        ↓
    실패? ─────→ Firewall Rule 추가 (management.azure.com)
        ↓ 성공
3단계: az login --identity 재시도
        ↓
    실패? ─────→ --debug 로그 확인 및 추가 FQDN 파악
        ↓ 성공
    완료
```

## 실전 시나리오 및 해결 예시

### 시나리오 1: GitHub Self-hosted Runner VM

#### 환경

```
- Runner VM: Private Subnet (10.0.4.0/24)
- System-assigned Managed Identity 활성화
- UDR: 0.0.0.0/0 → Azure Firewall
- 용도: Azure CLI로 리소스 배포
```

#### 문제

```bash
# Runner 스크립트
az login --identity
az vm list

# 에러
ERROR: Failed to connect to MSI. Please make sure MSI is configured correctly.
또는
Timeout when getting token from IMDS
```

#### 해결

**1. IMDS 확인**

```bash
curl -H "Metadata:true" "http://169.254.169.254/metadata/instance?api-version=2021-02-01"
# → 성공 (IMDS는 작동함)
```

**2. Firewall Rule 추가**

```
Azure Firewall → Application Rules:
  Name: Allow-Azure-Management-Runner
  Source: 10.0.4.0/24
  FQDN Tags: AzureResourceManager, AzureActiveDirectory
  Protocol: HTTPS:443
```

**3. 재시도**

```bash
az login --identity
# → 성공
az vm list
# → VM 목록 정상 출력
```

### 시나리오 2: Terraform 실행 VM

#### 환경

```
- Terraform VM: Private Subnet (10.0.5.0/24)
- System-assigned Managed Identity로 Terraform 인증
- UDR: 0.0.0.0/0 → Azure Firewall
- HTTP_PROXY 환경변수 설정됨 (기업 프록시)
```

#### 문제

```bash
terraform init
terraform plan

# 에러
Error: Error building AzureRM Client: could not get authenticated token
Error: Failed to get existing workspaces: autorest/azure: Service returned an error
```

#### 해결

**1. IMDS 확인**

```bash
curl -H "Metadata:true" "http://169.254.169.254/metadata/instance?api-version=2021-02-01"
# → 실패 (프록시를 거치려고 시도)
```

**2. 프록시 예외 추가**

```bash
# 기존 프록시 설정 확인
echo $HTTP_PROXY
# http://corpproxy.company.com:8080

# NO_PROXY 설정
export NO_PROXY="169.254.169.254,168.63.129.16,localhost,127.0.0.1"

# IMDS 재확인
curl -H "Metadata:true" "http://169.254.169.254/metadata/instance?api-version=2021-02-01"
# → 성공
```

**3. Firewall Rule 추가**

```
Application Rule:
  Source: 10.0.5.0/24
  FQDN Tags: AzureResourceManager
  Additional FQDNs:
    - registry.terraform.io (Terraform Registry)
    - releases.hashicorp.com (Provider 다운로드)
```

**4. 영구 설정**

```bash
# /etc/environment에 추가
sudo tee -a /etc/environment <<EOF
HTTP_PROXY=http://corpproxy.company.com:8080
HTTPS_PROXY=http://corpproxy.company.com:8080
NO_PROXY=169.254.169.254,168.63.129.16,localhost,127.0.0.1
EOF

# 재부팅 또는 재로그인
terraform plan
# → 성공
```

### 시나리오 3: Azure DevOps Agent VM

#### 환경

```
- DevOps Agent: Private Subnet (10.0.6.0/24)
- System-assigned Managed Identity
- UDR: 0.0.0.0/0 → Azure Firewall
- Pipeline에서 Azure CLI 태스크 사용
```

#### 문제

```yaml
# Pipeline YAML
- task: AzureCLI@2
  inputs:
    azureSubscription: 'MyServiceConnection'  # Managed Identity 기반
    scriptType: bash
    scriptLocation: inlineScript
    inlineScript: |
      az vm list --resource-group myRG

# 에러
ERROR: Please run 'az login' to setup account.
```

#### 해결

**1. Service Connection 확인**

Azure DevOps에서 Service Connection이 Managed Identity 기반인지 확인:
- Service Connection Type: Azure Resource Manager
- Authentication Method: Managed Identity

**2. IMDS 및 ARM 테스트**

Agent VM에 SSH 접속하여 테스트:

```bash
# IMDS
curl -H "Metadata:true" "http://169.254.169.254/metadata/instance?api-version=2021-02-01"
# → 성공

# ARM
az login --identity
# → 실패 (Timeout)
```

**3. Firewall Rule 추가**

```
Application Rule:
  Name: Allow-DevOps-Agent
  Source: 10.0.6.0/24
  FQDN Tags: AzureResourceManager, AzureActiveDirectory
  Additional FQDNs:
    - dev.azure.com (DevOps 서비스)
    - vstsagentpackage.azureedge.net (Agent 업데이트)
```

**4. Pipeline 재실행**

```bash
# Pipeline 재실행
# → 성공
```

## 추가 고려사항

### Azure Services Tag를 사용한 Network Rule

Application Rule 외에 Network Rule로도 설정 가능함 (덜 선호되지만 가능):

```
Network Rule:
  Name: Allow-Azure-Management-Network
  Source: 10.0.0.0/16
  Destination: AzureCloud (Service Tag)
  Protocol: TCP
  Destination Ports: 443
```

**단점**:
- Service Tag는 Azure의 모든 공인 IP 범위를 포함하므로 과도하게 넓음
- Application Rule의 FQDN 기반 제어가 더 정밀하고 권장됨

### Private Endpoint와의 관계

`management.azure.com`에 Private Endpoint를 생성할 수는 없음:
- ARM 엔드포인트는 Azure 공용 서비스임
- Private Endpoint는 특정 리소스(Storage, SQL DB 등)에만 사용 가능

따라서 Managed Identity 인증을 위해서는 반드시 Firewall에서 공용 엔드포인트 접근을 허용해야 함.

### Azure Firewall Premium과 TLS Inspection

Azure Firewall Premium의 TLS Inspection을 사용하는 경우:

**추가 고려사항**:
1. IMDS 트래픽은 HTTP이므로 TLS Inspection 영향 없음
2. ARM 트래픽은 HTTPS이지만, TLS Inspection을 활성화해도 대부분 문제없음
3. 단, 일부 Azure 서비스는 Certificate Pinning을 사용하여 TLS Inspection 시 실패할 수 있음

**권장 설정**:
```
TLS Inspection Policy:
- Azure Management 트래픽은 Bypass 권장
- Application Rule에서 AzureResourceManager Tag에 대해 TLS Inspection Bypass
```

### 다른 Azure Managed Services

다음 서비스들도 Managed Identity를 사용하며 동일한 Firewall 설정이 필요함:

```
1. App Service / Function App
   - WEBSITE_ENABLE_SYNC_UPDATE_SITE 설정 사용 시
   - Managed Identity로 Key Vault 접근 시

2. Azure Kubernetes Service (AKS)
   - Pod Identity 사용 시
   - AAD Pod Identity 또는 Workload Identity

3. Azure Container Instances (ACI)
   - Managed Identity로 리소스 접근 시

4. Azure Batch
   - Managed Identity로 Storage 접근 시

5. Azure Data Factory
   - Managed Identity로 연결된 서비스 접근 시
```

모두 동일하게 `management.azure.com` 및 `login.microsoftonline.com` 접근이 필요함.

## 검증 방법

모든 설정을 완료한 후 다음 방법으로 검증:

### 1. 기본 로그인 테스트

```bash
az login --identity
az account show

# 성공 시 출력:
{
  "environmentName": "AzureCloud",
  "id": "xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx",
  "isDefault": true,
  "name": "My Subscription",
  "state": "Enabled",
  "tenantId": "xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx",
  "user": {
    "assignedIdentity": {
      "principalId": "xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx",
      "tenantId": "xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx"
    },
    "name": "systemAssignedIdentity",
    "type": "servicePrincipal"
  }
}
```

### 2. 리소스 조회 테스트

```bash
# VM 목록 조회
az vm list --query "[].{Name:name, ResourceGroup:resourceGroup}" -o table

# 리소스 그룹 목록
az group list -o table

# Storage Account 목록
az storage account list -o table
```

### 3. Azure Firewall 로그 확인

```
Azure Portal → Firewall → Logs (Diagnostic Settings 활성화 필요)

KQL 쿼리:
AzureDiagnostics
| where Category == "AzureFirewallApplicationRule"
| where TimeGenerated > ago(1h)
| where msg_s contains "management.azure.com"
| project TimeGenerated, msg_s, Action, SourceIp, FQDN
| order by TimeGenerated desc

확인 사항:
- Action: "Allow" 여부
- FQDN: management.azure.com 매칭 여부
- SourceIp: VM의 Private IP 확인
```

### 4. 네트워크 연결 테스트

```bash
# TCP 연결 테스트
nc -zv management.azure.com 443

# 또는 telnet
telnet management.azure.com 443

# 또는 curl
curl -v https://management.azure.com

# 성공 시:
Connected to management.azure.com
또는
HTTP/1.1 401 Unauthorized (인증 없어도 연결은 성공)

# 실패 시:
Connection timed out
또는
Connection refused
```

## 문제 해결 체크리스트

Managed Identity 인증이 실패할 때 다음 순서로 확인:

```
□ VM에 System-assigned 또는 User-assigned Managed Identity가 활성화되어 있는가?
  → Azure Portal → VM → Identity 확인

□ IMDS 접근이 가능한가?
  → curl -H "Metadata:true" "http://169.254.169.254/metadata/instance?api-version=2021-02-01"

□ 프록시 환경변수가 설정되어 있는가?
  → echo $HTTP_PROXY $HTTPS_PROXY $NO_PROXY
  → IMDS IP(169.254.169.254)가 NO_PROXY에 포함되어 있는가?

□ UDR에 IMDS IP를 잘못 라우팅하는 경로가 있는가?
  → Azure Portal → Route Table → Routes
  → 169.254.169.254/32 또는 168.63.129.16/32 경로 확인

□ Azure Firewall Application Rule에 AzureResourceManager가 허용되어 있는가?
  → Firewall → Application Rules 확인

□ VM의 Subnet이 올바른 Route Table에 연결되어 있는가?
  → Subnet → Route Table 확인

□ NSG(Network Security Group)가 아웃바운드 443 포트를 차단하고 있지 않은가?
  → VM NIC → Network Security Group → Outbound rules 확인

□ Firewall 로그에서 트래픽이 Allow되는지 확인했는가?
  → Firewall → Logs → AzureFirewallApplicationRule

□ Azure CLI가 최신 버전인가?
  → az version
  → 오래된 버전은 IMDS 관련 버그가 있을 수 있음
```

## 일반적인 실수

### 실수 1: "Managed Identity만 설정하면 되는 거 아닌가?"

```
❌ 잘못된 생각:
"VM에 Managed Identity를 활성화했으니까 바로 사용할 수 있겠지?"

✓ 올바른 이해:
"Managed Identity는 VM 자체의 설정이고, 네트워크 통제(UDR, Firewall)가 있으면
  ARM 엔드포인트 접근을 허용해야 함"
```

### 실수 2: "IMDS만 되면 되는 거 아닌가?"

```
❌ 잘못된 생각:
"IMDS에서 토큰을 받으면 끝 아닌가?"

✓ 올바른 이해:
"az login --identity는 토큰을 받은 후 ARM API를 호출하여 구독 정보를 가져옴
  따라서 management.azure.com도 허용해야 함"
```

### 실수 3: "Network Rule만 추가하면 되겠지?"

```
❌ 잘못된 설정:
Azure Firewall Network Rule로 TCP 443만 허용

문제:
- Network Rule은 IP 기반 제어이므로 Azure의 모든 443 포트가 열림
- 보안상 과도하게 넓은 허용

✓ 올바른 설정:
Application Rule에서 FQDN Tag(AzureResourceManager) 사용
→ 특정 Azure 관리 엔드포인트만 허용
```

### 실수 4: "Private Endpoint로 해결할 수 있지 않나?"

```
❌ 잘못된 생각:
"management.azure.com에 Private Endpoint를 만들면 되겠지?"

✓ 올바른 이해:
"ARM 엔드포인트는 Azure 공용 서비스로 Private Endpoint를 지원하지 않음
  반드시 Firewall을 통한 공용 엔드포인트 접근이 필요함"
```

### 실수 5: "TLS Inspection 때문이 아닐까?"

```
❌ 잘못된 진단:
"Azure Firewall Premium의 TLS Inspection 때문에 막힌 것 같은데?"

✓ 올바른 진단:
"TLS Inspection보다 Application Rule 자체가 없어서 차단된 경우가 훨씬 많음
  먼저 Application Rule 추가하고, 그래도 안 되면 TLS Inspection 확인"
```

## 요약

### 핵심 포인트

1. **Managed Identity 인증은 두 단계**
   - IMDS(169.254.169.254)에서 토큰 획득
   - ARM(management.azure.com)에서 구독 정보 조회

2. **IMDS는 VM 내부 트래픽**
   - 프록시 예외 설정 필수
   - UDR로 라우팅하면 안 됨

3. **ARM 접근은 Firewall 허용 필요**
   - Application Rule에 AzureResourceManager FQDN Tag 권장
   - 최소한 management.azure.com:443 허용

4. **진단은 단계적으로**
   - IMDS 테스트 → ARM 테스트 → az login 재시도
   - 디버그 로그와 Firewall 로그 활용

### 권장 구성 요약

```
VM 설정:
✓ System-assigned Managed Identity 활성화
✓ NO_PROXY에 169.254.169.254 포함 (프록시 사용 시)

Route Table:
✓ 0.0.0.0/0 → Azure Firewall (워크로드 트래픽용)
✗ 169.254.169.254/32 경로 추가하지 말 것

Azure Firewall Application Rule:
✓ FQDN Tag: AzureResourceManager (권장)
✓ FQDN Tag: AzureActiveDirectory (선택적)
  또는
✓ 특정 FQDN: management.azure.com (최소 구성)

검증:
✓ curl로 IMDS 테스트
✓ curl로 ARM 테스트
✓ az login --identity 테스트
✓ Firewall 로그 확인
```

### 해결 흐름도

```
az login --identity 실패
        ↓
IMDS 접근 가능?
  ├─ No → 프록시 설정 / UDR 확인 → 수정
  └─ Yes
        ↓
ARM API 접근 가능?
  ├─ No → Firewall Rule 추가 → Application Rule
  └─ Yes
        ↓
az login 재시도
  ├─ 실패 → --debug 로그 확인 → 추가 FQDN 파악
  └─ 성공 → 완료
```

## 참고 자료

### Azure 공식 문서

- [Managed identities for Azure resources](https://learn.microsoft.com/azure/active-directory/managed-identities-azure-resources/overview)
- [Azure Instance Metadata Service (IMDS)](https://learn.microsoft.com/azure/virtual-machines/instance-metadata-service)
- [Azure Firewall FQDN tags](https://learn.microsoft.com/azure/firewall/fqdn-tags)
- [User-defined routes overview](https://learn.microsoft.com/azure/virtual-network/virtual-networks-udr-overview)
- [Hub-spoke network topology in Azure](https://learn.microsoft.com/azure/architecture/reference-architectures/hybrid-networking/hub-spoke)

### Azure CLI 관련

- [Sign in with Azure CLI using managed identity](https://learn.microsoft.com/cli/azure/authenticate-azure-cli-managed-identity)
- [Azure CLI configuration](https://learn.microsoft.com/cli/azure/azure-cli-configuration)

### 네트워크 트러블슈팅

```bash
# IMDS 메타데이터 확인
curl -H "Metadata:true" "http://169.254.169.254/metadata/instance?api-version=2021-02-01" | jq

# Managed Identity 토큰 획득
curl -H "Metadata:true" \
  "http://169.254.169.254/metadata/identity/oauth2/token?api-version=2018-02-01&resource=https://management.azure.com/"

# 라우팅 테이블 확인 (Linux)
ip route show
ip route get 169.254.169.254
ip route get <ARM IP>

# DNS 확인
nslookup management.azure.com
dig management.azure.com

# 네트워크 연결 확인
nc -zv management.azure.com 443
curl -v https://management.azure.com

# Azure CLI 디버그
az login --identity --debug
az account show --debug
```

### 관련 GitHub Issues

Managed Identity와 네트워크 통제 관련 커뮤니티 이슈:
- Azure CLI GitHub: Managed Identity timeout issues
- Azure Firewall: FQDN Tag 업데이트 내역
- Terraform Provider: Managed Identity authentication issues
