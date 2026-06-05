"use client"

import { useEffect, useState } from "react"

interface AiVote {
  id: number
  cycle_id: string
  coin: string
  voter: string
  voter_type: string
  direction: string | null
  confidence: number | null
  reasoning: string | null
  error: string | null
  created_at: string
}

interface CycleGroup {
  cycle_id: string
  created_at: string
  coin: string
  votes: AiVote[]
}

export default function AiVotesPage() {
  const [cycles, setCycles] = useState<CycleGroup[]>([])

  useEffect(() => {
    fetch("/api/ai-votes")
      .then((r) => r.json())
      .then((data: AiVote[]) => {
        const groups: Record<string, CycleGroup> = {}
        for (const v of data) {
          if (!groups[v.cycle_id]) {
            groups[v.cycle_id] = {
              cycle_id: v.cycle_id,
              created_at: v.created_at,
              coin: v.coin,
              votes: [],
            }
          }
          groups[v.cycle_id].votes.push(v)
        }
        setCycles(Object.values(groups).slice(0, 50))
      })
  }, [])

  function tallyText(votes: AiVote[]): string {
    const long = votes.filter((v) => v.direction === "long").length
    const short = votes.filter((v) => v.direction === "short").length
    const wait = votes.filter((v) => v.direction === "wait").length
    const failed = votes.filter((v) => v.error).length
    const parts = [`L:${long}`, `S:${short}`, `W:${wait}`]
    if (failed) parts.push(`ERR:${failed}`)
    return parts.join(" | ")
  }

  function winnerBadge(votes: AiVote[]): { label: string; color: string } {
    const counts: Record<string, number> = {}
    for (const v of votes) {
      if (v.direction) counts[v.direction] = (counts[v.direction] || 0) + 1
    }
    const max = Math.max(...Object.values(counts), 0)
    if (max === 0) return { label: "NO VOTES", color: "text-zinc-500" }
    const winners = Object.entries(counts).filter(([, c]) => c === max)
    if (winners.length > 1) return { label: "TIE → WAIT", color: "text-yellow-400" }
    const dir = winners[0][0]
    if (dir === "long") return { label: "LONG", color: "text-green-400" }
    if (dir === "short") return { label: "SHORT", color: "text-red-400" }
    return { label: "WAIT", color: "text-yellow-400" }
  }

  return (
    <div className="space-y-4">
      <h1 className="text-xl font-bold text-white">AI Voting History</h1>
      {cycles.length === 0 && (
        <p className="text-zinc-500">No AI voting cycles yet.</p>
      )}
      {cycles.map((cycle) => {
        const badge = winnerBadge(cycle.votes)
        return (
          <div
            key={cycle.cycle_id}
            className="rounded-xl border border-zinc-800 bg-zinc-950 p-4"
          >
            <div className="mb-3 flex items-center justify-between">
              <div className="flex items-center gap-3">
                <span className={`text-lg font-bold ${badge.color}`}>
                  {badge.label}
                </span>
                <span className="text-sm text-zinc-400">
                  {cycle.coin} · {tallyText(cycle.votes)}
                </span>
              </div>
              <span className="text-xs text-zinc-600">
                {cycle.created_at
                  ? new Date(cycle.created_at).toLocaleString()
                  : "—"}
              </span>
            </div>
            <div className="overflow-x-auto">
              <table className="w-full text-xs">
                <thead>
                  <tr className="text-left text-zinc-500">
                    <th className="pb-2 pr-4">Voter</th>
                    <th className="pb-2 pr-4">Direction</th>
                    <th className="pb-2 pr-4">Conf</th>
                    <th className="pb-2 pr-4">Reasoning</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-zinc-800">
                  {cycle.votes.map((v) => (
                    <tr key={v.id} className="text-white">
                      <td className="py-2 pr-4 font-medium text-zinc-300">
                        {v.voter}
                      </td>
                      <td className="py-2 pr-4">
                        {v.error ? (
                          <span className="text-red-400" title={v.error}>
                            ERROR
                          </span>
                        ) : (
                          <span
                            className={
                              v.direction === "long"
                                ? "text-green-400"
                                : v.direction === "short"
                                  ? "text-red-400"
                                  : "text-yellow-400"
                            }
                          >
                            {v.direction?.toUpperCase() ?? "—"}
                          </span>
                        )}
                      </td>
                      <td className="py-2 pr-4 text-zinc-400">
                        {v.confidence != null ? v.confidence.toFixed(2) : "—"}
                      </td>
                      <td className="py-2 pr-4 text-zinc-500 max-w-xs truncate">
                        {v.error || v.reasoning || "—"}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        )
      })}
    </div>
  )
}
