# Vision Agent

A LangChain-powered AI vision agent with a manual ReAct loop. Accepts text and base64-encoded images, and can call tools (e.g. YOLO object detection) to answer questions.

## Prerequisites

- Python 3.10+
- A running YOLO service (optional - only needed for `detect_objects`)


## Setup

Install dependencies (from `services/agent/`):

```bash
pip install -r requirements.txt
```

Configure environment:

```bash
cp .env.example .env
# Edit .env and set the shared AWS/S3 configuration and MODEL
```

`.env` variables:

| Variable | Default | Description |
|---|---|---|
| `MODEL` | - | One of the text-only Bedrock models allowed in `app.py` |
| `AWS_REGION` | `us-east-1` | AWS region for Bedrock and S3 |
| `AWS_S3_BUCKET` | `test-bucket` | Bucket shared by the agent and YOLO services |
| `YOLO_SERVICE_URL` | `http://localhost:8080` | URL of the YOLO microservice |

## Running

```bash
cd services/agent
python app.py
```

The server starts at `http://localhost:8000`.

## Testing with curl

### Health check

```bash
curl http://localhost:8000/health
```

Expected response:
```json
{"status": "ok"}
```

### Plain text message

```bash
curl -X POST http://localhost:8000/chat \
  -H "Content-Type: application/json" \
  -d '{"messages": [{"role": "user", "content": "Hello! What can you do?"}]}'
```

### Send a message with an image

```bash
echo "{\"messages\": [{\"role\": \"user\", \"content\": \"What objects are in this image?\", \"image_base64\": \"$(base64 < beatles.jpeg | tr -d '\\n')\"}]}" \
  | curl -X POST http://localhost:8000/chat \
         -H "Content-Type: application/json" \
         -d @-
```

## API Reference

### `POST /chat`

Request body:

```json
{
  "messages": [
    {
      "role": "user or assistant",
      "content": "message text",
      "image_base64": "optional raw base64 JPEG or PNG, user messages only"
    }
  ]
}
```

Response:

```json
{
  "response": "string"
}
```

### `GET /health`

Returns `{"status": "ok"}` when the service is running.
