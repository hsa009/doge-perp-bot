import { NextResponse } from "next/server"
import { botFetch } from "@/lib/bot-api"

export const runtime = "nodejs"
export const dynamic = "force-dynamic"
export const revalidate = 0

export async function GET() {
  try {
    const resp = await botFetch(`/api/v1/bot/models`, {
      signal: AbortSignal.timeout(15000),
    } as RequestInit)
    const data = await resp.json()
    return NextResponse.json(data, {
      headers: {
        "Cache-Control": "private, no-cache, no-store, must-revalidate, max-age=0",
        "Vercel-CDN-Cache-Control": "no-cache",
      },
    })
  } catch {
    return NextResponse.json({ error: "Bot API unreachable" }, { status: 502 })
  }
}

export async function POST(req: Request) {
  try {
    const body = await req.json()
    const resp = await botFetch(`/api/v1/bot/models`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
      signal: AbortSignal.timeout(15000),
    } as RequestInit)
    const data = await resp.json()
    return NextResponse.json(data)
  } catch {
    return NextResponse.json({ ok: false, error: "Bot API unreachable" }, { status: 502 })
  }
}
