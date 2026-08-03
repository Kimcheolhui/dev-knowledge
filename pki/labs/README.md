# 인증서 실습 개요

세션 문서([../certificate](../certificate/README.md), 1~5장)에서 다뢬 개념을 실제로 확인하기 위한 실습 계획이다. 이 문서는 개요만 담는다. 각 실습의 명령어와 매니페스트는 별도 문서로 분리한다.

아직 수행하지 않았다. 앞으로 진행하면서 각 Lab 문서를 추가한다.

## 기존 실습과의 관계

`aks/gw-api/01-application-gateway-for-containers-labs/03-https-and-cert-manager.md`에 cert-manager + Let's Encrypt HTTP-01(Gateway API solver) 실습이 이미 있다. 자체 서명 인증서로 HTTPS listener를 먼저 검증하고, 이후 실제 도메인으로 ACME 발급까지 이어지는 구성이다.

따라서 이 실습은 **발급 자체**를 반복하지 않는다. 발급 이후에 무엇이 일어나는지, 그리고 발급 경로가 여러 개일 때 무엇이 달라지는지에 집중한다.

| 구분 | 기존 AGC 실습 | 이 실습 |
|---|---|---|
| 검증 방식 | HTTP-01 | DNS-01 |
| 대상 리소스 | Gateway API | Ingress / Gateway 양쪽 |
| 초점 | 발급 성공까지 | 발급 이후 소비·갱신·장애 |

## 환경 전제

- AKS 클러스터
- 실제 소유한 퍼블릭 도메인. DNS 존에 대한 쓰기 권한이 있어야 한다
- Azure DNS 존 (DNS-01 검증용)
- cert-manager

도메인이 확보되어 있으므로 4-2에서 정리한 nip.io의 제약이 적용되지 않는다.

- DNS-01 검증이 가능하다 → 와일드카드 인증서를 발급할 수 있다
- 80 포트를 외부에 노출하지 않고 발급할 수 있다 → 내부 전용 서비스 시나리오를 다룰 수 있다

## 실습 목록

| Lab | 주제 | 연결되는 장 |
|---|---|---|
| 01 | DNS-01 검증과 와일드카드 발급 | 1-4 |
| 02 | 발급된 인증서 해부 | 2-2, 2-3, 3-1, 3-2 |
| 03 | 인증서 주입 경로 비교 | 1-3, 1-5 |
| 04 | 장애 재현 | 5-2, 5-3 |
| 05 | 클라이언트 인증서 검증 (선택) | 1-5, 3-3 |

### Lab 01. DNS-01 검증과 와일드카드 발급

Azure DNS 존에 TXT 레코드를 쓰는 방식으로 소유권을 검증한다. cert-manager가 존에 쓸 권한을 얻는 경로는 워크로드 아이덴티티로 구성한다.

- `ClusterIssuer`의 `solvers[].dns01.azureDNS` 설정
- `Order` → `Challenge` → TXT 레코드 생성 → 검증 → 레코드 삭제의 순서 관찰
- `*.<domain>` 와일드카드 인증서 발급. HTTP-01으로는 불가능한 이유를 대비해서 확인
- 전파 지연으로 검증이 지연되는 상황과 `Challenge` 상태 확인

Let's Encrypt staging 엔드포인트로 먼저 진행한다. 설정을 반복 수정하게 되므로 production으로 시작하면 발급 횟수 제한에 걸린다.

### Lab 02. 발급된 인증서 해부

발급 결과물을 문서 2~3장의 항목과 대조한다.

- `openssl x509 -text` — SAN, Basic Constraints, Key Usage / EKU, 유효기간, 발급자
- 서버 인증서 / 중간 CA / Root CA를 나란히 놓고 차이 확인
- `openssl s_client -showcerts` — 서버가 실제로 전송하는 체인
- `-servername` 유무에 따른 인증서 선택 차이 (SNI)
- 협상된 TLS 버전과 cipher suite 확인

### Lab 03. 인증서 주입 경로 비교

같은 결과(`Secret`을 참조하는 TLS 리스너)에 도달하는 경로가 여러 개다. 각 경로가 어디까지 자동인지가 다르다.

| 방식 | 트리거 | 인증서 출처 | 대상 |
|---|---|---|---|
| cert-manager ingress-shim | `cert-manager.io/cluster-issuer` 어노테이션 | ACME 발급 → `Secret` | NGINX, AGC, AGIC |
| app routing 애드온 + Key Vault | `kubernetes.azure.com/tls-cert-keyvault-uri` 어노테이션 | Key Vault → CSI 드라이버가 `Secret` 동기화 | managed NGINX |
| AGIC + Key Vault | `appgw.ingress.kubernetes.io/appgw-ssl-certificate` 어노테이션 | Application Gateway가 Key Vault를 직접 참조 | Application Gateway v2 |

확인할 내용은 다음과 같다.

- 어노테이션 하나로 어디까지 생성되는가. ingress-shim의 경우 `Certificate` 리소스가 사용자 손을 거치지 않고 만들어진다
- 갱신 주체가 누구인가. ACME 경로는 cert-manager, Key Vault 경로는 Key Vault의 갱신 정책
- 갱신된 인증서가 데이터 플레인에 반영되는 시점. Key Vault 참조 방식은 즉시가 아니라 폴링 주기에 달려 있다
- 실패했을 때 어디를 보는가. 각 경로의 상태 리소스와 로그 위치

### Lab 04. 장애 재현

5장의 사례를 재현 가능한 형태로 만든다.

- 중간 CA를 뺀 `Secret`을 구성하고, 클라이언트별로 결과가 갈리는 것을 확인한다. AIA로 보완하는 클라이언트와 그렇지 않은 클라이언트
- `Secret`을 갱신한 뒤 파드를 재시작하지 않고, 애플리케이션이 옛 인증서를 계속 서빙하는 상태를 만든다. Ingress Controller처럼 리로드하는 구성과 대비한다
- 만료 임박 인증서로 교체해 감시 지표가 어떻게 보이는지 확인한다

### Lab 05. 클라이언트 인증서 검증 (선택)

지금까지는 서버만 인증했다. 양방향으로 확장했을 때 무엇이 추가되는지 본다.

- `FrontendTLSPolicy`로 클라이언트 인증서 검증 구성 (AGC)
- 유효하지 않은 클라이언트 인증서가 백엔드로 전달되지 않는지 확인
- 인증서의 EKU가 `clientAuth`여야 하는 이유 (2-2)
- 클라이언트 인증서의 발급과 갱신은 누가 하는가 → [mtls](../mtls/README.md) 세션으로 연결

## 다음 단계

- 실습 대상 환경 확정 (기존 AGC 재사용 / NGINX Ingress 신규 구성)
- Lab 03에서 다룰 주입 경로를 셋 다 할지, 두 개로 줄일지 결정
- 도메인과 Azure DNS 존 정보 확정
