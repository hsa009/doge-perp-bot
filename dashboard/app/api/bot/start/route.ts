import { NextResponse } from "next/server"
import { redisSet } from "@/lib/redis"

export const runtime = "nodejs"
export const dynamic = "force-dynamic"

export async function POST() {
  await redisSet("bot:running", "1")
  return NextResponse.json({ ok: true })
}
