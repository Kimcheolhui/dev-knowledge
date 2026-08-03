# 4. Let's Encrypt와 nip.io

앞에서 인증서가 무엇이고 어떻게 발급되는지를 봤다. 이 장은 그 구조 안에서 실제로 쓰는 두 서비스가 어느 자리를 차지하는지 다룬다.

## 4-1. Let's Encrypt

### 무엇인가

비영리 인증기관이다. ISRG(Internet Security Research Group)라는 재단이 운영하고, Mozilla·EFF·Akamai·Cisco 등이 후원한다. 2015년 베타를 시작해 2016년 정식 서비스에 들어갔다.

2장의 구분으로 보면 **공인 CA**다. Root 인증서(ISRG Root X1)가 브라우저와 OS의 신뢰 저장소에 등재되어 있어, 여기서 발급받은 인증서는 별도 설정 없이 신뢰된다.

### 등장 배경

2010년대 초까지 HTTPS 적용률은 낮았다. 기술이 없어서가 아니라 절차가 부담스러웠기 때문이다.

- **비용**: 인증서는 유료였다. 도메인 하나에 연 단위 비용이 들었고, 와일드카드는 더 비쌌다
- **수동 절차**: CSR을 만들어 제출하고, 소유권 확인 메일을 받고, 발급된 파일을 내려받아 서버에 올리는 과정을 사람이 했다
- **갱신도 수동**: 1~2년마다 같은 과정을 반복해야 했다

여기에 2013년 대규모 감청 폭로 이후 "전 구간 암호화"가 기본이어야 한다는 인식이 더해졌다. 그러나 비용과 절차가 남아 있는 한 개인 사이트나 소규모 서비스는 넘어오기 어려웠다. Let's Encrypt는 이 두 장벽을 동시에 없애려고 만들어졌다.

순서로 보면 Let's Encrypt가 먼저고(2015), 브라우저가 HTTP 사이트에 "안전하지 않음" 표시를 붙이기 시작한 것은 그 뒤다(Chrome은 2017년 입력 필드부터, 2018년 모든 HTTP 페이지로 확대). 무료・자동 발급 수단이 먼저 생기면서 전면 HTTPS를 요구할 수 있는 조건이 만들어졌다.

### 무엇을 했는가

**1. 인증서를 무료로 발급했다**

비용 장벽이 사라졌다. 다만 이것만으로는 부족했다. 여전히 사람이 붙어야 하는 절차가 남아 있었기 때문이다.

**2. 발급 절차를 API로 만들었다**

더 중요한 쪽은 이것이다. Let's Encrypt는 ACME(Automatic Certificate Management Environment)라는 프로토콜을 만들어, 사람이 개입하던 자리를 전부 프로그램이 처리하도록 바꿨다.

1장에서 본 흐름이 바로 이것이다. 계정 등록, 발급 주문, 도메인 소유권 증명, CSR 제출, 인증서 수령이 모두 HTTP API 호출이다. cert-manager 같은 도구가 존재할 수 있는 이유가 여기 있다.

ACME는 이후 RFC 8555로 표준화됐고, 다른 상용 CA들도 채택했다. 즉 Let's Encrypt가 만든 것은 무료 인증서만이 아니라 **인증서 발급의 자동화 표준**이다.

**3. 수명을 90일로 정했다**

일부러 짧게 잡았다. 수동으로는 감당할 수 없는 주기로 만들어 자동 갱신을 강제한 것이다. 자동화가 제대로 동작하는지 90일마다 확인되는 구조이기도 하다.

2장에서 본 폐기 메커니즘의 한계와도 이어진다. 폐기가 잘 동작하지 않으니 수명을 짧게 가져가는 방향인데, Let's Encrypt는 그 방향을 처음부터 채택한 셈이다. 2025년부터는 6일짜리 단기 인증서와 IP 주소 인증서도 선택할 수 있다.

### 무엇을 보증하는가

Let's Encrypt는 **도메인 통제권만** 확인한다(DV, Domain Validation). 신청자가 어떤 조직인지, 믿을 만한 곳인지는 보지 않는다.

그래서 피싱 사이트도 Let's Encrypt 인증서를 받을 수 있다는 지적이 있다. 다만 이는 DV 인증서 전반의 성격이다. 인증서가 보증하는 것은 "지금 연결된 상대가 이 도메인의 통제권자가 맞다"이지 "이 사이트가 정직하다"가 아니다.

조직 실체를 확인하는 OV·EV 인증서는 Let's Encrypt가 발급하지 않는다. 서류 심사가 필요해 자동화할 수 없기 때문이다.

### 이 문서에서의 위치

| 장 | 대응 |
|---|---|
| 1장 | `ClusterIssuer`의 `spec.acme.server`가 가리키는 곳 |
| 1장 | HTTP-01 / DNS-01 검증을 요구하는 주체 |
| 2장 | 신뢰 체인의 중간 CA(R11 등)와 Root(ISRG Root X1) |

운영에 적용하기 전에는 staging 엔드포인트를 먼저 쓴다. 발급 절차는 동일하지만 신뢰되지 않는 테스트용 CA에서 서명하고, 발급 횟수 제한이 느슨하다. 실제 서비스용 엔드포인트에는 도메인당 발급 횟수 제한이 있어서, 설정을 시행착오로 맞추다 보면 한도에 걸릴 수 있다.

## 4-2. nip.io

### 무엇인가

와일드카드 DNS 서비스다. `<IP>.nip.io` 형태의 이름을 질의하면 그 IP를 그대로 응답한다.

```
10.0.0.1.nip.io        → 10.0.0.1
app.10.0.0.1.nip.io    → 10.0.0.1
api.10.0.0.1.nip.io    → 10.0.0.1
```

등록도 설정도 없다. 이름 안에 IP가 들어 있고 DNS 서버가 그것을 파싱해서 돌려준다.

### 등장 배경

테스트나 실습 환경에서는 도메인이 필요한데, 도메인을 확보하는 일이 매번 부담이다.

- 도메인을 사려면 비용과 시간이 든다. 잠깐 쓰고 버릴 환경에는 과하다
- `hosts` 파일을 고치는 방법은 그 장비에서만 동작한다. 다른 사람과 공유할 수 없고, 와일드카드도 안 된다
- 무엇보다 **공인 인증서를 받으려면 외부에서 조회되는 도메인이어야 한다.** 1장에서 본 대로 CA가 검증할 수 있어야 하기 때문이다

nip.io는 이 문제를 "이름 안에 IP를 넣는다"는 방식으로 우회한다.

### 어떤 역할을 하는가

**공인 인증서 발급을 가능하게 한다**

`nip.io`는 실제로 등록된 퍼블릭 도메인이고 외부에서 조회된다. 따라서 Let's Encrypt가 이 이름을 검증할 수 있다. 퍼블릭 IP 하나만 있으면 도메인 등록 없이 공인 인증서를 붙일 수 있다.

**호스트 기반 라우팅을 테스트할 수 있다**

앞에 아무 이름이나 붙일 수 있으므로 `app.<IP>.nip.io`, `api.<IP>.nip.io` 같은 이름을 얼마든지 만들 수 있다. Ingress의 호스트 규칙이나 3-2에서 본 SNI 기반 인증서 선택을 하나의 IP에서 확인할 수 있다.

### 한계

- 공용 서비스다. 가용성과 응답 속도가 남의 인프라에 달려 있다
- 이름에 IP가 노출되고 누구나 같은 이름을 조회할 수 있다
- 와일드카드 인증서는 발급할 수 없다. `*.nip.io`에 대한 DNS 레코드를 만들 권한이 없기 때문이다. DNS-01 검증도 같은 이유로 불가능하다
- 운영 환경에는 쓰지 않는다. 실습과 검증 용도에 한정한다

같은 방식의 서비스로 `sslip.io`가 있다. 동작은 동일하고, 한쪽이 응답하지 않을 때 대안으로 쓴다.

## 4-3. 둘을 합치면

이 둘의 조합이 실습 환경 구성의 최소 조건을 만든다.

1. 퍼블릭 IP를 가진 Ingress가 하나 있다
2. `app.<IP>.nip.io`를 도메인으로 쓴다. DNS 설정은 필요 없다
3. cert-manager가 Let's Encrypt에 인증서를 요청한다
4. HTTP-01 검증이 그 IP의 80 포트로 들어와 통과한다
5. 공인 인증서가 발급되고 브라우저에 자물쇠가 뜬다

도메인 구매, DNS 설정, 인증서 비용 중 어느 것도 필요하지 않다.

---

## 참고자료

**Let's Encrypt**

- [About Let's Encrypt](https://letsencrypt.org/about/) — ISRG와 후원 구조
- [How It Works](https://letsencrypt.org/how-it-works/) — 도메인 검증과 발급 흐름
- [Challenge Types](https://letsencrypt.org/docs/challenge-types/) — HTTP-01, DNS-01, TLS-ALPN-01
- [Rate Limits](https://letsencrypt.org/docs/rate-limits/)
- [Staging Environment](https://letsencrypt.org/docs/staging-environment/)
- [Chain of Trust](https://letsencrypt.org/certificates/)
- [Let's Encrypt Stats](https://letsencrypt.org/stats/) — 발급량과 HTTPS 적용률 추이
- [New: Six-day and IP Address Certificate Options in 2025](https://letsencrypt.org/2025/01/16/6-day-and-ip-certs/)
- [RFC 8555: Automatic Certificate Management Environment (ACME)](https://datatracker.ietf.org/doc/html/rfc8555)

**와일드카드 DNS 서비스**

- [nip.io](https://nip.io/)
- [sslip.io](https://sslip.io/) — 같은 방식의 대체 서비스
