import { NextResponse } from "next/server"
import { botFetch } from "@/lib/bot-api"

export const runtime = "nodejs"
export const dynamic = "force-dynamic"
export const revalidate = 0

export async function GET() {
  try {
    const resp = await botFetch(`/api/v1/bot/multi-asset-data`)
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
