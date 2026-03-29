# NanoClaw 프로젝트 분석 문서

> **Repository**: https://github.com/qwibitai/nanoclaw
> **Version**: 1.2.15 | **License**: MIT | **Runtime**: Node.js 20+ (TypeScript)
> **분석 기준일**: 2026-03-18

---

## NanoClaw란?

NanoClaw는 **개인용 Claude AI 어시스턴트**로, 에이전트를 각각의 **컨테이너(Docker/Apple Container)에서 격리 실행**하는 경량 오픈소스 프로젝트이다. [OpenClaw](https://github.com/openclaw/openclaw)의 핵심 기능을 수천 줄 규모의 이해 가능한 코드베이스로 재구현한 것이 특징이다.

### 핵심 철학

| 원칙 | 설명 |
|------|------|
| **Small enough to understand** | 하나의 프로세스, 소수의 소스 파일, 마이크로서비스 없음 |
| **Secure by isolation** | 에이전트가 Linux 컨테이너에서 실행, 명시적 마운트만 접근 가능 |
| **Built for the individual** | 포크 후 자유롭게 커스터마이징하는 bespoke 소프트웨어 |
| **AI-native** | 설치·모니터링·디버깅 모두 Claude Code로 수행 |
| **Skills over features** | 기능 추가가 아닌 Claude Code 스킬(브랜치)로 확장 |

### 한 줄 아키텍처

```
Channels ──→ SQLite ──→ Polling Loop ──→ Container (Claude Agent SDK) ──→ Response
```

---

## 문서 목차

| 파일 | 내용 |
|------|------|
| [01-architecture-overview.md](./01-architecture-overview.md) | 전체 아키텍처 및 시스템 구조 |
| [02-module-details.md](./02-module-details.md) | 소스 모듈별 상세 분석 |
| [03-security-model.md](./03-security-model.md) | 보안 모델 및 격리 계층 |
| [04-message-flow.md](./04-message-flow.md) | 메시지 처리 파이프라인 |
| [05-container-system.md](./05-container-system.md) | 컨테이너 격리 및 실행 시스템 |
| [06-channel-system.md](./06-channel-system.md) | 채널 추상화 및 레지스트리 |
| [07-ipc-and-scheduling.md](./07-ipc-and-scheduling.md) | IPC 시스템과 태스크 스케줄링 |
| [08-database-schema.md](./08-database-schema.md) | SQLite 데이터베이스 스키마 |

### Excalidraw 다이어그램

| 파일 | 내용 |
|------|------|
| [diagrams/architecture-overview.excalidraw](./diagrams/architecture-overview.excalidraw) | 전체 아키텍처 다이어그램 |
| [diagrams/message-flow.excalidraw](./diagrams/message-flow.excalidraw) | 메시지 처리 흐름 |
| [diagrams/module-dependencies.excalidraw](./diagrams/module-dependencies.excalidraw) | 모듈 의존성 관계도 |
| [diagrams/security-layers.excalidraw](./diagrams/security-layers.excalidraw) | 보안 계층 다이어그램 |
| [diagrams/container-lifecycle.excalidraw](./diagrams/container-lifecycle.excalidraw) | 컨테이너 라이프사이클 |

---

## 기술 스택

| 분류 | 기술 |
|------|------|
| Language | TypeScript (ESM) |
| Runtime | Node.js 20+ |
| Database | SQLite (better-sqlite3) |
| AI SDK | Claude Agent SDK (`@anthropic-ai/claude-code`) |
| Container | Docker / Apple Container |
| Logging | Pino + pino-pretty |
| Scheduling | cron-parser |
| Validation | Zod |
| Testing | Vitest |
| Formatting | Prettier + Husky |

## 주요 의존성 (package.json)

```json
{
  "dependencies": {
    "better-sqlite3": "^11.8.1",
    "cron-parser": "^5.5.0",
    "pino": "^9.6.0",
    "pino-pretty": "^13.0.0",
    "yaml": "^2.8.2",
    "zod": "^4.3.6"
  }
}
```

> 의존성 수가 6개로 극히 적다. 이는 "이해 가능한 코드베이스"를 지향하는 프로젝트 철학을 반영한다.

## 프로젝트 디렉토리 구조

```
nanoclaw/
├── src/                      # 호스트 프로세스 소스 코드
│   ├── index.ts              # 오케스트레이터 (메인 엔트리포인트)
│   ├── config.ts             # 설정 상수 정의
│   ├── types.ts              # TypeScript 타입 정의
│   ├── db.ts                 # SQLite 데이터베이스 레이어
│   ├── container-runner.ts   # 컨테이너 에이전트 스폰 및 관리
│   ├── container-runtime.ts  # 런타임 추상화 (Docker/Apple Container)
│   ├── credential-proxy.ts   # 크레덴셜 프록시 서버
│   ├── group-queue.ts        # 그룹별 메시지 큐 및 동시성 제어
│   ├── group-folder.ts       # 그룹 폴더 경로 검증
│   ├── ipc.ts                # IPC 파일 감시 및 처리
│   ├── mount-security.ts     # 마운트 보안 검증
│   ├── router.ts             # 메시지 포맷팅 및 라우팅
│   ├── remote-control.ts     # 원격 제어 세션
│   ├── sender-allowlist.ts   # 발신자 허용 목록
│   ├── task-scheduler.ts     # 스케줄 태스크 실행
│   ├── env.ts                # .env 파일 파서
│   ├── logger.ts             # Pino 로거 설정
│   ├── timezone.ts           # 타임존 유틸리티
│   └── channels/             # 채널 시스템
│       ├── index.ts          # 배럴 파일 (자동 등록)
│       └── registry.ts       # 채널 레지스트리
├── container/                # 에이전트 컨테이너
│   ├── Dockerfile            # 에이전트 컨테이너 이미지
│   ├── build.sh              # 빌드 스크립트
│   ├── agent-runner/         # 컨테이너 내부 에이전트 러너
│   │   ├── src/index.ts      # 에이전트 실행 로직
│   │   └── src/ipc-mcp-stdio.ts  # MCP stdio IPC
│   └── skills/               # 에이전트에 제공되는 스킬
├── groups/                   # 그룹별 메모리/파일 저장
│   ├── main/CLAUDE.md        # 메인 그룹 메모리 (관리자)
│   └── global/CLAUDE.md      # 전역 공유 메모리
├── docs/                     # 프로젝트 문서
├── config-examples/          # 설정 예제
├── scripts/                  # 유틸리티 스크립트
├── setup/                    # 셋업 스크립트
├── store/                    # SQLite DB 저장 (런타임 생성)
└── data/                     # IPC, 세션 데이터 (런타임 생성)
```
