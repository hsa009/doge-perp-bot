import { NextResponse } from "next/server"
import { redisGet, redisSet } from "@/lib/redis"

export const runtime = "nodejs"
export const dynamic = "force-dynamic"
export const revalidate = 0

export async function GET() {
  try {
    const [defsRaw, enabledRaw, detailsRaw] = await Promise.all([
      redisGet("config:model_defs"),
      redisGet("config:enabled_models"),
      redisGet("signal:details"),
    ])

    const defs: { key: string; model_id: string; name: string }[] = defsRaw ? JSON.parse(defsRaw) : []
    const enabled: string[] = enabledRaw ? enabledRaw.split(",").filter(Boolean) : []
    const details: any[] = detailsRaw ? JSON.parse(detailsRaw) : []

    const models = defs.map((d) => {
      const last = details.find((det) => det.key === d.key) ?? null
      return {
        key: d.key,
        name: d.name,
        model_id: d.model_id,
        enabled: enabled.includes(d.key),
        last,
      }
    })

    return new NextResponse(JSON.stringify({ models }), {
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

export async function POST(req: Request) {
  try {
    const { key, enabled } = await req.json()
    const enabledRaw = await redisGet("config:enabled_models")
    let enabledList: string[] = enabledRaw ? enabledRaw.split(",").filter(Boolean) : []

    if (enabled) {
      if (!enabledList.includes(key)) enabledList.push(key)
    } else {
      enabledList = enabledList.filter((k) => k !== key)
    }

    await redisSet("config:enabled_models", enabledList.join(","))
    return NextResponse.json({ ok: true })
  } catch (e: unknown) {
    const msg = e instanceof Error ? e.message : String(e)
    return NextResponse.json({ error: msg }, { status: 500 })
  }
}
