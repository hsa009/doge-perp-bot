import { NextResponse } from "next/server"
import { botFetch } from "@/lib/bot-api"

export const runtime = "nodejs"
export const dynamic = "force-dynamic"

export async function POST() {
  try {
    const resp = await botFetch(`/api/v1/bot/start`, {
      method: "POST",
      signal: AbortSignal.timeout(15000),
    } as RequestInit)
    const data = await resp.json()
    return NextResponse.json(data)
  } catch {
    return NextResponse.json({ ok: false, error: "Bot API unreachable" }, { status: 502 })
  }
}
