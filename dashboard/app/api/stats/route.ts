import { NextResponse } from "next/server"
import { createClient } from "@supabase/supabase-js"

export const runtime = "nodejs"
export const dynamic = "force-dynamic"

export async function GET() {
  const supabase = createClient(
    process.env.SUPABASE_URL || "",
    process.env.SUPABASE_KEY || ""
  )
  const { data, error } = await supabase
    .from("trades")
    .select("net_pnl_usd, entry_price, exit_price, status, closed_at")
    .eq("status", "closed")
    .order("closed_at", { ascending: false })

  if (error) return NextResponse.json({ error: error.message }, { status: 500 })

  const real = (data || []).filter((t: any) =>
    !(t.entry_price === 0.102 && t.exit_price === 0.105 && parseFloat(t.net_pnl_usd) === 0.3)
  )

  const total = real.length
  let totalPnl = 0
  let wins = 0
  for (const row of real) {
    const pnl = parseFloat(row.net_pnl_usd) || 0
    totalPnl += pnl
    if (pnl > 0) wins++
  }

  return new NextResponse(JSON.stringify({
    total_pnl: totalPnl,
    win_rate: total > 0 ? wins / total : 0,
    total_trades: total,
  }), {
    headers: {
      "Cache-Control": "private, no-cache, no-store, must-revalidate, max-age=0",
      "Vercel-CDN-Cache-Control": "no-cache",
    },
  })
}
