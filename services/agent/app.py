import logging

import httpx
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response
from langchain_core.messages import AIMessage, HumanMessage

from agent_runner import run_agent
from config import YOLO_SERVICE_URL
from s3_utils import download_bytes_from_s3
from schemas import ChatRequest, ChatResponse
from tools import _current_image_b64, _current_user_text, _working_image_b64

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


@app.post("/chat", response_model=ChatResponse)
def chat(request: ChatRequest):
    lc_messages = []
    latest_image = None
    latest_user_text = ""

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
            lc_messages.append(AIMessage(content=msg.content))

    token = _current_image_b64.set(latest_image)
    working_token = _working_image_b64.set(latest_image)
    text_token = _current_user_text.set(latest_user_text)
    try:
        result = run_agent(lc_messages)
        return ChatResponse(**result)
    finally:
        _current_image_b64.reset(token)
        _working_image_b64.reset(working_token)
        _current_user_text.reset(text_token)


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
    key = f"processed/{image_id}/image.png"
    try:
        image_bytes = download_bytes_from_s3(key)
    except Exception as error:
        logging.exception("Failed to download processed image from S3")
        raise HTTPException(status_code=404, detail="Image not found") from error

    return Response(content=image_bytes, media_type="image/png")


@app.get("/health")
def health():
    return {"status": "ok"}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000)
