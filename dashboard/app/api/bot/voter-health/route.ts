import { NextResponse } from "next/server"
import { botFetch } from "@/lib/bot-api"

export const runtime = "nodejs"
export const dynamic = "force-dynamic"
export const revalidate = 0

export async function GET() {
  try {
    const resp = await botFetch(`/api/v1/bot/voter-health`, {
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
