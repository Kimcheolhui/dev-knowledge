# Microsoft Foundry Q&A

## Q1. Application Insights는 프로젝트 단위로 연결하나요, 에이전트별로도 가능한가요?

**Foundry의 기본 서버 측 추적은 프로젝트 단위로 연결합니다.** 같은 프로젝트의 에이전트는 연결된 Application Insights를 함께 사용합니다. 에이전트별로 필터링해 조회할 수 있지만, 각각 별도의 리소스로 연결하는 방식은 아닙니다.

참고: [추적 설정](https://learn.microsoft.com/en-us/azure/foundry/observability/how-to/trace-agent-setup) · [에이전트 대시보드](https://learn.microsoft.com/en-us/azure/foundry/observability/how-to/how-to-monitor-agents-dashboard)

## Q2. 모델·에이전트별 입력·출력 토큰은 어디서 확인하나요? Application Insights가 필요한가요?

**기본 토큰 집계와 개별 호출의 사용량에는 Application Insights가 필수가 아닙니다.** Foundry 에이전트 대시보드와 상세 추적에는 필요합니다.

기본 집계는 **Azure Monitor가 수집하는 플랫폼 지표**입니다. Foundry·Azure 포털에서 볼 수 있지만, Application Insights를 연결해야 수집되는 데이터는 아닙니다.

| 확인 범위 | 조회 경로·지표 | Application Insights |
| --- | --- | --- |
| 모델·배포별 집계 | Foundry 리소스의 **Metrics** → `InputTokens`/`OutputTokens` | 불필요 |
| 에이전트별 집계(프리뷰) | Foundry **프로젝트 리소스의 Metrics** → `AgentInputTokens`/`AgentOutputTokens`를 `AgentId`로 구분 | 불필요 |
| 호출 한 건 | API 응답의 `usage` | 불필요 |
| 에이전트 대시보드·실행 추적 | Foundry의 에이전트 **Monitor**, 연결된 Application Insights의 **Logs(KQL)** | 필요 |

- **포털:** Azure Monitor의 범위 선택기에 프로젝트가 안 보이면, **Foundry 프로젝트 리소스를 직접 열어 Metrics로 진입**합니다. 프리뷰 지표의 별도 필수 등록 절차는 공개 문서에서 확인되지 않았습니다.
- **집계 API:** Azure Monitor **Metrics REST API**를 사용합니다. 모델은 `Microsoft.CognitiveServices/accounts`, 에이전트는 `Microsoft.CognitiveServices/accounts/projects` 리소스가 대상입니다. 상세 로그는 **Logs Query API**로 조회합니다.
- **호출별 필드:** Chat Completions는 `usage.prompt_tokens`/`completion_tokens`, Responses는 `usage.input_tokens`/`output_tokens`입니다. 과거 요청의 보관·조회는 Q5를 참고합니다.

모델 배포의 총사용량만으로는 같은 배포를 공유하는 에이전트들의 사용량을 나눌 수 없습니다. **에이전트별 집계에는 프로젝트의 Agent 지표**를 사용합니다. 기존 Azure OpenAI 지표 범주에서는 입력·출력이 `ProcessedPromptTokens`/`GeneratedTokens`로 표시되기도 합니다.

위 지표는 Foundry Models·Agent Service 기준이며, 외부 호스팅 모델·에이전트는 지원 범위를 따로 확인해야 합니다.

참고: [모델 지표](https://learn.microsoft.com/en-us/azure/azure-monitor/reference/supported-metrics/microsoft-cognitiveservices-accounts-metrics) · [프로젝트·에이전트 지표](https://learn.microsoft.com/en-us/azure/azure-monitor/reference/supported-metrics/microsoft-cognitiveservices-accounts-projects-metrics) · [에이전트 대시보드](https://learn.microsoft.com/en-us/azure/foundry/observability/how-to/how-to-monitor-agents-dashboard) · [Responses API](https://learn.microsoft.com/en-us/rest/api/microsoft-foundry/azureopenai/responses)

## Q3. 프로젝트 연결과 SDK로 수집하는 추적은 어떻게 다르며, 무엇을 먼저 적용하고 어떻게 통합하나요?

**서버 측은 Foundry 내부 실행을, 클라이언트 측은 앱 코드의 실행을 추적합니다.** 둘 중 하나를 고르는 관계가 아니라, 필요한 범위에 따라 함께 사용합니다.

| 구분 | 서버 측: 프로젝트 연결 | 클라이언트 측: SDK·OpenTelemetry |
| --- | --- | --- |
| 수집 방식 | Application Insights 연결 후 서비스가 자동 수집 | 앱에서 계측과 내보내기를 설정 |
| 주요 범위 | 서비스 내부의 모델·도구 호출, 토큰, 지연·오류 | 지원되는 SDK 호출과 직접 계측한 앱·도구 로직 |
| 적합한 경우 | 에이전트 내부에서 어느 단계가 느리거나 실패했는지 확인 | 전처리·후처리, 자체 도구·외부 호출까지 포함한 전체 요청 흐름 분석 |

서버 측 추적이 앱의 모든 함수·DB 호출까지 기록하지는 않으며, 클라이언트 SDK도 임의의 코드를 전부 자동 계측하지는 않습니다. 필요한 구간에 계측을 추가해야 합니다. 여기서 **클라이언트 측은 브라우저만이 아니라 백엔드·Hosted Agent 등 계측 코드를 실행하는 쪽**을 뜻합니다.

**Foundry 관리형 에이전트는 서버 측부터 적용하고, 앱 코드까지 분석해야 할 때 클라이언트 계측을 추가하는 순서를 권장합니다.** 반대로 로컬·외부 에이전트나 자체 코드 중심의 서비스는 SDK·프레임워크 계측부터 시작할 수 있습니다.

두 추적을 통합하려면:

1. 프로젝트에 Application Insights를 연결하고, 앱의 계측·내보내기도 설정해 **같은 Application Insights**로 전송합니다.
2. 앱의 상위 span 안에서 에이전트를 호출하고, SDK의 **추적 컨텍스트(`traceparent`) 전파**를 설정합니다.
3. 서버·클라이언트 span이 같은 trace ID에서 부모·자식 관계로 연결되는지 확인합니다.

같은 저장소로 전송하는 것만으로는 하나의 trace가 되지 않습니다. **호출 경계를 넘어 부모 span의 컨텍스트가 전달되어야 하며**, 사용하는 SDK의 전파 지원과 초기화 순서를 맞춰야 합니다.

참고: [서버 측 추적 설정](https://learn.microsoft.com/en-us/azure/foundry/observability/how-to/trace-agent-setup) · [클라이언트 계측·컨텍스트 전파](https://learn.microsoft.com/en-us/azure/foundry/observability/how-to/trace-agent-client-side)

## Q4. 한 요청의 반복 실행과 멀티턴 대화를 묶어 추적하려면 클라이언트 계측이 필수인가요?

**서버 내부 반복과 멀티턴 대화 조회에는 클라이언트 계측이 필수가 아닙니다.** 새 Foundry의 Prompt/Hosted 에이전트와 Responses/Conversations API, 프로젝트에 연결된 Application Insights 기준입니다.

| 범위 | 추적 방식 | 클라이언트 계측 |
| --- | --- | --- |
| 서비스 내부의 모델·도구 반복 | 한 실행의 trace 안에 상위·자식 span으로 기록 | 불필요 |
| 멀티턴 대화 | 각 실행의 trace를 **Conversation ID**로 묶어 조회 | 불필요 |
| 앱이 직접 수행하는 여러 API 호출·도구 실행을 하나의 trace로 연결 | 전체 루프를 감싸는 상위 span과 컨텍스트 전파 | 필요 |

**사용자 요청 한 번이 API 호출 한 번과 같지는 않습니다.** 앱이 도구 실행 결과를 제출하거나 에이전트를 여러 번 호출한다면, 서비스의 개별 trace만으로 앱의 전체 루프가 하나로 묶이지는 않습니다. 이때는 루프 전체의 상위 span을 유지하고 비동기 작업에도 컨텍스트를 전달해야 합니다.

멀티턴에서는 **Conversation을 생성하고 그 ID를 보관한 뒤, 매 턴 같은 `conversation=conversation.id`를 전달**합니다. Foundry는 서버 추적과 함께 Conversation 조회를 제공하므로, **Traces에서 Response ID나 Trace ID로 찾고 Conversation ID를 선택**해 대화 이력과 실행 단계를 봅니다.

Conversation ID를 전달하는 것은 대화 상태 유지 코드이지 추적 계측이 아닙니다. **trace ID는 한 실행의 span을 연결하고, Conversation ID는 여러 턴의 실행을 연결**합니다. 따라서 멀티턴을 조회하려고 모든 턴의 trace ID를 하나로 만들 필요는 없습니다.

참고: [서버 추적·Conversation 조회](https://learn.microsoft.com/en-us/azure/foundry/observability/how-to/trace-agent-setup#view-conversation-results) · [Conversations API의 대화 상태](https://learn.microsoft.com/en-us/azure/foundry/agents/concepts/runtime-components)

## Q5. 캐시된 입력 토큰도 Application Insights 없이 확인할 수 있나요?

**네, 지원되는 API·모델에서는 응답의 `usage`로 캐시 토큰 수를 확인할 수 있습니다.** 집계 지표도 Application Insights 없이 조회합니다.

| 확인 범위 | 필드·지표 |
| --- | --- |
| Chat Completions 응답 한 건 | `usage.prompt_tokens_details.cached_tokens` |
| Responses 응답 한 건 | `usage.input_tokens_details.cached_tokens` |
| Azure OpenAI 배포 집계 | `AzureOpenAIContextTokensCacheMatchRate` — 토큰 수가 아닌 캐시 적중 **비율** |
| 에이전트 집계(프리뷰) | `AgentModelCacheReadTokens`/`AgentModelCacheWriteTokens`/`AgentModelUncachedInputTokens` |

집계 조회 경로는 Q2와 같습니다. 에이전트 캐시 지표의 조회 차원은 `AgentName`·`AgentVersion`·`ModelDeploymentName`으로, Q2의 `AgentId` 기반 토큰 지표와 다릅니다.

**`cached_tokens`는 전체 입력 토큰에 이미 포함된 양**입니다. 예를 들어 입력 2,000개 중 캐시가 1,500개라면 비캐시 입력은 500개이지, 총입력이 3,500개인 것은 아닙니다. 앱이 한 턴에서 여러 응답을 생성하면 관련 응답의 사용량을 합산해야 합니다.

### 특정 요청의 입력·출력·캐시 토큰을 나중에 다시 보려면?

**호출 시에는 응답의 `usage`로 정확한 값을 읽지만, 사후 조회에는 보관된 데이터가 필요합니다.** 여기서 응답은 API를 호출한 앱이 받는 JSON·SDK 객체이지, Foundry 포털에 자동으로 남는 요청별 이력을 뜻하지 않습니다.

- **앱에서 보관:** `usage`와 요청·응답 ID를 앱 로그·DB 또는 Application Insights에 기록합니다.
- **서비스에 저장된 응답 조회:** 저장·조회가 지원되는 Responses API는 `GET /openai/v1/responses/{response_id}`로 `usage`를 다시 받을 수 있습니다. 저장 조건·보존 기간 안에서 가능하며, 진단용 요청 ID가 아닌 `response.id`가 필요합니다.
- **이미 수집된 추적 조회:** Application Insights 등에 해당 요청과 토큰 필드가 기록되어 있다면 그 이력을 조회합니다. 연결만으로 모든 API의 캐시 필드까지 보관된다고 보장되지는 않습니다.

**아무 기록도 없다면 특정 요청의 정확한 값은 복원할 수 없습니다.** Azure Monitor Metrics는 시간 구간별 합계이지 요청 이력이 아니므로, 합계를 건수로 나눠 평균을 내도 그 요청의 입력·출력·캐시 토큰 수는 알 수 없습니다.

참고: [프롬프트 캐싱](https://learn.microsoft.com/en-us/azure/foundry/openai/how-to/prompt-caching) · [모델 지표](https://learn.microsoft.com/en-us/azure/azure-monitor/reference/supported-metrics/microsoft-cognitiveservices-accounts-metrics) · [에이전트 캐시 지표](https://learn.microsoft.com/en-us/azure/azure-monitor/reference/supported-metrics/microsoft-cognitiveservices-accounts-projects-metrics) · [저장된 응답 조회](https://learn.microsoft.com/en-us/rest/api/microsoft-foundry/azureopenai/responses#get-response)
