import json
import os
import unittest
from unittest import mock

from praxis import llm
from praxis.agent import run_agent
from praxis.config import build_config
from praxis.demo_model import DemoClient
from praxis.tools import Workspace

MESSAGES = [
    {"role": "user", "content": "do the job"},
    {"role": "assistant", "text": "looking", "tool_calls": [{"id": "a1", "name": "list_files", "args": {"path": "receipts"}}]},
    {"role": "tool", "results": [{"id": "a1", "name": "list_files", "content": "receipts/receipt_01.txt", "ok": True}]},
]


class FakeResponse:
    def __init__(self, status=200, body=None, headers=None, text=""):
        self.status_code, self._body, self.headers, self.text = status, body, headers or {}, text

    def json(self):
        return self._body


class ConversionTests(unittest.TestCase):
    def test_openai_message_shapes(self):
        out = llm.to_openai_messages("SYSTEM", MESSAGES)
        self.assertEqual([m["role"] for m in out], ["system", "user", "assistant", "tool"])
        call = out[2]["tool_calls"][0]
        self.assertEqual(call["function"]["name"], "list_files")
        self.assertEqual(json.loads(call["function"]["arguments"]), {"path": "receipts"})
        self.assertEqual(out[3]["tool_call_id"], "a1")

    def test_openai_reply_parsing_and_usage(self):
        data = {
            "choices": [{"message": {"content": "hi", "tool_calls": [
                {"id": "x", "type": "function", "function": {"name": "read_file", "arguments": '{"path": "receipts/receipt_02.txt"}'}}]}}],
            "usage": {"prompt_tokens": 120, "completion_tokens": 30},
        }
        reply = llm.parse_openai_reply(data)
        self.assertEqual(reply.text, "hi")
        self.assertEqual(reply.tool_calls[0]["args"], {"path": "receipts/receipt_02.txt"})
        self.assertEqual((reply.tokens_in, reply.tokens_out), (120, 30))

    def test_unreadable_arguments_do_not_crash(self):
        data = {"choices": [{"message": {"content": None, "tool_calls": [
            {"id": "x", "function": {"name": "read_file", "arguments": "{not json"}}]}}]}
        self.assertIn("_unreadable_arguments", llm.parse_openai_reply(data).tool_calls[0]["args"])

    def test_extra_content_is_preserved_round_trip(self):
        """Some Gemini models attach a 'thought signature' that must be sent back."""
        data = {"choices": [{"message": {"content": "", "tool_calls": [
            {"id": "x", "function": {"name": "list_files", "arguments": "{}"}, "extra_content": {"google": {"thought_signature": "abc"}}}]}}]}
        call = llm.parse_openai_reply(data).tool_calls[0]
        messages = [{"role": "user", "content": "go"}, {"role": "assistant", "text": "", "tool_calls": [call]}]
        sent = llm.to_openai_messages("s", messages)[2]["tool_calls"][0]
        self.assertEqual(sent["extra_content"], {"google": {"thought_signature": "abc"}})

    def test_unexpected_reply_shape_is_a_clear_error(self):
        with self.assertRaises(llm.LLMError):
            llm.parse_openai_reply({"nope": 1})
        with self.assertRaises(llm.LLMError):
            llm.parse_anthropic_reply({"nope": 1})

    def test_anthropic_message_shapes(self):
        out = llm.to_anthropic_messages(MESSAGES)
        self.assertEqual([m["role"] for m in out], ["user", "assistant", "user"])
        self.assertEqual([b["type"] for b in out[1]["content"]], ["text", "tool_use"])
        result = out[2]["content"][0]
        self.assertEqual((result["type"], result["tool_use_id"], result["is_error"]), ("tool_result", "a1", False))

    def test_anthropic_reply_parsing(self):
        data = {"content": [{"type": "text", "text": "ok"}, {"type": "tool_use", "id": "t1", "name": "finish", "input": {"summary": "done"}}],
                "usage": {"input_tokens": 50, "output_tokens": 9}}
        reply = llm.parse_anthropic_reply(data)
        self.assertEqual(reply.tool_calls[0], {"id": "t1", "name": "finish", "args": {"summary": "done"}})
        self.assertEqual((reply.tokens_in, reply.tokens_out), (50, 9))

    def test_tool_schemas_avoid_union_types_that_gemini_rejects(self):
        from praxis.agent import tool_specs
        text = json.dumps(tool_specs(build_config(True, True, True)))
        self.assertNotIn('"type": ["', text)


class NetworkBehaviourTests(unittest.TestCase):
    def setUp(self):
        patcher = mock.patch.object(llm, "_sleep")
        self.sleep = patcher.start()
        self.addCleanup(patcher.stop)

    def test_retries_on_rate_limit_then_succeeds(self):
        responses = [FakeResponse(429), FakeResponse(429), FakeResponse(200, {"ok": True})]
        with mock.patch.object(llm.requests, "post", side_effect=responses) as post:
            self.assertEqual(llm._post_with_retry("u", {}, {}), {"ok": True})
        self.assertEqual(post.call_count, 3)
        self.assertEqual(self.sleep.call_count, 2)

    def test_respects_retry_after_header(self):
        responses = [FakeResponse(429, headers={"retry-after": "7"}), FakeResponse(200, {})]
        with mock.patch.object(llm.requests, "post", side_effect=responses):
            llm._post_with_retry("u", {}, {})
        self.sleep.assert_called_once_with(7.0)

    def test_gives_up_with_a_friendly_rate_limit_message(self):
        with mock.patch.object(llm.requests, "post", return_value=FakeResponse(429)) as post:
            with self.assertRaises(llm.LLMError) as ctx:
                llm._post_with_retry("u", {}, {})
        self.assertEqual(post.call_count, llm.MAX_ATTEMPTS)
        self.assertIn("Rate limit", str(ctx.exception))

    def test_bad_key_is_not_retried(self):
        with mock.patch.object(llm.requests, "post", return_value=FakeResponse(401)) as post:
            with self.assertRaises(llm.LLMError) as ctx:
                llm._post_with_retry("u", {}, {})
        self.assertEqual(post.call_count, 1)
        self.assertIn("key was rejected", str(ctx.exception))

    def test_network_failure_becomes_a_clear_error(self):
        with mock.patch.object(llm.requests, "post", side_effect=llm.requests.ConnectionError("boom")):
            with self.assertRaises(llm.LLMError) as ctx:
                llm._post_with_retry("u", {}, {})
        self.assertIn("Could not reach", str(ctx.exception))

    def test_error_messages_never_contain_the_api_key(self):
        client = llm.OpenAICompatClient("gemini", "https://example.test", "SECRET-KEY-123", "m")
        with mock.patch.object(llm.requests, "post", return_value=FakeResponse(400, text="bad request")):
            with self.assertRaises(llm.LLMError) as ctx:
                client.chat("s", [{"role": "user", "content": "x"}], [])
        self.assertNotIn("SECRET-KEY-123", str(ctx.exception))

    def test_the_key_goes_in_the_header_and_never_in_the_body(self):
        client = llm.OpenAICompatClient("gemini", "https://example.test/v1", "SECRET-KEY-123", "gem-model")
        body = {"choices": [{"message": {"content": "hi"}}]}
        with mock.patch.object(llm.requests, "post", return_value=FakeResponse(200, body)) as post:
            client.chat("s", [{"role": "user", "content": "x"}], [])
        args, kwargs = post.call_args
        self.assertEqual(args[0], "https://example.test/v1/chat/completions")
        self.assertEqual(kwargs["headers"]["Authorization"], "Bearer SECRET-KEY-123")
        self.assertNotIn("SECRET-KEY-123", json.dumps(kwargs["json"]))
        self.assertEqual(kwargs["json"]["model"], "gem-model")


class MakeClientTests(unittest.TestCase):
    def test_demo_needs_no_key(self):
        self.assertIsInstance(llm.make_client("demo"), DemoClient)

    def test_unknown_provider(self):
        with self.assertRaises(llm.LLMError):
            llm.make_client("nonsense")

    def test_missing_key_gives_a_helpful_message(self):
        with mock.patch.dict(os.environ, {}, clear=True):
            with self.assertRaises(llm.LLMError) as ctx:
                llm.make_client("gemini")
        self.assertIn("GEMINI_API_KEY", str(ctx.exception))

    def test_model_override_and_default(self):
        with mock.patch.dict(os.environ, {"GROQ_API_KEY": "k"}, clear=True):
            self.assertEqual(llm.make_client("groq").model, llm.PROVIDERS["groq"]["model"])
        with mock.patch.dict(os.environ, {"GROQ_API_KEY": "k", "AGENT_MODEL": "custom-model"}, clear=True):
            self.assertEqual(llm.make_client("groq").model, "custom-model")
        self.assertEqual(llm.make_client("groq", api_key="k", model="explicit").model, "explicit")

    def test_claude_uses_the_anthropic_adapter(self):
        self.assertIsInstance(llm.make_client("anthropic", api_key="k"), llm.AnthropicClient)

    def test_server_key_detection(self):
        with mock.patch.dict(os.environ, {"GEMINI_API_KEY": "k"}, clear=True):
            self.assertTrue(llm.server_key_available("gemini"))
            self.assertFalse(llm.server_key_available("groq"))


class AdapterWithAgentLoopTest(unittest.TestCase):
    """Run the real agent loop through the real OpenAI adapter, with only the network faked."""

    def test_full_loop_over_the_openai_adapter(self):
        def tool_reply(call_id, name, args):
            return FakeResponse(200, {"choices": [{"message": {"content": "", "tool_calls": [
                {"id": call_id, "type": "function", "function": {"name": name, "arguments": json.dumps(args)}}]}}],
                "usage": {"prompt_tokens": 100, "completion_tokens": 10}})

        responses = [tool_reply("c1", "list_files", {"path": "receipts"}), tool_reply("c2", "finish", {"summary": "done"})]
        client = llm.OpenAICompatClient("gemini", "https://example.test", "k", "m")
        workspace = Workspace.create()
        self.addCleanup(workspace.cleanup)
        with mock.patch.object(llm.requests, "post", side_effect=responses) as post:
            record = run_agent(client, build_config(False, False, False), workspace)
        self.assertTrue(record["finished"])
        self.assertEqual(record["tokens_in"], 200)
        second_request = post.call_args_list[1].kwargs["json"]["messages"]
        self.assertEqual(second_request[-1]["role"], "tool")  # the tool result was fed back to the model
        self.assertIn("receipt_01", second_request[-1]["content"])


if __name__ == "__main__":
    unittest.main()
