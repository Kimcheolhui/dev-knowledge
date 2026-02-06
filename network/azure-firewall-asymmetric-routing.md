# Azure Firewall을 활용한 hub-and-spoke 패턴에서의 비대칭 라우팅

## 개요

Azure Firewall을 사용하여 hub-and-spoke 네트워크 패턴을 구성할 때, Bastion 서버나 Self-hosted Runner와 같은 관리용 VM에 SSH 또는 RDP로 접속이 안 되는 문제가 발생할 수 있음. 이는 **비대칭 라우팅(Asymmetric Routing)** 때문이며, 인바운드와 아웃바운드 트래픽의 경로가 달라져서 TCP 세션이 정상적으로 수립되지 않는 현상임.

## 문제 상황

### 시나리오

```
구성:
- Bastion/Jump VM: Public IP가 직접 연결됨 (예: 20.1.2.3)
- Azure Firewall: Public IP = 23.100.56.40, Private IP = 10.2.1.4
- Bastion Subnet에 적용된 Route Table:
  1. 0.0.0.0/0 → VirtualAppliance 10.2.1.4 (모든 트래픽을 방화벽으로)
  2. 23.100.56.40/32 → Internet (방화벽 공인 IP만 예외)

현상:
- SSH 연결 시도 시 타임아웃 발생
- 또는 연결이 중간에 끊김
```

### 무슨 일이 발생하는가

1. **인바운드 트래픽 (정상)**
   ```
   클라이언트 (집/회사 IP) 
        ↓
   인터넷
        ↓
   VM Public IP (20.1.2.3)
        ↓
   VM NIC (정상 도착)
   ```

2. **아웃바운드 트래픽 (문제 발생)**
   ```
   VM에서 응답 패킷 전송 시도
        ↓
   라우팅 테이블 조회: 목적지 = 클라이언트 IP
        ↓
   23.100.56.40/32 매칭 안 됨 (클라이언트 IP ≠ 방화벽 IP)
        ↓
   0.0.0.0/0 규칙 적용
        ↓
   Azure Firewall (10.2.1.4)로 전송
        ↓
   Firewall에서 SNAT 처리 또는 상태 불일치로 드롭
   ```

3. **결과**
   - 클라이언트는 VM Public IP(20.1.2.3)와 TCP 세션을 시작함
   - 하지만 응답이 Firewall Public IP(23.100.56.40)에서 오거나 아예 오지 않음
   - TCP 핸드셰이크 실패로 연결 불가

## 왜 이런 문제가 발생하는가

### TCP 세션의 양방향 특성

많은 사람들이 오해하는 부분: **"SSH/HTTP는 인바운드 연결이니까 인바운드 경로만 사용하는 것 아닌가?"**

실제로는:
- TCP는 항상 **양방향(Full-duplex)** 통신임
- 연결은 인바운드로 들어오지만, **응답 패킷은 아웃바운드**임
- OS는 응답 패킷을 보낼 때 **라우팅 테이블을 참조**함

### TCP 핸드셰이크 상세 과정

```
3-way Handshake:

[클라이언트] ---- SYN ----→ [VM]
             (인바운드 경로: Internet → VM Public IP → VM NIC)

[클라이언트] ←--- SYN-ACK --- [VM]
             (아웃바운드 경로: VM → 라우팅 테이블 조회 → ???)
             ⚠️ 여기서 UDR 영향을 받음!

[클라이언트] ---- ACK ----→ [VM]
             (인바운드 경로: 위와 동일)
```

**핵심**: `SYN-ACK` 패킷은 VM 입장에서 **아웃바운드 패킷**이며, UDR(User Defined Route)의 영향을 100% 받음.

### VM이 응답을 어떻게 처리하는가

VM의 네트워크 스택은 다음과 같이 동작함:

```bash
1. 패킷 수신: "클라이언트 IP X.X.X.X에서 SYN 받음"
2. 응답 생성: "X.X.X.X로 SYN-ACK 보내야 함"
3. 라우팅 결정: "X.X.X.X로 가는 경로는?"
   → 라우팅 테이블 조회
   → 23.100.56.40/32? 아니오
   → 0.0.0.0/0 매칭! → Next hop: 10.2.1.4 (Azure Firewall)
4. 패킷 전송: Azure Firewall로 전송
```

VM은:
- 들어온 인터페이스를 기억하지 않음
- 세션 정보를 저장하지 않음
- 단순히 "목적지 IP에 따라 라우팅"만 수행함

이는 Stateful Firewall이나 NAT 장비와 다름. VM은 일반 호스트이므로 라우팅 테이블만 참조함.

### 방화벽 공인 IP 예외가 왜 도움이 안 되는가

현재 설정된 `23.100.56.40/32 → Internet` 예외의 의미:
- "VM이 **방화벽 공인 IP로** 나가는 트래픽은 Internet으로 직접 보내라"

문제:
- SSH 응답의 목적지는 **클라이언트 공인 IP**임 (예: 1.2.3.4)
- 방화벽 공인 IP(23.100.56.40)가 아님
- 따라서 이 예외 규칙은 SSH 트래픽에 전혀 적용되지 않음

## 검증 방법

VM에서 직접 확인할 수 있는 명령어:

```bash
# 클라이언트 IP로 가는 경로 확인
ip route get <클라이언트_공인_IP>

# 예시 출력 (문제 있는 경우):
# <클라이언트_IP> via 10.2.1.4 dev eth0 src 10.0.1.4
# → 10.2.1.4 (방화벽)을 경유함

# 예시 출력 (정상인 경우):
# <클라이언트_IP> via 10.0.1.1 dev eth0 src 10.0.1.4
# → 기본 게이트웨이 사용 (Internet으로 직접)
```

추가 확인 방법:

```bash
# 현재 라우팅 테이블 확인
route -n
# 또는
ip route show

# Azure Portal에서 확인
# VM → Networking → Network Interface → Effective routes
# 여기서 0.0.0.0/0의 Next hop type과 Next hop IP address 확인
```

## 해결 방법

### 1. Bastion Subnet을 Force-tunneling에서 제외 (권장 - 운영 편의)

관리용 서브넷은 인터넷 직접 접속을 유지하고, 워크로드 서브넷만 방화벽을 경유하게 함.

#### 구성 방법

```
Route Table 분리:

1. route-table-workload (워크로드 서브넷용)
   - 0.0.0.0/0 → VirtualAppliance 10.2.1.4

2. route-table-bastion (Bastion 서브넷용)
   - 별도 UDR 없음 (기본 시스템 라우트 사용)
   - 또는 특정 필요한 경로만 추가

서브넷 연결:
- Bastion Subnet → route-table-bastion (또는 연결 안 함)
- App Subnet → route-table-workload
- Data Subnet → route-table-workload
```

#### 장점
- 가장 간단하고 운영하기 쉬움
- SSH/RDP 관리 접속은 항상 정상 동작
- 워크로드 트래픽만 방화벽으로 중앙 집중

#### 단점
- Bastion의 아웃바운드 트래픽은 방화벽을 거치지 않음
- 관리 VM이 직접 인터넷 접속 가능 (보안 정책에 따라 문제될 수 있음)

#### 사용 시나리오
- 소규모/중규모 환경
- 관리 편의성이 중요한 경우
- Bastion의 아웃바운드 트래픽이 크지 않은 경우

### 2. VM Public IP 제거 + Firewall DNAT 구성 (권장 - 보안 강화)

모든 인바운드 트래픽도 방화벽을 경유하게 하여 대칭 경로를 만듦.

#### 구성 방법

```
1. VM에서 Public IP 제거
   - Bastion VM은 Private IP만 가짐 (예: 10.0.1.10)

2. Azure Firewall DNAT 규칙 생성
   포털: Firewall → Rules → DNAT Rules
   
   Name: Allow-SSH-to-Bastion
   Source: * (또는 특정 IP 범위)
   Destination: 23.100.56.40 (Firewall Public IP)
   Destination Port: 22
   Translated Address: 10.0.1.10 (Bastion Private IP)
   Translated Port: 22

3. Bastion Subnet Route Table
   - 0.0.0.0/0 → VirtualAppliance 10.2.1.4 (유지)
```

#### 트래픽 흐름

```
인바운드:
클라이언트 (1.2.3.4)
    ↓
Azure Firewall Public IP (23.100.56.40:22)
    ↓ (DNAT)
Bastion VM Private IP (10.0.1.10:22)

아웃바운드:
Bastion VM (10.0.1.10) → 응답 전송
    ↓ (UDR: 0.0.0.0/0)
Azure Firewall (10.2.1.4)
    ↓ (SNAT)
Azure Firewall Public IP (23.100.56.40)
    ↓
클라이언트 (1.2.3.4)

결과: 왕복 경로가 모두 방화벽을 경유하므로 대칭 라우팅 달성
```

#### 장점
- 모든 트래픽을 방화벽에서 중앙 집중 제어
- 인바운드/아웃바운드 모두 로깅 및 보안 정책 적용
- VM에 Public IP 불필요 (비용 절감)
- Hub-and-spoke 패턴의 정석

#### 단점
- 방화벽 장애 시 관리 접속도 불가 (방화벽이 SPOF)
- DNAT 규칙 관리 필요
- 방화벽 처리 지연 추가 (미미하지만)

#### 사용 시나리오
- 프로덕션 환경
- 모든 트래픽을 중앙에서 통제해야 하는 경우
- 보안 컴플라이언스 요구사항이 있는 경우
- Hub-and-spoke를 제대로 구현하려는 경우

### 3. 클라이언트 공인 IP 예외 추가 (임시 방법 - 비권장)

SSH를 시도하는 클라이언트의 공인 IP를 Internet 경로로 예외 처리함.

#### 구성 방법

```
Route Table에 추가:

Name: route-my-client-ip
Address Prefix: <내_공인_IP>/32 (예: 1.2.3.4/32)
Next Hop Type: Internet
```

#### 트래픽 흐름

```
인바운드:
클라이언트 (1.2.3.4)
    ↓
VM Public IP (20.1.2.3)
    ↓
Bastion VM

아웃바운드:
Bastion VM → 응답 전송 (목적지: 1.2.3.4)
    ↓ (UDR 조회)
    ↓ (1.2.3.4/32 매칭!)
    ↓ (Next Hop: Internet)
기본 게이트웨이 → 인터넷
    ↓
클라이언트 (1.2.3.4)

결과: 응답이 방화벽을 거치지 않고 직접 나가므로 대칭 경로 유지
```

#### 장점
- 즉시 적용 가능
- 기존 구성 변경 최소화

#### 단점
- 클라이언트 IP가 변경되면 즉시 접속 불가 (모바일, 가정용 인터넷 등)
- IP 주소마다 규칙 추가 필요 (관리 부담)
- 팀원/관리자가 많으면 관리 복잡도 증가
- 임시방편에 불과하며 장기 솔루션이 아님

#### 사용 시나리오
- 긴급하게 접속해야 하는 경우
- 일시적인 우회 방법으로만 사용
- 곧 해결 방법 1 또는 2로 전환할 계획이 있는 경우

## 해결 방법 비교

| 항목 | 방법 1: Bastion 제외 | 방법 2: Firewall DNAT | 방법 3: 클라이언트 IP 예외 |
|------|---------------------|----------------------|------------------------|
| **구현 난이도** | 낮음 | 중간 | 낮음 |
| **관리 편의성** | 높음 | 중간 | 낮음 (IP 변경 시마다) |
| **보안 수준** | 중간 | 높음 | 낮음 |
| **방화벽 통제** | 아웃바운드만 | 인바운드+아웃바운드 | 아웃바운드만 (예외 제외) |
| **장애 영향** | 독립적 | 방화벽 의존 | 독립적 |
| **비용** | Public IP 필요 | Public IP 불필요 | Public IP 필요 |
| **운영 안정성** | 높음 | 높음 | 낮음 |
| **권장도** | ⭐⭐⭐⭐ | ⭐⭐⭐⭐⭐ | ⭐⭐ |

## 실전 예시

### 예시 1: 개발 환경 (방법 1 적용)

```
시나리오:
- 소규모 개발팀
- 빠른 SSH 접속 필요
- Bastion 아웃바운드 트래픽 최소

구성:
[VNet 10.0.0.0/16]
    ├── Hub Subnet (10.0.1.0/24)
    │    └── Azure Firewall (10.0.1.4)
    │
    ├── Bastion Subnet (10.0.2.0/24) ← UDR 없음
    │    └── Jump VM (10.0.2.10, Public IP: 20.1.2.3)
    │
    └── App Subnet (10.0.3.0/24) ← UDR: 0/0 → 10.0.1.4
         └── App VM (10.0.3.10)

라우팅:
- Bastion Subnet: System default routes (Internet 직접)
- App Subnet: 0.0.0.0/0 → Firewall

결과:
- Jump VM SSH: 정상 (직접 인터넷)
- App VM 아웃바운드: 방화벽 경유
```

### 예시 2: 프로덕션 환경 (방법 2 적용)

```
시나리오:
- 프로덕션 환경
- 모든 트래픽 중앙 통제 필요
- 감사 로그 필수

구성:
[VNet 10.0.0.0/16]
    ├── Hub Subnet (10.0.1.0/24)
    │    └── Azure Firewall (10.0.1.4, Public IP: 23.100.56.40)
    │
    ├── Bastion Subnet (10.0.2.0/24) ← UDR: 0/0 → 10.0.1.4
    │    └── Jump VM (10.0.2.10, Private IP만)
    │
    └── App Subnet (10.0.3.0/24) ← UDR: 0/0 → 10.0.1.4
         └── App VM (10.0.3.10, Private IP만)

Firewall DNAT Rules:
- 23.100.56.40:22 → 10.0.2.10:22 (Jump VM SSH)
- 23.100.56.40:3389 → 10.0.2.10:3389 (Jump VM RDP)

라우팅:
- 모든 서브넷: 0.0.0.0/0 → Firewall

결과:
- 모든 인바운드: Firewall DNAT 경유
- 모든 아웃바운드: Firewall SNAT 경유
- 완전한 대칭 라우팅
- 모든 트래픽 로깅 및 제어
```

### 예시 3: Self-hosted GitHub Runner

```
시나리오:
- GitHub Actions Self-hosted Runner VM
- 아웃바운드로 GitHub API 접속 필요
- SSH 관리 접속 필요

문제:
- Runner VM에 Public IP 부여
- 0.0.0.0/0 → Firewall UDR 적용
- SSH 접속 불가

해결 (방법 2 적용):
1. Runner VM Public IP 제거
2. Firewall DNAT 규칙:
   23.100.56.40:2222 → 10.0.4.10:22
   
3. Runner VM에서 GitHub 접속:
   - 아웃바운드 트래픽 → Firewall 경유 → Internet
   - Firewall Application Rules로 github.com 허용

4. 관리자 SSH 접속:
   - ssh user@23.100.56.40 -p 2222
   - Firewall DNAT → Runner VM
   - 응답도 Firewall 경유 (대칭 경로)

장점:
- Runner는 Private IP만 사용
- 모든 GitHub API 호출 로깅
- SSH 접속 안정적
```

## 추가 고려사항

### Azure Bastion 서비스 사용

Azure의 관리형 Bastion 서비스를 사용하면 이 문제를 근본적으로 해결할 수 있음:

```
Azure Bastion 특징:
- VM에 Public IP 불필요
- 브라우저 기반 SSH/RDP (Azure Portal)
- NSG만으로 보안 제어 가능
- UDR 영향 받지 않음 (Azure 관리 트래픽)

구성:
[VNet]
    ├── AzureBastionSubnet ← 전용 서브넷 필수
    │    └── Azure Bastion 서비스
    │
    └── VM Subnet ← UDR: 0/0 → Firewall 적용 가능
         └── VM (Private IP만)

접속:
Azure Portal → VM → Connect → Bastion
→ 브라우저에서 SSH/RDP 세션 열림

장점:
- 비대칭 라우팅 문제 없음
- VM Public IP 불필요
- MFA, JIT 등 보안 기능 기본 제공
- 관리 트래픽과 애플리케이션 트래픽 완전 분리

단점:
- 별도 비용 (Basic: ~$0.19/시간)
- 브라우저 기반 접속만 가능 (SSH 클라이언트 직접 사용 불가)
```

### NSG와 UDR 우선순위

```
Azure 네트워킹에서 트래픽 처리 순서:

1. NSG (Network Security Group)
   - 허용/거부 결정
   - 서브넷/NIC 레벨

2. UDR (User Defined Routes)
   - 트래픽 경로 결정
   - 허용된 트래픽의 라우팅

3. System Routes
   - Azure 기본 라우팅

중요:
- NSG가 트래픽을 허용해도 UDR로 경로가 잘못되면 실패함
- 비대칭 라우팅은 NSG와 무관하게 발생
```

### 방화벽 로깅 활용

Azure Firewall을 사용하는 경우 진단 로깅으로 문제 추적 가능:

```
Azure Portal → Firewall → Diagnostic settings

로그 카테고리:
1. AzureFirewallApplicationRule
   - HTTP/HTTPS 트래픽
   
2. AzureFirewallNetworkRule
   - TCP/UDP 트래픽
   - SSH도 여기 기록됨

3. AzureFirewallDnatRule
   - DNAT 규칙 적용 로그

쿼리 예시 (Log Analytics):
AzureDiagnostics
| where Category == "AzureFirewallNetworkRule"
| where DestinationPort == 22
| project TimeGenerated, SourceIp, DestinationIp, Action, msg_s
| order by TimeGenerated desc
```

## 일반적인 실수

### 실수 1: "인바운드만 사용하니까 아웃바운드는 상관없다"

```
❌ 잘못된 생각:
"SSH는 인바운드 연결이니까 인바운드 규칙만 신경 쓰면 돼"

✓ 올바른 이해:
"TCP는 양방향이고, 응답도 아웃바운드 라우팅을 탐"
```

### 실수 2: "방화벽 IP를 예외로 뒀는데 왜 안 되지?"

```
❌ 잘못된 설정:
23.100.56.40/32 → Internet

이유: SSH 응답의 목적지는 클라이언트 IP이지 방화벽 IP가 아님

✓ 올바른 설정 (방법 3 사용 시):
<클라이언트_IP>/32 → Internet
```

### 실수 3: "NSG를 열어줬는데도 안 돼"

```
❌ NSG만 확인:
인바운드/아웃바운드 NSG 규칙 모두 Allow

이유: NSG는 통과하지만 UDR로 경로가 잘못되면 실패

✓ 확인해야 할 것:
1. NSG (Allow/Deny)
2. UDR (경로 설정)
3. Firewall Rules (DNAT/Network Rules)
```

### 실수 4: "UDR을 제거하면 해결되지 않나?"

```
❌ 단순 제거:
Bastion Subnet의 UDR을 아예 제거

문제:
- 일시적으로 SSH는 되지만
- 원래 목적인 "아웃바운드 트래픽 통제"를 포기하는 것

✓ 올바른 접근:
- 관리 트래픽과 워크로드 트래픽 분리
- 또는 대칭 라우팅 구성 (DNAT)
```

## 요약

### 핵심 개념

1. **비대칭 라우팅**
   - 인바운드와 아웃바운드 경로가 다름
   - TCP 세션이 정상 수립되지 않음

2. **TCP는 양방향**
   - 연결은 인바운드로 들어옴
   - 응답은 아웃바운드 라우팅을 따름

3. **UDR의 영향**
   - VM은 응답 패킷을 보낼 때 라우팅 테이블을 참조함
   - 들어온 경로를 기억하지 않음

### 해결 방법 선택 기준

```
운영 환경:
→ 방법 2 (Firewall DNAT) - 완전한 중앙 통제

개발 환경:
→ 방법 1 (Bastion 제외) - 관리 편의성

긴급 상황:
→ 방법 3 (클라이언트 IP 예외) - 임시 조치

장기 솔루션:
→ Azure Bastion 서비스 - 근본적 해결
```

### 체크리스트

```
비대칭 라우팅 문제 진단:
□ VM에 Public IP가 있는가?
□ 서브넷에 0.0.0.0/0 → Firewall UDR이 있는가?
□ 외부에서 Public IP로 직접 접속 시도하는가?
□ 응답 경로가 방화벽을 경유하는가?

해결 방법 적용:
□ 관리 서브넷과 워크로드 서브넷을 분리했는가?
□ DNAT 사용 시 인바운드/아웃바운드 모두 방화벽 경유하는가?
□ 클라이언트 IP 예외는 임시 조치로만 사용하는가?
□ Azure Bastion 서비스 도입을 검토했는가?

검증:
□ ip route get 명령으로 경로 확인했는가?
□ Azure Portal에서 Effective routes 확인했는가?
□ 방화벽 로그에서 트래픽 흐름 확인했는가?
```

## 참고 자료

### Azure 공식 문서

- [User-defined routes](https://learn.microsoft.com/azure/virtual-network/virtual-networks-udr-overview)
- [Azure Firewall DNAT rules](https://learn.microsoft.com/azure/firewall/tutorial-firewall-dnat)
- [Hub-spoke network topology](https://learn.microsoft.com/azure/architecture/reference-architectures/hybrid-networking/hub-spoke)
- [Azure Bastion](https://learn.microsoft.com/azure/bastion/bastion-overview)

### 관련 개념

- [RFC 1122 - Host Requirements](https://datatracker.ietf.org/doc/html/rfc1122) - TCP 동작 방식
- [RFC 5735 - Special Use IPv4 Addresses](https://datatracker.ietf.org/doc/html/rfc5735) - 예약된 IP 대역
- Asymmetric Routing in Stateful Firewalls

### 네트워킹 기본

```bash
# 리눅스에서 라우팅 확인
ip route show
ip route get <destination_ip>
netstat -rn

# Azure CLI로 확인
az network nic show-effective-route-table \
  --resource-group myRG \
  --name myVmNic \
  --output table
```
