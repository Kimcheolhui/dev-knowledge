# 07. IPC 시스템과 태스크 스케줄링

## IPC (Inter-Process Communication) 시스템

NanoClaw에서 호스트 프로세스와 컨테이너 에이전트 간의 통신은 **파일 기반 IPC**로 이루어진다. WebSocket이나 gRPC 대신 파일 시스템 감시(polling)를 사용하는 단순한 설계.

### IPC 디렉토리 구조

```
data/ipc/
├── main/                     # 메인 그룹 IPC 네임스페이스
│   ├── messages/             # 에이전트 → 호스트: 메시지 전송 요청
│   │   └── {timestamp}.json
│   ├── tasks/                # 에이전트 → 호스트: 태스크 관리 요청
│   │   └── {timestamp}.json
│   ├── input/                # 호스트 → 에이전트: 후속 메시지
│   │   ├── {timestamp}.json
│   │   └── _close            # 종료 신호 (센티널)
│   ├── current_tasks.json    # 호스트 → 에이전트: 태스크 스냅샷
│   └── available_groups.json # 호스트 → 에이전트: 그룹 목록
├── whatsapp_family/          # 비메인 그룹 IPC 네임스페이스
│   ├── messages/
│   ├── tasks/
│   └── input/
└── errors/                   # 처리 실패한 IPC 파일 보관
```

### IPC 메시지 유형

#### 에이전트 → 호스트 (messages/)

```json
{
  "type": "message",
  "chatJid": "120363336345@g.us",
  "text": "안녕하세요!"
}
```

#### 에이전트 → 호스트 (tasks/)

| type | 필드 | 설명 |
|------|------|------|
| `schedule_task` | prompt, schedule_type, schedule_value, targetJid, context_mode | 태스크 생성 |
| `pause_task` | taskId | 태스크 일시정지 |
| `resume_task` | taskId | 태스크 재개 |
| `cancel_task` | taskId | 태스크 삭제 |
| `update_task` | taskId, prompt?, schedule_type?, schedule_value? | 태스크 수정 |
| `refresh_groups` | (없음) | 그룹 메타데이터 새로고침 (메인만) |
| `register_group` | jid, name, folder, trigger, requiresTrigger?, containerConfig? | 그룹 등록 (메인만) |

#### 호스트 → 에이전트 (input/)

```json
{
  "type": "message",
  "text": "<context timezone=\"Asia/Seoul\" />\n<messages>...</messages>"
}
```

#### 종료 센티널 (input/_close)

빈 파일. 에이전트가 감지하면 현재 작업 완료 후 종료.

### IPC 워처 동작 (1초 폴링)

```typescript
const processIpcFiles = async () => {
  // 1. data/ipc/ 하위 모든 그룹 디렉토리 스캔
  // 2. 각 그룹의 messages/, tasks/ 디렉토리에서 .json 파일 처리
  // 3. 인가 검사 (sourceGroup, isMain 기반)
  // 4. 처리 완료된 파일 삭제
  // 5. 에러 시 errors/ 디렉토리로 이동
  setTimeout(processIpcFiles, IPC_POLL_INTERVAL);  // 1초 후 재실행
};
```

### 에러 처리

- IPC 파일 처리 실패 시 `data/ipc/errors/{group}-{filename}` 으로 이동
- 원본 파일은 삭제되어 무한 재처리 방지
- 인가 실패는 로그만 남기고 파일 삭제

---

## 태스크 스케줄링

### 태스크 모델

```typescript
interface ScheduledTask {
  id: string;              // "task-1710000000-abc123"
  group_folder: string;    // "whatsapp_family"
  chat_jid: string;        // "120363336345@g.us"
  prompt: string;          // "날씨 알려줘"
  schedule_type: 'cron' | 'interval' | 'once';
  schedule_value: string;  // "0 9 * * 1-5" | "3600000" | "2026-03-20T09:00:00Z"
  context_mode: 'group' | 'isolated';  // 세션 공유 여부
  next_run: string | null; // 다음 실행 시간 (ISO)
  last_run: string | null;
  last_result: string | null;
  status: 'active' | 'paused' | 'completed';
  created_at: string;
}
```

### 스케줄 유형 상세

#### Cron (크론 표현식)

```json
{ "schedule_type": "cron", "schedule_value": "0 9 * * 1-5" }
```
- `cron-parser` 라이브러리 사용
- 타임존 인식 (`TIMEZONE` 설정)
- 다음 실행: `CronExpressionParser.parse(value, { tz }).next().toISOString()`

#### Interval (밀리초 간격)

```json
{ "schedule_type": "interval", "schedule_value": "3600000" }
```
- 드리프트 방지: `next_run` 기준으로 계산 (Date.now() 아닌)
- 놓친 간격 건너뛰기: `while (next <= now) { next += ms; }`

#### Once (1회성)

```json
{ "schedule_type": "once", "schedule_value": "2026-03-20T09:00:00Z" }
```
- 실행 후 `status = 'completed'`, `next_run = null`

### 컨텍스트 모드

| 모드 | 설명 |
|------|------|
| `isolated` (기본) | 태스크마다 새로운 Claude 세션 사용 |
| `group` | 그룹의 현재 세션을 공유 (대화 맥락 유지) |

### 스케줄러 루프

```
60초마다:
  getDueTasks() → status='active' AND next_run <= now
       │
       ▼ 각 태스크에 대해
  getTaskById() → 상태 재확인 (paused/cancelled 체크)
       │
       ▼
  queue.enqueueTask(chatJid, taskId, () => runTask())
       │
       ▼ GroupQueue에서 슬롯 확보 시
  runTask()
       │
       ├── resolveGroupFolderPath() → 유효성 검증
       ├── writeTasksSnapshot() → 태스크 목록 기록
       ├── runContainerAgent() → 컨테이너 실행
       │   ├── 결과 스트리밍 → sendMessage(chatJid, text)
       │   └── 10초 후 closeStdin() → 태스크 컨테이너 빠른 종료
       │
       ▼ 실행 후
  logTaskRun() → task_run_logs 테이블에 기록
  computeNextRun() → 다음 실행 시간 계산
  updateTaskAfterRun() → next_run, last_result 업데이트
```

### 태스크 컨테이너의 빠른 종료

태스크는 단일 턴 실행이므로 결과 출력 후 30분 유휴 타임아웃까지 대기할 필요가 없다:

```typescript
const TASK_CLOSE_DELAY_MS = 10000;  // 10초

const scheduleClose = () => {
  closeTimer = setTimeout(() => {
    deps.queue.closeStdin(task.chat_jid);  // 종료 센티널 전송
  }, TASK_CLOSE_DELAY_MS);
};
```

결과 출력 10초 후 자동 종료 → 리소스 절약.

### 태스크 실행 로그

```typescript
interface TaskRunLog {
  task_id: string;       // 태스크 ID
  run_at: string;        // 실행 시작 시간
  duration_ms: number;   // 소요 시간
  status: 'success' | 'error';
  result: string | null; // 결과 (200자 제한)
  error: string | null;  // 에러 메시지
}
```

### 태스크 상태 전이

```
         schedule_task
              │
              ▼
         ┌─────────┐
         │  active  │ ←── resume_task
         └────┬─────┘
              │
    ┌─────────┼──────────┐
    │         │          │
    ▼         ▼          ▼
┌────────┐ ┌───────┐ ┌───────────┐
│ paused │ │ error │ │ completed │
│        │ │(retry)│ │ (once)    │
└────────┘ └───────┘ └───────────┘
    │
    ▼ (cancel_task)
 [삭제됨]
```

- `active` → 실행 대기/실행 중
- `paused` → 수동 일시정지 또는 유효하지 않은 그룹 폴더
- `completed` → once 타입 실행 완료
- `cancel_task` → DB에서 완전 삭제 (task_run_logs 포함)
