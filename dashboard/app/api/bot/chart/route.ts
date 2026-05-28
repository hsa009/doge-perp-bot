import { NextRequest, NextResponse } from "next/server"

export const runtime = "nodejs"
export const dynamic = "force-dynamic"
export const revalidate = 0

const HL_API = "https://api.hyperliquid.xyz/info"

export async function GET(req: NextRequest) {
  try {
    const interval = req.nextUrl.searchParams.get("interval") || "1m"
    const limit = Math.min(parseInt(req.nextUrl.searchParams.get("limit") || "200"), 500)

    const now = Date.now()
    const msMap: Record<string, number> = { "1m": 60_000, "5m": 300_000, "15m": 900_000 }
    const barMs = msMap[interval] || 60_000

    const resp = await fetch(HL_API, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        type: "candleSnapshot",
        req: { coin: "DOGE", interval, startTime: now - limit * barMs, endTime: now },
      }),
    })

    if (!resp.ok) {
      return NextResponse.json({ error: "Hyperliquid API error" }, { status: 502 })
    }

    const candles: any[] = await resp.json()

    return NextResponse.json({
      candles: candles.map((c: any) => ({
        time: Math.floor(c.t / 1000),
        open: parseFloat(c.o),
        high: parseFloat(c.h),
        low: parseFloat(c.l),
        close: parseFloat(c.c),
        volume: parseFloat(c.v),
      })),
    })
  } catch (e: unknown) {
    const msg = e instanceof Error ? e.message : String(e)
    return NextResponse.json({ error: msg }, { status: 500 })
  }
}
