# Microsoft Foundry Q&A

## Q1. Application Insights는 Foundry 프로젝트 단위로 연결하나요, 에이전트별로도 연결할 수 있나요?

**Foundry의 기본 서버 측 추적 연결은 프로젝트 단위입니다.** 같은 프로젝트의 에이전트는 연결된 Application Insights 리소스로 추적 데이터를 보냅니다. 기본 연결에서 에이전트마다 별도의 리소스를 지정하는 방식은 아닙니다.

- **에이전트별 조회는 가능합니다.** 모니터링 대시보드에서 특정 에이전트의 데이터를 따로 볼 수 있지만, 저장 리소스가 분리되는 것은 아닙니다.
- **직접 계측한 클라이언트 코드는 별도 전송 대상을 설정할 수 있습니다.** 다만 이 설정은 Foundry가 자동 수집하는 서버 측 추적의 전송 대상을 바꾸지는 않습니다.

참고 문서:

- [Foundry 에이전트 추적 설정](https://learn.microsoft.com/en-us/azure/foundry/observability/how-to/trace-agent-setup)
- [에이전트 모니터링 대시보드](https://learn.microsoft.com/en-us/azure/foundry/observability/how-to/how-to-monitor-agents-dashboard)

## Q2. 모델별 입력·출력 토큰 사용량은 Foundry가 기본 수집하나요, 아니면 Application Insights가 필요한가요?

**기본적인 모델·배포별 토큰 집계를 확인하는 데 Application Insights는 필수가 아닙니다.** Azure OpenAI 모델 배포는 Azure Monitor가 입력·출력 토큰 지표를 자동 수집합니다. 모델명·배포명으로 구분해 볼 수 있으며, Foundry의 모델 배포 메트릭 화면이나 Azure Monitor에서 확인할 수 있습니다.

| 확인하려는 정보 | 확인 방법 | Application Insights |
| --- | --- | --- |
| 모델·배포별 입력·출력 토큰 집계 | Azure Monitor의 `ProcessedPromptTokens`·`GeneratedTokens` | 불필요 |
| 모델 호출 한 건의 토큰 사용량 | API 응답의 `usage` 정보 | 불필요 |
| Foundry 대시보드에서 에이전트별 토큰 사용량·실행 추적 조회 | 프로젝트에 연결된 Application Insights | 필요 |

기본 모델 지표만으로는 같은 배포를 이용하는 여러 에이전트의 사용량을 나눠 볼 수 없습니다. 또한 위 토큰 지표는 **Azure OpenAI 배포 기준**이며, 파트너·외부 호스팅 모델은 지원 지표를 별도로 확인해야 합니다. API 응답의 토큰 필드도 API·모델에 따라 다를 수 있습니다.

참고 문서:

- [Foundry 모델 배포 모니터링](https://learn.microsoft.com/en-us/azure/foundry/foundry-models/how-to/monitor-models)
- [Azure OpenAI 모니터링 지표와 구분 항목](https://learn.microsoft.com/en-us/azure/foundry/openai/monitor-openai-reference)
- [Azure OpenAI Chat Completions API 응답](https://learn.microsoft.com/en-us/rest/api/microsoft-foundry/azureopenai/chat)
- [에이전트 모니터링 대시보드](https://learn.microsoft.com/en-us/azure/foundry/observability/how-to/how-to-monitor-agents-dashboard)

## Q3. 프로젝트 연결과 SDK로 수집하는 추적은 어떻게 다르며, 무엇을 먼저 적용하고 어떻게 통합하나요?

**서버 측 추적은 Foundry 내부 실행을, SDK의 클라이언트 측 추적은 애플리케이션 코드의 실행을 보여줍니다. 둘은 대체 관계가 아니라 보완 관계입니다.**

| 구분 | 서버 측: 프로젝트에 Application Insights 연결 | 클라이언트 측: Foundry SDK·OpenTelemetry 계측 |
| --- | --- | --- |
| 수집 방식 | 연결 후 서비스가 자동 수집. 애플리케이션 코드 변경 불필요 | 코드에서 계측을 활성화하고 추적 데이터를 내보내도록 설정 |
| 주요 범위 | 서비스 내부의 에이전트·모델·도구 실행, 토큰 사용량, 지연 시간, 오류 | SDK·프레임워크가 지원하는 호출과 직접 계측한 사용자 정의 로직 |
| 적합한 경우 | 에이전트 내부에서 어느 단계가 느리거나 실패했는지 확인 | 요청 전처리·후처리, 자체 도구·외부 의존성까지 포함한 전체 흐름 분석과 로컬 디버깅 |

클라이언트 계측도 모든 함수나 DB 호출을 자동으로 기록하지는 않습니다. 필요한 구간에 계측을 추가해야 합니다. 또한 여기서 클라이언트는 **애플리케이션·코드 측**을 뜻하며, Hosted Agent라면 그 코드가 Foundry 안에서 실행될 수도 있습니다.

### 적용 우선순위

**Foundry 관리형 에이전트는 서버 측 추적부터 적용하고, 운영 애플리케이션에는 클라이언트 계측을 추가하는 순서를 권장합니다.** 서버 측만으로 빠르게 내부 상태를 확인하고, 이후 사용자 요청부터 에이전트 응답까지의 전체 지연·오류를 연결해 분석할 수 있습니다. 로컬·외부 에이전트나 자체 코드 중심의 서비스라면 SDK·프레임워크 계측부터 시작하는 편이 적합합니다. 필수 순서는 아닙니다.

### 통합 방법

1. **프로젝트에 Application Insights를 연결**해 서버 측 추적을 활성화합니다.
2. **앱에서 Foundry SDK·OpenTelemetry 계측을 활성화**하고, 내보내기 대상을 프로젝트와 **같은 Application Insights 리소스**로 설정합니다.
3. **사용자 요청을 나타내는 상위 span 안에서 에이전트를 호출**하고, 지원 SDK/API가 W3C Trace Context(`traceparent` 등)를 서버로 전파하도록 설정합니다. SDK별 계측 초기화 순서도 맞춰야 합니다.
4. Foundry와 Application Insights에서 **같은 trace ID·operation ID로 연결되는지, 서버·클라이언트 span이 부모·자식 관계로 보이는지 확인**합니다.

**같은 Application Insights로 전송하는 것만으로는 하나의 추적으로 합쳐지지 않습니다.** 호출 경계를 넘어 추적 컨텍스트가 전달되어야 합니다. 공식 클라이언트 계측 예제는 `get_openai_client()`와 Responses API 기준이므로, 다른 API·언어 SDK는 전파 지원과 설정을 별도로 확인해야 합니다.

참고 문서:

- [Foundry 추적 설정(서버 측/클라이언트 측 선택)](https://learn.microsoft.com/en-us/azure/foundry/observability/how-to/trace-agent-setup)
- [Foundry 에이전트에 클라이언트 측 추적 추가](https://learn.microsoft.com/en-us/azure/foundry/observability/how-to/trace-agent-client-side)
- [에이전트 추적 개요(핵심 개념)](https://learn.microsoft.com/en-us/azure/foundry/observability/concepts/trace-agent-concept)
- [호스팅 에이전트란?](https://learn.microsoft.com/en-us/azure/foundry/agents/concepts/hosted-agents)

## Q4. 한 요청의 반복 실행과 멀티턴 대화는 어떻게 묶어 추적하나요? 서버 측 추적만으로 충분한가요?

**Foundry 서비스 내부에서 처리되는 한 번의 실행은 서버 측 추적만으로 묶을 수 있으므로, 클라이언트 계측이 항상 필수는 아닙니다.** 서버 측 추적이 지원하는 모델·도구 반복은 하나의 상위 span 아래 자식 span으로 기록됩니다. 다만 **사용자 요청 한 번이 곧 API 호출 한 번이라는 뜻은 아닙니다.**

| 반복 실행이 이루어지는 곳 | 하나의 trace ID로 묶는 방법 | 클라이언트 계측 |
| --- | --- | --- |
| Foundry가 서버 내부에서 처리하는 모델·도구 반복 | 프로젝트의 Application Insights 연결로 수집되는 상위·자식 span 확인 | 서버 내부 실행 조회에는 필수 아님 |
| 앱이 직접 도구를 실행하고 출력을 제출하거나, 에이전트·API를 여러 번 호출 | **전체 루프를 감싸는 활성 상위 span 하나**를 만들고 모든 호출에 `traceparent` 등 추적 컨텍스트 전파 | 여러 호출과 앱 코드를 함께 묶으려면 필요 |

SDK 계측이나 내보내기 설정만 추가한다고 여러 호출이 자동으로 합쳐지지는 않습니다. 비동기 콜백·별도 작업으로 넘어갈 때도 같은 추적 컨텍스트가 이어져야 합니다. Hosted Agent의 자체 코드 안에서 구현한 반복·도구 처리도 서비스의 자동 수집 범위와 구분해야 합니다.

### 멀티턴 대화는 어떻게 묶나요?

**턴마다 별도의 trace를 만들고, 같은 Conversation ID로 여러 trace를 묶어 조회하는 방식을 권장합니다.** 대화 전체를 하나의 긴 span으로 유지하거나 trace ID를 임의로 재사용할 필요는 없습니다.

1. **대화 상태를 유지합니다.** Responses/Conversations API에서는 Conversation을 생성하고 각 턴에 `conversation=conversation.id`를 전달합니다. Foundry classic에서는 같은 `thread_id`를 사용합니다. `previous_response_id`로 응답을 연결하는 것은 별도 방식이며, Conversation ID와 동일하지 않습니다.
2. **추적 데이터에도 대화 식별자가 있는지 확인합니다.** 서버 추적에 `conversation_id`가 기록되고 Conversation 조회가 지원되는 경우에는 클라이언트 계측 없이도 대화별로 묶어 볼 수 있습니다. 모든 API·SDK에서 자동으로 기록되는 것은 아닙니다.
3. **식별자가 빠지거나 앱 코드까지 연결해야 하면 클라이언트 계측을 보완합니다.** 각 턴의 span에 같은 대화 식별자를 속성으로 기록하고 Application Insights에서 그 값으로 조회합니다. 임의의 사용자 정의 속성만 추가했다고 Foundry의 Conversation 화면에도 자동으로 연결되는 것은 아닙니다.

정리하면 **한 실행 안의 연결은 추적 컨텍스트 전파**, **여러 턴 사이의 연결은 공통 대화 식별자**가 담당합니다. 같은 Application Insights로 전송하거나 같은 Conversation ID를 쓰는 것만으로 trace ID까지 같아지지는 않습니다.

참고 문서:

- [에이전트 추적 개요(핵심 개념)](https://learn.microsoft.com/en-us/azure/foundry/observability/concepts/trace-agent-concept)
- [Foundry 추적 설정 – Conversation 결과 보기](https://learn.microsoft.com/en-us/azure/foundry/observability/how-to/trace-agent-setup#view-conversation-results)
- [Foundry 에이전트 클라이언트 측 추적 – 커스텀 span 속성](https://learn.microsoft.com/en-us/azure/foundry/observability/how-to/trace-agent-client-side)
- [트레이스의 conversation ID로 대화 평가](https://learn.microsoft.com/en-us/azure/foundry/observability/how-to/cloud-evaluation-deployed-conversations)
- [에이전트·대화·응답 런타임 구성요소](https://learn.microsoft.com/en-us/azure/foundry/agents/concepts/runtime-components)
