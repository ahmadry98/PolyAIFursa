# 🤖 PolyAI

### AI-Powered Computer Vision & Image Processing Platform

PolyAI is a cloud-based computer vision system that combines **YOLO object detection, AI agents, image-processing tools, and AWS infrastructure** into a multi-service application.

Users can upload an image, detect objects using YOLO, interact with an AI agent, and apply image-processing operations through a tool-based architecture.

---

## 🚀 Overview

PolyAI was built to explore how computer vision, LLM-powered agents, and independent backend services can work together in a production-oriented architecture.

The system combines:

- YOLO object detection
- AI-agent orchestration
- Image-processing tools
- Persistent cloud image storage
- REST APIs
- Containerized microservices
- AWS infrastructure
- Kubernetes deployment
- CI/CD
- Monitoring and observability

---

## ✨ Key Features

### 👁️ Object Detection

Images are processed using **YOLOv8**, returning detected objects, labels, confidence scores, and annotated results.

### 🤖 AI Agent

An AI agent interprets user requests and coordinates the appropriate services and tools.

The agent can combine object-detection results with image-processing operations instead of exposing individual backend services directly to the user.

### 🛠️ Tool-Based Image Processing

Image operations are exposed through an MCP-based tool layer.

Supported operations include functionality such as:

- Rotate
- Flip
- Blur
- Resize
- Crop
- Add noise

### ☁️ Persistent Image Workflow

Images and intermediate processing results can be persisted in **Amazon S3**, allowing multiple operations to build on the current working image.

### 🔌 REST APIs

Independent FastAPI services expose functionality through HTTP APIs, keeping computer vision, agent logic, and image processing separated.

### 🐳 Containerized Architecture

Services are containerized using Docker and can be deployed as independent components.

---

## 🔄 How It Works

```text
User uploads an image
        │
        ▼
Image stored in S3
        │
        ▼
AI Agent receives user request
        │
        ├───────────────┐
        ▼               ▼
 YOLO Service      Image Tools
        │               │
        ▼               ▼
Object Detection   Image Processing
        │               │
        └───────┬───────┘
                │
                ▼
        Updated image in S3
                │
                ▼
         Result returned
```

---

## 🏗️ Architecture

PolyAI uses a service-oriented architecture in which AI reasoning, computer vision, image processing, and the user interface remain separate components.

```text
┌──────────────────────────────┐
│          Frontend            │
│           Next.js            │
└──────────────┬───────────────┘
               │
               │ REST
               ▼
┌──────────────────────────────┐
│           AI Agent           │
│          FastAPI             │
│                              │
│   Reasoning + Tool Calling   │
└───────┬──────────────┬───────┘
        │              │
        ▼              ▼
┌──────────────┐  ┌──────────────┐
│ YOLO Service │  │ Image-Proc   │
│   FastAPI    │  │ MCP Tools    │
│              │  │              │
│   YOLOv8     │  │ Edit Image   │
└──────┬───────┘  └──────┬───────┘
       │                  │
       └────────┬─────────┘
                │
                ▼
          Amazon S3
```

---

## 🛠️ Tech Stack

| Area | Technologies |
|---|---|
| **Backend** | Python, FastAPI |
| **Computer Vision** | YOLOv8 |
| **AI / Agents** | AWS Bedrock, ReAct-style agent |
| **Tool Integration** | MCP |
| **Frontend** | Next.js, TypeScript |
| **Storage** | Amazon S3 |
| **Database** | SQLAlchemy |
| **Containers** | Docker, Docker Compose |
| **Orchestration** | Kubernetes |
| **Infrastructure** | AWS |
| **CI/CD** | GitHub Actions |
| **Monitoring** | Prometheus, Grafana |

---

## 👁️ YOLO Detection Service

The YOLO service is responsible for computer-vision inference.

It accepts images and returns structured detection information including:

- Detected labels
- Detection count
- Confidence scores
- Processing time
- Annotated image output

Detection results can also be persisted and queried through the application's data layer.

---

## 🤖 Agent Workflow

The AI agent acts as the orchestration layer between the user and the underlying services.

Instead of requiring the user to manually select a service, the agent determines which tools are needed based on the request.

```text
User Request
     │
     ▼
 AI Agent
     │
     ├── Detect objects ──────► YOLO
     │
     ├── Rotate image ────────► MCP Tool
     │
     ├── Blur region ─────────► MCP Tool
     │
     ├── Resize image ────────► MCP Tool
     │
     └── Other operations ────► MCP Tool
```

This allows multiple capabilities to be exposed through a single conversational interface.

---

## 🛠️ Image Processing Tools

Image-processing functionality is separated from the AI agent through an MCP tool service.

This design allows the agent to invoke deterministic image operations while keeping the implementation independent from the reasoning layer.

Examples include:

```text
rotate
flip
blur
resize
crop
add_noise
```

---

## ☁️ S3 Image Persistence

Amazon S3 is used to persist original and processed images.

A typical multi-step workflow can look like:

```text
Original Image
      │
      ▼
     S3
      │
      ▼
YOLO Detection
      │
      ▼
Annotated Image
      │
      ▼
     S3
      │
      ▼
Image Processing Tool
      │
      ▼
Updated Image
      │
      ▼
     S3
```

Persisting the working image allows subsequent tool calls to operate on the latest version instead of restarting from the original image.

---

## 🗄️ Data Layer

The project includes a SQLAlchemy-based persistence layer for structured detection information.

The data model separates prediction sessions from individual detected objects, making detection results easier to store and query.

---

## 🐳 Docker

Services are containerized independently and coordinated using Docker Compose.

For local development:

```bash
docker compose -f compose.yaml -f compose.local.yaml build
docker compose -f compose.yaml -f compose.local.yaml up
```

For deployed environments using prebuilt images:

```bash
docker compose pull
docker compose up -d --remove-orphans
```

---

## ☸️ Kubernetes

The services can also be deployed through Kubernetes.

This allows the individual components of PolyAI to run and scale independently while maintaining separation between:

- Frontend
- Agent
- YOLO inference
- Image-processing services

---

## 🔁 CI/CD

GitHub Actions is used to automate build and deployment workflows.

Containerized services can be built and deployed to cloud environments without manually rebuilding the application directly on the server.

---

## 📊 Monitoring

PolyAI includes monitoring infrastructure using:

- **Prometheus** for metrics collection
- **Grafana** for visualization

This provides visibility into service behavior and application health across the distributed architecture.

---

## 🧪 Testing

The project includes automated tests across the backend services.

Testing covers areas such as:

- YOLO prediction behavior
- API endpoints
- S3 workflows
- Agent behavior
- Structured outputs
- Persistence
- Image-processing integrations

---

## 📂 Project Structure

```text
PolyAIFursa/
│
├── yolo/               # YOLO object-detection service
├── agent/              # AI agent and orchestration
├── frontend/           # Next.js frontend
├── img-proc-mcp/       # Image-processing MCP tools
├── monitoring/         # Prometheus / Grafana
├── infra/              # Infrastructure / deployment
│
├── compose.yaml
├── compose.local.yaml
└── README.md
```

---

## 🚀 Local Development

### Requirements

- Python 3
- Docker
- Node.js
- AWS credentials when using AWS-backed functionality

### Clone

```bash
git clone https://github.com/ahmadry98/PolyAIFursa.git
cd PolyAIFursa
```

### Python Environment

```bash
python3 -m venv .venv
source .venv/bin/activate
```

Each service contains its own dependencies and configuration.

---

## 🗺️ Project Status

PolyAI is a university software project focused on combining **computer vision, AI agents, cloud infrastructure, and distributed backend services**.

---

## 👨‍💻 Author

**Ahmad Rayan**

Computer Science graduate from Tel Aviv University.

Interested in software engineering, backend systems, cloud infrastructure, and AI-powered applications.
