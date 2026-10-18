"""Testar AI-loopen med en låtsasklient som beter sig som SDK:ns stream()."""

from types import SimpleNamespace

from app.advisor import Advisor


class FakeStream:
    def __init__(self, message):
        self.message = message

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    def __aiter__(self):
        async def gen():
            for block in self.message.content:
                if block.type == "text":
                    yield SimpleNamespace(type="text", text=block.text)

        return gen()

    async def get_final_message(self):
        return self.message


class FakeMessages:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def stream(self, **kwargs):
        self.calls.append({**kwargs, "messages": list(kwargs["messages"])})
        return FakeStream(self.responses.pop(0))


def _msg(stop_reason, *blocks):
    return SimpleNamespace(stop_reason=stop_reason, content=list(blocks))


def _text(t):
    return SimpleNamespace(type="text", text=t)


def _tool(id_, name, input_):
    return SimpleNamespace(type="tool_use", id=id_, name=name, input=input_)


def _advisor(model, state, responses):
    advisor = Advisor.__new__(Advisor)
    advisor.model_id = "claude-opus-5-5"
    advisor.effort = "medium"
    advisor.context = lambda: (model, state)
    advisor.conversations = __import__("collections").OrderedDict()
    fake = FakeMessages(responses)
    advisor.client = SimpleNamespace(beta=SimpleNamespace(messages=fake))
    return advisor, fake


async def _collect(gen):
    return [e async for e in gen]


async def test_tool_round_trip(model, state):
    advisor, fake = _advisor(
        model,
        state,
        [
            _msg("tool_use", _text("Kollar ditt lag."), _tool("t1", "get_my_team", {})),
            _msg("end_turn", _text("Ditt lag ser bra ut.")),
        ],
    )
    events = await _collect(advisor.chat(None, "Hur ser mitt lag ut?"))
    types = [e["type"] for e in events]
    assert types[0] == "conversation"
    assert "tool" in types and types[-1] == "done"
    assert "".join(e["text"] for e in events if e["type"] == "text") == "Kollar ditt lag.Ditt lag ser bra ut."

    second_call = fake.calls[1]
    assert second_call["fallbacks"] == "default"
    assert second_call["thinking"] == {"type": "adaptive"}
    tool_result = second_call["messages"][-1]["content"][0]
    assert tool_result["type"] == "tool_result" and tool_result["tool_use_id"] == "t1"
    assert "is_error" not in tool_result

    # Historiken är append-only och avslutas med assistentens svar
    cid = events[0]["id"]
    history = advisor.conversations[cid]
    assert [m["role"] for m in history] == ["user", "assistant", "user", "assistant"]


async def test_tool_error_is_reported_to_model(model, state):
    advisor, fake = _advisor(
        model,
        state,
        [
            _msg("tool_use", _tool("t1", "get_player", {"player": "Finns Inte"})),
            _msg("end_turn", _text("Hittade inte spelaren.")),
        ],
    )
    await _collect(advisor.chat(None, "Hur bra är Finns Inte?"))
    result = fake.calls[1]["messages"][-1]["content"][0]
    assert result["is_error"] is True


async def test_truncated_tool_call_is_closed(model, state):
    advisor, fake = _advisor(model, state, [_msg("max_tokens", _tool("t1", "get_my_team", {}))])
    events = await _collect(advisor.chat(None, "Hej"))
    assert any(e["type"] == "error" for e in events)
    history = next(iter(advisor.conversations.values()))
    # Sista meddelandet besvarar tool_use så att nästa fråga inte avvisas
    assert history[-1]["role"] == "user"
    assert history[-1]["content"][0]["tool_use_id"] == "t1"


async def test_conversation_continues(model, state):
    advisor, fake = _advisor(model, state, [_msg("end_turn", _text("Svar 1")), _msg("end_turn", _text("Svar 2"))])
    first = await _collect(advisor.chat(None, "Fråga 1"))
    cid = first[0]["id"]
    second = await _collect(advisor.chat(cid, "Fråga 2"))
    assert second[0]["id"] == cid
    assert len(fake.calls[1]["messages"]) == 3
