const BOT_API = "https://ghaith1122331-doge-bot.hf.space"
const HF_TOKEN = process.env.HF_TOKEN || ""

export async function botFetch(path: string, init?: RequestInit) {
  const headers: Record<string, string> = {
    "Cache-Control": "no-cache",
    ...((init?.headers as Record<string, string>) || {}),
  }
  if (HF_TOKEN) {
    headers["Authorization"] = `Bearer ${HF_TOKEN}`
  }
  return fetch(`${BOT_API}${path}`, {
    ...init,
    headers,
    cache: "no-store",
  })
}
