# 01. 아키텍처 개요

## 시스템 전체 구조

NanoClaw는 **단일 Node.js 프로세스**로 실행되는 AI 어시스턴트 시스템이다. 마이크로서비스 아키텍처가 아닌 모놀리식 구조를 채택하여 복잡도를 최소화했다.

### 핵심 설계 원칙

1. **단일 프로세스**: 하나의 Node.js 프로세스가 모든 로직을 처리
2. **이벤트 기반 폴링**: WebSocket이 아닌 타이머 기반 폴링 루프 사용
3. **파일 기반 IPC**: 컨테이너와 호스트 간 통신은 JSON 파일로 수행
4. **격리된 에이전트**: 각 에이전트는 독립 컨테이너에서 실행

## 아키텍처 다이어그램

> 📊 [diagrams/architecture-overview.excalidraw](./diagrams/architecture-overview.excalidraw)에서 상세 다이어그램 확인

```
┌─────────────────────────────────────────────────────────────────────┐
│                         HOST PROCESS (Node.js)                       │
│                                                                      │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌────────────────────┐  │
│  │ Channel  │  │ Channel  │  │ Channel  │  │   Credential       │  │
│  │ WhatsApp │  │ Telegram │  │ Discord  │  │   Proxy (:3001)    │  │
│  └────┬─────┘  └────┬─────┘  └────┬─────┘  └────────┬───────────┘  │
│       │              │              │                  │              │
│       └──────────────┼──────────────┘                  │              │
│                      ▼                                 │              │
│              ┌───────────────┐                         │              │
│              │   SQLite DB   │                         │              │
│              │ (messages.db) │                         │              │
│              └───────┬───────┘                         │              │
│                      │                                 │              │
│              ┌───────▼───────┐                         │              │
│              │  Message Loop │ (2s polling)             │              │
│              │  (index.ts)   │                         │              │
│              └───────┬───────┘                         │              │
│                      │                                 │              │
│              ┌───────▼───────┐    ┌────────────┐       │              │
│              │  Group Queue  │◄───│  IPC Watch  │       │              │
│              │ (concurrency) │    │  (1s poll)  │       │              │
│              └───────┬───────┘    └────────────┘       │              │
│                      │                                 │              │
│              ┌───────▼───────┐    ┌────────────┐       │              │
│              │  Container    │    │  Task       │       │              │
│              │  Runner       │    │  Scheduler  │       │              │
│              └───────┬───────┘    └────┬───────┘       │              │
│                      │                 │               │              │
└──────────────────────┼─────────────────┼───────────────┼──────────────┘
                       │                 │               │
           ┌───────────▼─────────────────▼───────────────▼───────────┐
           │              CONTAINER LAYER (Docker)                    │
           │                                                          │
           │  ┌─────────────┐ ┌─────────────┐ ┌─────────────┐       │
           │  │  Container   │ │  Container   │ │  Container   │       │
           │  │  Group A     │ │  Group B     │ │  Task Run    │       │
           │  │ ┌─────────┐ │ │ ┌─────────┐ │ │ ┌─────────┐ │       │
           │  │ │ Claude   │ │ │ │ Claude   │ │ │ │ Claude   │ │       │
           │  │ │ Agent SDK│ │ │ │ Agent SDK│ │ │ │ Agent SDK│ │       │
           │  │ └─────────┘ │ │ └─────────┘ │ │ └─────────┘ │       │
           │  │ /workspace/ │ │ /workspace/ │ │ /workspace/ │       │
           │  └─────────────┘ └─────────────┘ └─────────────┘       │
           └──────────────────────────────────────────────────────────┘
```

## 주요 서브시스템

### 1. 오케스트레이터 (index.ts)

시스템의 중심으로, 다음 역할을 수행한다:

- **상태 관리**: 마지막 처리 타임스탬프, 세션 ID, 등록된 그룹 관리
- **메시지 루프**: 2초 간격으로 새 메시지 폴링 → 그룹 큐에 전달
- **채널 초기화**: 등록된 채널 팩토리를 순회하며 연결
- **서브시스템 시작**: 스케줄러, IPC 워처, 크레덴셜 프록시 기동
- **그레이스풀 셧다운**: SIGTERM/SIGINT 시그널 핸들링

### 2. 채널 레이어 (channels/)

플러그인 방식의 메시징 채널 시스템:

- **자동 등록**: `channels/index.ts` 배럴 임포트 시 각 채널이 `registerChannel()` 호출
- **팩토리 패턴**: 크레덴셜 없으면 `null` 반환하여 자동 스킵
- **추상화**: `Channel` 인터페이스로 WhatsApp, Telegram, Discord, Slack, Gmail 통합

### 3. 컨테이너 실행 (container-runner.ts)

에이전트 격리 실행 핵심:

- **볼륨 마운트 빌드**: 그룹별 마운트 구성 (메인/비메인 구분)
- **스트리밍 출력 파싱**: `OUTPUT_START_MARKER`/`OUTPUT_END_MARKER`로 실시간 결과 파싱
- **타임아웃 관리**: IDLE_TIMEOUT(30분)과 컨테이너 타임아웃 이중 관리
- **크레덴셜 프록시 연동**: API 키를 컨테이너에 노출하지 않고 프록시 경유

### 4. 그룹 큐 (group-queue.ts)

동시성 및 순서 보장:

- **글로벌 동시성 제한**: `MAX_CONCURRENT_CONTAINERS` (기본 5)
- **그룹별 직렬화**: 같은 그룹의 메시지는 순차 처리
- **재시도 로직**: 지수 백오프(5s → 10s → 20s..., 최대 5회)
- **유휴 컨테이너 재사용**: IPC를 통한 후속 메시지 전송

### 5. 데이터 레이어 (db.ts)

SQLite 기반 영속 저장:

- **스키마 마이그레이션**: `ALTER TABLE` 기반 점진적 마이그레이션
- **JSON → SQLite 마이그레이션**: 레거시 JSON 파일 자동 변환
- **트랜잭션 없는 설계**: better-sqlite3의 동기 API 활용

### 6. 보안 레이어

다중 보안 경계:

- **컨테이너 격리**: 프로세스/파일시스템/네트워크 격리
- **크레덴셜 프록시**: 실제 API 키가 컨테이너에 진입하지 않음
- **마운트 허용 목록**: 외부 파일(`~/.config/nanoclaw/`)에서 관리
- **IPC 인가**: 메인/비메인 그룹의 권한 차등

## 데이터 흐름 요약

```
1. [Channel] 메시지 수신 → onMessage 콜백
2. [db.ts] storeMessage() → SQLite 저장
3. [index.ts] 메시지 루프에서 getNewMessages() 폴링
4. [group-queue.ts] enqueueMessageCheck() → 동시성 제어
5. [container-runner.ts] runContainerAgent() → Docker 스폰
6. [agent-runner] Claude SDK 실행 → 결과 스트리밍
7. [index.ts] 스트리밍 콜백 → channel.sendMessage() 응답
```

## 설정 상수 (config.ts)

| 상수 | 기본값 | 설명 |
|------|--------|------|
| `ASSISTANT_NAME` | `"Andy"` | 트리거 단어 (`@Andy`) |
| `POLL_INTERVAL` | `2000ms` | 메시지 폴링 주기 |
| `SCHEDULER_POLL_INTERVAL` | `60000ms` | 스케줄러 폴링 주기 |
| `IPC_POLL_INTERVAL` | `1000ms` | IPC 파일 감시 주기 |
| `IDLE_TIMEOUT` | `1800000ms` (30분) | 컨테이너 유휴 타임아웃 |
| `CONTAINER_TIMEOUT` | `1800000ms` (30분) | 컨테이너 하드 타임아웃 |
| `MAX_CONCURRENT_CONTAINERS` | `5` | 최대 동시 실행 컨테이너 수 |
| `CREDENTIAL_PROXY_PORT` | `3001` | 크레덴셜 프록시 포트 |
| `CONTAINER_MAX_OUTPUT_SIZE` | `10MB` | 컨테이너 출력 최대 크기 |
| `CONTAINER_IMAGE` | `nanoclaw-agent:latest` | 에이전트 컨테이너 이미지 |
