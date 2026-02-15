# Hub-and-Spoke 패턴에서 Managed Identity 인증과 Firewall 설정

## 개요

Hub-and-spoke 네트워크 패턴에서 Azure Firewall을 통해 모든 아웃바운드 트래픽을 제어하는 환경에서, System-assigned Managed Identity를 사용하는 VM이 `az login --identity` 명령을 실행할 때 실패하는 문제가 발생할 수 있음. 이는 단순히 로그인만 하는 것이 아니라, 로그인 후 Azure Resource Manager(ARM) 엔드포인트로 추가 호출을 시도하면서 발생하는 네트워크 차단 문제다.

이 문서는 해당 문제의 원인을 진단하고 해결하는 방법을 설명한다.

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

많은 경우 "Managed Identity가 막혔다"고 생각하지만, 실제로는 다음 단계에서 발생하는 네트워크 차단 문제다:

1. IMDS에서 토큰 획득 - 성공
2. 토큰으로 ARM API 호출하여 구독/테넌트 정보 조회 - 실패

## 원인 분석

Managed Identity 인증이 실패하는 원인은 크게 두 가지로 나눌 수 있음:

### 1. IMDS(169.254.169.254) 자체가 차단된 경우

System-assigned Managed Identity는 VM 내부에서 IMDS(Instance Metadata Service) 고정 IP `169.254.169.254`로 요청하여 토큰을 받는다. 이 트래픽은 VM 밖으로 나가면 안 되는 성격이고, VM 내부 프록시나 라우팅 정책이 IMDS 요청을 가로채면 즉시 실패한다.

#### IMDS 차단 원인

**프록시 환경변수 설정**
- VM에 `HTTP_PROXY` 또는 `HTTPS_PROXY` 환경변수가 설정되어 있으면 IMDS 호출도 프록시를 거치려고 시도한다
- Microsoft 공식 문서에서도 "IMDS 호출은 웹 프록시를 우회해야 한다"고 명시한다

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

IMDS 호출이 실패하면 `az login --identity`는 당연히 실패한다. 이 경우 IMDS 자체가 차단된 것이므로, 이번 이슈(Firewall 차단)의 원인이 아니다.

### 2. IMDS는 작동하지만 ARM 호출이 Firewall에서 차단된 경우 (가장 흔함)

이 경우가 가장 흔하게 발생하는 패턴이다. `az login --identity`는 실제로 다음 두 단계를 수행한다:

1. IMDS에서 토큰 받기 (성공)
2. 토큰으로 ARM에 접속하여 테넌트/구독 목록 조회 및 기본 구독 설정 (실패)

두 번째 단계에서 `management.azure.com` 등의 ARM 엔드포인트 접근이 Firewall에서 차단되면 로그인이 실패한다.

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

실패 지점이 `management.azure.com` 호출이라면 Firewall 설정 문제다.

## 해결 방법

### 최소 허용 목록

Azure Firewall Application Rule에 다음 FQDN을 허용해야 한다:

```
최소 구성:
- management.azure.com:443 (HTTPS)

이유: ARM API 엔드포인트로, 구독/테넌트 정보 조회 및 대부분의 Azure 관리 작업에 필요
```

### 권장 허용 목록 (Network Rule with Service Tag)

Azure Firewall Network Rule에서 Service Tag를 사용하여 허용할 수 있다:

```
Network Rule 설정:
  Name: Allow-Azure-Management
  Source: 10.0.0.0/16 (또는 특정 서브넷)
  Destination: AzureCloud (Service Tag)
  Protocol: TCP
  Destination Ports: 443
```

**참고**: Application Rule의 FQDN 기반 제어가 더 정밀하지만, Service Tag는 Azure 관리 평면 전체를 포괄적으로 허용한다.


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

□ Azure Firewall에 management.azure.com 접근이 허용되어 있는가?
  → Firewall → Network Rules 또는 Application Rules 확인
  → Service Tag AzureCloud 또는 FQDN management.azure.com

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

## 요약

### 핵심 포인트

1. **Managed Identity 인증은 두 단계**
   - IMDS(169.254.169.254)에서 토큰 획득
   - ARM(management.azure.com)에서 구독 정보 조회

2. **IMDS는 VM 내부 트래픽**
   - 프록시 예외 설정 필수
   - UDR로 라우팅하면 안 됨

3. **ARM 접근은 Firewall 허용 필요**
   - Network Rule에 AzureCloud Service Tag 사용 권장
   - 또는 Application Rule에 management.azure.com:443 허용

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

Azure Firewall Rule:
✓ Network Rule: Service Tag AzureCloud, TCP 443 (권장)
  또는
✓ Application Rule: management.azure.com:443 (최소 구성)

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
- [Azure CLI: Managed Identity timeout issues](https://github.com/Azure/azure-cli/issues?q=is%3Aissue+managed+identity+timeout)
- [Azure Firewall: FQDN Tag documentation](https://github.com/MicrosoftDocs/azure-docs/blob/main/articles/firewall/fqdn-tags.md)
- [Terraform azurerm Provider: Managed Identity authentication issues](https://github.com/hashicorp/terraform-provider-azurerm/issues?q=is%3Aissue+managed+identity+authentication)
