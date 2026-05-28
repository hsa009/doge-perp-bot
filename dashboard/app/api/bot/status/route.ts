import { NextResponse } from "next/server"
import { redisGet } from "@/lib/redis"

export const runtime = "nodejs"
export const dynamic = "force-dynamic"
export const revalidate = 0

const HL_INFO = "https://api.hyperliquid.xyz/info"

async function getMarkPrice(): Promise<number | null> {
  try {
    const resp = await fetch(HL_INFO, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ type: "allMids" }),
    })
    if (!resp.ok) return null
    const data: any = await resp.json()
    const mid = data?.mids?.DOGE || data?.DOGE || null
    return mid ? parseFloat(mid) : null
  } catch {
    return null
  }
}

export async function GET() {
  try {
    const [runningRaw, signalRaw, positionRaw,
      tpUsd, slUsd, tradeAmt, lev, minConf, maxLoss, maxLossEn, groqKey] = await Promise.all([
      redisGet("bot:running"),
      redisGet("signal:current"),
      redisGet("position:current"),
      redisGet("config:tp_usd"),
      redisGet("config:sl_usd"),
      redisGet("config:trade_amount"),
      redisGet("config:leverage"),
      redisGet("config:min_confidence"),
      redisGet("config:max_daily_loss"),
      redisGet("config:max_daily_loss_enabled"),
      redisGet("config:groq_api_key"),
    ])

    const position = positionRaw ? JSON.parse(positionRaw) : null
    const markPrice = await getMarkPrice()
    if (position && markPrice != null) {
      position.mark_price = markPrice
    }

    const body = {
      running: runningRaw === "1",
      last_signal: signalRaw ? JSON.parse(signalRaw) : null,
      position,
      mark_price: markPrice,
      config: {
        tp_usd: tpUsd || "3.0",
        sl_usd: slUsd || "3.0",
        trade_amount: tradeAmt || "10.0",
        leverage: lev || "10",
        min_confidence: minConf || "0.65",
        max_daily_loss: maxLoss || "2.0",
        max_daily_loss_enabled: maxLossEn || "1",
        groq_api_key: groqKey || "",
        ai_loop_interval: "600",
      },
    }
    return new NextResponse(JSON.stringify(body), {
      headers: {
        "Content-Type": "application/json",
        "Cache-Control": "private, no-cache, no-store, must-revalidate, max-age=0",
        "CDN-Cache-Control": "no-cache",
        "Vercel-CDN-Cache-Control": "no-cache",
      },
    })
  } catch (e: unknown) {
    const msg = e instanceof Error ? e.message : String(e)
    return NextResponse.json({ error: msg }, { status: 500 })
  }
}
