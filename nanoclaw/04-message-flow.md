# 04. 메시지 처리 파이프라인

> 📊 메시지 흐름 다이어그램: [diagrams/message-flow.excalidraw](./diagrams/message-flow.excalidraw)

## 전체 메시지 수명 주기

```
[사용자] "@Andy 안녕하세요"
    │
    ▼
[Channel] onMessage(chatJid, msg)
    │
    ├── /remote-control 명령? → handleRemoteControl()
    ├── 발신자 drop 모드? → 메시지 삭제
    │
    ▼
[db.ts] storeMessage(msg) → SQLite messages 테이블
    │
    ▼ (2초 후 폴링)
[index.ts] startMessageLoop()
    │
    ├── getNewMessages(registeredJids, lastTimestamp)
    ├── 그룹별로 메시지 분류 (messagesByGroup)
    │
    ▼ (트리거 검사)
[Trigger Check]
    ├── 메인 그룹? → 항상 처리
    ├── requiresTrigger=false? → 항상 처리
    ├── @Andy로 시작? + 발신자 허용? → 처리
    └── 트리거 없음 → 스킵 (컨텍스트로 축적)
    │
    ▼
[Group Queue] 활성 컨테이너 존재?
    ├── Yes → sendMessage() → IPC input 파일 (후속 메시지)
    └── No  → enqueueMessageCheck() → 새 컨테이너 스폰
    │
    ▼
[container-runner.ts] runContainerAgent()
    │
    ├── buildVolumeMounts() → 마운트 구성
    ├── buildContainerArgs() → Docker CLI 인수
    ├── spawn(docker, args) → 컨테이너 시작
    ├── stdin.write(JSON.stringify(input)) → 프롬프트 전달
    │
    ▼
[Container: agent-runner]
    │
    ├── Claude Agent SDK 실행
    ├── MCP 도구 활용 (send_message, schedule_task 등)
    ├── IPC input 폴링 (후속 메시지)
    │
    ▼ (OUTPUT_START_MARKER...OUTPUT_END_MARKER)
[Streaming Output]
    │
    ├── onOutput 콜백 → <internal> 태그 제거
    ├── channel.sendMessage(chatJid, text) → 사용자에게 전송
    │
    ▼
[사용자] "응답 수신"
```

## 트리거 로직 상세

### 트리거 패턴

```typescript
// config.ts
export const TRIGGER_PATTERN = new RegExp(`^@${escapeRegex(ASSISTANT_NAME)}\\b`, 'i');
// 기본값: /^@Andy\b/i
```

### 트리거 필요 여부 결정

```typescript
const needsTrigger = !isMainGroup && group.requiresTrigger !== false;
```

| 그룹 유형 | `isMain` | `requiresTrigger` | 트리거 필요 |
|----------|----------|-------------------|-----------|
| 메인 그룹 | `true` | - | ❌ |
| 개인 채팅 | `false` | `false` | ❌ |
| 일반 그룹 | `false` | `true`(기본) | ✅ |

### 비트리거 메시지의 축적

트리거가 필요한 그룹에서 트리거 없는 메시지는:
1. DB에 저장됨
2. 메시지 루프에서는 스킵됨
3. 나중에 트리거가 오면 `getMessagesSince(lastAgentTimestamp)` 로 모두 포함

```
[10:00] User1: 오늘 날씨 좋다 ← 저장만, 처리 안됨
[10:01] User2: 맞아          ← 저장만, 처리 안됨
[10:02] User1: @Andy 날씨 알려줘 ← 트리거!
         → 에이전트에게 10:00, 10:01, 10:02 메시지 모두 전달
```

## 메시지 포맷팅

### 에이전트에게 전달되는 형식 (XML)

```xml
<context timezone="Asia/Seoul" />
<messages>
<message sender="John" time="Mar 18, 2026, 2:22 PM">오늘 날씨 좋다</message>
<message sender="Jane" time="Mar 18, 2026, 2:23 PM">맞아</message>
<message sender="John" time="Mar 18, 2026, 2:24 PM">@Andy 날씨 알려줘</message>
</messages>
```

- XML 이스케이프 적용 (`&`, `<`, `>`, `"`)
- 타임존 변환 (`Intl.DateTimeFormat`)
- 봇 메시지 필터링 (`is_bot_message = 0`)

### 에이전트 응답 처리

```
에이전트 출력: "날씨 정보입니다. <internal>API 호출 완료</internal> 서울은 맑음입니다."
                                    │
                             stripInternalTags()
                                    │
                                    ▼
사용자에게: "날씨 정보입니다.  서울은 맑음입니다."
```

## 커서 관리와 에러 복구

### 이중 커서 시스템

```
lastTimestamp          ← "전체적으로 본" 메시지 위치 (중복 폴링 방지)
lastAgentTimestamp[jid] ← "그룹별로 처리한" 메시지 위치 (재처리 지점)
```

### 에러 시 커서 롤백

```typescript
const previousCursor = lastAgentTimestamp[chatJid] || '';
lastAgentTimestamp[chatJid] = missedMessages[missedMessages.length - 1].timestamp;
saveState();

// ... 에이전트 실행 ...

if (hadError && !outputSentToUser) {
  // 아직 사용자에게 아무것도 보내지 않았으면 → 롤백하여 재시도 가능
  lastAgentTimestamp[chatJid] = previousCursor;
  saveState();
}
```

**핵심 결정**: 이미 출력이 사용자에게 전송된 후 에러가 발생하면 롤백하지 않는다. 롤백하면 재처리 시 중복 응답이 전송되기 때문이다.

### 시작 시 복구 (recoverPendingMessages)

프로세스 크래시 후 재시작 시:

```typescript
for (const [chatJid, group] of Object.entries(registeredGroups)) {
  const pending = getMessagesSince(chatJid, lastAgentTimestamp[chatJid], ASSISTANT_NAME);
  if (pending.length > 0) {
    queue.enqueueMessageCheck(chatJid);  // 미처리 메시지 재처리
  }
}
```

## 유휴 컨테이너 재사용 (Follow-up Message)

컨테이너가 실행 중일 때 새 메시지가 도착하면:

```
1. queue.sendMessage(chatJid, formatted)
2. → IPC input 디렉토리에 JSON 파일 쓰기
   data/ipc/{group}/input/{timestamp}.json
3. → 컨테이너 내 agent-runner가 파일 감지
4. → Claude SDK에 후속 메시지로 전달
5. → 새 응답 스트리밍
```

이를 통해 30분 유휴 타임아웃 동안 컨테이너 재생성 없이 대화를 계속할 수 있다.

## 봇 메시지 필터링

에이전트의 응답이 다시 에이전트에게 전달되는 것을 방지:

```sql
-- db.ts의 getNewMessages() 쿼리
WHERE is_bot_message = 0 AND content NOT LIKE '{botPrefix}:%'
```

- `is_bot_message` 플래그 (새 메시지)
- `content NOT LIKE 'Andy:%'` 패턴 (레거시 호환)
- 빈 메시지 필터링 (`content != '' AND content IS NOT NULL`)
