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
    .from("bot_log")
    .select("*")
    .order("created_at", { ascending: false })
    .limit(200)

  if (error) return NextResponse.json({ error: error.message }, { status: 500 })
  return new NextResponse(JSON.stringify(data), {
    headers: {
      "Cache-Control": "private, no-cache, no-store, must-revalidate, max-age=0",
      "Vercel-CDN-Cache-Control": "no-cache",
    },
  })
}
