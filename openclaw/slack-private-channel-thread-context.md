# Slack Private 채널에서 쓰레드 첫 글이 Context에 누락되는 문제

## 증상

- Slack **공개 채널**에서는 쓰레드 댓글 세션에 이전 대화(쓰레드 첫 글 포함)가 context에 정상적으로 포함됨
- Slack **private 채널**에서는 쓰레드 댓글 세션에 쓰레드 첫 글이 context에 포함되지 않음
- 쓰레드 첫 글과 쓰레드 댓글은 서로 다른 세션에 속하지만, 정상적인 경우 댓글 세션에 이전 대화가 context로 주입됨

## 원인

Slack 봇 토큰에 `groups:history` 권한이 없으면 private 채널의 메시지 히스토리를 읽을 수 없다.

OpenClaw은 쓰레드 세션 시작 시 `thread.initialHistoryLimit` (기본값 20) 만큼 쓰레드 히스토리를 fetch하는데, `groups:history` 권한이 없으면 이 fetch가 실패하여 첫 글이 context에 포함되지 않는다.

공개 채널은 `channels:history`로 접근 가능하므로 문제가 발생하지 않는다.

## 해결 방법

Slack 앱 설정 → **OAuth & Permissions** → **Bot Token Scopes**에 `groups:history`를 추가한다.

## 시도했지만 근본 해결이 아닌 방법

### `thread.inheritParent: true` 설정

```json
{
  "channels": {
    "slack": {
      "thread": {
        "inheritParent": true
      }
    }
  }
}
```

이 설정은 쓰레드 세션이 **채널 세션의 히스토리 전체**를 상속하게 만든다. 결과적으로:

- 현재 쓰레드의 첫 글이 context에 포함되지만
- **다른 쓰레드의 첫 글과 봇의 첫 답변까지 함께 포함**됨
- 다른 쓰레드의 댓글은 포함되지 않음 (채널 레벨에 표시되지 않으므로)

현재 쓰레드의 내용만 context에 포함하고 싶다면 이 설정은 적합하지 않다.

## 관련 OpenClaw 설정 참고

| 설정 | 기본값 | 설명 |
|---|---|---|
| `channels.slack.thread.inheritParent` | `false` | 쓰레드 세션이 부모 채널 세션 히스토리를 상속할지 여부 |
| `channels.slack.thread.historyScope` | `"thread"` | 쓰레드 히스토리 범위 |
| `channels.slack.thread.initialHistoryLimit` | `20` | 쓰레드 세션 시작 시 fetch할 히스토리 수 |

## Slack 봇 권한 체크리스트 (채널 히스토리 관련)

- `channels:history` — 공개 채널 히스토리 읽기
- `groups:history` — **private 채널 히스토리 읽기** ← 이게 빠져있었음
- `im:history` — DM 히스토리 읽기
- `mpim:history` — 그룹 DM 히스토리 읽기
