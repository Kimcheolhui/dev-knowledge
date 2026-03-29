# 02. 모듈 상세 분석

> 📊 모듈 간 의존성 관계도: [diagrams/module-dependencies.excalidraw](./diagrams/module-dependencies.excalidraw)

## 모듈 의존성 매트릭스

```
                 config  types  db  logger  env  group-folder  container-runtime  mount-security  timezone
index.ts           ✓      ✓    ✓     ✓            ✓
container-runner   ✓      ✓         ✓       ✓     ✓              ✓                  ✓
db.ts              ✓      ✓         ✓              ✓
ipc.ts             ✓      ✓    ✓    ✓              ✓
group-queue.ts     ✓                ✓
task-scheduler.ts  ✓      ✓    ✓    ✓              ✓
router.ts                 ✓
credential-proxy              ✓    ✓
sender-allowlist   ✓                ✓
mount-security     ✓      ✓         ✓
```

---

## 1. index.ts — 오케스트레이터

**크기**: ~19.6KB | **역할**: 시스템의 메인 엔트리포인트

### 핵심 상태

```typescript
let lastTimestamp = ""; // 전체 메시지 커서
let sessions: Record<string, string> = {}; // 그룹폴더 → 세션ID
let registeredGroups: Record<string, RegisteredGroup> = {}; // JID → 그룹정보
let lastAgentTimestamp: Record<string, string> = {}; // 그룹별 에이전트 처리 커서
```

### 주요 함수

| 함수                               | 역할                                                              |
| ---------------------------------- | ----------------------------------------------------------------- |
| `main()`                           | 부트스트랩: 런타임 체크 → DB 초기화 → 채널 연결 → 서브시스템 시작 |
| `startMessageLoop()`               | 2초 폴링으로 새 메시지 감지, 트리거 검사, 큐 전달                 |
| `processGroupMessages(chatJid)`    | 그룹의 대기 메시지 처리 → 에이전트 실행 → 응답 전송               |
| `runAgent(group, prompt, chatJid)` | 에이전트 컨테이너 실행, 스트리밍 출력 처리                        |
| `recoverPendingMessages()`         | 시작 시 크래시 복구: 미처리 메시지 재처리                         |
| `registerGroup(jid, group)`        | 새 그룹 등록 및 폴더 생성                                         |

### 메시지 커서 이중 추적

```
lastTimestamp ─────── 전체 메시지 스트림에서 "본" 위치 (message loop에서 관리)
lastAgentTimestamp ── 그룹별로 에이전트가 "처리한" 위치 (processGroupMessages에서 관리)
```

에이전트 에러 시 `lastAgentTimestamp`를 롤백하여 재처리 가능. 단, 이미 사용자에게 출력이 전송된 경우에는 중복 방지를 위해 롤백하지 않는다.

---

## 2. container-runner.ts — 컨테이너 실행기

**크기**: ~21.6KB | **역할**: Docker 컨테이너 스폰 및 에이전트 실행 관리

### 핵심 함수

| 함수                                        | 역할                                              |
| ------------------------------------------- | ------------------------------------------------- |
| `buildVolumeMounts(group, isMain)`          | 그룹 유형에 따른 볼륨 마운트 목록 생성            |
| `buildContainerArgs(mounts, name)`          | Docker CLI 인수 조합                              |
| `runContainerAgent(group, input, ...)`      | 컨테이너 스폰 → stdin 전송 → stdout 스트리밍 파싱 |
| `writeTasksSnapshot(folder, isMain, tasks)` | 그룹 IPC 디렉토리에 태스크 목록 기록              |
| `writeGroupsSnapshot(folder, isMain, ...)`  | 사용 가능 그룹 목록 기록                          |

### 마운트 구성 (메인 그룹 vs 비메인 그룹)

**메인 그룹 마운트:**

| 컨테이너 경로             | 호스트 경로                            | 접근              |
| ------------------------- | -------------------------------------- | ----------------- |
| `/workspace/project`      | 프로젝트 루트                          | 읽기전용          |
| `/workspace/project/.env` | `/dev/null`                            | 읽기전용 (섀도잉) |
| `/workspace/group`        | `groups/main/`                         | 읽기/쓰기         |
| `/home/node/.claude`      | `data/sessions/main/.claude/`          | 읽기/쓰기         |
| `/workspace/ipc`          | `data/ipc/main/`                       | 읽기/쓰기         |
| `/app/src`                | `data/sessions/main/agent-runner-src/` | 읽기/쓰기         |

**비메인 그룹 마운트:**

| 컨테이너 경로        | 호스트 경로                       | 접근        |
| -------------------- | --------------------------------- | ----------- |
| `/workspace/group`   | `groups/{folder}/`                | 읽기/쓰기   |
| `/workspace/global`  | `groups/global/`                  | 읽기전용    |
| `/home/node/.claude` | `data/sessions/{folder}/.claude/` | 읽기/쓰기   |
| `/workspace/ipc`     | `data/ipc/{folder}/`              | 읽기/쓰기   |
| `/workspace/extra/*` | 추가 마운트 (허용 목록)           | 설정에 따름 |

### 스트리밍 출력 파싱

```
stdout → parseBuffer에 누적 → OUTPUT_START_MARKER...OUTPUT_END_MARKER 사이 JSON 추출
                                      ↓
                              ContainerOutput { status, result, newSessionId, error }
                                      ↓
                              onOutput 콜백 → 사용자에게 실시간 전송
```

---

## 3. db.ts — 데이터베이스 레이어

**크기**: ~19.9KB | **역할**: SQLite CRUD 및 스키마 관리

### 테이블 구조 (상세는 [08-database-schema.md](./08-database-schema.md) 참조)

- `chats` — 채팅방 메타데이터
- `messages` — 메시지 내용
- `scheduled_tasks` — 스케줄 태스크
- `task_run_logs` — 태스크 실행 로그
- `router_state` — 라우터 상태 (Key-Value)
- `sessions` — 그룹별 Claude 세션 ID
- `registered_groups` — 등록된 그룹 설정

### 마이그레이션 전략

- `ALTER TABLE ... ADD COLUMN` + try/catch (이미 존재하면 무시)
- JSON 파일 → SQLite 자동 마이그레이션 (`migrateJsonState()`)
- 후행 처리: 기존 데이터 backfill (`UPDATE ... WHERE ...`)

---

## 4. group-queue.ts — 그룹 큐

**크기**: ~10.7KB | **역할**: 그룹별 직렬 실행 + 글로벌 동시성 제한

### 상태 머신

```
         enqueueMessageCheck()
               │
    ┌──────────▼──────────┐
    │  active=false        │
    │  pendingMessages=true│──── (동시성 초과시) ──→ waitingGroups[]에 대기
    └──────────┬───────────┘
               │ (슬롯 확보)
    ┌──────────▼──────────┐
    │  active=true         │
    │  runForGroup()       │──→ processGroupMessages() 실행
    └──────────┬───────────┘
               │ (완료)
    ┌──────────▼──────────┐
    │  drainGroup()        │──→ pendingTasks 먼저 → pendingMessages → drainWaiting()
    └──────────────────────┘
```

### 유휴 컨테이너 재사용 메커니즘

1. 에이전트 출력 후 `notifyIdle()` → `idleWaiting = true`
2. 새 메시지 도착 시 `sendMessage()` → IPC input 파일 쓰기 → 컨테이너가 읽음
3. IDLE_TIMEOUT(30분) 초과 시 `closeStdin()` → `_close` 센티널 파일 생성

---

## 5. ipc.ts — IPC 시스템

**크기**: ~14.5KB | **역할**: 컨테이너↔호스트 파일 기반 통신

### IPC 네임스페이스

```
data/ipc/
├── {group_folder}/
│   ├── messages/       ← 에이전트가 보내는 메시지
│   │   └── {ts}.json   { type: "message", chatJid, text }
│   ├── tasks/          ← 에이전트의 태스크 요청
│   │   └── {ts}.json   { type: "schedule_task"|"pause_task"|... }
│   ├── input/          ← 호스트가 에이전트에게 보내는 후속 메시지
│   │   ├── {ts}.json   { type: "message", text }
│   │   └── _close      센티널: 컨테이너 종료 신호
│   ├── current_tasks.json    ← 현재 태스크 스냅샷
│   └── available_groups.json ← 사용 가능 그룹 목록
```

### 인가 모델

| IPC 작업                | 메인 그룹 | 비메인 그룹 |
| ----------------------- | --------- | ----------- |
| 다른 채팅에 메시지 전송 | ✅        | ❌          |
| 자기 채팅에 메시지 전송 | ✅        | ✅          |
| 다른 그룹 태스크 스케줄 | ✅        | ❌          |
| 자기 그룹 태스크 스케줄 | ✅        | ✅          |
| 그룹 등록               | ✅        | ❌          |
| 그룹 새로고침           | ✅        | ❌          |

---

## 6. task-scheduler.ts — 태스크 스케줄러

**크기**: ~8.1KB | **역할**: 예약된 태스크의 주기적 실행

### 스케줄 유형

| 유형       | schedule_value 예시      | 설명                      |
| ---------- | ------------------------ | ------------------------- |
| `cron`     | `"0 9 * * 1-5"`          | 크론 표현식 (타임존 인식) |
| `interval` | `"3600000"`              | 밀리초 간격 반복          |
| `once`     | `"2026-03-20T09:00:00Z"` | 1회성 실행                |

### 실행 흐름

```
60초마다 loop() → getDueTasks() → 각 태스크를 queue.enqueueTask()
                                          ↓
                                   runTask() → runContainerAgent()
                                          ↓
                                   결과 → sendMessage() + logTaskRun()
                                          ↓
                                   computeNextRun() → updateTaskAfterRun()
```

### 드리프트 방지

`computeNextRun()`은 `Date.now()`가 아닌 예정된 시간(`task.next_run`)을 기준으로 다음 실행 시간을 계산하여 누적 드리프트를 방지한다:

```typescript
let next = new Date(task.next_run!).getTime() + ms;
while (next <= now) {
  next += ms;
} // 놓친 간격 건너뛰기
```

---

## 7. router.ts — 메시지 라우터

**크기**: ~1.5KB | **역할**: 메시지 포맷팅 및 채널 라우팅

### 인바운드 포맷팅 (에이전트로)

```xml
<context timezone="Asia/Seoul" />
<messages>
<message sender="User" time="Mar 18, 2026, 2:22 PM">Hello @Andy</message>
</messages>
```

### 아웃바운드 포맷팅 (사용자에게)

- `<internal>...</internal>` 태그 제거 (에이전트 내부 추론)
- 빈 문자열이면 전송하지 않음

---

## 8. credential-proxy.ts — 크레덴셜 프록시

**크기**: ~4.1KB | **역할**: API 키를 컨테이너 외부에서 주입

### 두 가지 인증 모드

| 모드        | 환경변수                  | 프록시 동작                                                     |
| ----------- | ------------------------- | --------------------------------------------------------------- |
| **api-key** | `ANTHROPIC_API_KEY`       | 모든 요청에 `x-api-key` 헤더 주입                               |
| **oauth**   | `CLAUDE_CODE_OAUTH_TOKEN` | `Authorization: Bearer` 헤더의 placeholder를 실제 토큰으로 교체 |

### 흐름

```
Container → ANTHROPIC_BASE_URL=http://host:3001 → Credential Proxy → api.anthropic.com
            ANTHROPIC_API_KEY=placeholder           (실제 키 주입)
```

---

## 9. container-runtime.ts — 런타임 추상화

**크기**: ~4.5KB | **역할**: Docker/Apple Container 런타임 추상화

- `CONTAINER_RUNTIME_BIN = 'docker'`
- `PROXY_BIND_HOST`: macOS=`127.0.0.1`, Linux=docker0 브리지 IP
- `hostGatewayArgs()`: Linux에서 `--add-host=host.docker.internal:host-gateway` 추가
- `ensureContainerRuntimeRunning()`: 시작 시 `docker info` 검증
- `cleanupOrphans()`: 이전 실행의 고아 컨테이너 정리

---

## 10. mount-security.ts — 마운트 보안

**크기**: ~10.6KB | **역할**: 추가 마운트의 보안 검증

### 검증 단계

1. 외부 허용 목록 로드 (`~/.config/nanoclaw/mount-allowlist.json`)
2. 컨테이너 경로 검증 (경로 탈출 방지: `..`, 절대 경로 차단)
3. 호스트 경로 확장 (`~` → 홈 디렉토리) 및 심볼릭 링크 해제 (`realpathSync`)
4. 차단 패턴 매칭 (`.ssh`, `.gnupg`, `.aws`, `.env` 등)
5. 허용 루트 검사 (경로가 허용된 디렉토리 하위인지)
6. 읽기/쓰기 권한 결정 (비메인 그룹 강제 읽기전용 옵션)

---

## 11. sender-allowlist.ts — 발신자 허용 목록

**크기**: ~3.1KB | **역할**: 채팅별 메시지 발신자 필터링

### 두 가지 모드

| 모드      | 동작                                          |
| --------- | --------------------------------------------- |
| `trigger` | 모든 메시지 저장, 허용된 발신자만 트리거 가능 |
| `drop`    | 허용되지 않은 발신자 메시지 완전 삭제         |

---

## 12. remote-control.ts — 원격 제어

**크기**: ~5.4KB | **역할**: Claude Code Remote Control 세션 관리

- 메인 그룹에서 `/remote-control` 명령으로 시작
- `claude remote-control` 프로세스를 detach 모드로 스폰
- stdout 폴링으로 URL 감지 (30초 타임아웃)
- 프로세스 생존 확인 및 재시작 시 복구 (`STATE_FILE`)

---

## 13. 유틸리티 모듈

| 모듈              | 크기  | 역할                                            |
| ----------------- | ----- | ----------------------------------------------- |
| `config.ts`       | 2.5KB | 환경 변수 및 상수 정의                          |
| `types.ts`        | 3.3KB | 전체 TypeScript 인터페이스 정의                 |
| `env.ts`          | 1.3KB | `.env` 파일 파싱 (process.env에 로드하지 않음!) |
| `logger.ts`       | 0.5KB | Pino 로거 + uncaughtException 핸들링            |
| `timezone.ts`     | 0.4KB | UTC → 로컬 시간 변환 (Intl API)                 |
| `group-folder.ts` | 1.5KB | 그룹 폴더 이름 검증 및 경로 해결                |

### env.ts의 보안 설계

`.env` 파일을 `process.env`에 로드하지 않는다. 이는 의도적 설계로, `process.env`에 비밀 값을 넣으면 자식 프로세스(컨테이너)에 상속될 수 있기 때문이다. 대신 `readEnvFile(keys)`로 필요한 값만 명시적으로 읽는다.
