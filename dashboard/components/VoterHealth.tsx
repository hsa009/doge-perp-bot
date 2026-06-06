"use client"

import { useEffect, useState } from "react"

interface VoterStat {
  voter: string
  voter_type: string
  total_calls: number
  successful: number
  failed: number
  last_error: string | null
  last_success: string | null
  last_direction: string | null
}

export default function VoterHealth() {
  const [voters, setVoters] = useState<VoterStat[]>([])

  useEffect(() => {
    fetch("/api/bot/voter-health")
      .then((r) => r.json())
      .then(setVoters)
      .catch(() => {})
    const id = setInterval(() => {
      fetch("/api/bot/voter-health")
        .then((r) => r.json())
        .then(setVoters)
        .catch(() => {})
    }, 30_000)
    return () => clearInterval(id)
  }, [])

  if (!voters.length) return null

  return (
    <div className="rounded-xl border border-zinc-800 bg-zinc-900 p-6">
      <h2 className="mb-4 text-sm font-semibold text-zinc-400 uppercase tracking-wider">Voter Health</h2>
      <div className="space-y-2">
        {voters.map((v) => {
          const pct = v.total_calls > 0 ? Math.round((v.successful / v.total_calls) * 100) : 0
          const healthy = pct >= 80 && v.failed === 0
          const degraded = pct >= 50
          return (
            <div key={v.voter} className="flex items-center gap-3 text-sm">
              <span
                className={`h-2.5 w-2.5 shrink-0 rounded-full ${
                  healthy ? "bg-green-500" : degraded ? "bg-yellow-500" : "bg-red-500"
                }`}
              />
              <span className="w-28 truncate font-medium text-zinc-300" title={v.voter}>
                {v.voter}
              </span>
              <span className="w-16 text-zinc-500">{v.voter_type}</span>
              <span className="w-20 text-zinc-400">
                {v.successful}/{v.total_calls}
              </span>
              {v.last_error ? (
                <span className="truncate text-red-400" title={v.last_error}>
                  {v.last_error.length > 30 ? v.last_error.slice(0, 30) + "…" : v.last_error}
                </span>
              ) : v.last_direction ? (
                <span
                  className={
                    v.last_direction === "long"
                      ? "text-green-400"
                      : v.last_direction === "short"
                        ? "text-red-400"
                        : "text-yellow-400"
                  }
                >
                  {v.last_direction.toUpperCase()}
                </span>
              ) : (
                <span className="text-zinc-600">—</span>
              )}
            </div>
          )
        })}
      </div>
    </div>
  )
}
