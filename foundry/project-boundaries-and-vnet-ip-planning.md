# Microsoft Foundry Project 구분과 VNet IP 설계

> 확인 기준: 2026-10-16. Project 구분 기준과 VNet 주소 공간 사용에 관한 질문을 정리한 문서.
> 현재 Foundry의 **Foundry resource 아래 Project를 두는 구조** 기준이다. Hub 기반 Foundry classic에는 그대로 적용하지 않는다.
> 기능, 지원 리전, 제한 사항은 바뀔 수 있으므로 실제 설계 전 공식 문서를 재확인한다.

## 핵심 요약

- **Project는 팀별로 반드시 하나씩 만드는 단위가 아니다.** 구분되는 유스케이스의 자산, 권한, 개발 작업을 관리하는 논리적 경계다.
- **운영 워크로드의 환경별 전용 Foundry resource를 기본값**으로 검토한다. 여러 운영 워크로드의 resource 공유는 문서화된 예외로 판단한다.
- 팀과 조직은 소유권과 공유 가능 범위를 정하는 기준이다. 팀·조직별로 Project를 하나씩 만들 필요는 없다.
- BYO VNet Integration에서는 **같은 Foundry resource의 모든 Project가 위임 서브넷을 공유**한다. Project마다 별도 CIDR이 필요한 구조가 아니다.
- **Hosted Agent와 Prompt Agent 모두 지원되는 최소 서브넷 크기는 `/27`**이다. `/24`는 특히 Hosted Agent 운영환경의 권장 크기이며, 필수 최소 크기는 아니다.
- Hosted Agent는 활성 세션을 실행하는 컴퓨트가 늘면서 사설 IP 수요도 증가한다. 기본 매핑은 **동시 Hosted Agent 세션과 IP가 1:1**이다.
- 미사용 주소는 확장과 업그레이드에 필요할 수 있다. 모든 resource에 `/24`를 일괄 배정하지 않고 필요한 용량과 격리 수준으로 판단한다.
- 사내 주소 공간이 부족하면 **Managed VNet**을 검토한다. 네트워크 통제, 지원 리전, 연결 방식, 비용상의 제약도 함께 확인한다.

## 1. 질문과 검토 항목

### 질문 1: Project는 팀, 워크로드, 조직 중 무엇을 기준으로 나누나?

유스케이스별 Project 분리와 운영 워크로드별 resource 격리를 구분한다. 공유와 격리의 상세 기준은 Foundry 도입 가이드와 CAF를 참고한다. AI Landing Zone은 네트워크, 보안, 모니터링을 포함한 구현 레퍼런스다.

### 질문 2: VNet Integration 시 Project별 IP 대역 낭비를 어떻게 해소하나?

**Project별 IP 사용량 증가**와 **Foundry resource별 전용 서브넷 확보**를 구분한다. `/27` 적용 여부는 다음 항목을 확인한 뒤 판단한다.

1. 실제 resource와 Project의 구성 관계
2. Hosted Agent의 동시 활성 세션과 Project별 네트워크 구성요소
3. 확장, 배포, 업그레이드 여유
4. BYO VNet이 필수인지, Managed VNet을 사용할 수 있는지

## 2. Project와 Foundry resource의 경계

| 계층 | 주요 역할 | 구분할 때 볼 항목 |
| --- | --- | --- |
| Project | 유스케이스별 자산과 역할 할당, Agent, 파일, 평가 등 개발 작업 관리 | 사용자 경험, 접근권한, 데이터 사용, 개발 흐름 |
| Foundry resource | Project들이 사용하는 상위 인프라와 거버넌스 경계 | 네트워크, 보안 설정, 모델 배포, 운영 영향 범위 |
| 연결된 Azure 서비스 | Storage, AI Search, Key Vault 등 데이터와 연결 기반 | 해당 서비스의 자체 RBAC, 네트워크, 데이터 격리 |
| Subscription / Landing Zone | 조직 정책과 환경별 관리 경계 | 정책, 비용 관리, 보안, 운영, 서비스별 쿼터 |

**Project를 나눴다고 네트워크, 모델 용량, 비용, 연결된 데이터가 모두 독립되는 것은 아니다.** 사용하는 API와 기능에 따라 Project 수준 격리 지원 여부도 다르다.

쿼터는 제한의 종류에 따라 구독, 리전, 모델, 배포 등의 범위에서 적용된다. **Foundry resource를 추가한다고 구독·리전 단위 쿼터까지 자동으로 분리되거나 늘어나지는 않는다.**

### 팀과 조직은 소유권·공유 기준

CAF는 공유 가능한 경계를 정하는 예로 다음을 든다.

- **사업부**: 공통 운영 책임과 예산
- **데이터 도메인**: 공통 규제와 데이터 처리 기준
- **제품 소유권**: 공통 개발 수명주기와 플랫폼 운영

경계 안에서는 공유를 검토할 수 있지만, 전용 resource가 필요한 워크로드는 따로 격리할 수 있다. 경계를 넘는 공유는 허용하지 않는 방식으로 정책을 수립한다.

### 워크로드, 유스케이스, Agent의 관계

워크로드는 독립적인 배포·운영 책임을 갖는 업무 서비스 단위로 판단한다. 하나의 워크로드 안에 여러 유스케이스와 Agent가 있을 수 있다.

| 상황 | 판단 방향 |
| --- | --- |
| 같은 팀이 상담 지원 서비스와 HR 도우미를 개발 | 팀이 같다는 이유로 합치지 않는다. 별도 워크로드로 보고 운영 격리를 검토 |
| 여러 팀이 하나의 상담 지원 서비스를 공동 개발 | 팀 수만큼 나눌 필요는 없다. 서비스의 유스케이스와 권한 경계로 구성 |
| 하나의 흐름에 검색, 요약, 티켓 생성 Agent가 있음 | Agent마다 Project를 만들 필요는 없다. 구분되는 유스케이스인지 판단 |
| 같은 제품 안에 서로 다른 사용자 경험과 자산·권한을 갖는 유스케이스가 있음 | resource 안에서 유스케이스별 Project 분리 |
| Dev와 Prod | Project 구분만으로 끝내지 않고 resource와 필요 시 구독까지 격리 |

CAF는 **운영 워크로드 환경별 전용 플랫폼 인스턴스**를 기본값으로, 그 안의 **구분되는 유스케이스별 Project**를 권장한다. 모든 경우에 `워크로드 : resource : Project = 1 : 1 : 1`이어야 한다는 뜻은 아니다.

### 탐색은 공유, 운영은 격리가 기본

- **탐색·PoC**: 공용 탐색용 resource 아래 유스케이스별 Project를 두어 실험 속도를 높일 수 있다.
- **운영**: 워크로드의 운영환경별 전용 resource를 기본으로 한다.
- **운영 공유 예외**: 규제, 데이터 분류, 네트워크, 신원 경계가 일치하고, 공동 장애·쿼터 소진 위험을 수용하며, 명확한 관리 책임자를 둔 경우 검토한다.

IP 절약이나 비용 압박만으로 서로 다른 운영 워크로드를 합치는 것은 충분한 정당화가 아니다. 공유 후 다시 분리하려면 상태와 구성을 재생성해야 하는 부담도 고려한다.

근거: [CAF AI platform sharing decision guidance](https://learn.microsoft.com/en-us/azure/cloud-adoption-framework/ai/platform/ai-platform-sharing-isolation-colocation), [Foundry 조직 도입 가이드](https://learn.microsoft.com/en-us/azure/foundry/concepts/planning)

## 3. Private Endpoint와 VNet Integration 구분

| 구성 | 목적 | 직접 관리하는 주소 공간 사용 |
| --- | --- | --- |
| Foundry 인바운드 Private Endpoint | 직접 관리하는 네트워크에서 Foundry 엔드포인트로 사설 접속 | Private Endpoint에 할당되는 사설 IP |
| Agent Service BYO VNet Integration / Injection | Agent 실행 환경의 아웃바운드 연결을 직접 관리하는 네트워크에 통합 | 직접 확보한 전용 위임 서브넷 |
| Foundry Managed VNet | Microsoft가 관리하는 네트워크에서 Agent 아웃바운드 격리 | Agent용 위임 서브넷은 불필요. 직접 관리하는 VNet의 인바운드 Private Endpoint는 별도 고려 |
| Storage, Search 등 연결 서비스의 Private Endpoint | 각 데이터 서비스로 사설 접속 | 별도 산정. Managed Private Endpoint인지 직접 관리하는 VNet의 Private Endpoint인지도 구분 |

**Foundry에 Private Endpoint로 접속한다는 이유만으로 Agent용 `/24`가 필요한 것은 아니다.** 인바운드만 사설화하고 아웃바운드는 public인 구성도 별도로 존재한다.

### BYO VNet에서 서브넷을 공유하는 단위

- 서브넷은 `Microsoft.App/environments`에 위임한다.
- **같은 Foundry resource의 모든 Project가 같은 위임 서브넷 용량을 사용**한다.
- **서로 다른 Foundry resource는 하나의 위임 서브넷을 공유할 수 없다.**
- Project가 추가되면 프로젝트용 네트워크 구성요소의 IP 소비는 늘 수 있지만, Project마다 새 `/24`나 `/27`이 생기는 것은 아니다.

Project별 IP 사용량과 별도 Foundry resource를 생성하면서 확보하는 서브넷 주소 공간을 구분해야 한다.

근거: [Foundry Agent Service 네트워크 옵션](https://learn.microsoft.com/en-us/azure/foundry/agents/concepts/networking-options)

## 4. 서브넷 크기: 최소 지원과 운영 권장 구분

| 서브넷 | 전체 주소 수 | Azure 예약 5개 제외 |
| --- | --- | --- |
| `/27` | 32 | 27 |
| `/26` | 64 | 59 |
| `/25` | 128 | 123 |
| `/24` | 256 | 251 |

- **Hosted Agent**: 지원되는 최소 크기는 `/27`. 운영, 특히 확장이 예상되는 경우 `/24`가 권장 크기다.
- **Prompt Agent**: 지원되는 최소 크기는 `/27`. 여러 Project의 구성요소가 소비하는 IP를 합산해야 한다.
- **할당 후 서브넷 크기를 변경할 수 없으므로**, 향후 확장에 필요한 용량까지 초기 크기에 반영해야 한다.
- **계획 사용률은 80% 미만**을 목표로 한다. 배포·업그레이드와 일시적인 확장에 필요한 여유를 남긴다.

공식 문서의 `/27` 운영 사용에 관한 권고 수준은 다르다. 네트워크 옵션 문서는 Prompt Agent 또는 소규모 Hosted Agent 구성에서 사용할 수 있다고 설명하지만, 네트워킹 상세 문서는 운영에서 `/27` 사용을 권장하지 않는다. **최소 지원 크기와 운영 권장값을 구분**하고, `/27`을 모든 운영환경에 일괄 적용하지 않는다.

`/26`이나 `/25`도 용량 검토 대상이 될 수 있지만, 사용량 검증과 성장·유지보수 여유를 확인한 뒤 선택할 크기다.

근거: [서브넷 크기 계획](https://learn.microsoft.com/en-us/azure/foundry/agents/concepts/networking-options#plan-your-subnet-size), [IP 할당과 용량 계획](https://learn.microsoft.com/en-us/azure/foundry/agents/concepts/agents-networking-deep-dive#subnet-sizing-and-ip-allocation)

## 5. Hosted Agent에서 IP 사용량이 늘어나는 이유

### 컨테이너 수보다 활성 세션과 실행 컴퓨트로 이해

Hosted Agent는 컨테이너 이미지를 기반으로 실행하지만, 네트워크 용량 계획에서는 이를 실행하는 **Micro VM과 세션**이 중요하다.

1. 세션이 생성되거나 재개된다.
2. 플랫폼이 세션을 실행할 컴퓨트를 프로비저닝한다.
3. BYO VNet에서는 실행 컴퓨트가 위임 서브넷의 네트워크 인터페이스와 사설 IP를 사용한다.
4. 동시에 활성화된 세션이 늘면 컴퓨트와 IP 수요도 늘어난다.

공식 문서는 기본적으로 동시 Hosted Agent 세션과 가용 IP를 **1:1**로 매핑한다. 이는 모든 구성에서 고정된 규칙은 아니다. Azure 지원을 통해 최대 **IP 1개당 동시 세션 10개** 매핑을 요청할 수 있지만, 요구사항과 리전 용량에 따라 달라지므로 사전 승인 없이 보장된 전제로 사용하지 않는다.

### 요청 수, 세션 수, 대화 기록 수는 다르다

| 개념 | 의미 | IP 계획에서의 해석 |
| --- | --- | --- |
| 요청 | Agent에 대한 개별 호출이나 대화 턴 | 요청 하나마다 IP 하나가 추가되는 것은 아님 |
| 세션 | 샌드박스 컴퓨트와 보존되는 파일 상태 | 동시에 실행 컴퓨트를 유지하는 세션 수가 중요 |
| 대화 | 메시지, 도구 호출, 응답의 이력 | 저장된 대화 수만큼 IP를 계속 유지하는 것은 아님 |

같은 세션에서 여러 턴을 처리할 수 있다. 세션 연속성과 대화 연속성은 별개의 개념이며, 프로토콜에 따라 연결 방식이 다르다.

### 유휴 세션의 수명주기

- 세션의 유휴 시간 제한 기본값은 **15분**이다.
- 설정 가능 범위는 **2~60분**이다.
- 유휴 시간 제한에 도달하면 플랫폼은 컴퓨트를 회수하고 상태를 저장한다.
- 다시 참조되면 컴퓨트를 프로비저닝하고 저장된 상태를 복원한다.

따라서 순간적인 요청 수뿐 아니라 **세션이 컴퓨트를 유지하는 시간**도 용량에 영향을 준다. 유휴 시간을 줄이면 유지되는 컴퓨트를 줄이는 데 도움이 될 수 있지만, 재개 시 프로비저닝과 상태 복원이 필요하므로 응답 지연과 사용 패턴을 함께 검토한다.

### 필요한 주소 수의 구성

서브넷 용량에는 다음을 모두 포함한다.

- Hosted Agent 활성 세션을 위한 IP
- Project별 네트워크 구성요소와 데이터 프록시
- 배포·업그레이드 중 일시적으로 추가되는 IP
- 확장 여유

예를 들어 `/27`의 가용 주소 27개가 활성 세션 27개를 보장하지는 않는다. 실제 동시 세션은 네트워크 용량 외에 구독·리전의 서비스 쿼터에도 제한된다.

Prompt Agent는 버전마다 IP를 소비하는 방식이 아니라 Project 단위 네트워크 구성요소를 공유한다. 공식 옵션 문서는 Project당 약 10개까지의 작은 고정 IP 풀로 설명한다. 모든 Project가 항상 정확히 10개를 사용한다는 뜻은 아니다.

근거: [Hosted Agent 네트워킹 상세](https://learn.microsoft.com/en-us/azure/foundry/agents/concepts/agents-networking-deep-dive), [Hosted Agent 세션 관리](https://learn.microsoft.com/en-us/azure/foundry/agents/how-to/manage-hosted-sessions)

## 6. IP 주소 공간 부담을 줄이는 선택지

### 선택지 A: Managed VNet

사내 주소 공간이 부족하고 네트워크 통제 요구를 충족할 수 있다면 우선 검토한다.

- Microsoft가 Agent 실행 네트워크의 주소 범위와 IP 할당을 관리한다.
- Prompt Agent와 Hosted Agent를 지원한다.
- 지원되는 Azure 데이터 서비스에는 Managed Private Endpoint로 접근할 수 있다.
- 직접 관리하는 VNet에서 resource마다 Agent용 `/24`를 확보할 필요를 줄일 수 있다.
- 직접 관리하는 VNet의 Foundry 인바운드 Private Endpoint 등은 별도 고려한다.

제약도 있다.

- 지원 리전과 필요한 기능을 확인해야 한다.
- 기존 사내 Firewall, UDR, Peering을 직접 통제하는 BYO VNet과 같은 모델이 아니다.
- 기존 사내 Firewall을 Managed VNet의 Firewall로 사용할 수 없다.
- FQDN 아웃바운드 규칙은 관리형 Firewall 비용을 발생시킬 수 있다. 여러 Foundry account가 그 관리형 Firewall을 공유할 수 없다.
- 온프레미스 접근 방식과 아웃바운드 로깅 지원 여부를 확인해야 한다.
- BYO VNet에서 Managed VNet으로의 변경에는 resource 재배포가 필요하므로 초기 설계에서 판단한다.

근거: [Foundry Managed VNet 가이드](https://learn.microsoft.com/en-us/azure/foundry/how-to/managed-virtual-network)

### 선택지 B: BYO VNet에서 용량에 맞게 산정

사내망 직접 접근, ExpressRoute, 중앙 Firewall, UDR 통제 등이 필수라면 BYO VNet을 검토한다.

- resource 전체의 최대 동시 활성 세션과 Project별 구성요소를 합산한다.
- 운영 권장 크기인 `/24`를 기준으로 검토하되, 더 작은 구성을 선택하려면 용량과 위험을 검증한다.
- 할당 후 크기를 바꿀 수 없다는 점과 재구성 부담을 반영한다.
- IP가 부족한 기존 구성은 지원을 통한 세션 매핑 변경 가능성도 확인한다.

### 선택지 C: 워크로드 경계의 과도한 세분화 재검토

- Agent 하나, 기능 하나마다 resource가 필요한 것은 아니다.
- 같은 제품의 동일 운영 경계라면 하나의 resource 안에서 유스케이스별 Project로 구성할 수 있다.
- 서로 다른 운영 워크로드의 resource 공유는 CAF의 예외 조건을 검토한다.
- IP 절약만을 이유로 보안·데이터 격리가 필요한 워크로드를 합치지 않는다.

### 주소 공간 확보와 실제 할당은 별개

resource 10개에 `/24`를 하나씩 배정하면 Agent 서브넷용으로 **2,560개 주소 공간을 확보**한다. 그렇다고 생성 직후 IP 2,560개가 실제로 할당되는 것은 아니다.

사용하지 않는 private IP 자체의 비용 문제라기보다, 사내에서 라우팅 가능한 비중복 주소 공간을 얼마나 예약해야 하는지의 문제다. 한편 미사용 주소 일부는 확장과 업그레이드를 위한 운영 여유이므로 모두 낭비로 보지는 않는다.

## 7. 질문별 정리

### Project는 어떤 기준으로 나누나?

Foundry Project는 유스케이스별 자산과 접근권한을 관리하는 논리적 개발 경계다. 팀이나 조직과 반드시 1:1로 구성하지 않는다. 운영환경에서는 Project 구분과 별도로 워크로드의 운영환경별 Foundry resource 격리를 기본으로 검토한다. 팀·조직, 데이터 민감도, 운영 책임, 비용 배분 등의 조건에 따라 공유 가능한 범위를 정하고, 공유가 필요한 경우 예외 기준을 수립한다. 상세 판단 기준은 Foundry 도입 가이드와 CAF의 AI platform sharing 가이드를, 인프라 구현은 AI Landing Zone을 참고한다.

### VNet Integration의 IP 주소 공간 사용을 어떻게 줄이나?

Foundry의 BYO VNet Integration은 Project마다 별도 서브넷을 요구하지 않는다. 같은 Foundry resource의 Project들이 하나의 위임 서브넷을 공유한다. 지원 최소 크기는 `/27`이지만, Hosted Agent 운영환경에는 확장과 업그레이드 여유를 고려해 `/24`가 권장된다. `/27`로 일괄 축소하지 않고 예상 동시 활성 세션과 전체 Project 사용량을 기준으로 크기를 산정해야 한다. 사내 주소 공간이 부족하다면 Managed VNet도 대안으로 검토할 수 있다.

### Hosted Agent는 왜 추가 IP가 필요한가?

Hosted Agent는 동시 활성 세션 증가에 따라 실행 컴퓨트와 사설 IP 수요가 증가한다. 확장과 업그레이드 중에는 추가 IP가 필요하므로 서브넷에 미사용 주소를 남겨야 한다. 모든 워크로드에 같은 크기를 배정하지 않고 예상 동시 활성 세션과 운영 여유를 기준으로 산정한다.

## 8. 실제 설계 전에 확인할 항목

- 현재 Foundry resource 기반 구성인지, Hub 기반 classic 구성인지
- resource와 Project가 각각 몇 개이며 어떤 관계인지
- 인바운드 Private Endpoint만 사용하는지, BYO VNet Injection까지 사용하는지
- Hosted Agent와 Prompt Agent의 사용 비중
- 필요한 리전과 해당 네트워크 옵션의 지원 여부
- resource 전체의 최대 동시 Hosted Agent 활성 세션과 유휴 시간
- 연결 데이터 서비스와 각 서비스의 Private Endpoint 구성
- 중앙 Firewall, UDR, 온프레미스 연결, 로깅 요구사항
- 구독·리전 등 적용 범위별 서비스 쿼터
- 배포·플랫폼 업그레이드와 향후 성장 여유

## 9. 공식 가이드 읽는 순서

| 순서 | 문서 | 확인할 내용 |
| --- | --- | --- |
| 1 | [Foundry rollout across my organization](https://learn.microsoft.com/en-us/azure/foundry/concepts/planning) | 조직 도입, 격리 경계, 운영과 탐색의 배치 원칙 |
| 2 | [CAF AI platform sharing decision guidance](https://learn.microsoft.com/en-us/azure/cloud-adoption-framework/ai/platform/ai-platform-sharing-isolation-colocation) | 운영 격리 기본값, 공유 예외, 유스케이스별 Project |
| 3 | [Foundry architecture](https://learn.microsoft.com/en-us/azure/foundry/concepts/architecture) | resource, Project, 연결 서비스의 경계 |
| 4 | [CAF Architecture and governance for AI](https://learn.microsoft.com/en-us/azure/cloud-adoption-framework/ai/ready) | 기존 Landing Zone에 AI 워크로드를 배치하는 원칙 |
| 5 | [Foundry baseline in an Azure landing zone](https://learn.microsoft.com/en-us/azure/architecture/ai-ml/architecture/baseline-microsoft-foundry-landing-zone) | 플랫폼 팀과 워크로드 팀의 책임, 워크로드 소유 resource |
| 6 | [AI Landing Zones](https://azure.github.io/AI-Landing-Zones/) | 네트워크, 보안, 모니터링을 포함한 구현 레퍼런스 |
| 7 | [Agent Service networking options](https://learn.microsoft.com/en-us/azure/foundry/agents/concepts/networking-options) | 인바운드·아웃바운드 선택, BYO와 Managed VNet, 최소 서브넷 |
| 8 | [Agent Service networking deep dive](https://learn.microsoft.com/en-us/azure/foundry/agents/concepts/agents-networking-deep-dive) | Micro VM, 데이터 프록시, IP 할당, 동시 세션 용량 |
| 9 | [Manage hosted agent sessions](https://learn.microsoft.com/en-us/azure/foundry/agents/how-to/manage-hosted-sessions) | 세션과 대화의 차이, 유휴 시간, 컴퓨트 회수·재개 |
| 10 | [Configure managed virtual network](https://learn.microsoft.com/en-us/azure/foundry/how-to/managed-virtual-network) | Managed VNet의 지원 범위, 제약과 비용 |

관련 문서: [Microsoft Foundry 모델 호스팅과 데이터 경계](./model-hosting-and-data-boundary.md)
