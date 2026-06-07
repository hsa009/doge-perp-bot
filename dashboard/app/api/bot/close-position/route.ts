import { NextResponse } from "next/server"
import { botFetch } from "@/lib/bot-api"

export const runtime = "nodejs"
export const dynamic = "force-dynamic"

export async function POST() {
  try {
    const resp = await botFetch(`/api/v1/bot/close-position`, {
      method: "POST",
      signal: AbortSignal.timeout(30_000),
    } as RequestInit)
    const data = await resp.json()
    return NextResponse.json(data)
  } catch (e: unknown) {
    const msg = e instanceof Error ? e.message : String(e)
    return NextResponse.json({ ok: false, error: msg }, { status: 500 })
  }
}
