"""프롬프트 5개를 각각 10회 시행하며 Standard와 Flex를 비교한다.

Python 3.10 이상과 두 모델의 Global Standard 배포가 필요하다.

설치 및 필수 환경변수 설정 (저장소 루트에서 실행):
    python -m pip install -r foundry/flex/requirements.txt
    export AZURE_OPENAI_ENDPOINT="https://YOUR-RESOURCE.openai.azure.com"
    export AZURE_OPENAI_API_KEY="YOUR-KEY"

배포 이름이 모델 ID와 다르면 다음 환경변수도 설정한다.
생략하면 각각 gpt-6-sol, gpt-6-luna를 배포 이름으로 사용한다.
    export AZURE_OPENAI_SOL_DEPLOYMENT="YOUR-SOL-DEPLOYMENT"
    export AZURE_OPENAI_LUNA_DEPLOYMENT="YOUR-LUNA-DEPLOYMENT"

실행:
    python foundry/flex/compare.py
    python foundry/flex/compare.py --repeats 1 --interval 0
    python foundry/flex/compare.py --prompt "Explain how TCP works." --repeats 1

Standard는 service_tier="default", Flex는 service_tier="flex"로 요청한다.
한 시행의 네 요청이 모두 끝난 뒤 10초 쉬고 다음 시행을 시작한다.
기본 설정은 총 50회 시행, 200개 요청이며 마지막 시행 뒤에는 쉬지 않는다.
요청별 제한 시간은 900초이며, 재시도나 Standard 폴백은 하지 않는다.
요청 결과는 완료되는 즉시 results/ 아래 JSONL 파일에 저장한다.
응답 전문, 토큰 사용량, 실제 처리 티어, 오류의 원인 예외까지 기록한다.
측정값은 첫 토큰 도착 시간이 아니라 전체 응답을 받을 때까지 걸린 시간이다.
각 요청에는 비용이 발생할 수 있으며, API 키는 결과 파일에 저장하지 않는다.

공식 문서:
    https://learn.microsoft.com/azure/foundry/openai/how-to/flex-processing
"""

import argparse
import asyncio
import json
import math
import os
import platform
import sys
import traceback
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from time import perf_counter
from typing import Literal, TextIO
from uuid import uuid4

from openai import APIError, APIStatusError, AsyncOpenAI, __version__ as openai_version

ServiceTier = Literal["default", "flex"]
TIERS: tuple[ServiceTier, ...] = ("default", "flex")
MODEL_IDS = ("gpt-6-sol", "gpt-6-luna")


@dataclass(frozen=True)
class Prompt:
    id: str
    text: str


PROMPTS = (
    Prompt(
        "network",
        "TCP와 UDP의 차이를 연결 설정, 신뢰성, 순서 보장, 오버헤드, 사용 사례의 "
        "다섯 항목으로 설명해줘. 한국어로 항목마다 두 문장 이내로 작성해줘.",
    ),
    Prompt(
        "summary",
        "다음 가상 회의록의 결정 사항과 담당자별 할 일을 한국어로 정리해줘. "
        "없는 내용은 추가하지 마.\n"
        "회의록: API p95 지연시간이 목표 800ms보다 높은 1,200ms로 측정됐다. "
        "캐시를 먼저 적용하고 DB 증설은 효과 확인 후 결정한다. "
        "민수는 금요일까지 캐시 실험을, 지연은 목요일까지 부하 테스트를 완료한다. "
        "영희는 월요일에 결과를 취합해 배포 여부를 결정한다. "
        "캐시 적중률 목표는 70%이며 권한별 응답은 캐시에서 제외한다.",
    ),
    Prompt(
        "extraction",
        "아래 가상 문의에서 ticket_id, product, issue, urgency를 추출해 JSON 배열만 "
        "반환해줘. urgency는 결제 중단이면 high, 나머지는 normal이다. "
        "알 수 없는 product는 null로 표시해줘.\n"
        "T-101: 결제 API 오류로 모든 고객의 결제가 중단됐습니다.\n"
        "T-102: 관리자 대시보드의 CSV 다운로드 버튼 위치를 알려주세요.\n"
        "T-103: 사용 설명서가 필요합니다. 제품명은 아직 확인하지 못했습니다.",
    ),
    Prompt(
        "reasoning",
        "작업 240개를 작업자 4명이 동시에 시작해 처리한다. 작업 하나에 정확히 "
        "45초가 걸리며 배분과 전환에는 시간이 들지 않는다. 전체 작업이 끝난 뒤 "
        "검증에 30초가 추가된다. 검증까지의 총시간을 초와 분으로 계산해줘. "
        "작업자가 6명일 때의 시간과 원래 대비 단축률도 계산해줘. "
        "계산식과 최종값만 간결하게 제시해줘.",
    ),
    Prompt(
        "coding",
        "Python 3.10 이상의 sum_paid_orders 함수를 작성해줘. 입력은 customer_id, "
        "status, amount 키가 있는 딕셔너리의 리스트이며 amount는 금액 문자열이다. "
        "status가 paid인 주문만 고객별로 합산한 딕셔너리를 반환해줘. "
        "금액 계산은 decimal.Decimal을 사용하고 빈 입력은 빈 딕셔너리를 반환해줘. "
        "타입 힌트와 assert 테스트 두 개를 포함해 코드 블록 하나만 반환해줘.",
    ),
)


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class RunLog:
    output: TextIO
    request_count: int = 0
    success_count: int = 0

    def write(self, record: dict[str, object]) -> None:
        # await 없이 한 줄을 쓰므로 동시 요청끼리 JSON이 섞이지 않는다.
        self.output.write(json.dumps(record, ensure_ascii=False, allow_nan=False) + "\n")
        self.output.flush()
        if record["type"] == "request":
            self.request_count += 1
            if record["success"] is True:
                self.success_count += 1


def describe_error(error: BaseException) -> dict[str, object]:
    return {
        "type": type(error).__name__,
        "message": str(error),
        "traceback": "".join(traceback.format_exception(error)),
    }


async def send_request(
    client: AsyncOpenAI,
    deployment: str,
    tier: ServiceTier,
    prompt: str,
    log: RunLog,
    context: dict[str, object],
) -> bool:
    label = f"trial={context['trial']} | {deployment} | requested={tier}"
    record: dict[str, object] = {
        **context,
        "type": "request",
        "deployment": deployment,
        "requested_service_tier": tier,
        "prompt": prompt,
        "started_at": utc_now(),
        "finished_at": None,
        "elapsed_seconds": None,
        "success": False,
        "outcome": "interrupted",
        "actual_service_tier": None,
        "response_status": None,
        "request_id": None,
        "http_status": None,
        "usage": None,
        "output_text": None,
        "response": None,
        "error": None,
    }
    started = perf_counter()
    try:
        try:
            # model에는 모델 ID가 아니라 Azure에서 지정한 배포 이름을 넣는다.
            response = await client.responses.create(
                model=deployment,
                input=prompt,
                service_tier=tier,
            )
        finally:
            # 출력과 파일 저장에 드는 시간은 요청 지연시간에서 제외한다.
            elapsed = perf_counter() - started
            record.update(finished_at=utc_now(), elapsed_seconds=elapsed)
    except APIError as error:
        # 한 요청이 실패해도 다른 세 요청의 결과는 끝까지 수집한다.
        record.update(outcome="api_error", error=describe_error(error))
        print(f"\n[{label}] ERROR after {elapsed:.3f}s: {type(error).__name__}: {error}")
        if isinstance(error, APIStatusError):
            record.update(http_status=error.status_code, request_id=error.request_id)
            print(f"HTTP status={error.status_code} | request_id={error.request_id}")
        traceback.print_exception(error, file=sys.stdout)
    else:
        # 다른 티어로 처리되거나 응답이 미완료된 경우 비교 성공으로 세지 않는다.
        success = response.service_tier == tier and response.status == "completed"
        record.update(
            success=success,
            outcome="success" if success else "response_error",
            actual_service_tier=response.service_tier,
            response_status=response.status,
            request_id=response._request_id,
            usage=response.usage.model_dump(mode="json") if response.usage is not None else None,
            output_text=response.output_text,
            response=response.model_dump(mode="json"),
        )
        print(
            f"\n[{label}] {'OK' if success else 'ERROR'} | "
            f"actual={response.service_tier} | status={response.status} | {elapsed:.3f}s"
        )
        if response.usage is not None:
            print(
                f"Tokens: input={response.usage.input_tokens}, "
                f"output={response.usage.output_tokens}, total={response.usage.total_tokens}"
            )
        if response.service_tier != tier:
            print(f"ERROR: requested tier {tier!r}, received {response.service_tier!r}.")
        if response.status != "completed":
            print(
                f"ERROR: response did not complete: {response.incomplete_details}; "
                f"error={response.error}"
            )
    finally:
        unhandled = sys.exc_info()[1]
        if record["outcome"] == "interrupted" and unhandled is not None:
            record.update(
                success=False,
                outcome="cancelled" if isinstance(unhandled, asyncio.CancelledError) else "internal_error",
                error=describe_error(unhandled),
            )
        # 완료된 요청부터 저장하므로 다른 요청을 기다리다 중단해도 결과가 남는다.
        log.write(record)
    return record["success"] is True


async def compare(
    endpoint: str,
    key: str,
    deployments: tuple[str, str],
    prompts: tuple[Prompt, ...] = PROMPTS,
    repeats: int = 10,
    interval: float = 10.0,
    output_path: Path | None = None,
) -> int:
    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ") + "_" + uuid4().hex[:8]
    if output_path is None:
        output_path = Path(__file__).resolve().parent / "results" / f"{run_id}.jsonl"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    total_trials = len(prompts) * repeats
    expected_requests = total_trials * len(deployments) * len(TIERS)
    started = perf_counter()
    completed_trials = 0
    status = "failed"

    # 기존 실행 결과를 덮어쓰지 않도록 배타적 생성 모드를 사용한다.
    with output_path.open("x", encoding="utf-8") as output:
        log = RunLog(output)
        log.write(
            {
                "type": "run_start",
                "schema_version": 1,
                "run_id": run_id,
                "started_at": utc_now(),
                "python_version": platform.python_version(),
                "openai_version": openai_version,
                "prompts": [asdict(prompt) for prompt in prompts],
                "models": dict(zip(MODEL_IDS, deployments)),
                "service_tiers": list(TIERS),
                "repeats": repeats,
                "interval_seconds": interval,
                "interval_policy": "after_trial_completion",
                "order": "repetition_then_prompt",
                "expected_trials": total_trials,
                "expected_requests": expected_requests,
                "timeout_seconds": 900.0,
                "max_retries": 0,
                "standard_fallback": False,
            }
        )
        print(f"Results: {output_path.resolve()}", flush=True)
        print(f"Planned: {total_trials} trials, {expected_requests} requests", flush=True)
        try:
            async with AsyncOpenAI(
                base_url=f"{endpoint.rstrip('/')}/openai/v1/",
                api_key=key,
                timeout=900.0,
                # 자동 재시도가 측정 시간에 섞이지 않도록 끈다.
                max_retries=0,
            ) as client:
                # 시간대에 따른 영향을 줄이기 위해 다섯 프롬프트를 번갈아 시행한다.
                for repetition in range(1, repeats + 1):
                    for prompt in prompts:
                        trial = completed_trials + 1
                        context: dict[str, object] = {
                            "run_id": run_id,
                            "trial": trial,
                            "repetition": repetition,
                            "prompt_id": prompt.id,
                        }
                        print(
                            f"\nTrial {trial}/{total_trials} | "
                            f"repetition={repetition} | prompt={prompt.id}",
                            flush=True,
                        )
                        tasks = [
                            asyncio.create_task(
                                send_request(
                                    client, deployment, tier, prompt.text, log,
                                    {**context, "model_id": model_id},
                                )
                            )
                            for model_id, deployment in zip(MODEL_IDS, deployments)
                            for tier in TIERS
                        ]
                        try:
                            results = await asyncio.gather(*tasks)
                        finally:
                            # 중단 시 진행 중인 요청도 기록한 뒤 파일을 닫는다.
                            for task in tasks:
                                if not task.done():
                                    task.cancel()
                            await asyncio.gather(*tasks, return_exceptions=True)
                        completed_trials += 1
                        print(f"Trial successful: {sum(results)}/4", flush=True)
                        if completed_trials < total_trials:
                            await asyncio.sleep(interval)
            status = "completed" if log.success_count == expected_requests else "completed_with_errors"
        except asyncio.CancelledError:
            status = "interrupted"
            raise
        finally:
            log.write(
                {
                    "type": "run_end",
                    "run_id": run_id,
                    "finished_at": utc_now(),
                    "status": status,
                    "completed_trials": completed_trials,
                    "recorded_requests": log.request_count,
                    "successful_requests": log.success_count,
                    "unsuccessful_requests": log.request_count - log.success_count,
                    "elapsed_seconds": perf_counter() - started,
                }
            )
            print(f"\n{status}: {log.success_count}/{log.request_count} successful | {output_path}")
    return 0 if status == "completed" else 1


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--prompt", help="기본 프롬프트 5개 대신 사용할 단일 프롬프트")
    parser.add_argument("--repeats", type=int, default=10, help="프롬프트별 시행 횟수 (기본: 10)")
    parser.add_argument("--interval", type=float, default=10.0, help="시행 완료 후 대기할 초 (기본: 10)")
    parser.add_argument("--output", type=Path, help="저장할 JSONL 파일 경로 (기존 파일 덮어쓰기 금지)")
    args = parser.parse_args()

    if args.repeats < 1:
        parser.error("--repeats는 1 이상이어야 합니다.")
    if not math.isfinite(args.interval) or args.interval < 0:
        parser.error("--interval은 0 이상의 유한한 숫자여야 합니다.")
    if args.prompt is not None and not args.prompt.strip():
        parser.error("--prompt는 비어 있을 수 없습니다.")
    endpoint = os.environ.get("AZURE_OPENAI_ENDPOINT", "").strip()
    key = os.environ.get("AZURE_OPENAI_API_KEY", "").strip()
    if not endpoint or not key:
        parser.error("Set AZURE_OPENAI_ENDPOINT (resource root URL) and AZURE_OPENAI_API_KEY.")
    deployments = (
        os.environ.get("AZURE_OPENAI_SOL_DEPLOYMENT", "gpt-6-sol").strip(),
        os.environ.get("AZURE_OPENAI_LUNA_DEPLOYMENT", "gpt-6-luna").strip(),
    )
    if not all(deployments):
        parser.error("Deployment names must not be empty.")
    prompts = (Prompt("custom", args.prompt),) if args.prompt is not None else PROMPTS
    try:
        return asyncio.run(
            compare(endpoint, key, deployments, prompts, args.repeats, args.interval, args.output)
        )
    except FileExistsError:
        parser.error("--output 파일이 이미 존재합니다. 다른 파일 이름을 지정하세요.")
    except KeyboardInterrupt:
        print("\n중단했습니다. 완료·취소된 요청 기록은 결과 파일에 남아 있습니다.", file=sys.stderr)
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
