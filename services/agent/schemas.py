from typing import Optional

from pydantic import BaseModel


class TokenUsage(BaseModel):
    input: int = 0
    output: int = 0
    total: int = 0


class ChatMessage(BaseModel):
    role: str
    content: str
    image_base64: Optional[str] = None


class ChatRequest(BaseModel):
    messages: list[ChatMessage]


class ChatResponse(BaseModel):
    response: str
    prediction_id: Optional[str] = None
    annotated_image: Optional[str] = None
    annotated_image_url: Optional[str] = None
    agent_loop_time_s: float
    iterations: int
    tools_called: list[str]
    context_limit_exceeded: bool = False
    tokens_used: TokenUsage
