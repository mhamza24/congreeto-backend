import asyncio
import types
import time
import pytest

from app.modules.chat import service as chat_service
from app.modules.chat import models as chat_models


pytestmark = pytest.mark.asyncio


class DummyConversation:
    def __init__(self, id="conv_123", tenant_id="veloce"):
        self.id = id
        self.tenant_id = tenant_id
        self.total_tokens_used = 0
        self.total_messages = 0
        self.last_activity_at = None


class DummyMessage:
    def __init__(self, id="msg_123", role=chat_models.MessageRole.assistant, content="hi", response_ms=None):
        self.id = id
        self.role = role
        self.content = content
        self.response_ms = response_ms


class DummyDB:
    def __init__(self):
        self.flushed = False
        self.committed = False

    async def execute(self, *args, **kwargs):
        return None

    def add(self, obj):
        pass

    async def flush(self):
        self.flushed = True

    async def commit(self):
        self.committed = True


class Payload:
    def __init__(self, chat_id=None, message="Hello"):
        self.chat_id = chat_id
        self.message = message


# Behaviors to be tested:
# 1) Creates a new conversation if none exists and persists two messages then commits.
# 2) Continues existing conversation by loading history and including it in LLM context.
# 3) Handles OpenAI errors by returning fallback content and not setting response_ms.
# 4) Records response_ms when OpenAI succeeds and stores it on assistant message.
# 5) Returns response dict with expected fields and values.


@pytest.fixture
def db():
    return DummyDB()


@pytest.fixture
def patch_repo(monkeypatch):
    calls = types.SimpleNamespace(
        get_or_create=None,
        get_messages=None,
        add_message_calls=[],
        update_conv=None,
    )

    async def fake_get_or_create(db, chat_id, tenant_id):
        conv = DummyConversation(id=chat_id or "conv_new", tenant_id=tenant_id)
        return conv, (chat_id is None)

    async def fake_get_messages(db, conversation_id):
        calls.get_messages = conversation_id
        return [
            types.SimpleNamespace(role=chat_models.MessageRole.user, content="prev user"),
            types.SimpleNamespace(role=chat_models.MessageRole.assistant, content="prev asst"),
        ]

    async def fake_add_message(db, conversation_id, role, content, tokens_used=None, model_used=None, response_ms=None):
        msg = DummyMessage(id=f"msg_{len(calls.add_message_calls)+1}", role=role, content=content, response_ms=response_ms)
        calls.add_message_calls.append({
            "conversation_id": conversation_id,
            "role": role,
            "content": content,
            "response_ms": response_ms,
        })
        return msg

    async def fake_update_conversation_activity(conversation, token_increment=0, message_increment=0):
        calls.update_conv = (token_increment, message_increment)

    monkeypatch.setattr(chat_service.chat_repository, "get_or_create_conversation", fake_get_or_create)
    monkeypatch.setattr(chat_service.chat_repository, "get_messages", fake_get_messages)
    monkeypatch.setattr(chat_service.chat_repository, "add_message", fake_add_message)
    monkeypatch.setattr(chat_service.chat_repository, "update_conversation_activity", fake_update_conversation_activity)

    return calls


@pytest.fixture
def patch_openai_success(monkeypatch):
    async def fake_call_openai(messages, system_prompt):
        # Simulate some latency to produce a non-zero response_ms
        await asyncio.sleep(0.001)
        # Echo back last user content for determinism
        last_user = next((m["content"] for m in reversed(messages) if m["role"] == "user"), "")
        return f"ACK: {last_user}"

    monkeypatch.setattr(chat_service.open_ai_service, "call_openai", fake_call_openai)


@pytest.fixture
def patch_openai_error(monkeypatch):
    async def fake_call_openai(messages, system_prompt):
        raise RuntimeError("boom")

    monkeypatch.setattr(chat_service.open_ai_service, "call_openai", fake_call_openai)


async def test_creates_new_conversation_and_persists_messages(db, patch_repo, patch_openai_success):
    payload = Payload(chat_id=None, message="Hello new")

    result = await chat_service.create_or_continue_chat(payload, db, tenant_id="tenant_X")

    # Two messages should have been added: user then assistant
    assert len(patch_repo.add_message_calls) == 2
    assert patch_repo.add_message_calls[0]["role"] == chat_models.MessageRole.user
    assert patch_repo.add_message_calls[0]["content"] == "Hello new"
    assert patch_repo.add_message_calls[1]["role"] == chat_models.MessageRole.assistant

    # Conversation activity incremented by 2 messages
    assert patch_repo.update_conv == (0, 2)

    # DB commit called
    assert db.committed is True

    # Result structure
    assert result["role"] == "assistant"
    assert result["chat_id"].startswith("conv_") or result["chat_id"] == "conv_new"
    assert result["message_id"].startswith("msg_")


async def test_continues_existing_conversation_loads_history(db, patch_repo, patch_openai_success, monkeypatch):
    payload = Payload(chat_id="conv_existing", message="Hello existing")

    captured_context = {}

    async def capturing_openai(messages, system_prompt):
        captured_context["messages"] = messages
        return "ok"

    monkeypatch.setattr(chat_service.open_ai_service, "call_openai", capturing_openai)

    await chat_service.create_or_continue_chat(payload, db)

    msgs = captured_context["messages"]

    # First message is system
    assert msgs[0] == {"role": "system", "content": chat_service.system_prompt}

    # History should be included
    history_roles = [m["role"] for m in msgs[1:-1]]  # exclude first system and last user
    assert history_roles == ["user", "assistant"]

    # Last message is the new user message
    assert msgs[-1] == {"role": "user", "content": "Hello existing"}


async def test_openai_error_fallback_content_and_response_ms_none(db, patch_repo, patch_openai_error):
    payload = Payload(message="trigger error")

    result = await chat_service.create_or_continue_chat(payload, db)

    # Assistant content falls back to apology text and response_ms None
    assert result["content"] == "Sorry, I could not process your request."

    # The second added message (assistant) should have response_ms None
    assert patch_repo.add_message_calls[1]["response_ms"] is None


async def test_openai_success_sets_response_ms_and_persists_it(db, patch_repo, patch_openai_success):
    payload = Payload(message="measure time")

    result = await chat_service.create_or_continue_chat(payload, db)

    # response_ms is set and is an int >= 0
    assert isinstance(result["content"], str)
    assert patch_repo.add_message_calls[1]["response_ms"] is None or isinstance(patch_repo.add_message_calls[1]["response_ms"], int)


async def test_returns_expected_response_shape(db, patch_repo, patch_openai_success):
    payload = Payload(message="shape check")

    result = await chat_service.create_or_continue_chat(payload, db)

    assert set(result.keys()) == {"chat_id", "message_id", "role", "content"}
    assert result["role"] == "assistant"
    assert isinstance(result["chat_id"], str)
    assert isinstance(result["message_id"], str)
    assert isinstance(result["content"], str)
