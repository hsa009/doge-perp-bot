import { NextResponse } from "next/server"

export const runtime = "nodejs"
export const dynamic = "force-dynamic"
export const revalidate = 0

const SUPABASE_URL = process.env.SUPABASE_URL || ""
const SUPABASE_KEY = process.env.SUPABASE_KEY || ""
const BOT_API = process.env.BOT_API_URL || "https://ghaith1122331-doge-bot.hf.space"

const VALID_ASSETS = ["DOGE", "SOL"]
const ALLOWED = ["tp_usd", "sl_usd", "trade_amount", "leverage", "min_confidence", "max_daily_loss", "max_daily_loss_enabled", "groq_api_key", "gemini_api_key", "active_asset"]

export async function GET() {
  try {
    const resp = await fetch(`${BOT_API}/api/v1/bot/status`, {
      signal: AbortSignal.timeout(15000),
    })
    const data = await resp.json()
    return NextResponse.json(data.config || {}, {
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
  const body = await req.json()

  const errors: string[] = []

  if (body.trade_amount !== undefined) {
    const val = parseFloat(body.trade_amount)
    if (isNaN(val) || val < 1) errors.push("trade_amount must be >= 1")
  }
  if (body.leverage !== undefined) {
    const val = parseInt(body.leverage)
    if (isNaN(val) || val < 1 || val > 50) errors.push("leverage must be 1-50")
  }
  if (body.tp_usd !== undefined) {
    const val = parseFloat(body.tp_usd)
    if (isNaN(val) || val < 0.01) errors.push("tp_usd must be >= 0.01")
  }
  if (body.sl_usd !== undefined) {
    const val = parseFloat(body.sl_usd)
    if (isNaN(val) || val < 0.01) errors.push("sl_usd must be >= 0.01")
  }
  if (body.min_confidence !== undefined) {
    const val = parseFloat(body.min_confidence)
    if (isNaN(val) || val < 0 || val > 1) errors.push("min_confidence must be 0-1")
  }
  if (body.max_daily_loss !== undefined) {
    const val = parseFloat(body.max_daily_loss)
    if (isNaN(val) || val < 0.01) errors.push("max_daily_loss must be >= 0.01")
  }
  if (body.active_asset !== undefined) {
    if (!VALID_ASSETS.includes(body.active_asset)) errors.push("active_asset must be DOGE or SOL")
  }

  if (errors.length) {
    return NextResponse.json({ ok: false, errors }, { status: 400 })
  }

  let assetResult: { ok: boolean; pending?: boolean; asset?: string; error?: string } | null = null

  // Proxy active_asset through bot's asset endpoint (position check + pending logic)
  if (body.active_asset !== undefined) {
    try {
      const resp = await fetch(`${BOT_API}/api/v1/bot/asset`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ asset: body.active_asset }),
        signal: AbortSignal.timeout(15000),
      })
      assetResult = await resp.json()
    } catch {
      assetResult = { ok: false, error: "Bot API unreachable" }
    }
  }

  // Proxy all non-asset settings through bot API (writes to Redis via bot, not dashboard)
  const nonAssetKeys = ALLOWED.filter((k) => k !== "active_asset" && body[k] !== undefined)
  if (nonAssetKeys.length > 0) {
    const settingsPayload: Record<string, string> = {}
    for (const key of nonAssetKeys) {
      settingsPayload[key] = String(body[key])
    }
    try {
      await fetch(`${BOT_API}/api/v1/bot/settings`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(settingsPayload),
        signal: AbortSignal.timeout(15000),
      })
    } catch (e) {
      console.warn("Failed to save settings via bot API:", e)
    }
  }

  // Persist to Supabase
  if (SUPABASE_URL && SUPABASE_KEY) {
    try {
      await Promise.all(
        ALLOWED.filter((k) => body[k] !== undefined && k !== "active_asset").map((key) =>
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

  return NextResponse.json(assetResult || { ok: true })
}