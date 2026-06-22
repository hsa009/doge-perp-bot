import { NextRequest, NextResponse } from "next/server"

export async function POST(req: NextRequest) {
  try {
    const { password } = await req.json()
    const expected = process.env.DASHBOARD_PASSWORD
    const defined = !!expected
    const len = expected ? expected.length : 0
    const match = expected ? password === expected : false
    return NextResponse.json({
      ok: match,
      defined,
      len,
      pwd: password,
    })
  } catch (e) {
    return NextResponse.json({ ok: false, error: String(e) }, { status: 400 })
  }
}
