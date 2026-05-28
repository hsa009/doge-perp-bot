"use client"

import { useEffect, useState, useCallback } from "react"

interface ModelResult {
  key: string
  name: string
  model_id: string
  enabled: boolean
  last: {
    direction: string
    confidence: number
    reasoning: string
  } | null
}

export default function AiModelsCard() {
  const [models, setModels] = useState<ModelResult[]>([])
  const [expanded, setExpanded] = useState<string | null>(null)

  const fetchModels = useCallback(async () => {
    try {
      const resp = await fetch("/api/bot/models")
      if (resp.ok) {
        const data = await resp.json()
        setModels(data.models ?? [])
      }
    } catch {
      // ignore
    }
  }, [])

  useEffect(() => {
    fetchModels()
    const interval = setInterval(fetchModels, 10_000)
    return () => clearInterval(interval)
  }, [fetchModels])

  const toggleModel = async (key: string, enabled: boolean) => {
    setModels((prev) =>
      prev.map((m) => (m.key === key ? { ...m, enabled } : m))
    )
    await fetch("/api/bot/models", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ key, enabled }),
    })
  }

  const activeCount = models.filter((m) => m.enabled).length

  const directionColor: Record<string, string> = {
    long: "text-green-400",
    short: "text-red-400",
    wait: "text-yellow-400",
  }

  return (
    <div className="rounded-xl border border-zinc-800 bg-zinc-900 p-6">
      <p className="mb-4 text-sm font-medium text-zinc-400">
        AI Models <span className="text-zinc-600">({models.length} models, {activeCount} active)</span>
      </p>
      <div className="space-y-3">
        {models.map((m) => {
          const isExpanded = expanded === m.key
          return (
            <div
              key={m.key}
              className={`rounded-lg border p-3 transition-colors ${
                m.enabled ? "border-zinc-700" : "border-zinc-800 opacity-50"
              }`}
            >
              <div className="flex items-center gap-3">
                <button
                  onClick={() => toggleModel(m.key, !m.enabled)}
                  className={`relative inline-flex h-5 w-9 shrink-0 cursor-pointer rounded-full border-2 border-transparent transition-colors ${
                    m.enabled ? "bg-blue-600" : "bg-zinc-700"
                  }`}
                >
                  <span
                    className={`inline-block h-4 w-4 rounded-full bg-white transition-transform ${
                      m.enabled ? "translate-x-4" : "translate-x-0"
                    }`}
                  />
                </button>
                <span className="min-w-0 flex-1 text-sm font-medium text-white truncate">
                  {m.name}
                </span>
                {!m.enabled && (
                  <span className="rounded bg-zinc-800 px-1.5 py-0.5 text-[10px] uppercase text-zinc-500">
                    Disabled
                  </span>
                )}
                {m.last ? (
                  <>
                    <span
                      className={`text-xs font-semibold ${
                        directionColor[m.last.direction] || "text-white"
                      }`}
                    >
                      {m.last.direction.toUpperCase()}
                    </span>
                    <span className="text-xs text-zinc-400">
                      {(m.last.confidence * 100).toFixed(0)}%
                    </span>
                  </>
                ) : (
                  <span className="text-xs text-zinc-600">—</span>
                )}
              </div>
              {m.last && m.last.reasoning && (
                <div className="mt-2 ml-12">
                  <p
                    className={`text-xs text-zinc-500 cursor-pointer ${
                      isExpanded ? "" : "line-clamp-1"
                    }`}
                    onClick={() => setExpanded(isExpanded ? null : m.key)}
                  >
                    {m.last.reasoning}
                  </p>
                </div>
              )}
            </div>
          )
        })}
      </div>
      {models.length === 0 && (
        <p className="text-sm text-zinc-600">No models loaded yet</p>
      )}
    </div>
  )
}
