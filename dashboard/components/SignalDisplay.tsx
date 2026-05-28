"use client"

import { useEffect, useState } from "react"

interface ModelDetail {
  name: string
  direction: string
  confidence: number
  reasoning: string
}

interface Props {
  signal: {
    direction: string
    confidence: number
    regime: string
    reasoning: string
    prompt?: string
    model_details?: ModelDetail[]
  } | null
  signalTimestamp?: number
  aiLoopInterval?: number
  running?: boolean
}

export default function SignalDisplay({ signal, signalTimestamp, aiLoopInterval, running }: Props) {
  const [expanded, setExpanded] = useState(false)
  const [remaining, setRemaining] = useState(0)

  useEffect(() => {
    if (!running || !signalTimestamp || !aiLoopInterval) {
      setRemaining(0)
      return
    }
    const tick = () => {
      const now = Date.now() / 1000
      const next = signalTimestamp + aiLoopInterval
      setRemaining(Math.max(0, Math.floor(next - now)))
    }
    tick()
    const id = setInterval(tick, 1000)
    return () => clearInterval(id)
  }, [running, signalTimestamp, aiLoopInterval])

  if (!signal) {
    return (
      <div className="rounded-xl border border-zinc-800 bg-zinc-900 p-6">
        <p className="text-sm text-zinc-400">Last Signal</p>
        <p className="mt-2 text-zinc-500">No signal yet</p>
      </div>
    )
  }

  const colorMap: Record<string, string> = {
    long: "text-green-400",
    short: "text-red-400",
    wait: "text-yellow-400",
  }

  const hasDetails = signal.prompt || (signal.model_details && signal.model_details.length > 0)

  const fmt = (s: number) => {
    const m = Math.floor(s / 60)
    const sec = s % 60
    return `${m}:${sec.toString().padStart(2, "0")}`
  }

  return (
    <div className="rounded-xl border border-zinc-800 bg-zinc-900 p-6">
      <div className="flex items-center justify-between">
        <p className="text-sm text-zinc-400">Last Signal</p>
        {hasDetails && (
          <button
            onClick={() => setExpanded(!expanded)}
            className="text-xs text-zinc-500 hover:text-zinc-300 transition-colors"
          >
            {expanded ? "Hide AI Details" : "Show AI Details"}
          </button>
        )}
      </div>
      <div className="mt-2 flex items-baseline gap-3">
          <span className={`text-2xl font-bold ${colorMap[signal.direction] || "text-white"}`}>
            {signal.direction?.toUpperCase() ?? "—"}
          </span>
        <span className="text-lg text-zinc-400">
          {(signal.confidence * 100).toFixed(0)}%
        </span>
        <span className="rounded bg-zinc-800 px-2 py-0.5 text-xs text-zinc-400">
          {signal.regime}
        </span>
      </div>
      <p className="mt-2 text-xs text-zinc-500">{signal.reasoning}</p>
      <p className="mt-1 text-xs text-zinc-600">
        {running && remaining > 0 ? `Next signal in ${fmt(remaining)}` : "Next signal —"}
      </p>

      {expanded && hasDetails && (
        <div className="mt-4 space-y-3 border-t border-zinc-800 pt-4">
          {signal.prompt && (
            <div>
              <p className="mb-1 text-xs font-medium text-zinc-400">Prompt</p>
              <pre className="max-h-48 overflow-auto rounded bg-zinc-950 p-3 text-xs text-zinc-300 whitespace-pre-wrap">
                {signal.prompt}
              </pre>
            </div>
          )}
          {signal.model_details && signal.model_details.length > 0 && (
            <div>
              <p className="mb-1 text-xs font-medium text-zinc-400">Model Responses</p>
              <div className="space-y-2">
                {signal.model_details.map((m, i) => (
                  <div key={i} className="rounded bg-zinc-950 p-3 text-xs">
                    <div className="flex items-center gap-2 mb-1">
                      <span className="font-medium text-zinc-200">{m.name}</span>
                      <span className={colorMap[m.direction] || "text-zinc-400"}>
                        {m.direction.toUpperCase()}
                      </span>
                      <span className="text-zinc-500">
                        {(m.confidence * 100).toFixed(0)}%
                      </span>
                    </div>
                    {m.reasoning && (
                      <p className="text-zinc-400">{m.reasoning}</p>
                    )}
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  )
}
