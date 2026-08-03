# 2. SPIFFE와 SPIRE

[인증서 세션](../certificate/README.md)은 **서버 인증서**를 다뤄다. 도메인 이름이 있고, 공인 CA가 그 이름의 통제권을 확인하고, 클라이언트가 신뢰 저장소를 기준으로 검증하는 구조다.

이 장은 다른 문제를 다룬다. 워크로드끼리 서로를 인증해야 할 때, 즉 **도메인 이름이 식별자로 적합하지 않은 상황**에서의 인증서다.

## 2-1. 등장 배경

### 워크로드에는 안정적인 이름이 없다

클러스터 안의 워크로드는 IP가 계속 바뀌고, 파드는 수시로 생성·삭제되며, 노드도 교체된다. 서버 인증서 모델이 전제하는 "고정된 이름"이 성립하지 않는다.

Service 이름을 쓸 수는 있지만, 그것은 위치를 가리키는 이름이지 "누구인가"를 가리키는 이름이 아니다. 같은 Service 뒤에 다른 워크로드가 붙어도 이름은 그대로다.

### 자격 증명을 배포하는 문제

워크로드에 인증서나 키를 넣어주려면 그 워크로드를 먼저 인증해야 한다. 그런데 인증하려면 자격 증명이 필요하다. 부트스트랩 단계에서 순환이 생긴다.

실무에서는 보통 이 순환을 "장기 자격 증명을 이미지나 매니페스트에 넣는다"로 끓는다. 인증서 세션 5-1의 Ericsson 사례가 그 결과 중 하나다. 배포된 자격 증명은 수명이 길고, 어디에 몇 개가 있는지 추적되지 않으며, 유출돼도 감지되지 않는다.

### 신뢰 경계가 네트워크에서 워크로드로 이동했다

과거에는 네트워크 경계 안쪽을 신뢰했다. 같은 VPC, 같은 서브넷이면 통과였다. 멀티 클러스터·멀티 클라우드·하이브리드 구성에서는 그 경계가 의미를 잃는다. 신뢰의 단위를 네트워크 위치가 아니라 워크로드 자체로 옮겨야 한다.

SPIFFE는 이 셋을 함께 다루기 위해 나왔다.

## 2-2. SPIFFE

**S**ecure **P**roduction **I**dentity **F**ramework **F**or **E**veryone. 구현체가 아니라 **명세**다. CNCF Graduated 프로젝트다.

세 가지를 정의한다.

### SPIFFE ID

워크로드의 식별자다. URI 형식이다.

```
spiffe://<trust-domain>/<workload-path>

spiffe://example.org/ns/payment/sa/api-server
spiffe://prod.acme.com/frontend
```

- **trust domain**: 하나의 신뢰 루트가 관할하는 범위. 보통 조직이나 환경 단위
- **path**: 그 안에서 워크로드를 구분하는 경로. 네임스페이스나 서비스 어카운트를 반영하는 경우가 많다

도메인 이름과 달리 DNS에 존재할 필요가 없고, 위치가 아니라 정체성을 가리킨다.

### SVID

SPIFFE Verifiable Identity Document. SPIFFE ID를 담은 검증 가능한 문서다. 두 형식이 있다.

| 형식 | 내용 | 용도 |
|---|---|---|
| X.509-SVID | X.509 인증서. SPIFFE ID가 **SAN의 URI 항목**에 들어간다 | mTLS |
| JWT-SVID | JWT. SPIFFE ID가 `sub` 클레임에 들어간다 | L7 인증, mTLS가 불가능한 경로 |

X.509-SVID는 인증서 세션 2장에서 본 것과 같은 X.509 인증서다. 다른 점은 식별자가 DNS 이름이 아니라 URI라는 것, 그리고 수명이 매우 짧다는 것이다. 기본값은 시간 단위이고 자동으로 갱신된다.

### Workload API

워크로드가 자신의 SVID를 받아오는 인터페이스다. 로컬 소켓(유닉스 도메인 소켓)으로 노출된다.

핵심은 **워크로드가 아무 자격 증명도 제시하지 않는다**는 점이다. 소켓에 연결하기만 하면 된다. 상대편이 호출자의 프로세스 정보를 커널에서 직접 확인해 신원을 판정한다. 2-1에서 말한 부트스트랩 순환을 이 방식으로 끓는다.

또한 이 API는 SVID를 스트리밍으로 밀어준다. 갱신된 SVID가 만료 전에 자동으로 전달되므로, 애플리케이션은 갱신 로직을 직접 구현하지 않는다. 인증서 세션 1-5에서 본 "갱신된 `Secret`을 앱이 다시 읽게 만드는 문제"가 여기서는 API 계약에 포함되어 있다.

## 2-3. SPIRE

SPIFFE의 레퍼런스 구현이다. 역시 CNCF Graduated다. 두 구성 요소로 이루어진다.

| 구성 요소 | 역할 |
|---|---|
| SPIRE Server | trust domain의 CA. 등록 항목(registration entry)을 관리하고 SVID를 서명한다 |
| SPIRE Agent | 노드마다 하나. Workload API를 노출하고, 워크로드를 판정해 SVID를 전달한다 |

신원 판정은 두 단계다.

### 노드 인증 (Node Attestation)

Agent가 Server에게 "나는 어느 노드인가"를 증명한다. 사람이 넣어준 자격 증명이 아니라, 플랫폼이 제공하는 증거를 쓴다.

- Azure: 관리 ID 토큰
- AWS: 인스턴스 아이덴티티 문서
- Kubernetes: 프로젝티드 서비스 어카운트 토큰
- 하드웨어: TPM

### 워크로드 인증 (Workload Attestation)

Agent가 소켓에 연결한 프로세스를 판정한다. 커널에서 얻은 PID를 기준으로 그 프로세스의 속성을 조회한다.

- Kubernetes: 네임스페이스, 서비스 어카운트, 파드 레이블, 컨테이너 이미지
- 유닉스: UID, GID, 실행 파일 경로

이 속성들이 Server에 등록된 항목의 선택자와 일치하면 해당 SPIFFE ID의 SVID를 발급한다.

두 단계 모두 "이미 그 자리에 존재한다는 사실"을 증거로 쓴다. 별도로 배포한 비밀에 의존하지 않는다.

### 페더레이션

trust domain이 다르면 서로의 SVID를 검증할 수 없다. SPIRE는 trust bundle을 교환해 다른 trust domain의 SVID를 검증할 수 있게 한다. 클러스터 간, 조직 간 mTLS가 여기에 해당한다.

## 2-4. cert-manager와의 관계

같은 X.509를 다루지만 해결하는 문제가 다르다.

| | cert-manager | SPIFFE / SPIRE |
|---|---|---|
| 식별자 | DNS 이름 | SPIFFE ID (URI) |
| 검증 대상 | 도메인 통제권 | 워크로드의 실행 컨텍스트 |
| 신뢰 근거 | 공인 CA와 브라우저 신뢰 저장소 | trust domain 내부의 CA |
| 주 용도 | 외부 클라이언트 → 서비스 (단방향) | 워크로드 ↔ 워크로드 (양방향) |
| 전달 경로 | `Secret` → 볼륨 또는 리스너 | Workload API |
| 수명 | 일 단위 이상 | 시간 단위 이하 |
| 갱신 반영 | 소비자가 다시 읽어야 한다 (인증서 세션 1-5) | API가 밀어준다 |

배타적이지 않다. 실제 구성에서는 **외부 접점은 cert-manager + 공인 CA, 내부 워크로드 간은 SPIFFE**로 나누는 형태가 일반적이다.

두 세계를 잇는 지점도 있다. cert-manager의 `csi-driver-spiffe`는 SPIFFE 형식의 SVID를 cert-manager의 발급자로부터 받아 CSI 볼륨으로 전달한다. SPIRE 없이 cert-manager 위에서 SPIFFE ID 기반 mTLS를 구성하는 경로다.

서비스 메시도 이 모델을 쓴다. Istio는 워크로드 신원을 SPIFFE ID 형식으로 표현하고, 사이드카가 짧은 수명의 인증서를 자동으로 받아 mTLS를 수립한다. 3장에서 다룬다.

## 2-5. 도입 판단

적합한 경우.

- 여러 클러스터나 여러 클라우드에 걸친 워크로드가 서로 인증해야 한다
- 쿠버네티스 밖(VM, 베어메탈)까지 같은 신원 체계로 묶어야 한다
- 장기 자격 증명을 이미지나 매니페스트에서 제거해야 한다
- 규제로 인해 워크로드 간 통신에 상호 인증이 요구된다

과한 경우.

- 단일 클러스터이고 서비스 메시를 이미 쓰고 있다. 메시가 제공하는 신원으로 충분하다
- 워크로드 간 인증이 요구되지 않고 외부 접점만 TLS면 된다
- 운영 인력이 SPIRE Server의 CA 운영과 백업, 등록 항목 관리를 감당하기 어렵다

SPIRE Server가 trust domain의 단일 신뢰 루트이므로, 이 구성 요소의 가용성과 키 보호가 곳 전체 신뢰의 조건이 된다. 인증서 세션 2-1에서 본 Root CA 격리 논리가 여기에도 적용된다.

---

## 참고자료

**SPIFFE**

- [SPIFFE](https://spiffe.io/)
- [SPIFFE Concepts](https://spiffe.io/docs/latest/spiffe-about/spiffe-concepts/)
- [SPIFFE ID 명세](https://github.com/spiffe/spiffe/blob/main/standards/SPIFFE-ID.md)
- [X.509-SVID 명세](https://github.com/spiffe/spiffe/blob/main/standards/X509-SVID.md)
- [Workload API 명세](https://github.com/spiffe/spiffe/blob/main/standards/SPIFFE_Workload_API.md)
- [CNCF SPIFFE 프로젝트 페이지](https://www.cncf.io/projects/spiffe/)

**SPIRE**

- [SPIRE 문서](https://spiffe.io/docs/latest/spire-about/)
- [Node Attestation](https://spiffe.io/docs/latest/spire-about/spire-concepts/#node-attestation)
- [Workload Attestation](https://spiffe.io/docs/latest/spire-about/spire-concepts/#workload-attestation)
- [spiffe/spire](https://github.com/spiffe/spire)

**연계**

- [cert-manager csi-driver-spiffe](https://cert-manager.io/docs/usage/csi-driver-spiffe/)
- [Istio Security — Identity](https://istio.io/latest/docs/concepts/security/)
