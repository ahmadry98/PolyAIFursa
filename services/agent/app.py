import logging
import re

import httpx
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response
from langchain_core.messages import AIMessage, HumanMessage

from agent_runner import run_agent
from config import YOLO_SERVICE_URL
from image_utils import _init_working_image_in_s3
from s3_utils import download_bytes_from_s3
from schemas import ChatRequest, ChatResponse
from tools import (
    _current_chat_id,
    _current_image_b64,
    _current_user_text,
    _edit_step,
    _working_image_b64,
    _working_s3_key,
)

app = FastAPI(title="Vision Agent")

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",
        "http://127.0.0.1:3000",
        "http://32.197.155.17:3000",
        "http://dev.ahmad.fursa.click:3000",
        "http://67.202.49.42:3000",
        "http://prod.ahmad.fursa.click:3000",
    ],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


def _chat_id_from_processed_url(url: str | None) -> str | None:
    if not url:
        return None

    match = re.search(r"/processed/([^/]+)/image", url)
    if not match:
        return None

    return match.group(1)


@app.post("/chat", response_model=ChatResponse)
def chat(request: ChatRequest):
    lc_messages = []
    latest_image = None
    latest_user_text = ""
    latest_chat_id = None

    for msg in request.messages:
        if msg.role == "user":
            latest_user_text = msg.content
            if msg.image_base64:
                latest_image = msg.image_base64
                content = (
                    msg.content
                    + "\n[An image was uploaded. Use existing tools to analyze "
                    "it according to user instructions.]"
                )
            else:
                content = msg.content
            lc_messages.append(HumanMessage(content=content))
        else:
            latest_chat_id = (
                _chat_id_from_processed_url(msg.annotated_image_url)
                or _chat_id_from_processed_url(msg.image_url)
                or latest_chat_id
            )
            lc_messages.append(AIMessage(content=msg.content))

    working_s3_key = None
    chat_id = latest_chat_id
    if latest_image:
        image_state = _init_working_image_in_s3(latest_image)
        chat_id = image_state["chat_id"]
        working_s3_key = image_state["working_s3_key"]
    elif chat_id:
        working_s3_key = f"{chat_id}/working/current.png"

    token = _current_image_b64.set(latest_image)
    working_token = _working_image_b64.set(None)
    text_token = _current_user_text.set(latest_user_text)
    chat_token = _current_chat_id.set(chat_id)
    working_s3_token = _working_s3_key.set(working_s3_key)
    step_token = _edit_step.set(0)
    try:
        result = run_agent(lc_messages)
        return ChatResponse(**result)
    finally:
        _current_image_b64.reset(token)
        _working_image_b64.reset(working_token)
        _current_user_text.reset(text_token)
        _current_chat_id.reset(chat_token)
        _working_s3_key.reset(working_s3_token)
        _edit_step.reset(step_token)


@app.get("/prediction/{uid}/image")
def get_prediction_image(uid: str):
    """Proxy the annotated image from the internal YOLO service."""
    try:
        with httpx.Client(timeout=30.0) as client:
            response = client.get(f"{YOLO_SERVICE_URL}/prediction/{uid}/image")
    except httpx.RequestError as error:
        raise HTTPException(
            status_code=502,
            detail="The object detection service is unavailable.",
        ) from error

    if response.status_code == 404:
        raise HTTPException(status_code=404, detail="Image not found")
    if response.is_error:
        raise HTTPException(
            status_code=502,
            detail="The object detection service could not return the image.",
        )

    content_type = response.headers.get("content-type", "image/jpeg")
    return Response(content=response.content, media_type=content_type)


@app.get("/processed/{image_id}/image")
def get_processed_image(image_id: str):
    """Proxy a processed MCP image stored by the agent in S3."""
    working_key = f"{image_id}/working/current.png"
    old_processed_key = f"processed/{image_id}/image.png"
    try:
        image_bytes = download_bytes_from_s3(working_key)
    except Exception as error:
        try:
            image_bytes = download_bytes_from_s3(old_processed_key)
        except Exception as fallback_error:
            logging.exception("Failed to download processed image from S3")
            raise HTTPException(
                status_code=404,
                detail="Image not found",
            ) from fallback_error

    return Response(content=image_bytes, media_type="image/png")


@app.get("/health")
def health():
    return {"status": "ok"}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000)
