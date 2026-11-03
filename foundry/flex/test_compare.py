import asyncio
from collections import Counter
import contextlib
from datetime import datetime
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import AsyncMock, patch

import httpx
from openai import AsyncOpenAI

import compare


def response_body(body, status="completed", tier=None):
    return {
        "id": "resp_test",
        "object": "response",
        "created_at": 1,
        "model": body["model"],
        "status": status,
        "service_tier": tier or body["service_tier"],
        "output": [{
            "id": "msg_test",
            "type": "message",
            "role": "assistant",
            "status": "completed",
            "content": [{"type": "output_text", "text": "테스트 응답", "annotations": []}],
        }],
        "incomplete_details": {"reason": "max_output_tokens"} if status == "incomplete" else None,
        "usage": {
            "input_tokens": 19,
            "input_tokens_details": {"cached_tokens": 3},
            "output_tokens": 15,
            "output_tokens_details": {"reasoning_tokens": 2},
            "total_tokens": 34,
        },
    }


class BenchmarkTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.path = Path(directory.name) / "run.jsonl"

    def records(self):
        return [json.loads(line) for line in self.path.read_text(encoding="utf-8").splitlines()]

    async def run_benchmark(self, mode="success", **options):
        sent = []
        gates = {}
        pause_counts = []

        async def handler(request):
            body = json.loads(request.content)
            batch = len(sent) // 4
            gate = gates.setdefault(batch, asyncio.Event())
            sent.append(body)
            if len(sent) % 4 == 0:
                gate.set()
            # 네 요청이 실제 전송 계층에 도착하기 전에는 응답하지 않는다.
            await asyncio.wait_for(gate.wait(), timeout=3)
            if mode == "errors":
                pair = (body["model"], body["service_tier"])
                if pair == ("sol-deployment", "default"):
                    try:
                        raise ConnectionResetError("test connection reset")
                    except ConnectionResetError as cause:
                        raise httpx.ConnectError("test transport error", request=request) from cause
                if pair == ("sol-deployment", "flex"):
                    return httpx.Response(
                        429, headers={"x-request-id": "test-error-id"},
                        json={"error": {"message": "test capacity unavailable"}},
                    )
                if pair == ("luna-deployment", "default"):
                    body = response_body(body, tier="flex")
                else:
                    body = response_body(body, status="incomplete")
            else:
                body = response_body(body)
            return httpx.Response(200, headers={"x-request-id": "test-success-id"}, json=body)

        async def pause(seconds):
            self.assertGreaterEqual(seconds, 0)
            saved = [record for record in self.records() if record["type"] == "request"]
            pause_counts.append(len(saved))
            self.assertEqual(len(saved), len(sent))
            self.assertEqual(len(saved) % 4, 0)

        client = AsyncOpenAI(
            base_url="https://example.invalid/openai/v1/",
            api_key="fake-test-key",
            max_retries=0,
            http_client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
        )
        with (
            patch.object(compare, "AsyncOpenAI", return_value=client) as constructor,
            patch.object(compare.asyncio, "sleep", side_effect=pause) as sleep,
            contextlib.redirect_stdout(io.StringIO()),
        ):
            result = await compare.compare(
                "https://example.invalid/", "fake-test-key",
                ("sol-deployment", "luna-deployment"), output_path=self.path, **options,
            )
        self.assertEqual(constructor.call_args.kwargs["max_retries"], 0)
        self.assertEqual(constructor.call_args.kwargs["timeout"], 900.0)
        self.assertEqual(
            constructor.call_args.kwargs["base_url"], "https://example.invalid/openai/v1/"
        )
        return result, sent, sleep, pause_counts

    async def test_default_run_has_200_records_and_49_completed_trial_pauses(self):
        result, sent, sleep, pause_counts = await self.run_benchmark()
        records = self.records()
        requests = records[1:-1]
        self.assertEqual(result, 0)
        self.assertEqual(len(sent), 200)
        self.assertEqual(len(records), 202)
        self.assertEqual(records[0]["expected_trials"], 50)
        self.assertEqual(records[0]["expected_requests"], 200)
        self.assertEqual(records[0]["interval_seconds"], 10.0)
        self.assertEqual(records[0]["repeats"], 10)
        self.assertEqual(sleep.await_count, 49)
        self.assertTrue(all(call.args == (10.0,) for call in sleep.await_args_list))
        self.assertEqual(pause_counts, list(range(4, 200, 4)))
        self.assertEqual(records[-1]["status"], "completed")
        self.assertEqual(records[-1]["recorded_requests"], 200)
        self.assertEqual(records[-1]["successful_requests"], 200)
        self.assertEqual(records[-1]["completed_trials"], 50)
        self.assertEqual(
            Counter(record["prompt_id"] for record in requests),
            {prompt.id: 40 for prompt in compare.PROMPTS},
        )
        for trial in range(1, 51):
            group = [record for record in requests if record["trial"] == trial]
            prompt = compare.PROMPTS[(trial - 1) % 5]
            self.assertEqual(len(group), 4)
            self.assertEqual({record["prompt"] for record in group}, {prompt.text})
            self.assertEqual({record["repetition"] for record in group}, {(trial - 1) // 5 + 1})
            self.assertEqual(
                {(record["model_id"], record["requested_service_tier"]) for record in group},
                {(model, tier) for model in compare.MODEL_IDS for tier in compare.TIERS},
            )
        for record in requests:
            self.assertTrue(record["success"])
            self.assertEqual(record["request_id"], "test-success-id")
            self.assertEqual(record["output_text"], "테스트 응답")
            self.assertEqual(record["usage"]["input_tokens_details"]["cached_tokens"], 3)
            self.assertEqual(record["usage"]["output_tokens_details"]["reasoning_tokens"], 2)
            self.assertEqual(record["response"]["usage"], record["usage"])
            self.assertGreaterEqual(record["elapsed_seconds"], 0)
            self.assertLessEqual(
                datetime.fromisoformat(record["started_at"]),
                datetime.fromisoformat(record["finished_at"]),
            )
        self.assertNotIn("fake-test-key", self.path.read_text())
        self.assertNotIn("api_key", records[0])
        self.assertNotIn("endpoint", records[0])

    async def test_errors_are_saved_without_retries_and_later_trials_continue(self):
        result, sent, sleep, _ = await self.run_benchmark(
            "errors", prompts=compare.PROMPTS[:2], repeats=2, interval=0,
        )
        records = self.records()
        requests = records[1:-1]
        self.assertEqual(result, 1)
        self.assertEqual(len(sent), 16)
        self.assertEqual(len(requests), 16)
        self.assertEqual(sleep.await_count, 3)
        self.assertEqual(records[-1]["status"], "completed_with_errors")
        self.assertEqual(records[-1]["successful_requests"], 0)
        self.assertEqual(records[-1]["completed_trials"], 4)
        connections = [record for record in requests if record["error"] and
                       record["error"]["type"] == "APIConnectionError"]
        self.assertEqual(len(connections), 4)
        self.assertTrue(all("test connection reset" in record["error"]["traceback"]
                            for record in connections))
        self.assertTrue(all(record["usage"] is None for record in connections))
        http_errors = [record for record in requests if record["http_status"] == 429]
        self.assertEqual(len(http_errors), 4)
        self.assertTrue(all(record["request_id"] == "test-error-id" for record in http_errors))
        self.assertEqual(sum(record["outcome"] == "response_error" for record in requests), 8)

    async def test_cancellation_keeps_completed_and_inflight_records(self):
        ready = asyncio.Event()
        first_written = asyncio.Event()
        blocked = asyncio.Event()
        sent = []
        original_write = compare.RunLog.write

        def write(log, record):
            original_write(log, record)
            if record["type"] == "request" and record["success"]:
                first_written.set()

        async def handler(request):
            body = json.loads(request.content)
            sent.append(body)
            if len(sent) == 4:
                ready.set()
            await ready.wait()
            if (body["model"], body["service_tier"]) != ("sol-deployment", "default"):
                await blocked.wait()
            return httpx.Response(200, json=response_body(body))

        client = AsyncOpenAI(
            api_key="fake-test-key", max_retries=0,
            http_client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
        )
        with (
            patch.object(compare, "AsyncOpenAI", return_value=client),
            patch.object(compare.RunLog, "write", new=write),
            contextlib.redirect_stdout(io.StringIO()),
        ):
            task = asyncio.create_task(compare.compare(
                "https://example.invalid", "fake-test-key",
                ("sol-deployment", "luna-deployment"), output_path=self.path,
            ))
            await asyncio.wait_for(first_written.wait(), timeout=3)
            self.assertEqual(len(self.records()), 2)
            task.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await asyncio.wait_for(task, timeout=3)
        records = self.records()
        self.assertEqual(len(records), 6)
        self.assertEqual(Counter(record["outcome"] for record in records[1:-1]),
                         {"success": 1, "cancelled": 3})
        self.assertEqual(records[-1]["status"], "interrupted")
        self.assertEqual(records[-1]["recorded_requests"], 4)
        self.assertEqual(records[-1]["successful_requests"], 1)

    async def test_existing_file_is_not_overwritten(self):
        self.path.write_text("keep existing data", encoding="utf-8")
        with patch.object(compare, "AsyncOpenAI") as constructor:
            with self.assertRaises(FileExistsError):
                await compare.compare(
                    "https://example.invalid", "fake-test-key",
                    ("sol-deployment", "luna-deployment"), output_path=self.path,
                )
        constructor.assert_not_called()
        self.assertEqual(self.path.read_text(), "keep existing data")

    async def test_callers_handled_exception_does_not_change_success(self):
        output = io.StringIO()
        client = AsyncOpenAI(
            api_key="fake-test-key",
            http_client=httpx.AsyncClient(transport=httpx.MockTransport(
                lambda request: httpx.Response(200, json=response_body(json.loads(request.content)))
            )),
        )
        with contextlib.redirect_stdout(io.StringIO()):
            async with client:
                try:
                    raise ValueError("unrelated caller error")
                except ValueError:
                    success = await compare.send_request(
                        client, "sol-deployment", "default", "prompt", compare.RunLog(output),
                        {"run_id": "test", "trial": 1, "repetition": 1,
                         "prompt_id": "custom", "model_id": "gpt-6-sol"},
                    )
        self.assertTrue(success)
        record = json.loads(output.getvalue())
        self.assertEqual(record["outcome"], "success")
        self.assertIsNone(record["error"])


class CommandLineTests(unittest.TestCase):
    ENV = {
        "AZURE_OPENAI_ENDPOINT": "https://example.invalid",
        "AZURE_OPENAI_API_KEY": "fake-test-key",
    }

    def test_invalid_options_fail_before_sending_requests(self):
        for arguments in (
            ["--repeats", "0"], ["--repeats", "-1"],
            ["--interval", "-1"], ["--interval", "nan"], ["--interval", "inf"],
            ["--prompt", "   "],
        ):
            with (
                self.subTest(arguments=arguments),
                patch.dict(os.environ, self.ENV, clear=True),
                patch("sys.argv", ["compare.py", *arguments]),
                patch.object(compare, "AsyncOpenAI") as constructor,
                contextlib.redirect_stderr(io.StringIO()),
                self.assertRaises(SystemExit) as error,
            ):
                compare.main()
            self.assertEqual(error.exception.code, 2)
            constructor.assert_not_called()

    def test_missing_credentials_fail_before_sending_requests(self):
        with (
            patch.dict(os.environ, {}, clear=True),
            patch("sys.argv", ["compare.py"]),
            contextlib.redirect_stderr(io.StringIO()),
            self.assertRaises(SystemExit) as error,
        ):
            compare.main()
        self.assertEqual(error.exception.code, 2)

    def test_custom_prompt_and_overrides_are_forwarded(self):
        with (
            patch.dict(os.environ, self.ENV, clear=True),
            patch("sys.argv", ["compare.py", "--prompt", "custom", "--repeats", "1",
                              "--interval", "0", "--output", "custom.jsonl"]),
            patch.object(compare, "compare", new_callable=AsyncMock, return_value=0) as run,
        ):
            self.assertEqual(compare.main(), 0)
        arguments = run.await_args.args
        self.assertEqual(arguments[3], (compare.Prompt("custom", "custom"),))
        self.assertEqual(arguments[4:], (1, 0.0, Path("custom.jsonl")))


if __name__ == "__main__":
    unittest.main()
