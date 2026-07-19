import { NextResponse } from "next/server";

const AGENT_URL = process.env.AGENT_SERVICE_URL ?? "http://agent-svc:8000";

function proxyImageUrl(url: string | null | undefined): string | null {
  if (!url) return null;

  const agentUrl = new URL(url, AGENT_URL);
  return `/api/agent-image${agentUrl.pathname}${agentUrl.search}`;
}

export async function POST(request: Request) {
  const body = await request.text();

  const response = await fetch(`${AGENT_URL}/chat`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body,
  });

  const text = await response.text();
  if (!response.ok) {
    return new NextResponse(text, {
      status: response.status,
      headers: { "Content-Type": "text/plain" },
    });
  }

  const data = JSON.parse(text);
  data.annotated_image_url = proxyImageUrl(data.annotated_image_url);

  return NextResponse.json(data);
}
