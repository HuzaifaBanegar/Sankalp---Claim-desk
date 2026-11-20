"""The API answers without a model when we swap in a fake. No key, no cost."""
from fastapi.testclient import TestClient
from langchain_core.messages import AIMessage

import agent.graph as g
from app import app


class FakeLLM:
    """Asks for one tool call, then answers. Enough to test the wiring."""

    def __init__(self):
        self.calls = 0

    def bind_tools(self, tools):
        return self

    def invoke(self, messages):
        self.calls += 1
        if self.calls == 1:
            return AIMessage(content="", tool_calls=[{"name": "lookup_batch", "args": {"batch_no": "K2300101"}, "id": "t1"}])
        return AIMessage(content="Batch K2300101 expires on 30-09-2025.")


def test_ask_runs_the_tool_loop(monkeypatch):
    fake = FakeLLM()
    monkeypatch.setattr(g, "get_llm", lambda: fake)
    r = TestClient(app).post("/api/ask", json={"question": "When does K2300101 expire?"})
    assert r.status_code == 200
    body = r.json()
    assert "30-09-2025" in body["evidence"][0]
    assert body["model_calls"] == 2
    assert [event["event"] for event in body["debug_trace"]] == [
        "intake_checked", "intake_routed", "model_responded", "model_routed",
        "tool_completed", "model_responded", "model_routed",
    ]


def test_health():
    assert TestClient(app).get("/api/health").json()["ok"] is True


def test_intent_exposes_only_valid_tools():
    assert [tool.name for tool in g.available_tools({"intake": {"intent": "claim_status"}})] == ["search_claims"]
    assert [tool.name for tool in g.available_tools({"intake": {"intent": "claim_triage"}})] == ["lookup_batch"]


def test_incomplete_claim_is_stopped_before_model_call():
    r = TestClient(app).post("/api/ask", json={"question": "Please process an expiry claim for STK0143."})
    assert r.status_code == 200
    body = r.json()
    assert "batch number" in body["answer"]
    assert body["model_calls"] == 0
    assert [event["event"] for event in body["debug_trace"]] == [
        "intake_checked", "request_blocked", "intake_routed",
    ]
