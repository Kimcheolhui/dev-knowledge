# Agent Workflow의 Pregel과 DAG

## 개요

Agent workflow의 실행 모델에는 크게 두 가지 접근 방식이 있음:
- **Superstep (BSP) 모델**: Pregel 기반의 동기화 실행
- **DAG 모델**: 의존성 기반의 비동기 실행

이 문서는 Microsoft Agent Framework Issue #3087을 중심으로 두 모델의 차이와 특징을 정리함.

## Microsoft Agent Framework Issue #3087

### 문제 상황

사용자가 fan-out/fan-in 워크플로우를 구현했으나 예상과 다른 병렬 실행 동작이 관찰됨.

**워크플로우 구조:**
```
         시작
           |
        fan-out
       /       \
  짧은 작업들     긴 작업
 (5s→5s→5s)      (20s)
       \       /
         fan-in
           |
         종료
```

### 기대한 동작 vs 실제 동작

**기대한 동작 (파이프라인 병렬):**
- 왼쪽 경로(15초)와 오른쪽 경로(20초)가 동시에 시작
- 둘 다 독립적으로 실행되어 긴 작업이 끝나는 20초에 전체 완료

**실제 관찰된 동작:**
- 첫 번째 5초 작업만 20초 작업과 병렬 실행
- 나머지 5초 작업들은 20초 작업이 끝날 때까지 대기
- 총 실행 시간: 약 25-30초

### 핵심 문제

사용자는 "완전한 파이프라인 병렬"을 기대했으나, 프레임워크는 superstep 기반으로 동작하여 step 단위 동기화가 발생함.

이는 버그가 아니라 **실행 모델의 근본적인 차이**에서 발생한 문제임.

## Superstep (BSP) 실행 모델

### 개념

Superstep은 BSP(Bulk Synchronous Parallel) 모델에서 온 개념으로, Pregel 같은 그래프 처리 엔진에서 사용됨.

### 핵심 규칙

**모든 노드는 같은 단계(step)를 끝내야 다음 단계로 넘어갈 수 있음**

```
Step 1: 모든 활성 노드 실행
--- barrier ---
Step 2: 다음 노드들 실행
--- barrier ---
Step 3: ...
```

### 실행 타임라인

```
Step 1: A1, B1 실행 (20초 - B1 때문)
--- barrier ---
Step 2: A2 실행 (5초)
--- barrier ---
Step 3: A3 실행 (5초)
--- barrier ---
총 소요 시간: 30초
```

### 특징

**장점:**
- 상태 일관성 보장
- 재현 가능성 (deterministic execution)
- 분산 환경에서 안정적
- Agent 간 메시지 전달을 안전하게 처리

**단점:**
- 경로별 완전한 파이프라인 병렬 불가능
- Barrier로 인한 대기 시간 발생
- 빠른 경로가 느린 경로를 기다려야 함

### 왜 Agent Framework가 Superstep을 쓰는가?

여러 agent가 **상태를 공유하고, 메시지를 주고받으며, 협업하는 것**이 목적임.

이런 환경에서는:
- 안정성과 일관성이 병렬성보다 중요함
- 상태 동기화가 필수적임
- 디버깅과 재현이 용이해야 함

## DAG 실행 모델

### 개념

DAG(Directed Acyclic Graph) 기반 실행 모델의 핵심 규칙:

**의존성이 풀리는 순간, 즉시 실행함**

Barrier가 없고, step 개념도 없음. 오직 그래프만 존재함.

### 실행 타임라인

```
t=0     A1, B1 시작
t=5     A1 끝 → A2 즉시 시작
t=10    A2 끝 → A3 즉시 시작
t=15    A3 끝
t=20    B1 끝
총 소요 시간: 20초
```

### 실행 철학

**Superstep:**
"전체 시스템의 일관성"

**DAG:**
"각 노드의 진행 가능성"

글로벌 동기화 없이, 매 순간 "지금 실행 가능한 노드는 뭐지?"만 확인함.

### 특징

**장점:**
- 완전한 파이프라인 병렬 실행
- CPU가 노는 시간 최소화
- 의존성만 맞으면 즉시 실행
- 높은 처리량

**단점:**
- 실행 순서의 재현성 부족 (non-deterministic)
- 상태 동기화 어려움
- Agent 간 메시지 일관성 유지 어려움
- 디버깅 복잡함

## Superstep vs DAG 비교

| 항목 | Superstep (BSP) | DAG |
|------|----------------|-----|
| **실행 단위** | Step 기반, 전역 동기화 | 노드 기반, 의존성만 체크 |
| **병렬성** | Step 내에서만 병렬 | 의존성 허용 범위 내 완전 병렬 |
| **동기화** | 명시적 barrier | 의존성으로 암묵적 동기화 |
| **상태 일관성** | 보장됨 | 직접 관리 필요 |
| **재현성** | Deterministic | Non-deterministic |
| **적합 용도** | Agent 협업, 상태 공유 | 파이프라인, 데이터 처리 |
| **대표 시스템** | Pregel, LangGraph | Ray, Airflow, Prefect |

### 실행 시간 차이 예시

Fan-out/fan-in 시나리오 (A1→A2→A3 (각 5초), B1 (20초)):

- **DAG 방식**: 20초 (병렬)
- **Superstep 방식**: 30초 (순차적 barrier)

## Agent Framework와 실행 모델

### Microsoft Agent Framework

두 가지 실행 모델을 제공함:

| 모델 | 실행 방식 | 특징 |
|------|----------|------|
| **Workflow** | Superstep | 안정성, 일관성, agent orchestration용 |
| **Task/Concurrent Agent** | Async/DAG 방식 | 완전 병렬 가능 |

즉:
- Workflow를 쓰면 → superstep
- Task/Agent를 직접 orchestration하면 → DAG처럼 동작

### 다른 Agent Framework들

**1. DAG/Task 그래프 기반**

- **Ray**: Task 그래프 기반 병렬/분산 실행, 의존성만 맞으면 즉시 실행
- **Haystack Pipelines**: Directed multigraph로 컴포넌트 연결, concurrent 처리

**2. 그래프 기반이지만 Pregel 계열**

- **LangGraph**: 그래프로 모델링하되 Pregel(superstep) 런타임 사용, fan-out/fan-in 지원하나 완전한 파이프라인 병렬과는 다름
- **LlamaIndex Workflows**: Event-driven, step-based, 초기 DAG 시도했으나 루프/동적 제어 필요로 확장

**3. 데이터 오케스트레이터 (DAG 엔진)**

- **Airflow/Dagster/Prefect**: 순수 DAG 오케스트레이터, agent 단계를 task로 만들어 실행 가능

## 언제 어떤 모델을 선택해야 하는가?

### DAG가 적합한 경우

- 단계가 비교적 고정된 파이프라인 (ETL, 검색→요약→검증)
- 병렬화가 성능에 직결됨
- 상태 일관성보다 처리량이 중요
- 각 단계가 독립적

**예시**: 대규모 데이터 처리, 배치 작업, 독립적인 여러 LLM 호출

### Superstep이 적합한 경우

- 루프와 동적 제어 필요 (계획 수정)
- Human-in-the-loop
- Agent 간 상태 공유 및 메시지 협업
- 장기 실행 및 재개 필요
- 디버깅과 재현성이 중요

**예시**: Multi-agent 협업, 대화형 agent, 복잡한 의사결정 workflow

## 결론

Issue #3087의 사용자는 DAG를 기대했으나, Microsoft Agent Framework의 Workflow는 superstep으로 동작함.

이는 버그가 아니라:
- **설계 철학의 차이**
- **용도에 따른 적절한 선택**

Agent Framework에서 완전 병렬이 필요하면:
- Workflow 대신 Task/Agent orchestration 사용
- 또는 다른 DAG 기반 프레임워크 고려

핵심은 **각 모델의 트레이드오프를 이해하고 상황에 맞게 선택**하는 것임.
