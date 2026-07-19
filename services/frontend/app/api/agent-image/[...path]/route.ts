import { NextResponse } from "next/server";

const AGENT_URL = process.env.AGENT_SERVICE_URL ?? "http://agent-svc:8000";

interface RouteContext {
  params: Promise<{
    path: string[];
  }>;
}

export async function GET(request: Request, context: RouteContext) {
  const { path } = await context.params;
  const requestUrl = new URL(request.url);
  const agentUrl = new URL(`/${path.join("/")}${requestUrl.search}`, AGENT_URL);

  const response = await fetch(agentUrl);
  if (!response.ok) {
    return new NextResponse(await response.text(), { status: response.status });
  }

  return new NextResponse(response.body, {
    status: response.status,
    headers: {
      "Content-Type": response.headers.get("content-type") ?? "application/octet-stream",
      "Cache-Control": "no-store",
    },
  });
}
