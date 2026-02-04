# MySQL Replication Lag 모니터링

## 개요

Primary-Secondary(Master-Slave) 구조의 MySQL 환경에서 Primary DB에 대량 INSERT 작업이 발생하면서 DB에 문제가 발생한 이슈를 기반으로 정리한 내용임. Replication lag가 무엇인지, 왜 발생하는지, 어떻게 측정하는지, 그리고 실제 운영 환경에서 어떤 메트릭 변화 패턴이 나타나는지를 다룸.

## Replication Lag란

Replication Lag는 Primary(또는 Source) MySQL에서 발생한 변경(Write)이 Replica(또는 Slave) MySQL에 얼마나 늦게 반영되고 있는지의 시간 차이를 의미함.

즉, "Primary DB에는 이미 반영된 데이터가 Replica DB에서는 아직 보이지 않는 상태가 얼마나 지속되는가"를 나타내는 지표임.

## MySQL Replication 구조와 Lag 발생 지점

MySQL Replication은 크게 3단계로 동작함:

1. Primary가 binlog에 변경사항 기록
2. Replica의 IO Thread가 binlog를 읽어서 relay log에 저장
3. Replica의 SQL Thread가 relay log를 읽어서 실제 DB에 반영

Replication Lag는 거의 항상 **3번 단계(SQL Thread)**에서 발생함. relay log에는 이미 쌓여있는데, Replica가 그걸 "처리하지 못하고 있는 상태"가 Lag임.

## Replication Lag 발생 원인

대표 원인은 다음과 같음:

| 원인 | 설명 |
|------|------|
| Replica CPU/IO 부족 | SQL Thread가 쿼리를 처리 못함 |
| 긴 트랜잭션 | Primary에서 대용량 UPDATE/DELETE 발생 |
| 인덱스 미스 | Replica에서 쿼리 재실행이 느림 |
| Lock 경합 | Replica 내부에서 lock 대기 |
| 네트워크 지연 | IO Thread가 binlog를 늦게 가져옴 (상대적으로 드묾) |
| Single-thread apply | 기본 MySQL은 apply가 단일 스레드 |

특히 대용량 UPDATE, ALTER TABLE, bulk insert가 있으면 Lag가 폭발적으로 증가함.

## Replication Lag가 위험한 이유

Replica는 보통 다음 용도로 사용됨:

- Read 분산
- Analytics
- 백업
- Failover

Lag가 커지면 다음 문제가 발생함:

- 사용자는 방금 쓴 데이터가 안 보임
- API에서 read-after-write consistency가 깨짐
- 장애 시 Replica로 failover 했더니 데이터가 과거 시점

즉, 데이터 정합성 문제로 이어짐.

## Lag 측정 방법

가장 기본적인 지표:

```sql
SHOW SLAVE STATUS\G
```

여기서 핵심 필드:

```
Seconds_Behind_Master: 37
```

의미: Primary의 마지막 binlog 이벤트 시점과 Replica가 마지막으로 적용한 시점의 차이 (초)

37이면, Replica는 37초 과거 데이터를 보고 있는 것임.

### 중요한 포인트 (많이 오해하는 부분)

Replication Lag는 "binlog를 못 받아오는 것"이 아니라 "받아왔지만 적용을 못하는 것"이 대부분임.

즉, 네트워크 문제가 아니라 Replica의 처리 성능 문제임.

## Seconds_Behind_Master 정확한 정의

많은 사람들이 오해하는 부분인데, Replication Lag 측정 기준은 다음과 같음:

```
Replication Lag = 
(Primary의 최신 binlog event의 timestamp) 
- 
(Replica가 마지막으로 실행한 binlog event의 timestamp)
```

**둘 다 Primary 기준 시간임**. Replica가 "언제 실행했는지"는 계산에 전혀 들어가지 않음.

그래서 이런 이상한 현상이 생김:

- Replica가 지금 열심히 INSERT를 실행 중인데도 Lag는 계속 증가할 수 있음
- 왜냐하면 Replica는 아직 timestamp 15:36이 찍힌 이벤트를 처리 중인데, Primary의 최신 binlog timestamp는 이미 15:43이기 때문

Replica가 몇 시에 실행했는지는 중요하지 않음. 기준이 Primary 시간이기 때문임.

## binlog란

MySQL의 binlog (Binary Log)는 Primary에서 발생한 모든 "데이터 변경 이벤트"를 순서대로 기록하는 복제/복구용 로그 파일임.

### binlog에 기록되는 것

- INSERT, UPDATE, DELETE
- CREATE/ALTER/DROP TABLE
- 트랜잭션 커밋 순서
- 각 이벤트의 Primary 기록 시각(timestamp)

반대로, SELECT 같은 읽기 쿼리는 기록되지 않음.

### binlog의 핵심 역할

1. **Replication의 소스**: Replica는 이 binlog를 읽어 동일한 변경을 재현
2. **시점 복구 (PITR)**: 백업 시점 이후의 변경을 binlog로 재적용
3. **변경 이력 보존**: 데이터가 "어떤 순서로 바뀌었는지"의 진실한 기록

### Replication에서의 흐름

1. Primary가 변경 발생 → binlog에 기록
2. Replica IO Thread가 binlog를 읽어 → relay log에 저장
3. Replica SQL Thread가 relay log를 실행 → 실제 데이터 반영

Replication의 출발점이 binlog임.

### binlog 파일 구조 (개념)

binlog는 사람이 바로 읽는 텍스트가 아니라 바이너리 포맷임. 하지만 풀어보면 이런 정보가 들어 있음:

```
# at 12345
# 2026-02-04 15:36:12 server id 1 end_log_pos 23456
INSERT INTO orders VALUES(...)
```

여기서 중요한 것:

- timestamp (15:36:12) → Replication Lag 계산의 기준
- server id, log position → 순서 보장

### binlog 기록 방식 (포맷)

MySQL에는 3가지 binlog 포맷이 있음:

| 포맷 | 기록 방식 | 특징 |
|------|-----------|------|
| STATEMENT | 실행된 SQL 그대로 | 재현성 문제 가능 |
| ROW | 변경된 row 데이터 | 가장 안전, 가장 많이 사용 |
| MIXED | 상황에 따라 혼합 | 과도기적 방식 |

실무/클라우드 환경은 거의 ROW를 사용함.

## relay log와 실제 INSERT 실행

많은 분들이 relay log에 INSERT가 쌓이는지, 그리고 Datadog에서 그게 어떻게 보이는지를 혼동함.

### 핵심 개념

Datadog에서는 "Replica에서 실제로 INSERT가 수행된 흔적"이 보임. relay log는 단순 로그 파일일 뿐이고, 메트릭에 잡히는 것은 SQL Thread가 relay log를 실행하면서 발생한 실제 쿼리 실행임.

### 실제로 일어나는 일

순서를 정확히 보면:

1. Primary: INSERT 발생
2. binlog에 INSERT 이벤트 기록
3. Replica IO Thread: binlog를 읽어서 relay log에 저장 (아직 DB에는 반영 안 됨)
4. Replica SQL Thread: relay log를 읽어서 진짜 INSERT 실행

**4번이 매우 중요함. Replica는 INSERT 문을 실제로 실행함.** 그냥 "데이터 파일을 복사"하는 게 아님.

### Datadog에 보이는 메트릭

Datadog의 MySQL integration은 이런 메트릭을 수집함:

- `mysql.performance.queries`
- `mysql.performance.com_insert`
- `mysql.performance.com_update`
- `mysql.performance.com_delete`
- `mysql.replication.seconds_behind_master`

여기서 핵심: Replica SQL Thread가 relay log를 처리하면서 실제로 INSERT를 수행하기 때문에 `com_insert`가 Replica에서도 증가함.

즉, **Replica에도 INSERT QPS 스파이크가 보임.**

### 실제 현상 (운영에서 자주 보는 패턴)

상황: Master에서 100만 row INSERT 배치 실행, Replica가 2분 lag 발생

Datadog에서 보이는 패턴:

| 시간 | Master | Replica |
|------|--------|---------|
| 10:00 | INSERT QPS 폭증 | 조용함 |
| 10:01 | 정상 | 조용함 |
| 10:02 | 정상 | INSERT QPS 폭증 |
| 10:03 | 정상 | INSERT QPS 폭증 |
| 10:04 | 정상 | 정상 |

이게 Replica가 밀린 걸 따라잡는 모습임.

### relay log는 INSERT가 아닌가?

relay log는 이런 형태임:

```sql
INSERT INTO orders VALUES(...)
INSERT INTO orders VALUES(...)
INSERT INTO orders VALUES(...)
```

그냥 로그 파일일 뿐임. 하지만 SQL Thread가 이걸 읽으면 Replica에서 진짜 INSERT 쿼리 실행이 일어남. 그래서 Datadog에는 쿼리 실행으로 보임.

### 매우 중요한 관찰 포인트

그래서 실무에서 이런 현상을 보면 바로 알 수 있음: "아, 이 Replica 지금 lag 따라잡고 있구나"

왜냐하면:

1. Replica에서 갑자기 INSERT/UPDATE QPS가 급증
2. CPU/IO 튐
3. Seconds_Behind_Master 급격히 감소

이 3개가 동시에 발생함. 이건 relay log를 "소화 중"이라는 뜻임.

## 실제 사례 분석

### 타임라인

- Master 대량 INSERT: 15:36~43
- Replica 1&2 INSERT 발생: 15:37~48
- Replication lag:
  - Replica 1: 15:37~50 & 15:50~17:02 (15:50~16:56에 점진적으로 상승하면서 16:56에 peak를 찍고 내려옴)
  - Replica 2: 15:36~15:49 & 15:49~17:01 (16:53에 peak) & 17:01~17:08 (17:06 peak)

### 시간 순서대로 실제 내부에서 일어난 일

#### 1) 15:36 ~ 15:43 — Master 대량 INSERT

이 시간 동안 Primary에서는 binlog가 폭발적으로 생성됨:

- binlog에 수십/수백만 INSERT 이벤트 기록
- Replica IO Thread는 이걸 거의 실시간으로 relay log에 받아옴
- 하지만 SQL Thread는 처리 못 하고 밀리기 시작
- 즉, 이 시점부터 Lag가 생성됨

#### 2) 15:37 ~ 15:48 — Replica에서 INSERT가 보이기 시작

이게 매우 중요한 신호임. 이때 Datadog에서 Replica의 INSERT가 보였다는 건 SQL Thread가 relay log를 읽기 시작했다는 의미임.

하지만 Master 속도를 못 따라가므로:

```
relay log 적재 속도 > SQL Thread 처리 속도
```

Lag 계속 증가함.

#### 3) 왜 replication lag 그래프가 "점진 상승 → 피크 → 하락" 형태인가

이 모양은 정확히 다음 상황을 의미함:

**Phase A — Lag 증가 구간 (15:50까지)**

- Master 작업은 이미 끝남 (15:43)
- 하지만 relay log에는 아직 수많은 INSERT가 쌓여 있음
- SQL Thread는 계속 실행 중인데 backlog가 더 많음
- 그래서 lag는 계속 증가
- "처리 중인데도 lag가 늘어나는" 이상한 구간 - 이게 정상임

**Phase B — Peak (Replica1: 16:56, Replica2: 16:53)**

이 시점이 의미하는 바:

- relay log backlog의 마지막 지점에 도달한 시점
- 즉, 이제 더 이상 따라잡을 대상이 거의 없음
- 이 시점이 가장 과거 시점과의 차이가 최대
- 그래서 lag가 최고점

**Phase C — Lag 급감 구간**

여기서부터는:

```
SQL Thread 처리 속도 > 남은 backlog
```

- lag가 빠르게 줄어듦
- Datadog에서 INSERT QPS가 계속 높게 보였을 것
- 이게 "따라잡는 구간"임

#### 4) Replica 2가 피크가 두 번 찍힌 이유

- 15:49~17:01 (16:53 peak)
- 17:01~17:08 (17:06 peak)

이건 아주 전형적인 현상임. 의미:

- relay log 안에 "무거운 쿼리"가 중간에 하나 껴있음
- 예를 들어: 인덱스 없는 대량 INSERT, 큰 트랜잭션, FK/Index 비용 큰 테이블
- SQL Thread는 단일 스레드이기 때문에 그 한 쿼리에서 수 분 멈춰있음
- 그래서 lag가 다시 튐

Replica1에는 이 구간이 덜했고, Replica2에는 더 심했던 것. 이건 Replica 스펙 차이 / IO 차이 / 인덱스 캐시 상태 차이 때문임.

### 이 타임라인으로 알 수 있는 것

이 데이터만으로 다음을 확정할 수 있음:

- 네트워크 문제 아님 (IO Thread 정상)
- relay log는 제때 받아옴
- Replica SQL apply 병목
- Single-thread apply의 한계
- 중간에 매우 무거운 statement 존재
- Replica1, 2의 디스크/CPU/버퍼캐시 상태가 달랐음

이건 거의 교과서적인 replication lag 케이스임.

### 한 줄 요약

Replica는 relay log를 받아오는 데 문제가 없었고, SQL Thread가 relay log를 실제 INSERT로 실행하느라 1시간 넘게 밀렸다가 16:53~16:56 시점에 backlog 끝에 도달하면서 lag가 피크를 찍고 급격히 줄어든 상황임.

## Master 대량 INSERT 시 메트릭 변화 순서

Master 1대 + Replica 2대(비동기 복제, 일반적인 MySQL replication 가정)에서 Master에 대량 INSERT 배치가 들어왔을 때 Datadog에서 흔히 보이는 메트릭들의 변화 순서와 상호작용을 시간 흐름대로 정리함.

### Phase A — Master에서 대량 INSERT 시작 직후 (T0 ~ T0+수초~수십초)

#### Master

**INSERT(QPS / Com_insert)**
- 즉시 급증함
- 배치가 클수록 높은 plateau(평평하게 높음) 또는 톱니(버스트 반복) 형태

**CPU**
- 대개 급상승함
- row 기반 binlog/인덱스/제약조건/트랜잭션 커밋 비용이 함께 들어가서 CPU를 밀어 올림
- 단, 스토리지 IO가 병목이면 CPU가 100%까지 안 가고 "중간 수준"에서 정체될 수도 있음(대신 IO wait이 늘어남)

**Memory**
- 형태가 두 가지로 갈림:
  - 버퍼 풀(InnoDB buffer pool)이 충분하면: 큰 변화 없이 완만한 상승 또는 안정
  - 버퍼 풀이 작거나 워킹셋이 큼: dirty page 증가/flush 압력으로 성능이 흔들리며, 메모리 자체는 크게 안 늘어도 "효율"이 떨어짐

**Replication log(=lag)**
- Master에는 보통 이 메트릭이 의미가 없거나 0으로 보임

**Aborted connections**
- 대량 INSERT 자체가 "연결을 끊게 만드는" 직접 원인은 아님
- 다만 아래 조건이면 Master에서 증가할 수 있음:
  - 쿼리가 느려져서 클라이언트 타임아웃/프록시 타임아웃 발생
  - connection backlog가 차서 handshake 실패
  - max_connections에 근접/초과
  - 스레드/메모리 압박으로 accept 지연
- 즉, INSERT 폭증 → 응답 지연 증가 → 타임아웃 증가 → aborted_connection 증가 순서로 "2차적으로" 따라옴

### Phase B — Replica들이 "따라가기 시작하지만 점점 밀리는" 구간 (T0+수초 ~ 배치 종료 시점 근처)

#### Replica 1 / Replica 2 공통

이 구간에서 중요한 포인트는 IO Thread(받기) vs SQL Thread(적용)임.

**INSERT(QPS / Com_insert)**
- Replica에서도 INSERT가 증가하기 시작함
- 왜냐하면 relay log를 SQL thread가 실제로 실행하면서 "진짜 INSERT"가 발생하기 때문
- 다만 Master의 INSERT 곡선과 동일한 시간대/동일한 모양이 아닐 수 있음
- Master가 15:36~15:43에 폭증, Replica는 15:37~15:48에 폭증 같은 식으로 "지연된 시작 + 더 길게 지속" 형태가 흔함

**CPU**
- Replica도 SQL thread가 relay log를 적용하면서 CPU가 증가함
- Replica는 보통 읽기 트래픽(서비스 read)도 같이 받는 경우가 많아, 읽기 부하 + apply 부하가 겹치면 더 쉽게 포화됨

**Memory**
- apply 과정에서 인덱스 갱신/페이지 변경이 많아져 buffer pool pressure가 늘 수 있음
- Master와 동일하게 "메모리 사용량" 자체보다 dirty pages 증가, flush lag, buffer pool miss가 더 본질적인 병목이 되는 경우가 많음

**Replication log(lag)**
- 이 구간에서 lag는 보통 상승함
- Primary는 계속 binlog timestamp를 최신으로 당기는데, Replica는 아직 과거 timestamp 이벤트를 적용 중이라 둘의 차이가 커지기 때문
- 특히 "열심히 적용은 하는데도 lag가 계속 증가"가 가능한 구간임

**Aborted connections**
- Replica에서 aborted connection이 늘 수 있는 대표 패턴:
  - Replica가 apply로 바빠져서 read 쿼리 응답이 느려짐 → 앱/프록시 타임아웃 증가
  - 커넥션 폭증 + thread 처리 지연 → handshake/authorization 지연

### Phase C — Master의 대량 INSERT가 끝난 직후 (배치 종료 직후 ~ 수 분)

#### Master

**INSERT**
- 급락해서 정상 수준으로 돌아옴(배치 종료)

**CPU**
- 보통 INSERT 종료와 거의 동시에 하락하지만, 디스크 flush/체크포인트 부담이 뒤늦게 남아 있으면 꼬리(tail)가 길어질 수 있음

**Memory**
- 큰 변화 없이 안정화되는 경우가 많음

**Aborted connections**
- 배치 동안 타임아웃이 있었다면, 종료 후 진정되는 경향

#### Replica 1 / Replica 2

**INSERT**
- 계속 높게 유지되거나 오히려 더 올라갈 수 있음
- Master가 멈췄으니 "새로 쌓이는 양"은 줄지만, backlog(밀린 이벤트)가 많으면 Replica는 한동안 계속 바쁨

**CPU**
- Replica에서 SQL apply가 본격적으로 catch-up(따라잡기) 하면서 CPU가 더 치솟는 경우가 흔함
- 이때 Replica별 차이가 두드러짐
- 디스크/캐시 상태/동시 read 부하에 따라 Replica1은 40분 만에 따라잡고 Replica2는 70분 걸리는 식으로 벌어질 수 있음

**Replication log(lag)**
- 여기서 가장 헷갈리는 그림이 나옴
- Master는 이미 끝났는데 lag는 한동안 계속 상승할 수 있음
- 이유: lag는 "현재 시각 대비 지연"이 아니라 "Primary binlog timestamp 기준으로 얼마나 과거 이벤트를 적용 중인지"라서, Replica가 아직 배치 초반(예: 15:36 timestamp) 이벤트를 처리 중인데 Primary 최신은 배치 끝(예: 15:43 timestamp)까지 가있으면 lag는 그 차이만큼 계속 커질 수 있음(피크 찍기 전까지)

**Aborted connections**
- 이 구간이 Replica에서 aborted connection이 더 잘 늘어나는 구간임
- 서비스가 Replica read를 치고 있는데 Replica는 apply로 CPU/IO를 소모하며 read latency가 튀고 타임아웃/커넥션 리셋이 발생하기 쉬움

### Phase D — Lag가 피크를 찍고 감소(따라잡기 구간)

#### Replica 1 / Replica 2

**Replication log(lag)**
- **피크(최고점)**는 보통 이런 의미임:
  - Replica가 아직 "가장 과거 timestamp 이벤트"를 처리 중인 시점이 마지막에 가까워지고, 그 순간 Primary 최신과의 차이가 최대가 된 상태
- 이후에는 backlog 끝을 향해 가면서 Replica가 최신 timestamp 이벤트들을 적용하게 되고 lag가 빠르게 감소함

**INSERT / CPU**
- 이때 Replica의 INSERT와 CPU는 보통 높은 상태로 유지되다가, backlog가 거의 소진되면 급격히 하락함
- Datadog에서 흔히 보는 그림:
  - lag: 내려감
  - replica insert: 높게 유지 → 어느 순간 툭 떨어짐
  - replica CPU: 높게 유지 → 함께 떨어짐

**Memory**
- flush 압력/dirty pages가 내려가면서 안정화됨

**Aborted connections**
- read latency가 안정되면 동반 감소함

### Phase E — 완전 정상화

- Replica lag는 0 또는 매우 낮은 값으로 수렴
- Replica insert/cpu는 평시 수준
- aborted connections도 평시 수준

### Replica1/Replica2가 서로 다르게 보이는 대표 이유

Replica2에서 피크가 두 번 찍히는 식의 패턴은 보통 아래 중 하나임:

- 중간에 매우 무거운 이벤트/트랜잭션이 끼어 있음(단일 스레드 apply가 해당 구간에서 오래 멈춤)
- Replica2가 해당 시점에 read 트래픽이 더 많음
- 디스크 IO/버퍼캐시 상태 차이(캐시 미스가 더 많이 나는 Replica가 더 느림)
- (설정) replica parallel apply(멀티스레드 적용) 여부 차이 또는 효율 차이

### 가장 흔한 "변화 순서"를 한 줄로 묶으면

Master INSERT 급증 → Master CPU 상승 → Replica INSERT/CPU가 지연되어 상승 → Replica lag 상승(때로는 Master 종료 후에도 계속) → Replica lag 피크 → Replica가 따라잡으며 lag 감소 → Replica INSERT/CPU 하락 → aborted connections(있다면) 전 과정에서 '지연/타임아웃'에 의해 후행적으로 증가했다가 안정화

## Storage IO와 Aborted Connection 지연 현상

### 관찰된 현상

Replica의 aborted connection과 storage_io_count, io_consumption_percent는 cpu_percent, replication_log보다 30분 정도 메트릭이 늦게 튐.

### 핵심 개념

CPU / replication lag는 "SQL Thread가 열심히 일하기 시작한 시점"을 보여주고, IO / aborted connection은 "그 작업의 누적 결과로 스토리지가 버티지 못하기 시작한 시점"을 보여줌.

그래서 항상 20~40분 정도 늦게 튐. 이건 이상한 게 아니라, 오히려 정상적인 순서임.

### 시간 순서로 내부에서 무슨 일이 벌어지는가

#### ① 먼저 튀는 것: CPU, INSERT, replication lag

이 시점은:

- Replica SQL Thread가 relay log를 읽어서 미친 듯이 INSERT를 실행하기 시작한 시점

특징:
- CPU 상승
- Replica INSERT QPS 상승
- replication lag 상승 (아직 과거 timestamp 처리 중이라)

이때는 스토리지가 아직 괜찮음. 왜냐하면:

**대부분의 작업이 아직 buffer pool (메모리) 안에서 처리되고 있기 때문임. 디스크는 거의 안 건드림.**

#### ② 20~40분 후에 튀는 것: storage_io_count, io_consumption_percent

여기서부터가 핵심임.

MySQL(InnoDB)은 INSERT를 하면:

1. 페이지를 buffer pool에서 수정 (메모리)
2. dirty page로 표시
3. 나중에 디스크로 flush

즉, 처음 20~40분 동안은 디스크가 아니라 메모리가 일을 하고 있었던 것임.

그러다가 어느 시점에:

- dirty page가 한계치에 도달
- checkpoint 압박
- background flush가 감당 못 함
- 강제 flush 발생

이 순간부터 디스크 IO가 폭발함. 그래서 storage_io_count, io_consumption_percent가 뒤늦게 폭증함.

#### ③ 그리고 그 다음에 튀는 것: aborted connections

이건 IO 폭발의 결과임.

디스크가 병목이 되면:

- 쿼리 latency 급증
- thread가 IO wait 상태로 오래 머묾
- 커넥션 응답 지연
- 클라이언트 / 프록시 타임아웃
- aborted connection 증가

즉, aborted connection은 CPU 때문이 아니라 디스크 flush 지옥 때문에 발생함. 그래서 항상 IO 튄 다음에 튐.

### 메트릭이 보이는 순서

| 순서 | 메트릭 | 의미 |
|------|--------|------|
| 1 | replica CPU, INSERT | SQL thread가 relay log 적용 시작 |
| 2 | replication lag 증가 | 아직 과거 이벤트 처리 중 |
| 3 | (30분 뒤) storage IO 폭증 | dirty page 한계치 도달, 강제 flush |
| 4 | (곧 이어서) aborted connections | IO wait으로 인한 응답 지연, 타임아웃 |

### 중요한 포인트

처음 20~40분 동안은 "메모리 기반 처리"임. 디스크는 아직 조용함.

그래서 이 구간에서는:

- CPU만 높음
- IO는 정상
- 성능도 비교적 괜찮음

하지만 메모리(buffer pool)의 dirty page가 한계치에 도달하는 순간, 모든 게 바뀜:

- 강제 flush 시작
- 디스크 IO 폭발
- 모든 쿼리가 느려짐
- connection timeout 증가

이게 "30분 뒤에 IO/aborted connection이 튀는" 이유임.

### 실무적 대응 방안

이 패턴을 알면 다음을 할 수 있음:

1. **초반 CPU 상승 시점에 경고 발생** → "곧 IO 폭발 올 것" 예측 가능
2. **buffer pool 크기 조정** → dirty page 한계치를 늦춤
3. **innodb_io_capacity 설정** → background flush를 더 적극적으로
4. **배치 작업 chunk 분할** → 한 번에 처리하는 양을 줄여서 dirty page 누적 방지

## 실무에서 Lag가 100% 터지는 패턴

다음 작업을 하면 거의 무조건 Lag 발생:

- ALTER TABLE
- 인덱스 없는 대량 UPDATE
- 수백만 row DELETE
- 배치 작업

그래서 실무에서는 이런 작업을 할 때:

- pt-online-schema-change
- gh-ost
- chunk 단위 UPDATE

같은 툴을 쓰는 이유가 바로 Replication Lag를 막기 위해서임.

## 핵심 정리

### Replication Lag 한 줄 정의

Replication Lag는 Replica가 Primary의 변경사항을 따라가지 못해 과거 시점의 데이터를 보여주는 시간 차이임.

### 중요한 오해 바로잡기

Replication Lag는 "binlog를 못 받아오는 것"이 아니라 "받아왔지만 적용을 못하는 것"이 대부분임. 즉, 네트워크 문제가 아니라 Replica의 처리 성능 문제임.

### Replication Lag 측정 기준

Primary 시간 기준으로, Replica가 얼마나 과거의 binlog 이벤트까지밖에 적용하지 못했는지를 나타내는 값임. Replica가 언제 실행했는지는 계산에 들어가지 않음.

### 대량 INSERT 시 메트릭 변화 핵심 패턴

Master INSERT 급증 → Replica가 지연되어 따라감 → lag가 계속 증가 → peak 도달 → 빠르게 감소 → 정상화

Storage IO와 aborted connection은 CPU/lag보다 20~40분 늦게 튐. 이는 메모리 기반 처리가 한계에 도달해 디스크 flush가 시작되기 때문임.
