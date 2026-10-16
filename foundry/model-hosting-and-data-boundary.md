# Microsoft Foundry 모델 호스팅과 데이터 경계

> 확인 기준: 2026-09-29. Foundry 문서는 자주 바뀌므로 도입 전 원문 재확인 필요.

## 핵심 요약

- Foundry 카탈로그 모델은 **채널마다 운영 주체와 추론 위치가 다름**
- 원 모델 개발사(OpenAI, DeepSeek, Moonshot 등)의 API로 요청을 넘기는 **proxy 구조인 채널은 없음**. 가중치를 가진 사업자(Microsoft, Fireworks, Anthropic)가 직접 서빙함
- **Azure 밖에서 추론**: Fireworks on Foundry, Claude Hosted on Anthropic
- **Azure에서 돌지만 제3자가 운영·데이터 처리 책임**: Claude Hosted on Azure
- Azure로 과금되고 Azure 엔드포인트로 호출한다고 해서 **Azure DC에서 처리된다는 보장은 없음**
- 보장의 근거는 대부분 **계약 + 공식 문서 + 제3자 감사** 수준임. 고객이 실제 추론 위치를 기술적으로 검증할 수단은 표준 배포에 없음

| 채널 | 운영 주체 | 추론 위치 | 입력·출력이 가는 곳 | 제3자에게 넘어가는 것 | 데이터 처리 약관 |
| --- | --- | --- | --- | --- | --- |
| Direct from Azure | Microsoft | Azure | 배포 유형 범위 내 Azure 리전 | 없음 | Microsoft DPA |
| Hugging Face (Managed compute) | Microsoft | Azure | Azure (현재 Global만) | 없음 | Azure 약관 + Preview 약관 |
| Fireworks on Foundry | Fireworks (MS subprocessor) | **Fireworks GPU, Microsoft 시설 밖** | Fireworks 인프라 | 입력·출력 전체 (Fireworks) | Microsoft DPA (예외 있음) |
| Claude Hosted on Azure | **Anthropic** | Azure | Azure (Global 또는 US Data Zone) | 사용량 메타데이터, 안전 플래그 콘텐츠 | **Anthropic DPA** |
| Claude Hosted on Anthropic | **Anthropic** | **Anthropic 인프라** | Azure 밖, 선택 리전 밖 가능 | 입력·출력 전체 + 연락처·거래·사용량 정보 | **Anthropic DPA** |
| Foundry Labs | 항목별 | 항목별 | 항목별 | 항목별 | 항목별 |

## 1. 누가, 어디서, 어떻게 호스팅하나

### Direct from Azure

- "Foundry Models sold by Azure". Azure OpenAI 전체와 xAI, DeepSeek, Meta, Mistral, MAI 등 선별 모델
- Microsoft가 가중치를 받아 **Azure에서 직접 서빙**함. 공식 문서 표현은 이러함

> Microsoft hosts the Models sold by Azure in Microsoft's Azure environment and Models sold by Azure do NOT interact with any services operated by providers of Models sold by Azure

- 입력·출력·임베딩·학습 데이터는 OpenAI 등 모델 개발사에 제공되지 않음

### Hugging Face

- **신규 Foundry**: Managed compute(preview)로 배포함. GPU, 서빙 런타임, 컨테이너, 보안 패치는 Microsoft가 운영함
- 가중치는 HF에서 한 번 가져와 검증한 뒤 **Microsoft 관리 Azure 스토리지**에 미리 올려 둠. 배포·추론 시 HF Hub로 나가는 연결이 필요 없음
- **Foundry (classic)**: 배포할 때 HF Hub에서 가중치를 받아 Azure VM에서 추론함. HF와 통신하는 건 가중치 다운로드뿐이고, 프롬프트는 HF로 가지 않음
- HF Inference Providers(`router.huggingface.co`)는 HF가 여러 외부 사업자로 요청을 넘기는 **proxy**라서 Foundry 배포와는 다른 경계임

### Fireworks on Foundry

- Microsoft first-party 서비스로 판매·과금되지만 **추론은 Fireworks 엔진과 GPU**에서 실행됨. Microsoft FAQ(2026-09-24)의 표현은 이러함

> Yes, customer data travels outside Microsoft facilities because Fireworks runs inferencing for this service on Fireworks' GPUs.

- Fireworks는 **Microsoft의 subprocessor**임. DeepSeek, Moonshot 같은 모델 개발사는 고객 데이터에 접근하지 않음
- 배포 리소스, RBAC, 과금 같은 제어 영역은 고객 Azure 구독에 있음. 하지만 이는 GPU가 어디 있는지와 무관함
- 구독 관리자가 `Fireworks.EnableDeploy` 기능을 등록해야만 사용할 수 있음

### Claude (Anthropic)

- 4개 컬렉션에 속하지 않는 파트너 채널임. Azure Marketplace의 "Claude Platform on Foundry" 오퍼를 구독해야 사용할 수 있음
- 두 호스팅 옵션 모두 **Anthropic이 판매자이자 운영자이고, 입력·출력의 독립 data processor**임
- **Hosted on Azure**: 요청 수신, API, GPU 추론이 모두 Azure 인프라에서 이뤄지지만, 그 위의 서비스는 Anthropic이 운영함. Microsoft가 가중치를 가져와 직접 운영하는 구조가 아님
- **Hosted on Anthropic**: Anthropic 인프라에서 처리됨
- 두 옵션이 모두 있는 모델은 기본값이 Hosted on Azure임

### Foundry Labs

- 연구·실험 모델을 모아 둔 **큐레이션 라벨**임. 공식 사이트 설명은 "deploy through Microsoft Foundry or GitHub"
- 컬렉션 전체에 공통으로 적용되는 호스팅 약정은 없음. 모델별로 실제 배포 방식이 위 채널 중 무엇인지 보고 판단해야 함

> 같은 모델이 여러 채널에 동시에 있을 수 있음. 예를 들어 gpt-oss-120b는 Direct from Azure에도 있고 Fireworks(`FW-GPT-OSS-120B`)에도 있음. 모델 이름이 아니라 **어떤 카탈로그 항목으로 배포했는지**로 판단해야 함.

## 2. 데이터가 어디까지 나갈 수 있나

### 추론 처리 범위: 배포 유형

Microsoft가 운영하는 채널(Direct from Azure, Claude Hosted on Azure)에 적용됨.

| 배포 유형 | 입력·출력 처리 범위 |
| --- | --- |
| Global (Standard / Provisioned / Batch) | 모델이 배포된 **모든 Azure 리전** |
| Data Zone | Microsoft가 정한 zone 안 (US, EU, APAC) |
| Standard / Regional Provisioned | 지정한 Azure **geography** 안. 같은 geography 안의 리전끼리는 이동 가능 |

- 한국 리소스에 Global Standard로 배포하면 **해외 Azure 리전에서 추론될 수 있음**. 단, Azure 밖으로 나가지는 않음
- Managed compute는 현재 `GlobalManagedCompute`(Global)만 지원함
- Fireworks는 Data Zone이 US 리전으로 고정되고, Global PTU도 있음. 위 Azure 설명을 Fireworks에 그대로 적용하면 안 됨 (추론 위치는 Fireworks GPU)
- Claude Hosted on Anthropic은 Global Standard만 지원하고, 처리 위치는 Anthropic 인프라임

### 데이터 종류별 이동 범위

| 데이터 | Direct from Azure | HF Managed compute | Fireworks | Claude Hosted on Azure | Claude Hosted on Anthropic |
| --- | --- | --- | --- | --- | --- |
| 입력·출력 | Azure (배포 유형 범위) | Azure | **Fireworks GPU** | Azure | **Anthropic 인프라** |
| 사용량·과금 메타데이터 | Microsoft | Microsoft | Microsoft, Fireworks(토큰 수 등) | Microsoft, **Anthropic** | Microsoft, **Anthropic** |
| 연락처·거래 정보 | Microsoft | Microsoft | Microsoft | Microsoft (Anthropic과의 공유 여부는 문서에 없음) | Microsoft가 **Anthropic과 공유 가능** |
| 안전 검토용 콘텐츠 | 플래그된 샘플 → Microsoft abuse monitoring 저장소, 승인된 Microsoft 직원 검토 | 콘텐츠 필터·abuse monitoring 없음 (preview) | 문서화 안 됨 | 플래그 콘텐츠 → **Anthropic Trust & Safety**, 예외적으로 Anthropic 직원 검토 | Anthropic |

모델 채널과 별개로, 에이전트에 **Grounding with Bing Search**를 붙이면 검색 쿼리가 **Azure compliance·Geo 경계 밖**으로 나가고 Microsoft DPA도 적용되지 않음. 모델만이 아니라 연결된 도구까지 봐야 함.

## 3. 어디에, 얼마나 저장되나

| 채널 | 저장되는 것 | 위치 | 기간 |
| --- | --- | --- | --- |
| Direct from Azure | 모델에는 저장 안 됨 (stateless) | - | - |
| | 상태 저장 기능 데이터 (Files, Responses API, Threads, Stored completions, Batch, fine-tuning 데이터) | 고객 Foundry 리소스, 리소스와 **같은 geography** | 고객이 삭제할 때까지. 기본 AES-256 암호화, CMK 선택 가능 |
| | abuse monitoring 샘플 (사람 검토 대상) | 리소스의 **geography**, 리소스별로 논리 분리. EEA 배포는 EEA 소재 직원만 검토 | 현재 문서에 수치 없음 |
| HF Managed compute | 저장 관련 문서 없음 | - | - |
| Fireworks | Fireworks 측: 기본값 **Zero Data Retention**. 입력·출력은 휘발성 메모리에만 있고(프롬프트 캐시는 수 분), 메타데이터만 로그로 남음 | Microsoft 측 저장 데이터는 배포 시 선택한 리전 | - |
| Claude (두 옵션 공통) | Anthropic 약관 기준 | Hosted on Azure: 선택한 Azure geography. Hosted on Anthropic: Anthropic 인프라 | 입력·출력 **30일 안에 삭제**. 사용 정책 위반으로 플래그되면 입력·출력 **최대 2년**, 분류 점수 **최대 7년**. Covered Models(Mythos급, Fable 포함)는 ZDR 계약이 있어도 **30일 보존**(Foundry 포함) |

- Direct from Azure에서 **Modified abuse monitoring**을 승인받으면(Limited Access 자격 필요) abuse monitoring 저장과 사람 검토가 없어짐. 자동 검토는 계속됨
- Claude 보존 기간은 Anthropic API 기준 정책임. Foundry 고객도 Anthropic 데이터 사용 약관을 따른다고 명시돼 있지만, Foundry만을 위한 수치는 따로 없음
- Fireworks의 ZDR은 Fireworks 자체 정책임. Microsoft 문서가 Foundry 경유 요청에도 적용된다고 명시하지는 않음

## 4. 어떻게 확신할 수 있나: 보장 수준

### 보장 근거의 종류

| 수준 | 무엇 | 구속력 | 한계 |
| --- | --- | --- | --- |
| **계약 (Microsoft)** | Product Terms, Privacy & Security Terms, DPA | Microsoft에 법적 의무 | 추론 처리 위치나 운영자를 모델별로 적어 두지 않음. Preview는 Core Online Services에서 빠짐 |
| **계약 (제3자)** | Anthropic DPA, Commercial Terms | Anthropic에 법적 의무 | Microsoft는 Non-Microsoft Product에 보증·책임을 지지 않음 |
| **공식 문서** | Learn 데이터 처리 문서, 제3자 기술 문서 | 설명 문서이며 DPA가 처리를 규율한다고 안내함 | 자주 바뀌고 문서끼리 어긋나기도 함 |
| **제3자 감사** | SOC 1/2, ISO 27001/27018/42001 보고서 (Service Trust Portal, Anthropic·Fireworks Trust Center) | 감사인이 통제가 있고 작동하는지 확인함 | 개별 요청이 어디서 처리됐는지를 증명하지는 않음 |
| **고객 측 기술 통제** | Azure Policy, 기능 opt-in, CMK, private endpoint 등 | 고객이 직접 강제·감사할 수 있음 | "어떤 배포를 만들 수 있는가"만 통제함. 서비스 내부 처리는 검증 못 함 |
| **기술 공개·원격 증명** | TEE attestation 등 | - | **Foundry 표준 배포에는 없음** |

### 주장별 근거

| 주장 | 근거 문서 | 수준 |
| --- | --- | --- |
| sold by Azure 모델의 입력·출력을 모델 개발사에 제공하지 않음 | Learn "Data, privacy, and security for Models sold by Azure" | 공식 문서 (DPA가 처리를 규율한다고 명시) |
| 고객 데이터로 생성형 AI 기반 모델을 학습하지 않음 | Universal License Terms: "will not use Customer Data to train any generative AI foundation model, except pursuant to Customer's documented instructions" | **계약** |
| 저장 데이터는 지정 Geo에 남음 | Privacy & Security Terms: "Microsoft will store Customer Data at rest within the specified Geo" (Core Online Services 대상. sold by Azure 모델 포함, Preview 제외) | **계약** |
| 추론은 배포 유형 범위 안에서만 처리됨 | Learn deployment types, data privacy 문서 | 공식 문서 |
| abuse monitoring 저장소가 리소스 geography에 있음, EEA 배포는 EEA 직원만 검토 | Learn data privacy, abuse monitoring 문서 | 공식 문서 |
| HF Managed compute는 Azure에서 추론하고 HF로 나가지 않음 | Learn managed compute overview | 공식 문서. Preview라 Geo 저장 약정 대상도 아님 |
| Fireworks 처리에 Microsoft DPA 적용 | Learn Fireworks privacy FAQ: Product Terms + DPA 적용, Fireworks는 subprocessor, 예외(EU Data Boundary 제외, FedRAMP·PCI·SOC 1 Type 2·HITRUST 미충족) | **계약** (FAQ가 계약 적용을 명시) |
| Fireworks는 입력·출력을 저장하지 않음 | Fireworks Docs (ZDR) | 제3자 문서 |
| Claude Hosted on Azure에서 입력·출력은 Azure에 머묾 | Anthropic Docs "prompts and completions remain within Azure", Learn "processed on Azure infrastructure" | 공식 문서. 책임 주체는 Anthropic DPA |
| Claude 보존 기간 | Anthropic Privacy Center, Anthropic DPA | **제3자 계약**·문서 |

### 고객이 직접 강제할 수 있는 것

배포 SKU는 ARM 리소스 속성이라 Azure Policy로 막거나 감사할 수 있음. 예를 들어 Global 배포를 막아 처리 범위를 Data Zone이나 geography로 제한하려면:

```json
{
  "if": {
    "allOf": [
      { "field": "type", "equals": "Microsoft.CognitiveServices/accounts/deployments" },
      { "not": { "field": "Microsoft.CognitiveServices/accounts/deployments/sku.name", "in": ["DataZoneStandard", "Standard"] } }
    ]
  },
  "then": { "effect": "Deny" }
}
```

- **Fireworks 차단**: `Fireworks.EnableDeploy`를 등록하지 않으면 Fireworks 모델을 배포할 수 없음
- **Claude 차단**: Marketplace 오퍼를 구독하지 않거나, Azure Policy로 배포 가능한 모델을 제한함
- **저장 최소화**: 상태 저장 기능(Responses API의 `store`, Stored completions 등)을 쓰지 않거나 삭제함. 저장 데이터는 CMK로 암호화함
- **사람 검토 제거**: Modified abuse monitoring을 신청함 (Direct from Azure만 해당)

이 통제들은 **어떤 채널과 배포 유형을 쓸 수 있는지**만 보장함. 서비스 안에서 실제로 어느 GPU가 요청을 처리했는지는 고객이 확인할 수 없음. 하드웨어 수준의 증명이 필요하다면 Azure confidential GPU VM에 오픈 모델을 직접 호스팅하는 별도 구성이 필요함.

## 5. 확인되지 않은 부분

- **Fireworks GPU의 물리 위치**: Microsoft FAQ는 "Microsoft 시설 밖", Fireworks Docs는 "Fireworks infrastructure within Azure"라고 해서 서로 어긋남. 더 최신이고 서비스에 특화된 Microsoft FAQ를 우선하고, Azure 밖으로 간주함
- Fireworks Global PTU와 커스텀 모델의 추론 위치
- Direct from Azure abuse monitoring 데이터의 보존 기간 수치
- HF Managed compute의 로그·보존 규정
- Claude Hosted on Azure의 가중치 관리 주체, 안전 플래그 전송 opt-out 절차
- DPA 본문의 보존·삭제 기한, Subprocessors List의 현재 등재 업체
- 모든 모델의 호스팅 주체·데이터 처리를 한 번에 정리한 **공식 통합 문서는 없음**. 채널별 문서와 계약을 함께 읽어야 함

## 참고 자료

Microsoft

- [Microsoft Foundry Models overview](https://learn.microsoft.com/en-us/azure/foundry/concepts/foundry-models-overview)
- [Foundry Models sold by Azure](https://learn.microsoft.com/en-us/azure/foundry/foundry-models/concepts/models-sold-directly-by-azure)
- [Data, privacy, and security for Foundry Models sold by Azure](https://learn.microsoft.com/en-us/azure/foundry/responsible-ai/openai/data-privacy)
- [Abuse monitoring](https://learn.microsoft.com/en-us/azure/foundry/openai/concepts/abuse-monitoring)
- [Deployment types for Microsoft Foundry Models](https://learn.microsoft.com/en-us/azure/foundry/foundry-models/concepts/deployment-types)
- [Managed compute in Microsoft Foundry](https://learn.microsoft.com/en-us/azure/foundry/concepts/managed-compute-overview)
- [Hugging Face models in Microsoft Foundry](https://learn.microsoft.com/en-us/azure/foundry/foundry-models/how-to/hugging-face-models)
- [Fireworks on Microsoft Foundry privacy and compliance FAQ](https://learn.microsoft.com/en-us/azure/foundry/how-to/fireworks/privacy-compliance-faq)
- [Fireworks models on Microsoft Foundry](https://learn.microsoft.com/en-us/azure/foundry/how-to/fireworks/enable-fireworks-models)
- [Compare hosting options for Claude models in Microsoft Foundry](https://learn.microsoft.com/en-us/azure/foundry/foundry-models/concepts/claude-models-hosting-comparison)
- [Data, privacy, and security for Claude models in Microsoft Foundry](https://learn.microsoft.com/en-us/azure/foundry/responsible-ai/claude-models/data-privacy)
- [Grounding with Bing Search tools](https://learn.microsoft.com/en-us/azure/foundry/agents/how-to/tools/bing-tools)
- [Microsoft Product Terms](https://www.microsoft.com/licensing/terms/)
- [Privacy & Security Terms](https://www.microsoft.com/licensing/terms/product/PrivacyandSecurityTerms)
- [Microsoft Products and Services Data Protection Addendum](https://aka.ms/DPA)
- [Service Trust Portal](https://servicetrust.microsoft.com/)

제3자

- [Claude in Microsoft Foundry – Claude Platform Docs](https://platform.claude.com/docs/en/build-with-claude/claude-in-microsoft-foundry)
- [Anthropic: How long do you store my organization's data?](https://privacy.claude.com/en/articles/7996866-how-long-do-you-store-my-organization-s-data)
- [Anthropic: Data retention practices for Covered Models](https://privacy.claude.com/en/articles/15425996-data-retention-practices-for-covered-models)
- [Anthropic Data Processing Addendum](https://www.anthropic.com/legal/data-processing-addendum)
- [Fireworks: Zero Data Retention](https://docs.fireworks.ai/guides/security_compliance/data_handling)
- [Microsoft Foundry – Fireworks AI Docs](https://docs.fireworks.ai/ecosystem/integrations/azure-foundry)
- [Hugging Face Inference Providers](https://huggingface.co/docs/inference-providers/en/index)
- [Microsoft Foundry Labs](https://labs.ai.azure.com/)
