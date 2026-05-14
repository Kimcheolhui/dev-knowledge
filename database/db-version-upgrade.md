# Database Version Upgrade 운영 정리

작성일: 2026-05-14

## 핵심 요약

Database version upgrade는 일반 애플리케이션 배포보다 훨씬 보수적으로 접근한다. DB는 상태를 가진 시스템이고, 한 번 잘못되면 단순히 프로세스를 재시작하는 수준으로 복구되지 않기 때문이다.

Major version upgrade는 자주 하지 않는다. 하지만 아예 안 하는 작업도 아니다. DB 버전에도 support lifecycle이 있고, EOL, 보안 패치, cloud provider 정책, 신규 기능, 성능 개선 때문에 언젠가는 upgrade가 필요해진다.

Downtime에 대해서는 조금 나눠서 이해해야 한다.

- 이론적으로는 무중단 또는 near-zero downtime upgrade가 가능하다.
- 실무적으로는 짧은 downtime이나 read-only window를 감수하는 경우가 많다.
- 특히 단일 primary 구조, in-place upgrade, write-heavy 서비스에서는 downtime 가능성이 높다.
- 반대로 replica, logical replication, CDC, blue-green 구조를 잘 쓰면 downtime을 크게 줄일 수 있다.

결국 DB version upgrade의 핵심은 "무조건 중단되냐"가 아니라, 어느 시점에 write를 막을지, replication lag를 어떻게 줄일지, endpoint를 어떻게 전환할지, 실패 시 어디까지 되돌릴 수 있는지를 미리 정하는 것이다.

## DB 업그레이드가 조심스러운 이유

애플리케이션 서버는 stateless하게 만들 수 있다. 문제가 생기면 이전 버전 컨테이너를 다시 띄우거나 트래픽을 되돌리는 식의 rollback이 비교적 쉽다.

DB는 다르다. 실제 데이터가 있고, 그 데이터는 계속 변한다. DB version upgrade는 단순히 DB binary를 갈아끼우는 작업이 아니라 다음 요소에 영향을 줄 수 있다.

- storage format
- system catalog
- query optimizer
- index 동작
- SQL 문법 호환성
- authentication plugin
- replication protocol
- backup/restore 방식
- client driver compatibility
- extension 또는 plugin compatibility

그래서 DB upgrade에서 가장 무서운 부분은 "업그레이드 명령이 실패하는 것"만이 아니다. 업그레이드는 성공했는데 특정 쿼리가 느려지거나, 일부 SQL 동작이 달라지거나, 장애 발생 후 rollback이 어려워지는 상황이 더 위험할 수 있다.

## Upgrade를 자주 하지 않는 이유

DB major version upgrade는 보통 몇 달 전부터 준비한다. MySQL 5.7에서 8.0으로 올리거나, PostgreSQL 13에서 16으로 올리거나, Oracle 12c에서 19c로 올리는 작업은 일반 배포처럼 매주 할 수 있는 일이 아니다.

보통 다음을 먼저 확인한다.

- target version으로 바로 올라갈 수 있는지
- deprecated SQL syntax가 있는지
- driver, ORM, extension, plugin이 호환되는지
- backup을 실제로 restore할 수 있는지
- upgrade 후 query plan이 크게 바뀌지 않는지
- rollback이 가능한 시점과 불가능한 시점이 어디인지

따라서 "DB는 한 번 제대로 해놓고 같은 버전을 계속 쓴다"는 말은 현업에서 오래 방치되는 경우가 있다는 의미로는 어느 정도 맞다. 하지만 좋은 운영 방식이라고 보기는 어렵다. support 종료와 보안 리스크 때문에 언젠가는 upgrade 계획을 세워야 한다.

## Downtime과 upgrade 방식

DB upgrade는 크게 in-place upgrade와 side-by-side upgrade로 나눌 수 있다.

### In-place upgrade

기존 DB 인스턴스 자체를 새 버전으로 올리는 방식이다. 관리형 DB에서 major version upgrade를 실행하거나, VM에 설치된 DB binary를 교체하고 upgrade command를 실행하는 방식이 여기에 해당한다.

구조는 단순하지만 downtime이 생기기 쉽다. DB process를 내리고, binary를 바꾸고, catalog나 internal metadata를 변환하고, 다시 올리는 동안 write는 당연히 불가능하고 read도 막힐 수 있다.

관리형 DB의 in-place major upgrade도 보통 다음 흐름을 가진다.

1. pre-check 수행
2. backup 또는 snapshot 생성
3. DB 중지 또는 maintenance mode 진입
4. engine binary 교체
5. system table/catalog upgrade
6. DB 재시작
7. post-check 수행

이 과정에서는 짧든 길든 connection interruption이 발생할 수 있다. 그래서 in-place upgrade에서는 "downtime이 필수인가"보다 "downtime을 얼마나 짧게 잡을 수 있는가"가 더 현실적인 질문이 된다.

### Side-by-side upgrade

새 버전의 DB를 별도로 만들고, 기존 DB 데이터를 복제하거나 restore한 뒤, 최종 시점에 애플리케이션 트래픽을 새 DB로 넘기는 방식이다.

이 방식은 다음 이름으로도 불린다.

- blue-green deployment
- replica promotion
- logical replication cutover
- CDC 기반 migration
- new cluster migration

장점은 기존 DB를 그대로 두고 새 DB를 충분히 검증할 수 있다는 것이다. 또한 최종 cutover 시간만 잘 줄이면 downtime을 매우 짧게 만들 수 있다.

대신 운영 난이도는 올라간다. replication lag, 데이터 차이, sequence/auto increment, 권한, connection string, DNS, rollback 방향까지 모두 고려해야 한다.

## Write-heavy 서비스의 DB upgrade

write가 많은 서비스에서는 DB upgrade가 특히 어렵다. 이유는 write는 순서와 정합성이 중요하기 때문이다.

- 같은 row를 동시에 수정할 수 있다.
- transaction 순서가 중요하다.
- auto increment, sequence, unique constraint 충돌이 생길 수 있다.
- 결제, 주문, 포인트, 재고처럼 한 번 잘못 쓰면 보정이 어려운 데이터가 있다.
- old DB와 new DB에 동시에 write하면 conflict resolution이 필요하다.

그래서 write-heavy 서비스는 cutover 시점에 다음 중 하나를 선택한다.

| 방식                                   | 설명                                          | 장점                             | 단점                                 |
| -------------------------------------- | --------------------------------------------- | -------------------------------- | ------------------------------------ |
| 전체 서비스 중단                       | 애플리케이션을 내리고 DB upgrade 후 다시 올림 | 가장 단순하고 정합성 확보가 쉬움 | downtime이 명확히 발생               |
| read-only mode                         | write만 막고 read는 허용                      | 사용자에게 일부 기능 제공 가능   | write 기능은 중단됨                  |
| queue 적재                             | write 요청을 queue에 쌓고 cutover 후 처리     | 사용자 요청을 완전히 버리지 않음 | 중복 처리, 순서 보장, 실패 보상 필요 |
| old primary에서 new primary로 failover | replica sync 후 new DB를 primary로 승격       | downtime을 짧게 만들 수 있음     | 복제와 승격 절차가 복잡              |

이론적으로는 dual-write까지 설계하면 무중단에 더 가까워질 수 있다. 하지만 충돌, 재시도, 부분 실패 처리가 매우 어렵기 때문에 보통은 마지막 전환 시점에 write를 짧게 막는 쪽이 더 안전하다.

## Read-heavy 서비스와 replica

read 중심 서비스는 write-heavy 서비스보다 선택지가 조금 더 많다. 잠깐 동안 write가 막혀도 괜찮고, stale read를 어느 정도 허용할 수 있다면 read replica를 열어둔 채 primary upgrade를 진행하는 전략을 생각할 수 있다.

다만 replica를 쓰면 다음 조건을 같이 봐야 한다.

- replica lag가 커져도 서비스가 버틸 수 있는지
- 구버전 primary에서 신버전 replica로 replication이 가능한지
- rollback 방향의 replication도 가능한지
- 애플리케이션이 read/write endpoint를 분리할 수 있는지
- 사용자가 방금 쓴 데이터가 잠시 보이지 않아도 되는지

그래서 "read replica만 열어두면 된다"는 식으로 단순하게 보면 안 된다. read-only 서비스라면 가능한 전략이지만, consistency model과 replication lag를 감수할 수 있어야 한다.

## Oracle 관련 정리

Oracle에는 여러 고가용성 기술이 있다. 그런데 이 기술들이 모두 "master DB 두 개가 동시에 write를 받고 자동 sync한다"는 뜻은 아니다.

### Oracle RAC

Oracle RAC(Real Application Clusters)는 여러 DB instance가 하나의 shared database storage를 바라보는 구조다. 여러 노드가 같은 DB를 서비스할 수 있으므로 instance 장애에 강하고, 일부 workload는 분산할 수 있다.

하지만 RAC는 일반적으로 "서로 다른 두 master DB가 각자 데이터를 가지고 양방향 sync한다"는 의미의 multi-master replication과는 다르다. 같은 database를 여러 instance가 열어 사용하는 shared-disk clustering에 가깝다.

### Oracle Data Guard

Data Guard는 primary DB와 standby DB를 두고 redo log를 전송해 standby를 유지하는 기술이다. 장애 시 standby를 primary로 전환하거나, 계획된 switchover를 수행할 수 있다.

Data Guard를 잘 사용하면 upgrade 중 downtime을 줄일 수 있다. 예를 들어 standby를 먼저 upgrade하고, switchover한 뒤 기존 primary를 upgrade하는 식의 rolling upgrade 전략을 구성할 수 있다. 다만 이것도 버전 조합, 구성 방식, 라이선스, 운영 절차에 따라 달라진다.

### Oracle GoldenGate

GoldenGate는 CDC 기반 replication 제품이다. 서로 다른 DB 간 데이터 변경을 복제하거나, migration/cutover를 더 유연하게 구성할 수 있다. 양방향 replication도 가능하지만 conflict resolution이 필요할 수 있다.

즉, Oracle에서 고급 기능을 쓰면 downtime을 매우 줄일 수 있는 것은 맞다. 하지만 "Oracle은 master 두 개를 두면 알아서 sync되므로 무중단 upgrade가 된다"고 이해하면 위험하다.

더 정확히는 다음에 가깝다.

> Oracle은 RAC, Data Guard, GoldenGate 같은 고가용성/복제 옵션이 강력하고, 이를 잘 설계하면 rolling upgrade나 near-zero downtime migration이 가능하다. 하지만 구성, 라이선스, 운영 난이도, 애플리케이션 특성에 따라 결과가 달라진다.

## MySQL/PostgreSQL에서도 무중단에 가깝게 가능한가?

MySQL이나 PostgreSQL에서도 무중단에 가깝게 upgrade하는 것은 가능하다. Oracle만의 이야기는 아니다.

MySQL에서는 replica를 새 버전으로 구성한 뒤 replication을 따라잡게 하고, 마지막에 read-only 전환 후 replica를 primary로 승격하는 방식을 사용할 수 있다. Cloud provider가 제공하는 blue-green deployment 기능을 쓰는 경우도 있다.

PostgreSQL에서는 logical replication을 이용해 새 major version cluster로 데이터를 복제한 뒤 cutover할 수 있다. `pg_upgrade`를 쓰면 빠르게 major upgrade할 수 있지만, 구성에 따라 downtime이 필요하다.

다만 MySQL/PostgreSQL에서도 완전한 의미의 zero downtime은 쉽지 않다. 특히 write cutover 시점에는 다음 문제가 남는다.

- 마지막 replication lag를 0에 가깝게 맞추는 문제
- old DB로 들어오는 write를 언제 막을지 결정하는 문제
- 애플리케이션 connection pool을 어떻게 끊고 새 DB로 붙일지의 문제
- DNS TTL이나 client-side DNS cache 문제
- rollback 시 데이터가 어느 방향으로 흐를지의 문제

그래서 현업에서 말하는 zero downtime upgrade는 실제로는 near-zero downtime 또는 minimal downtime에 가까운 경우가 많다. 수 초에서 수 분 정도의 write freeze, connection reset, 일부 요청 실패 가능성은 여전히 고려해야 한다.

## 대표적인 upgrade 전략

### 전략 1. Maintenance window + in-place upgrade

가장 단순한 방식이다.

1. 서비스 점검 공지
2. 애플리케이션 중지
3. DB backup/snapshot
4. DB in-place upgrade
5. 애플리케이션 smoke test
6. 서비스 재개

작은 서비스, 내부 서비스, 야간 downtime을 허용할 수 있는 서비스에서는 이 방식이 가장 현실적일 수 있다. 이론적으로 가장 세련된 방식은 아니지만, 실무적으로는 리스크를 줄이는 좋은 선택이 될 수 있다.

### 전략 2. Read-only mode + upgrade

write를 막고 read만 허용하는 방식이다.

예를 들어 게시판 서비스라면 글쓰기/수정/삭제는 잠시 막고 조회는 계속 열어둘 수 있다. 사용자 입장에서는 전체 장애보다 낫다.

단점은 서비스가 read-only mode를 지원해야 한다는 것이다. 애플리케이션 코드에서 write API를 일괄 차단하거나, feature flag로 write 기능을 막거나, DB 계정 권한을 임시로 read-only로 바꾸는 방식이 필요하다.

### 전략 3. Replica promotion

새 버전 replica를 준비하고, replication lag가 0에 가까워졌을 때 write를 멈춘 뒤 replica를 primary로 승격한다.

대략적인 흐름은 다음과 같다.

1. 기존 primary에서 replica 생성
2. replica를 target version으로 upgrade하거나 target version replica를 구성
3. replication lag 모니터링
4. cutover 시점에 old primary write 중지
5. lag가 0인지 확인
6. replica를 primary로 승격
7. 애플리케이션 endpoint 전환

이 방식은 downtime을 줄일 수 있지만, replication compatibility와 promotion 절차가 중요하다.

### 전략 4. Logical replication / CDC migration

old DB와 new DB를 동시에 두고, old DB의 변경 사항을 new DB로 계속 흘려보낸다. MySQL binlog, PostgreSQL logical replication, Debezium, GoldenGate 같은 기술이 여기에 해당한다.

장점은 새 DB를 미리 만들어 오래 검증할 수 있고, cutover 시간을 줄일 수 있다는 것이다.

단점은 운영 난이도가 높다는 것이다. schema 변경, sequence, trigger, foreign key, large transaction, replication lag, 장애 시 재처리까지 고려해야 한다.

### 전략 5. DNS 또는 connection string cutover

신규 DB를 준비한 뒤 애플리케이션이 바라보는 endpoint를 바꾸는 방식이다. Private DNS record를 바꾸거나, DB proxy endpoint를 바꾸거나, application secret의 connection string을 바꾼 뒤 rollout할 수 있다.

이 방식은 endpoint 전환을 단순화할 수 있지만, DNS TTL, client DNS cache, connection pool 때문에 즉시 모든 트래픽이 새 DB로 가지 않을 수 있다. 기존 connection은 DNS를 다시 조회하지 않고 계속 old DB에 붙어 있을 수 있다.

따라서 DNS cutover를 쓸 때도 보통 다음을 함께 한다.

- TTL을 미리 낮춤
- connection pool recycle
- pod 또는 application process 순차 재시작
- old DB write 차단
- 양쪽 DB 접속 로그 확인

## 최종 정리

DB version upgrade는 자주 하는 작업은 아니지만, 피할 수 없는 운영 작업이다. 무중단에 가깝게 만드는 기술은 있지만, write 정합성, replication lag, connection 전환, rollback 문제 때문에 실무에서는 짧은 downtime이나 read-only window를 감수하는 경우가 많다.

정리하면, DB upgrade는 "버튼을 눌러 버전을 올리는 작업"이 아니라 "데이터 흐름을 끊지 않거나, 끊어야 한다면 어디서 얼마나 짧게 끊을지 설계하는 작업"에 가깝다.
