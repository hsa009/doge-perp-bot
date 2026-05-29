import { NextResponse } from "next/server"

export const runtime = "nodejs"
export const dynamic = "force-dynamic"
export const revalidate = 0

const BOT_API = process.env.BOT_API_URL || "https://ghaith1122331-doge-bot.hf.space"

export async function GET() {
  try {
    const resp = await fetch(`${BOT_API}/api/v1/bot/status`, {
      next: { revalidate: 0 },
      headers: { "Cache-Control": "no-cache" },
    })
    if (!resp.ok) {
      return NextResponse.json({ error: "Bot API unreachable" }, { status: 502 })
    }
    const data = await resp.json()
    return new NextResponse(JSON.stringify(data), {
      headers: {
        "Content-Type": "application/json",
        "Cache-Control": "private, no-cache, no-store, must-revalidate, max-age=0",
        "CDN-Cache-Control": "no-cache",
        "Vercel-CDN-Cache-Control": "no-cache",
      },
    })
  } catch (e: unknown) {
    const msg = e instanceof Error ? e.message : String(e)
    return NextResponse.json({ error: msg }, { status: 502 })
  }
}
