"""The "brain" connection: one small interface, several providers behind it.

The agent only ever calls  client.chat(system, messages, tools)  and gets back an
LLMReply. Which company's model answers is decided here, by a setting.

Inside the agent, messages use one simple neutral format:
  {"role": "user", "content": "text"}
  {"role": "assistant", "text": "...", "tool_calls": [{"id", "name", "args"}]}
  {"role": "tool", "results": [{"id", "name", "content", "ok"}]}
Each adapter below translates that format to what its provider expects.

The HTTP calls use the plain `requests` library on purpose, so the request and
response shapes are visible and easy to explain.
"""

from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass, field

import requests

MAX_ATTEMPTS = 4
RETRY_STATUS = {429, 500, 502, 503, 504, 529}
REQUEST_TIMEOUT = 90
_sleep = time.sleep  # a variable so tests can skip real waiting


class LLMError(Exception):
    """Something went wrong talking to the model. The message is safe to show to a user."""


@dataclass
class LLMReply:
    text: str = ""
    tool_calls: list[dict] = field(default_factory=list)
    tokens_in: int = 0
    tokens_out: int = 0


# name -> how to reach it. Model names change often, so each can be overridden
# with the AGENT_MODEL setting.
PROVIDERS: dict[str, dict] = {
    "gemini": {
        "label": "Google Gemini (free tier)",
        "kind": "openai",
        "base_url": "https://generativelanguage.googleapis.com/v1beta/openai",
        "env_key": "GEMINI_API_KEY",
        "model": "gemini-flash-latest",
    },
    "groq": {
        "label": "Groq (free tier)",
        "kind": "openai",
        "base_url": "https://api.groq.com/openai/v1",
        "env_key": "GROQ_API_KEY",
        "model": "llama-3.3-70b-versatile",
    },
    "openrouter": {
        "label": "OpenRouter (free models)",
        "kind": "openai",
        "base_url": "https://openrouter.ai/api/v1",
        "env_key": "OPENROUTER_API_KEY",
        "model": "openrouter/free",
    },
    "anthropic": {
        "label": "Anthropic Claude (paid)",
        "kind": "anthropic",
        "base_url": "https://api.anthropic.com/v1/messages",
        "env_key": "ANTHROPIC_API_KEY",
        "model": "claude-haiku-5-5",
    },
}
LIVE_PROVIDERS = list(PROVIDERS)


# ---------------------------------------------------------------------------
# Talking to the network (shared by every adapter)
# ---------------------------------------------------------------------------
def _backoff_seconds(attempt: int, retry_after: str | None) -> float:
    """How long to wait before trying again: the provider's hint, else 2, 4, 8... seconds."""
    if retry_after:
        try:
            return min(float(retry_after), 30.0)
        except ValueError:
            pass
    return float(min(2 ** (attempt + 1), 20))


def _friendly_error(response: requests.Response) -> LLMError:
    status = response.status_code
    snippet = (response.text or "").strip().replace("\n", " ")[:300]
    if status in (401, 403):
        return LLMError("The API key was rejected. Check that it is correct and has access to this model.")
    if status == 429:
        return LLMError(
            "Rate limit reached. Free tiers allow only a few requests per minute. "
            "Wait a minute and try again, or use a different provider or key."
        )
    if status == 404:
        return LLMError("Model not found. Check the model name (set AGENT_MODEL) in the provider's docs.")
    if status == 400:
        return LLMError(f"The provider rejected the request: {snippet}")
    return LLMError(f"The provider returned an error ({status}): {snippet}")


def _post_with_retry(url: str, headers: dict, payload: dict) -> dict:
    """POST JSON, retrying a few times on rate limits and temporary server errors."""
    for attempt in range(MAX_ATTEMPTS):
        is_last = attempt == MAX_ATTEMPTS - 1
        try:
            response = requests.post(url, headers=headers, json=payload, timeout=REQUEST_TIMEOUT)
        except requests.RequestException as exc:
            if is_last:
                raise LLMError(f"Could not reach the provider ({exc.__class__.__name__}).")
            _sleep(_backoff_seconds(attempt, None))
            continue
        if response.status_code == 200:
            try:
                return response.json()
            except ValueError:
                raise LLMError("The provider sent a reply that was not valid JSON.")
        if response.status_code in RETRY_STATUS and not is_last:
            _sleep(_backoff_seconds(attempt, response.headers.get("retry-after")))
            continue
        raise _friendly_error(response)
    raise LLMError("The provider did not answer.")  # not reachable, keeps type checkers happy


# ---------------------------------------------------------------------------
# Adapter 1: OpenAI-compatible APIs (Gemini, Groq and OpenRouter all speak this)
# ---------------------------------------------------------------------------
def to_openai_messages(system: str, messages: list[dict]) -> list[dict]:
    out: list[dict] = [{"role": "system", "content": system}]
    for message in messages:
        role = message["role"]
        if role == "user":
            out.append({"role": "user", "content": message["content"]})
        elif role == "assistant":
            item: dict = {"role": "assistant", "content": message.get("text") or None}
            calls = []
            for call in message.get("tool_calls", []):
                entry = {
                    "id": call["id"],
                    "type": "function",
                    "function": {"name": call["name"], "arguments": json.dumps(call["args"])},
                }
                if call.get("extra"):  # e.g. Gemini "thought signatures"; must be sent back
                    entry["extra_content"] = call["extra"]
                calls.append(entry)
            if calls:
                item["tool_calls"] = calls
            out.append(item)
        elif role == "tool":
            for result in message["results"]:
                out.append(
                    {
                        "role": "tool",
                        "tool_call_id": result["id"],
                        "name": result["name"],
                        "content": result["content"],
                    }
                )
    return out


def to_openai_tools(tools: list[dict]) -> list[dict]:
    return [
        {"type": "function", "function": {"name": t["name"], "description": t["description"], "parameters": t["parameters"]}}
        for t in tools
    ]


def parse_openai_reply(data: dict) -> LLMReply:
    try:
        message = data["choices"][0]["message"]
    except (KeyError, IndexError, TypeError):
        raise LLMError("The provider sent a reply in an unexpected shape.")
    calls = []
    for raw in message.get("tool_calls") or []:
        function = raw.get("function") or {}
        try:
            args = json.loads(function.get("arguments") or "{}")
        except json.JSONDecodeError:
            args = {"_unreadable_arguments": str(function.get("arguments"))[:200]}
        call = {"id": raw.get("id") or f"call_{len(calls)}", "name": function.get("name", ""), "args": args}
        if raw.get("extra_content"):
            call["extra"] = raw["extra_content"]
        calls.append(call)
    usage = data.get("usage") or {}
    return LLMReply(
        text=(message.get("content") or "").strip(),
        tool_calls=calls,
        tokens_in=int(usage.get("prompt_tokens") or 0),
        tokens_out=int(usage.get("completion_tokens") or 0),
    )


class OpenAICompatClient:
    def __init__(self, provider: str, base_url: str, api_key: str, model: str):
        self.provider, self.base_url, self.api_key, self.model = provider, base_url.rstrip("/"), api_key, model
        self.is_demo = False

    def chat(self, system: str, messages: list[dict], tools: list[dict]) -> LLMReply:
        payload = {
            "model": self.model,
            "messages": to_openai_messages(system, messages),
            "tools": to_openai_tools(tools),
            "temperature": 0,
        }
        headers = {"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"}
        return parse_openai_reply(_post_with_retry(f"{self.base_url}/chat/completions", headers, payload))


# ---------------------------------------------------------------------------
# Adapter 2: Anthropic Claude
# ---------------------------------------------------------------------------
def to_anthropic_messages(messages: list[dict]) -> list[dict]:
    out: list[dict] = []
    for message in messages:
        role = message["role"]
        if role == "user":
            out.append({"role": "user", "content": message["content"]})
        elif role == "assistant":
            blocks: list[dict] = []
            if message.get("text"):
                blocks.append({"type": "text", "text": message["text"]})
            for call in message.get("tool_calls", []):
                blocks.append({"type": "tool_use", "id": call["id"], "name": call["name"], "input": call["args"]})
            out.append({"role": "assistant", "content": blocks})
        elif role == "tool":
            blocks = [
                {
                    "type": "tool_result",
                    "tool_use_id": r["id"],
                    "content": r["content"],
                    "is_error": not r.get("ok", True),
                }
                for r in message["results"]
            ]
            out.append({"role": "user", "content": blocks})
    return out


def to_anthropic_tools(tools: list[dict]) -> list[dict]:
    return [{"name": t["name"], "description": t["description"], "input_schema": t["parameters"]} for t in tools]


def parse_anthropic_reply(data: dict) -> LLMReply:
    blocks = data.get("content")
    if not isinstance(blocks, list):
        raise LLMError("The provider sent a reply in an unexpected shape.")
    text_parts, calls = [], []
    for block in blocks:
        if block.get("type") == "text":
            text_parts.append(block.get("text", ""))
        elif block.get("type") == "tool_use":
            calls.append({"id": block["id"], "name": block["name"], "args": block.get("input") or {}})
    usage = data.get("usage") or {}
    return LLMReply(
        text="\n".join(text_parts).strip(),
        tool_calls=calls,
        tokens_in=int(usage.get("input_tokens") or 0),
        tokens_out=int(usage.get("output_tokens") or 0),
    )


class AnthropicClient:
    def __init__(self, api_key: str, model: str, url: str = PROVIDERS["anthropic"]["base_url"]):
        self.provider, self.api_key, self.model, self.url = "anthropic", api_key, model, url
        self.is_demo = False

    def chat(self, system: str, messages: list[dict], tools: list[dict]) -> LLMReply:
        payload = {
            "model": self.model,
            "max_tokens": 4096,
            "system": system,
            "messages": to_anthropic_messages(messages),
            "tools": to_anthropic_tools(tools),
        }
        headers = {
            "x-api-key": self.api_key,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        }
        return parse_anthropic_reply(_post_with_retry(self.url, headers, payload))


# ---------------------------------------------------------------------------
# Choosing a provider
# ---------------------------------------------------------------------------
def server_key_available(provider: str) -> bool:
    """True if the host (for example a Space secret) has a key for this provider."""
    info = PROVIDERS.get(provider)
    return bool(info and os.environ.get(info["env_key"]))


def default_model(provider: str) -> str:
    return os.environ.get("AGENT_MODEL") or PROVIDERS[provider]["model"]


def make_client(provider: str | None = None, api_key: str | None = None, model: str | None = None):
    """Build the brain for a run. provider 'demo' gives the scripted stand-in (no key needed)."""
    provider = (provider or os.environ.get("LLM_PROVIDER") or "gemini").lower()
    if provider == "demo":
        from .demo_model import DemoClient

        return DemoClient()
    if provider not in PROVIDERS:
        raise LLMError(f"Unknown provider '{provider}'. Choose one of: demo, {', '.join(PROVIDERS)}.")
    info = PROVIDERS[provider]
    key = api_key or os.environ.get(info["env_key"])
    if not key:
        raise LLMError(f"No API key for {info['label']}. Set {info['env_key']} in your .env file or paste a key in the app.")
    chosen_model = model or default_model(provider)
    if info["kind"] == "anthropic":
        return AnthropicClient(key, chosen_model)
    return OpenAICompatClient(provider, info["base_url"], key, chosen_model)
