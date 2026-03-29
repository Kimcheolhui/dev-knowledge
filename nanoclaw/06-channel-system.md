# 06. 채널 시스템

## 채널 추상화

NanoClaw는 플러그인 방식의 채널 시스템을 사용한다. 핵심은 `Channel` 인터페이스와 자동 등록 메커니즘이다.

## Channel 인터페이스 (types.ts)

```typescript
export interface Channel {
  name: string;
  connect(): Promise<void>;
  sendMessage(jid: string, text: string): Promise<void>;
  isConnected(): boolean;
  ownsJid(jid: string): boolean;
  disconnect(): Promise<void>;
  setTyping?(jid: string, isTyping: boolean): Promise<void>;  // 선택적
  syncGroups?(force: boolean): Promise<void>;                  // 선택적
}
```

| 메서드 | 필수 | 설명 |
|--------|------|------|
| `connect()` | ✅ | 채널 연결 (인증, WebSocket 등) |
| `sendMessage()` | ✅ | 특정 JID에 메시지 전송 |
| `isConnected()` | ✅ | 연결 상태 확인 |
| `ownsJid()` | ✅ | 이 채널이 해당 JID를 소유하는지 판단 |
| `disconnect()` | ✅ | 연결 해제 |
| `setTyping()` | ❌ | 타이핑 인디케이터 (지원하는 채널만) |
| `syncGroups()` | ❌ | 그룹/채팅 메타데이터 동기화 |

## 자동 등록 메커니즘

### 등록 흐름

```
1. src/channels/index.ts (배럴 파일)에서 채널 모듈 import
2. 각 채널 모듈이 import 시점에 registerChannel() 호출
3. index.ts의 main()에서 getRegisteredChannelNames() 순회
4. 각 팩토리 호출 → 크레덴셜 없으면 null 반환 → 스킵
5. 유효한 채널만 channels[] 배열에 추가
```

### 레지스트리 코드 (channels/registry.ts)

```typescript
const registry = new Map<string, ChannelFactory>();

export function registerChannel(name: string, factory: ChannelFactory): void {
  registry.set(name, factory);
}

export function getChannelFactory(name: string): ChannelFactory | undefined {
  return registry.get(name);
}

export function getRegisteredChannelNames(): string[] {
  return [...registry.keys()];
}
```

### ChannelFactory 시그니처

```typescript
export interface ChannelOpts {
  onMessage: OnInboundMessage;        // 메시지 수신 콜백
  onChatMetadata: OnChatMetadata;     // 메타데이터 업데이트
  registeredGroups: () => Record<string, RegisteredGroup>;  // 등록된 그룹 조회
}

export type ChannelFactory = (opts: ChannelOpts) => Channel | null;
```

**`null` 반환 패턴**: 크레덴셜이 설정되지 않으면 `null`을 반환하여 해당 채널을 비활성화. 에러를 발생시키지 않으므로 사용하지 않는 채널은 자동 스킵.

### 배럴 파일 (channels/index.ts)

```typescript
// Channel self-registration barrel file.
// Each import triggers the channel module's registerChannel() call.

// discord
// gmail
// slack
// telegram
// whatsapp
```

> 기본 코드베이스에는 채널 구현이 포함되어 있지 않다. 각 채널은 스킬(`/add-whatsapp`, `/add-telegram` 등)로 추가된다.

## 채널 콜백 처리 (index.ts)

```typescript
const channelOpts = {
  onMessage: (chatJid: string, msg: NewMessage) => {
    // 1. /remote-control 명령 인터셉트
    // 2. 발신자 허용 목록 drop 모드 처리
    // 3. storeMessage(msg) → SQLite 저장
  },
  onChatMetadata: (chatJid, timestamp, name?, channel?, isGroup?) => {
    storeChatMetadata(chatJid, timestamp, name, channel, isGroup);
  },
  registeredGroups: () => registeredGroups,
};
```

## JID (Chat Identifier) 규칙

각 채널은 고유한 JID 형식을 사용:

| 채널 | JID 예시 | 그룹 패턴 |
|------|----------|----------|
| WhatsApp | `120363336345@g.us` | `*@g.us` |
| WhatsApp (1:1) | `821012345678@s.whatsapp.net` | `*@s.whatsapp.net` |
| Discord | `dc:123456789` | `dc:*` |
| Telegram | `tg:123456789` | `tg:*` |
| Slack | `slack:C0123456789` | `slack:*` |
| Gmail | `gmail:*` | `gmail:*` |

### ownsJid() 구현 패턴

각 채널은 `ownsJid()`에서 자신의 JID 패턴을 매칭:

```typescript
// WhatsApp 예시
ownsJid(jid: string): boolean {
  return jid.endsWith('@g.us') || jid.endsWith('@s.whatsapp.net');
}

// Discord 예시
ownsJid(jid: string): boolean {
  return jid.startsWith('dc:');
}
```

## 메시지 라우팅

### findChannel()

```typescript
export function findChannel(channels: Channel[], jid: string): Channel | undefined {
  return channels.find((c) => c.ownsJid(jid));
}
```

에이전트 응답 전송 시:

```typescript
const channel = findChannel(channels, chatJid);
if (!channel) {
  logger.warn({ chatJid }, 'No channel owns JID, cannot send message');
  return;
}
await channel.sendMessage(chatJid, text);
```

## 채널 추가 방법 (스킬 시스템)

NanoClaw의 철학에 따라, 채널은 코드 변경(스킬)으로 추가한다:

```bash
# Claude Code에서
/add-whatsapp   # WhatsApp 채널 추가 스킬
/add-telegram   # Telegram 채널 추가 스킬
/add-discord    # Discord 채널 추가 스킬
/add-slack      # Slack 채널 추가 스킬
/add-gmail      # Gmail 채널 추가 스킬
```

스킬 실행 시:
1. 채널 소스 코드가 `src/channels/`에 추가됨
2. `channels/index.ts` 배럴에 import 추가됨
3. 필요한 의존성이 `package.json`에 추가됨
4. `.env`에 크레덴셜 설정 안내

## 그레이스풀 셧다운

```typescript
const shutdown = async (signal: string) => {
  proxyServer.close();
  await queue.shutdown(10000);
  for (const ch of channels) await ch.disconnect();
  process.exit(0);
};
```

각 채널의 `disconnect()`가 순차 호출되어 정리 작업 수행.
