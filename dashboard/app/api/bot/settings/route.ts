import { NextResponse } from "next/server"
import { redisGet, redisSet } from "@/lib/redis"

export const runtime = "nodejs"
export const dynamic = "force-dynamic"
export const revalidate = 0

const SUPABASE_URL = process.env.SUPABASE_URL || ""
const SUPABASE_KEY = process.env.SUPABASE_KEY || ""

const ALLOWED = ["tp_usd", "sl_usd", "trade_amount", "leverage", "min_confidence", "max_daily_loss", "max_daily_loss_enabled", "groq_api_key"]

export async function GET() {
  const results = await Promise.all(ALLOWED.map((k) => redisGet(`config:${k}`)))
  const config: Record<string, string> = {}
  for (let i = 0; i < ALLOWED.length; i++) {
    config[ALLOWED[i]] = results[i] || ""
  }
  return new NextResponse(JSON.stringify(config), {
    headers: {
      "Cache-Control": "private, no-cache, no-store, must-revalidate, max-age=0",
      "Vercel-CDN-Cache-Control": "no-cache",
    },
  })
}

export async function POST(req: Request) {
  const body = await req.json()

  if (body.trade_amount !== undefined) {
    const val = parseFloat(body.trade_amount)
    if (isNaN(val) || val < 1) {
      return NextResponse.json({ ok: false, error: "trade_amount must be >= 1" }, { status: 400 })
    }
  }

  const ops: Promise<void>[] = []

  for (const key of ALLOWED) {
    if (body[key] !== undefined) {
      ops.push(redisSet(`config:${key}`, String(body[key])))
    }
  }

  await Promise.all(ops)

  if (SUPABASE_URL && SUPABASE_KEY) {
    try {
      await Promise.all(
        ALLOWED.filter((k) => body[k] !== undefined).map((key) =>
          fetch(`${SUPABASE_URL}/rest/v1/bot_config`, {
            method: "POST",
            headers: {
              "Content-Type": "application/json",
              apikey: SUPABASE_KEY,
              Authorization: `Bearer ${SUPABASE_KEY}`,
              Prefer: "resolution=merge-duplicates",
            },
            body: JSON.stringify({ key, value: String(body[key]) }),
          })
        )
      )
    } catch (e) {
      console.warn("Failed to persist settings to Supabase:", e)
    }
  }

  return NextResponse.json({ ok: true })
}