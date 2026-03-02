import asyncio
import json
import types
from datetime import datetime, timezone

import pytest

from app.modules.chat import service as chat_service
from app.modules.chat import schemas as chat_schemas
from app.modules.chat import models as chat_models
from app.utils.system_prompt_aria import aria_veloce_website_guide
from app.utils.system_prompt_aria_veloce import aria_veloce_brand_representative
from app.utils.system_prompt_portfolio import veloce_portfolio

pytestmark = pytest.mark.asyncio


# ------------------------------------------------------------
# Dummy models and helpers
# ------------------------------------------------------------
class DummyConversation:
    def __init__(
        self,
        *,
        id: str = "conv_int_1",  # internal PK
        public_id: str = "conv_pub_1",
        tenant_id: str = "veloce",
        status: chat_models.ConversationStatus = chat_models.ConversationStatus.open,
        is_lead: bool = False,
        total_messages: int = 0,
        total_tokens_used: int = 0,
        created_at: datetime | None = None,
        last_activity_at: datetime | None = None,
        messages: list | None = None,
    ):
        self.id = id
        self.public_id = public_id
        self.tenant_id = tenant_id
        self.status = status
        self.is_lead = is_lead
        self.total_messages = total_messages
        self.total_tokens_used = total_tokens_used
        self.created_at = created_at or datetime.now(timezone.utc)
        self.last_activity_at = last_activity_at or datetime.now(timezone.utc)
        self.messages = messages or []


class DummyMessage:
    def __init__(
        self,
        *,
        id: str = "msg_int_1",
        public_id: str = "msg_pub_1",
        role: chat_models.MessageRole = chat_models.MessageRole.assistant,
        content: str = "hi",
        tokens_used: int | None = None,
        model_used: str | None = None,
        response_ms: int | None = None,
        created_at: datetime | None = None,
    ):
        self.id = id
        self.public_id = public_id
        self.role = role
        self.content = content
        self.tokens_used = tokens_used
        self.model_used = model_used
        self.response_ms = response_ms
        self.created_at = created_at or datetime.now(timezone.utc)


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


# ------------------------------------------------------------
# Fixtures
# ------------------------------------------------------------
@pytest.fixture
def db():
    return DummyDB()


@pytest.fixture
def patch_repo(monkeypatch):
    """Patch repository functions used by service layer and capture calls."""
    calls = types.SimpleNamespace(
        get_or_create=None,
        get_history_called=False,
        get_history_for=None,
        add_message_calls=[],
        update_conv=None,
        list_args=None,
        list_return=None,
        detail_return=None,
    )

    async def fake_get_or_create_conversation(db, *, conversation_public_id, tenant_id):
        if conversation_public_id:
            conv = DummyConversation(public_id=conversation_public_id, tenant_id=tenant_id)
            is_new = False
        else:
            conv = DummyConversation(public_id="conv_new", tenant_id=tenant_id)
            is_new = True
        calls.get_or_create = (conversation_public_id, tenant_id)
        return conv, is_new

    async def fake_get_conversation_history(db, *, conversation_id, limit=None):
        calls.get_history_called = True
        calls.get_history_for = conversation_id
        return [
            DummyMessage(public_id="m1", role=chat_models.MessageRole.user, content="prev user"),
            DummyMessage(public_id="m2", role=chat_models.MessageRole.assistant, content="prev asst"),
        ]

    async def fake_add_message(
        db,
        *,
        conversation_id,
        role,
        content,
        tokens_used=None,
        model_used=None,
        response_ms=None,
    ):
        msg = DummyMessage(
            public_id=f"msg_pub_{len(calls.add_message_calls)+1}",
            role=role,
            content=content,
            response_ms=response_ms,
        )
        calls.add_message_calls.append({
            "conversation_id": conversation_id,
            "role": role,
            "content": content,
            "response_ms": response_ms,
        })
        return msg

    async def fake_update_conversation_activity(conversation, *, message_increment=0, token_increment=0):
        calls.update_conv = (message_increment, token_increment)
        # mutate conversation like real repo would rely on commit to flush
        conversation.total_messages += message_increment
        conversation.total_tokens_used += token_increment
        conversation.last_activity_at = datetime.now(timezone.utc)

    async def fake_get_conversations(db, *, tenant_id, page_size, cursor=None, status=None):
        calls.list_args = dict(tenant_id=tenant_id, page_size=page_size, cursor=cursor, status=status)
        if calls.list_return is not None:
            return calls.list_return
        # default list return if not overridden
        convs = [
            DummyConversation(public_id="c1"),
            DummyConversation(public_id="c2"),
        ]
        return convs, "nextc", 10

    async def fake_get_conversation_detail(db, *, public_id, tenant_id):
        return calls.detail_return

    monkeypatch.setattr(chat_service, "repo", types.SimpleNamespace(
        get_or_create_conversation=fake_get_or_create_conversation,
        get_conversation_history=fake_get_conversation_history,
        add_message=fake_add_message,
        update_conversation_activity=fake_update_conversation_activity,
        get_conversations=fake_get_conversations,
        get_conversation_detail=fake_get_conversation_detail,
    ))

    return calls


@pytest.fixture
def patch_openai_capture(monkeypatch):
    captured = {}

    async def capturing_openai(messages, system_prompt):
        captured["messages"] = messages
        captured["system_prompt"] = system_prompt
        return "OK"

    monkeypatch.setattr(chat_service, "openai_service", types.SimpleNamespace(call_openai=capturing_openai))
    return captured


@pytest.fixture
def patch_openai_error(monkeypatch):
    async def failing_openai(messages, system_prompt):
        raise RuntimeError("boom")

    monkeypatch.setattr(chat_service, "openai_service", types.SimpleNamespace(call_openai=failing_openai))


# ------------------------------------------------------------
# Behaviors (for documentation per instructions)
# ------------------------------------------------------------
# 1) Uses the website system prompt when chatbot_identity=website and does NOT append the portfolio.
# 2) Uses the demo system prompt by default and appends the JSON portfolio blob.
# 3) Includes prior conversation history only when continuing an existing conversation.
# 4) Persists user and assistant messages, updates counters by +2, and commits the DB transaction.
# 5) On LLM error, falls back to a friendly apology and stores response_ms=None.
# 6) Returns ChatReplyResponse with enum role=assistant and valid IDs.
# 7) Lists conversations: maps repository rows to summary schema with correct pagination metadata.
# 8) Conversation detail: raises on missing conversation and maps messages when present.


# ------------------------------------------------------------
# Tests for create_or_continue_chat
# ------------------------------------------------------------
async def test_website_identity_uses_website_prompt_only(db, patch_repo, patch_openai_capture):
    payload = chat_schemas.ChatCreateRequest(
        conversation_id=None,
        message="Hello site",
        chatbot_identity=chat_schemas.ChatbotIdentityEnum.website,
        tenant_id="t1",
    )

    await chat_service.create_or_continue_chat(db, payload=payload)

    # Assert the system prompt equals the website guide JSON (no portfolio appended)
    sp = patch_openai_capture["system_prompt"]
    assert json.loads(sp) == aria_veloce_website_guide

    # Messages should contain only the new user message for a new conversation
    msgs = patch_openai_capture["messages"]
    assert msgs == [{"role": "user", "content": "Hello site"}]


async def test_demo_identity_includes_portfolio_blob(db, patch_repo, patch_openai_capture):
    payload = chat_schemas.ChatCreateRequest(
        conversation_id=None,
        message="Hello demo",
        # default chatbot_identity is veloce_demo
        tenant_id="t1",
    )

    await chat_service.create_or_continue_chat(db, payload=payload)

    sp = patch_openai_capture["system_prompt"]
    # The demo path uses brand representative prompt and appends portfolio JSON
    assert "Company portfolio:" in sp
    assert json.dumps(veloce_portfolio) in sp


async def test_includes_history_only_for_existing_conversation(db, patch_repo, patch_openai_capture):
    payload = chat_schemas.ChatCreateRequest(
        conversation_id="conv_existing",
        message="Hello again",
        tenant_id="t1",
    )

    await chat_service.create_or_continue_chat(db, payload=payload)

    msgs = patch_openai_capture["messages"]
    # History (2 messages) + new user
    assert msgs[0] == {"role": chat_models.MessageRole.user.value, "content": "prev user"}
    assert msgs[1] == {"role": chat_models.MessageRole.assistant.value, "content": "prev asst"}
    assert msgs[-1] == {"role": "user", "content": "Hello again"}
    assert patch_repo.get_history_called is True


async def test_persists_messages_updates_counters_and_commits(db, patch_repo, patch_openai_capture):
    payload = chat_schemas.ChatCreateRequest(
        conversation_id=None,
        message="persist",
        tenant_id="t1",
    )

    result = await chat_service.create_or_continue_chat(db, payload=payload)

    # Two messages added: user then assistant
    assert len(patch_repo.add_message_calls) == 2
    assert patch_repo.add_message_calls[0]["role"] == chat_models.MessageRole.user
    assert patch_repo.add_message_calls[1]["role"] == chat_models.MessageRole.assistant

    # Conversation counters updated with +2 messages
    assert patch_repo.update_conv == (2, 0) or patch_repo.update_conv == (2, 0) or patch_repo.update_conv == (2, 0)
    # Accept any ordering of args as we pass by name; ensure message_increment == 2
    assert patch_repo.update_conv[0] == 2

    # DB committed
    assert db.committed is True

    # Response shape and types
    assert isinstance(result.conversation_id, str)
    assert isinstance(result.message_id, str)
    assert result.role == chat_models.MessageRole.assistant
    assert isinstance(result.content, str)


async def test_openai_error_fallback_and_response_ms_none(db, patch_repo, patch_openai_error):
    payload = chat_schemas.ChatCreateRequest(
        conversation_id=None,
        message="trigger error",
        tenant_id="t1",
    )

    result = await chat_service.create_or_continue_chat(db, payload=payload)

    # Assistant content falls back to apology text and response_ms None on stored assistant message
    assert result.content == "Sorry, I could not process your request right now."
    assert patch_repo.add_message_calls[1]["response_ms"] is None


# ------------------------------------------------------------
# Tests for list_conversations
# ------------------------------------------------------------
async def test_list_conversations_maps_and_pagination(db, patch_repo):
    # Arrange fake list return
    convs = [
        DummyConversation(public_id="convA", total_messages=3, total_tokens_used=30),
        DummyConversation(public_id="convB", total_messages=1, total_tokens_used=10),
    ]
    patch_repo.list_return = (convs, "cursor123", 42)

    payload = chat_schemas.ConversationListRequest(page_size=2)

    resp = await chat_service.list_conversations(db, payload=payload, tenant_id="tenantX")

    assert len(resp.items) == 2
    assert resp.items[0].id == "convA"
    assert resp.items[1].id == "convB"

    assert resp.meta.total == 42
    assert resp.meta.page_size == 2
    assert resp.meta.next_cursor == "cursor123"
    assert resp.meta.has_next is True


# ------------------------------------------------------------
# Tests for get_conversation_detail
# ------------------------------------------------------------
async def test_get_conversation_detail_raises_when_missing(db, patch_repo):
    patch_repo.detail_return = None

    with pytest.raises(ValueError):
        await chat_service.get_conversation_detail(
            db,
            conversation_public_id="nope",
            tenant_id="tenant1",
        )


async def test_get_conversation_detail_maps_messages(db, patch_repo):
    conv = DummyConversation(
        public_id="convZ",
        messages=[
            DummyMessage(public_id="m1", role=chat_models.MessageRole.user, content="u1"),
            DummyMessage(public_id="m2", role=chat_models.MessageRole.assistant, content="a1", response_ms=123),
        ],
    )
    patch_repo.detail_return = conv

    resp = await chat_service.get_conversation_detail(
        db,
        conversation_public_id="convZ",
        tenant_id="tenant1",
    )

    assert resp.id == "convZ"
    assert len(resp.messages) == 2
    assert resp.messages[0].id == "m1"
    assert resp.messages[0].role == chat_models.MessageRole.user
    assert resp.messages[0].content == "u1"
    assert resp.messages[1].response_ms == 123
