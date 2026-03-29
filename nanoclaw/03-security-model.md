# 03. 보안 모델

> 📊 보안 계층 다이어그램: [diagrams/security-layers.excalidraw](./diagrams/security-layers.excalidraw)

## 신뢰 모델

| 엔티티 | 신뢰 수준 | 근거 |
|--------|----------|------|
| 메인 그룹 | **신뢰됨** | 사용자의 개인 채팅(self-chat), 관리 권한 |
| 비메인 그룹 | **비신뢰** | 다른 사용자가 악의적일 수 있음 |
| 컨테이너 에이전트 | **샌드박스됨** | 격리된 실행 환경 |
| 메시징 입력 | **사용자 입력** | 프롬프트 인젝션 가능 |

## 보안 경계 5계층

### 계층 1: 컨테이너 격리 (Primary Boundary)

에이전트는 Docker 컨테이너(경량 Linux VM)에서 실행된다:

- **프로세스 격리**: 컨테이너 프로세스가 호스트에 영향 불가
- **파일시스템 격리**: 명시적으로 마운트된 디렉토리만 접근 가능
- **비루트 실행**: 권한 없는 `node` 사용자(uid 1000)로 실행
- **임시 컨테이너**: 호출마다 새 환경 (`--rm` 플래그)
- **네트워크**: 무제한 (API 호출 필요)

```dockerfile
USER node                  # 비루트 실행
WORKDIR /workspace/group   # 제한된 작업 디렉토리
```

### 계층 2: 크레덴셜 격리 (Credential Proxy)

**실제 API 키는 절대 컨테이너에 들어가지 않는다.**

```
┌──────────────┐    placeholder key    ┌──────────────┐    real key    ┌──────────────┐
│  Container   │ ────────────────────→ │  Credential  │ ────────────→ │  Anthropic   │
│  Agent       │                       │  Proxy       │               │  API         │
│              │ ←──────────────────── │  (:3001)     │ ←──────────── │              │
└──────────────┘    response           └──────────────┘               └──────────────┘
```

**컨테이너에 설정되는 환경변수:**
```bash
ANTHROPIC_BASE_URL=http://host.docker.internal:3001
ANTHROPIC_API_KEY=placeholder           # API key 모드
CLAUDE_CODE_OAUTH_TOKEN=placeholder     # OAuth 모드
```

**접근 불가능한 것들:**
- `.env` 파일 → `/dev/null`로 섀도잉됨
- `process.env` → 비밀 값 미로드 (`readEnvFile()`은 반환만 함)
- `/proc` → 컨테이너 격리로 호스트 프로세스 정보 접근 불가

### 계층 3: 마운트 보안

**외부 허용 목록** (`~/.config/nanoclaw/mount-allowlist.json`):
- 프로젝트 루트 **외부**에 저장
- 컨테이너에 **절대 마운트되지 않음**
- 에이전트가 수정 **불가능**

**기본 차단 패턴** (DEFAULT_BLOCKED_PATTERNS):
```
.ssh, .gnupg, .gpg, .aws, .azure, .gcloud, .kube, .docker,
credentials, .env, .netrc, .npmrc, .pypirc,
id_rsa, id_ed25519, private_key, .secret
```

**검증 프로세스:**
```
1. 컨테이너 경로 검증 (.. 금지, 절대 경로 금지)
2. 호스트 경로 확장 (~ → /home/user)
3. 심볼릭 링크 해제 (realpathSync) → 탈출 공격 방지
4. 차단 패턴 매칭
5. 허용 루트 확인
6. 읽기/쓰기 권한 결정
```

**허용 목록 예시:**
```json
{
  "allowedRoots": [
    { "path": "~/projects", "allowReadWrite": true, "description": "개발 프로젝트" },
    { "path": "~/Documents", "allowReadWrite": false, "description": "문서 (읽기전용)" }
  ],
  "blockedPatterns": ["password", "token"],
  "nonMainReadOnly": true
}
```

### 계층 4: IPC 인가

파일 기반 IPC에서 그룹의 디렉토리 경로가 신원(identity) 역할:

| 작업 | 메인 그룹 | 비메인 그룹 |
|------|----------|------------|
| 자기 채팅에 메시지 전송 | ✅ | ✅ |
| 다른 채팅에 메시지 전송 | ✅ | ❌ |
| 자기 그룹 태스크 관리 | ✅ | ✅ |
| 다른 그룹 태스크 관리 | ✅ | ❌ |
| 그룹 등록 | ✅ | ❌ |
| 그룹 새로고침 | ✅ | ❌ |
| `isMain` 설정 | ❌ (방어) | ❌ |

**IPC 인가 코드 예시:**
```typescript
if (isMain || (targetGroup && targetGroup.folder === sourceGroup)) {
  await deps.sendMessage(data.chatJid, data.text);
} else {
  logger.warn('Unauthorized IPC message attempt blocked');
}
```

### 계층 5: 세션 격리

각 그룹은 격리된 Claude 세션을 가진다:

```
data/sessions/
├── main/.claude/          # 메인 그룹 세션
├── whatsapp_family/.claude/   # 가족 그룹 세션
└── telegram_work/.claude/     # 업무 그룹 세션
```

- 그룹 간 대화 이력 접근 불가
- 세션 데이터에는 전체 메시지 이력과 읽은 파일 내용 포함
- 교차 그룹 정보 유출 방지

## 프로젝트 루트 읽기전용 마운트

메인 그룹의 프로젝트 루트는 **읽기전용**으로 마운트된다:

```typescript
mounts.push({
  hostPath: projectRoot,
  containerPath: '/workspace/project',
  readonly: true,  // ← 중요!
});
```

**이유**: 에이전트가 `src/`, `dist/`, `package.json` 등 호스트 코드를 수정할 수 있으면, 다음 재시작 시 샌드박스를 우회하는 악성 코드가 실행될 수 있다. 에이전트가 쓰기 필요한 경로(그룹 폴더, IPC, `.claude/`)는 별도 마운트로 제공된다.

## 발신자 허용 목록

채팅별로 메시지 발신자를 필터링하는 추가 보안 레이어:

```json
{
  "default": { "allow": "*", "mode": "trigger" },
  "chats": {
    "group-jid@g.us": {
      "allow": ["user1@s.whatsapp.net", "user2@s.whatsapp.net"],
      "mode": "trigger"
    }
  },
  "logDenied": true
}
```

| 모드 | 허용된 발신자 | 비허용 발신자 |
|------|-------------|-------------|
| `trigger` | 메시지 저장 + 트리거 가능 | 메시지 저장, 트리거 불가 |
| `drop` | 메시지 저장 + 트리거 가능 | 메시지 완전 삭제 |

> `is_from_me` (자기 메시지)는 허용 목록을 우회한다.

## 보안 아키텍처 전체 다이어그램

```
┌─────────────────────────────────────────────────────────────────┐
│                      UNTRUSTED ZONE                              │
│  WhatsApp/Telegram/Discord 메시지 (잠재적 악의)                    │
└───────────────────────────┬─────────────────────────────────────┘
                            │
                            ▼ 트리거 검사, 발신자 필터링, 입력 이스케이프
┌─────────────────────────────────────────────────────────────────┐
│                    HOST PROCESS (TRUSTED)                         │
│  • 메시지 라우팅 및 저장                                           │
│  • IPC 인가 검사                                                  │
│  • 마운트 보안 검증 (외부 허용 목록)                                 │
│  • 컨테이너 라이프사이클 관리                                       │
│  • 크레덴셜 프록시 (인증 헤더 주입)                                  │
└───────────────────────────┬─────────────────────────────────────┘
                            │
                            ▼ 명시적 마운트만, 비밀 정보 없음
┌─────────────────────────────────────────────────────────────────┐
│                 CONTAINER (ISOLATED/SANDBOXED)                    │
│  • Claude Agent SDK 실행                                         │
│  • Bash 명령 (샌드박스 내)                                        │
│  • 파일 조작 (마운트된 경로만)                                      │
│  • API 호출은 크레덴셜 프록시 경유                                  │
│  • 환경/파일시스템에 실제 크레덴셜 없음                               │
└─────────────────────────────────────────────────────────────────┘
```
