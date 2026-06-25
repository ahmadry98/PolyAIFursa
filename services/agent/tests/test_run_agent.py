import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import app
from langchain_core.messages import AIMessage, HumanMessage


class FakeLLMWithTools:
    def __init__(self):
        self.calls = 0

    def invoke(self, messages):
        self.calls += 1

        if self.calls == 1:
            return AIMessage(
                content="",
                tool_calls=[
                    {
                        "name": "detect_objects",
                        "args": {},
                        "id": "call_1",
                    }
                ],
            )

        return AIMessage(
            content="I found 2 people in the image.",
            response_metadata={},
            usage_metadata={
                "input_tokens": 20,
                "output_tokens": 8,
                "total_tokens": 28,
            },
        )


class FakeTool:
    def invoke(self, tool_call):
        return type(
            "FakeToolMessage",
            (),
            {
                "content": (
                    '{"uid":"prediction-123",'
                    '"predicted_image":null,'
                    '"detection_count":2,'
                    '"labels":["person","person"]}'
                )
            },
        )()


def test_run_agent_calls_tool_and_returns_final_answer(monkeypatch):
    fake_llm = FakeLLMWithTools()

    monkeypatch.setattr(app, "llm_with_tools", fake_llm)
    monkeypatch.setattr(app, "TOOLS", {"detect_objects": FakeTool()})
    monkeypatch.setattr(app, "YOLO_SERVICE_URL", "http://localhost:8080")

    result = app.run_agent(
        [HumanMessage(content="What objects are in this image?")]
    )

    assert result["response"] == "I found 2 people in the image."
    assert result["prediction_id"] == "prediction-123"
    assert result["annotated_image_url"] == (
        "http://localhost:8080/prediction/prediction-123/image"
    )
    assert result["iterations"] == 2
    assert result["tools_called"] == ["detect_objects"]
    assert result["tokens_used"].total == 28
    assert result["context_limit_exceeded"] is False


def test_run_agent_stops_at_max_iterations(monkeypatch):
    class AlwaysToolCallingLLM:
        def invoke(self, messages):
            return AIMessage(
                content="",
                tool_calls=[
                    {
                        "name": "detect_objects",
                        "args": {},
                        "id": "call_loop",
                    }
                ],
            )

    monkeypatch.setattr(app, "llm_with_tools", AlwaysToolCallingLLM())
    monkeypatch.setattr(app, "TOOLS", {"detect_objects": FakeTool()})

    result = app.run_agent(
        [HumanMessage(content="Keep detecting objects")],
        max_iterations=1,
    )

    assert result["context_limit_exceeded"] is True
    assert result["iterations"] == 1
    assert result["tools_called"] == ["detect_objects"]
