# 05. 컨테이너 시스템

> 📊 컨테이너 라이프사이클: [diagrams/container-lifecycle.excalidraw](./diagrams/container-lifecycle.excalidraw)

## 컨테이너 아키텍처

NanoClaw의 에이전트는 각각 독립된 Docker 컨테이너에서 실행된다. 컨테이너는 `node:22-slim` 기반의 커스텀 이미지(`nanoclaw-agent:latest`)를 사용한다.

### Dockerfile 구성

```
node:22-slim
├── Chromium + 시스템 의존성 (agent-browser용)
├── agent-browser (전역 설치)
├── @anthropic-ai/claude-code (전역 설치)
├── agent-runner (TypeScript 앱)
└── entrypoint.sh
```

### 컨테이너 내부 디렉토리 구조

```
/
├── app/                          # agent-runner 소스
│   ├── src/ → (bind mount)       # 그룹별 커스터마이징 가능한 소스
│   ├── node_modules/
│   └── entrypoint.sh
├── home/node/
│   └── .claude/ → (bind mount)   # Claude 세션 데이터
├── workspace/
│   ├── group/ → (bind mount)     # 그룹 작업 디렉토리 (rw)
│   ├── project/ → (bind mount)   # 프로젝트 루트 (ro, 메인만)
│   ├── global/ → (bind mount)    # 글로벌 메모리 (ro, 비메인만)
│   ├── extra/ → (bind mount)     # 추가 마운트
│   └── ipc/ → (bind mount)       # IPC 네임스페이스
│       ├── messages/             # 에이전트 → 호스트 메시지
│       ├── tasks/                # 에이전트 → 호스트 태스크
│       ├── input/                # 호스트 → 에이전트 후속 메시지
│       ├── current_tasks.json    # 태스크 스냅샷
│       └── available_groups.json # 그룹 목록
└── tmp/dist/                     # 컴파일된 agent-runner
```

## 컨테이너 라이프사이클

```
┌────────┐    docker run -i --rm    ┌──────────┐
│ Spawn  │ ──────────────────────→ │ Running  │
└────────┘                          └────┬─────┘
                                         │
                    ┌────────────────────┼────────────────────┐
                    │                    │                    │
                    ▼                    ▼                    ▼
             ┌───────────┐      ┌──────────────┐     ┌──────────────┐
             │ stdin에    │      │ Idle Wait    │     │ Timeout      │
             │ 프롬프트   │      │ (IPC input   │     │ (hard kill)  │
             │ 전송      │      │  대기중)      │     │              │
             └─────┬─────┘      └──────┬───────┘     └──────────────┘
                   │                    │
                   ▼                    ▼
             ┌───────────┐      ┌──────────────┐
             │ Claude SDK│      │ _close 파일   │
             │ 실행      │      │ 감지 → 종료   │
             └─────┬─────┘      └──────────────┘
                   │
                   ▼
             ┌───────────┐
             │ 결과 출력  │ → OUTPUT_START...OUTPUT_END
             │ (stdout)  │
             └─────┬─────┘
                   │
                   ▼
             ┌───────────┐
             │ Container │ → --rm으로 자동 정리
             │ Exit      │
             └───────────┘
```

### 1단계: 스폰

```typescript
const containerArgs = ['run', '-i', '--rm', '--name', containerName, ...];
const container = spawn('docker', containerArgs, { stdio: ['pipe', 'pipe', 'pipe'] });
```

- `-i`: stdin 연결 유지
- `--rm`: 종료 시 자동 삭제
- `--user ${hostUid}:${hostGid}`: 호스트 사용자 ID로 실행 (바인드 마운트 접근)

### 2단계: 입력 전달

```typescript
container.stdin.write(JSON.stringify(input));
container.stdin.end();
```

`ContainerInput`:
```typescript
interface ContainerInput {
  prompt: string;           // 포맷팅된 메시지 (XML)
  sessionId?: string;       // 이전 Claude 세션 ID
  groupFolder: string;      // 그룹 폴더 이름
  chatJid: string;          // 채팅 JID
  isMain: boolean;          // 메인 그룹 여부
  isScheduledTask?: boolean; // 스케줄 태스크 여부
  assistantName?: string;   // 어시스턴트 이름
}
```

### 3단계: Entrypoint 실행

```bash
#!/bin/bash
set -e
cd /app && npx tsc --outDir /tmp/dist 2>&1 >&2    # agent-runner 재컴파일
ln -s /app/node_modules /tmp/dist/node_modules      # 의존성 링크
chmod -R a-w /tmp/dist                               # 읽기전용으로 잠금
cat > /tmp/input.json                                # stdin → 파일
node /tmp/dist/index.js < /tmp/input.json            # 실행
```

> agent-runner 소스가 그룹별로 바인드 마운트되어 커스터마이징 가능. 매 실행마다 재컴파일하여 변경사항 반영.

### 4단계: Agent Runner 실행

컨테이너 내부의 `agent-runner/src/index.ts`가:

1. stdin에서 `ContainerInput` JSON 읽기
2. Claude Agent SDK (`@anthropic-ai/claude-code`) 초기화
3. MCP 서버 시작 (IPC 도구 제공: `send_message`, `schedule_task` 등)
4. 에이전트 실행 → 결과를 `OUTPUT_START_MARKER`/`OUTPUT_END_MARKER`로 감싸서 stdout 출력
5. IPC input 디렉토리 폴링하여 후속 메시지 처리
6. `_close` 센티널 파일 감지 시 종료

### 5단계: 스트리밍 출력

```
stdout: ...SDK 로그...---NANOCLAW_OUTPUT_START---
{"status":"success","result":"안녕하세요!","newSessionId":"abc-123"}
---NANOCLAW_OUTPUT_END---...더 많은 로그...
```

호스트의 container-runner가 실시간으로 파싱하여 `onOutput` 콜백 호출.

### 6단계: 종료 및 정리

- 정상 종료: exit code 0 → 성공
- 타임아웃: 하드 타임아웃 초과 → `docker stop` → SIGKILL
- 유휴 종료: `_close` 센티널 → 에이전트 자체 종료
- `--rm` 플래그로 컨테이너 자동 삭제

## 에이전트에게 제공되는 도구

### MCP Tools (ipc-mcp-stdio.ts)

| 도구 | 설명 |
|------|------|
| `send_message` | 즉시 메시지 전송 (작업 중 중간 응답) |
| `schedule_task` | 반복/일회성 태스크 스케줄링 |
| `pause_task` / `resume_task` | 태스크 일시정지/재개 |
| `cancel_task` | 태스크 취소 |
| `update_task` | 태스크 수정 |
| `register_group` | 새 그룹 등록 (메인만) |
| `refresh_groups` | 그룹 목록 새로고침 (메인만) |

### 기본 도구

- **Bash**: 컨테이너 내부에서 자유롭게 실행
- **파일 I/O**: 마운트된 디렉토리 내 읽기/쓰기
- **agent-browser**: Chromium 기반 웹 브라우징 자동화
- **Agent Swarms**: Claude Code의 서브에이전트 기능

## 그룹별 Agent Runner 커스터마이징

```
container/agent-runner/src/     ← 원본 소스
        │
        ▼ (최초 실행 시 복사)
data/sessions/{group}/agent-runner-src/  ← 그룹별 사본
        │
        ▼ (바인드 마운트)
/app/src  (컨테이너 내부)
        │
        ▼ (entrypoint에서 재컴파일)
/tmp/dist/  (실행 바이너리)
```

에이전트가 `/app/src/`를 수정하면 해당 그룹에만 적용된다. 다른 그룹의 agent-runner에는 영향이 없다.

## 클로드 세션 관리

```
data/sessions/{group}/.claude/
├── settings.json      ← 에이전트 설정 (swarms, memory 등)
├── skills/            ← container/skills/에서 동기화
└── ...                ← Claude Code 세션 파일
```

### settings.json 기본값

```json
{
  "env": {
    "CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS": "1",
    "CLAUDE_CODE_ADDITIONAL_DIRECTORIES_CLAUDE_MD": "1",
    "CLAUDE_CODE_DISABLE_AUTO_MEMORY": "0"
  }
}
```

## 고아 컨테이너 정리

시작 시 이전 실행의 고아 컨테이너를 정리:

```typescript
// container-runtime.ts
const output = execSync(`docker ps --filter name=nanoclaw- --format '{{.Names}}'`);
for (const name of orphans) {
  execSync(`docker stop ${name}`);
}
```
