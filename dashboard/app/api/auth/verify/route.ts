import { NextRequest, NextResponse } from "next/server"

export async function POST(req: NextRequest) {
  try {
    const { password } = await req.json()
    const expected = process.env.DASHBOARD_PASSWORD
    if (!expected || password !== expected) {
      return NextResponse.json({ ok: false }, { status: 401 })
    }
    return NextResponse.json({ ok: true })
  } catch {
    return NextResponse.json({ ok: false }, { status: 400 })
  }
}
