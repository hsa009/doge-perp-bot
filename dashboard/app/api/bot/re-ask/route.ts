import { NextResponse } from "next/server"

export const runtime = "nodejs"
export const dynamic = "force-dynamic"

const BOT_URL = process.env.BOT_URL || "https://gitr_wg25b-1a4.k.jrnm.app"

export async function POST() {
  try {
    const resp = await fetch(`${BOT_URL}/api/v1/bot/re-ask`, {
      method: "POST",
      signal: AbortSignal.timeout(120_000),
    })
    const data = await resp.json()
    return NextResponse.json(data)
  } catch (e: unknown) {
    const msg = e instanceof Error ? e.message : String(e)
    return NextResponse.json({ ok: false, error: msg }, { status: 500 })
  }
}
