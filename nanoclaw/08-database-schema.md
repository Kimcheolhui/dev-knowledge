# 08. 데이터베이스 스키마

## 개요

NanoClaw는 **SQLite** (`better-sqlite3`)를 사용하며, 데이터베이스 파일은 `store/messages.db`에 저장된다. 동기(synchronous) API를 사용하여 트랜잭션 복잡성 없이 간결한 코드를 유지한다.

## 테이블 스키마

### chats — 채팅방 메타데이터

```sql
CREATE TABLE chats (
  jid TEXT PRIMARY KEY,          -- 채팅 고유 ID (WhatsApp JID, Discord ID 등)
  name TEXT,                     -- 채팅방 이름
  last_message_time TEXT,        -- 마지막 메시지 시간 (ISO 8601)
  channel TEXT,                  -- 채널 유형 ('whatsapp', 'discord', 'telegram' 등)
  is_group INTEGER DEFAULT 0     -- 그룹 여부 (1=그룹, 0=개인)
);
```

**특수 레코드**: `jid='__group_sync__'`는 그룹 메타데이터 동기화 시간을 저장.

### messages — 메시지 내용

```sql
CREATE TABLE messages (
  id TEXT,                       -- 메시지 고유 ID
  chat_jid TEXT,                 -- 소속 채팅방 JID
  sender TEXT,                   -- 발신자 ID
  sender_name TEXT,              -- 발신자 표시 이름
  content TEXT,                  -- 메시지 내용
  timestamp TEXT,                -- 발신 시간 (ISO 8601)
  is_from_me INTEGER,            -- 자기 메시지 여부
  is_bot_message INTEGER DEFAULT 0,  -- 봇 메시지 여부
  PRIMARY KEY (id, chat_jid),
  FOREIGN KEY (chat_jid) REFERENCES chats(jid)
);
CREATE INDEX idx_timestamp ON messages(timestamp);
```

### scheduled_tasks — 스케줄 태스크

```sql
CREATE TABLE scheduled_tasks (
  id TEXT PRIMARY KEY,           -- 태스크 ID ("task-{timestamp}-{random}")
  group_folder TEXT NOT NULL,    -- 그룹 폴더 이름
  chat_jid TEXT NOT NULL,        -- 결과 전송 대상 채팅
  prompt TEXT NOT NULL,          -- 실행할 프롬프트
  schedule_type TEXT NOT NULL,   -- 'cron' | 'interval' | 'once'
  schedule_value TEXT NOT NULL,  -- 크론 표현식 | 밀리초 | ISO 날짜
  context_mode TEXT DEFAULT 'isolated',  -- 'group' | 'isolated'
  next_run TEXT,                 -- 다음 실행 시간 (ISO)
  last_run TEXT,                 -- 마지막 실행 시간
  last_result TEXT,              -- 마지막 실행 결과 (200자)
  status TEXT DEFAULT 'active',  -- 'active' | 'paused' | 'completed'
  created_at TEXT NOT NULL       -- 생성 시간
);
CREATE INDEX idx_next_run ON scheduled_tasks(next_run);
CREATE INDEX idx_status ON scheduled_tasks(status);
```

### task_run_logs — 태스크 실행 로그

```sql
CREATE TABLE task_run_logs (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  task_id TEXT NOT NULL,         -- 태스크 ID (FK)
  run_at TEXT NOT NULL,          -- 실행 시작 시간
  duration_ms INTEGER NOT NULL,  -- 소요 시간 (밀리초)
  status TEXT NOT NULL,          -- 'success' | 'error'
  result TEXT,                   -- 실행 결과
  error TEXT,                    -- 에러 메시지
  FOREIGN KEY (task_id) REFERENCES scheduled_tasks(id)
);
CREATE INDEX idx_task_run_logs ON task_run_logs(task_id, run_at);
```

### router_state — 라우터 상태 (Key-Value)

```sql
CREATE TABLE router_state (
  key TEXT PRIMARY KEY,
  value TEXT NOT NULL
);
```

**저장되는 키:**
| 키 | 값 | 설명 |
|----|---|------|
| `last_timestamp` | ISO 문자열 | 마지막으로 확인한 메시지 타임스탬프 |
| `last_agent_timestamp` | JSON 문자열 | 그룹별 마지막 에이전트 처리 타임스탬프 |

### sessions — 그룹별 Claude 세션

```sql
CREATE TABLE sessions (
  group_folder TEXT PRIMARY KEY,  -- 그룹 폴더 이름
  session_id TEXT NOT NULL        -- Claude 세션 ID
);
```

### registered_groups — 등록된 그룹

```sql
CREATE TABLE registered_groups (
  jid TEXT PRIMARY KEY,           -- 채팅 JID
  name TEXT NOT NULL,             -- 그룹 이름
  folder TEXT NOT NULL UNIQUE,    -- 그룹 폴더 이름 (고유)
  trigger_pattern TEXT NOT NULL,  -- 트리거 패턴 ("@Andy")
  added_at TEXT NOT NULL,         -- 등록 시간
  container_config TEXT,          -- 컨테이너 설정 JSON
  requires_trigger INTEGER DEFAULT 1,  -- 트리거 필요 여부
  is_main INTEGER DEFAULT 0      -- 메인 그룹 여부
);
```

## 마이그레이션 전략

NanoClaw는 전용 마이그레이션 프레임워크 없이 **try/catch 기반 점진적 마이그레이션**을 사용:

```typescript
// 새 컬럼 추가
try {
  database.exec(`ALTER TABLE messages ADD COLUMN is_bot_message INTEGER DEFAULT 0`);
  // 기존 데이터 backfill
  database.prepare(`UPDATE messages SET is_bot_message = 1 WHERE content LIKE ?`).run(`${ASSISTANT_NAME}:%`);
} catch {
  /* column already exists - 무시 */
}
```

### 마이그레이션 이력

| 컬럼/변경 | 테이블 | 설명 |
|----------|--------|------|
| `context_mode` | scheduled_tasks | 태스크 컨텍스트 모드 |
| `is_bot_message` | messages | 봇 메시지 플래그 + backfill |
| `is_main` | registered_groups | 메인 그룹 플래그 + backfill |
| `channel`, `is_group` | chats | 채널 유형 및 그룹 여부 + JID 패턴 backfill |

## JSON → SQLite 마이그레이션

레거시 JSON 파일이 존재하면 자동으로 SQLite로 마이그레이션:

```typescript
function migrateJsonState(): void {
  // router_state.json → router_state 테이블
  // sessions.json → sessions 테이블
  // registered_groups.json → registered_groups 테이블
  // 마이그레이션 후 .migrated 확장자로 리네임
}
```

## 주요 쿼리 패턴

### 새 메시지 조회 (Sliding Window)

```sql
SELECT * FROM (
  SELECT id, chat_jid, sender, sender_name, content, timestamp, is_from_me
  FROM messages
  WHERE timestamp > ? AND chat_jid IN (?, ?, ...)
    AND is_bot_message = 0 AND content NOT LIKE 'Andy:%'
    AND content != '' AND content IS NOT NULL
  ORDER BY timestamp DESC
  LIMIT 200
) ORDER BY timestamp
```

- 서브쿼리: 최신 200개 → 시간순 정렬
- 봇 메시지 이중 필터링 (플래그 + 레거시 패턴)

### 만기 태스크 조회

```sql
SELECT * FROM scheduled_tasks
WHERE status = 'active' AND next_run IS NOT NULL AND next_run <= ?
ORDER BY next_run
```

### 채팅 메타데이터 Upsert

```sql
INSERT INTO chats (jid, name, last_message_time, channel, is_group)
VALUES (?, ?, ?, ?, ?)
ON CONFLICT(jid) DO UPDATE SET
  name = excluded.name,
  last_message_time = MAX(last_message_time, excluded.last_message_time),
  channel = COALESCE(excluded.channel, channel),
  is_group = COALESCE(excluded.is_group, is_group)
```

- `MAX()`로 시간 역행 방지
- `COALESCE()`로 null 값 보존

## ER 다이어그램

```
┌─────────────────┐      ┌──────────────────┐
│     chats       │      │    messages       │
├─────────────────┤      ├──────────────────┤
│ jid (PK)        │◄─────│ chat_jid (FK)     │
│ name            │      │ id (PK)           │
│ last_message_time│      │ sender            │
│ channel         │      │ sender_name       │
│ is_group        │      │ content           │
└─────────────────┘      │ timestamp         │
                         │ is_from_me        │
                         │ is_bot_message    │
                         └──────────────────┘

┌─────────────────────┐      ┌──────────────────┐
│  scheduled_tasks     │      │  task_run_logs    │
├─────────────────────┤      ├──────────────────┤
│ id (PK)             │◄─────│ task_id (FK)      │
│ group_folder        │      │ id (PK, auto)     │
│ chat_jid            │      │ run_at            │
│ prompt              │      │ duration_ms       │
│ schedule_type       │      │ status            │
│ schedule_value      │      │ result            │
│ context_mode        │      │ error             │
│ next_run            │      └──────────────────┘
│ last_run            │
│ last_result         │
│ status              │
│ created_at          │
└─────────────────────┘

┌─────────────────┐  ┌──────────────────┐  ┌─────────────────────┐
│  router_state   │  │    sessions      │  │ registered_groups    │
├─────────────────┤  ├──────────────────┤  ├─────────────────────┤
│ key (PK)        │  │ group_folder(PK) │  │ jid (PK)            │
│ value           │  │ session_id       │  │ name                │
└─────────────────┘  └──────────────────┘  │ folder (UNIQUE)     │
                                            │ trigger_pattern     │
                                            │ added_at            │
                                            │ container_config    │
                                            │ requires_trigger    │
                                            │ is_main             │
                                            └─────────────────────┘
```
