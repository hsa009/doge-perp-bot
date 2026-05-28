export async function redisGet(key: string): Promise<string | null> {
  const url = process.env.UPSTASH_REDIS_URL || ""
  const token = process.env.UPSTASH_REDIS_TOKEN || ""
  const resp = await fetch(url, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      Authorization: `Bearer ${token}`,
    },
    body: JSON.stringify(["GET", key]),
  })
  const data = await resp.json()
  return data.result ?? null
}

export async function redisSet(key: string, value: string): Promise<void> {
  const url = process.env.UPSTASH_REDIS_URL || ""
  const token = process.env.UPSTASH_REDIS_TOKEN || ""
  await fetch(url, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      Authorization: `Bearer ${token}`,
    },
    body: JSON.stringify(["SET", key, value]),
  })
}
