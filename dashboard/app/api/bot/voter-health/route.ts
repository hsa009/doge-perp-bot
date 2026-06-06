import { NextResponse } from "next/server"

export const runtime = "nodejs"
export const dynamic = "force-dynamic"
export const revalidate = 0

const BOT_API = process.env.BOT_API_URL || "https://ghaith1122331-doge-bot.hf.space"

export async function GET() {
  try {
    const resp = await fetch(`${BOT_API}/api/v1/bot/voter-health`, {
      signal: AbortSignal.timeout(15000),
    })
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
