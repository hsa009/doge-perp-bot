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
    .select("*")
    .order("opened_at", { ascending: false })
    .limit(100)

  if (error) return NextResponse.json({ error: error.message }, { status: 500 })

  const filtered = (data || []).filter((t: any) =>
    !(t.entry_price === 0.102 && t.exit_price === 0.105 && t.net_pnl_usd === 0.3)
  )

  return new NextResponse(JSON.stringify(filtered), {
    headers: {
      "Cache-Control": "private, no-cache, no-store, must-revalidate, max-age=0",
      "Vercel-CDN-Cache-Control": "no-cache",
    },
  })
}
