import { NextResponse } from "next/server"

export const runtime = "nodejs"
export const dynamic = "force-dynamic"

const BOT_API = process.env.BOT_API_URL || "https://ghaith1122331-doge-bot.hf.space"

export async function POST() {
  try {
    const resp = await fetch(`${BOT_API}/api/v1/bot/stop`, {
      method: "POST",
      signal: AbortSignal.timeout(15000),
    })
    const data = await resp.json()
    return NextResponse.json(data)
  } catch {
    return NextResponse.json({ ok: false, error: "Bot API unreachable" }, { status: 502 })
  }
}
