"use client"

import { useEffect, useState, useCallback } from "react"
import StatusCard from "../components/StatusCard"
import SignalDisplay from "../components/SignalDisplay"
import PnLSummary from "../components/PnLSummary"
import SettingsPanel from "../components/SettingsPanel"
import AiModelsCard from "../components/AiModelsCard"
import TradingChart from "../components/TradingChart"
import ProfitCalculator from "../components/ProfitCalculator"

interface BotStatus {
  running: boolean
  last_signal: {
    direction: string
    confidence: number
    regime: string
    reasoning: string
    timestamp?: number
    prompt?: string
    tiebreaker_used?: boolean
    round1_details?: {
      name: string
      direction: string
      confidence: number
      reasoning: string
    }[]
    model_details?: {
      name: string
      direction: string
      confidence: number
      reasoning: string
    }[]
  } | null
  position: {
    coin: string
    direction?: string
    size: number
    entry_price: number
    unrealized_pnl: number
    leverage?: number
    tp_price?: number
    sl_price?: number
    mark_price?: number
  } | null
  mark_price: number | null
  config: {
    tp_usd: string
    sl_usd: string
    trade_amount: string
    leverage: string
    min_confidence: string
    max_daily_loss: string
    max_daily_loss_enabled: string
    groq_api_key: string
    ai_loop_interval: string
  }
}

const defaultConfig = {
  tp_usd: "3.0",
  sl_usd: "3.0",
  trade_amount: "10.0",
  leverage: "10",
  min_confidence: "0.65",
  max_daily_loss: "2.0",
  max_daily_loss_enabled: "1",
  groq_api_key: "",
  ai_loop_interval: "600",
}

export default function Dashboard() {
  const [status, setStatus] = useState<BotStatus | null>(null)
  const [stats, setStats] = useState({ total_pnl: 0, win_rate: 0, total_trades: 0 })
  const [loading, setLoading] = useState(true)
  const [toggling, setToggling] = useState(false)
  const [closing, setClosing] = useState(false)
  const [reasking, setReasking] = useState(false)
  const [forcing, setForcing] = useState(false)

  const fetchStatus = useCallback(async () => {
    try {
      const resp = await fetch("/api/bot/status")
      if (resp.ok) setStatus(await resp.json())
    } finally {
      setLoading(false)
    }
  }, [])

  const fetchStats = useCallback(async () => {
    const resp = await fetch("/api/stats")
    if (resp.ok) setStats(await resp.json())
  }, [])

  useEffect(() => {
    fetchStatus()
    fetchStats()
    const interval = setInterval(fetchStatus, 10_000)
    return () => clearInterval(interval)
  }, [fetchStatus, fetchStats])

  const handleToggle = async () => {
    setToggling(true)
    const action = status?.running ? "stop" : "start"
    try {
      await fetch(`/api/bot/${action}`, { method: "POST" })
      await fetchStatus()
    } finally {
      setToggling(false)
    }
  }

  const handleClosePosition = async () => {
    setClosing(true)
    try {
      await fetch("/api/bot/close-position", { method: "POST" })
      await new Promise((r) => setTimeout(r, 3000))
      await fetchStatus()
    } finally {
      setClosing(false)
    }
  }

  const handleReAsk = async () => {
    setReasking(true)
    try {
      await fetch("/api/bot/re-ask", { method: "POST" })
      await new Promise((r) => setTimeout(r, 3000))
      await fetchStatus()
    } finally {
      setReasking(false)
    }
  }

  const handleForceTrade = async () => {
    setForcing(true)
    try {
      await fetch("/api/bot/force-trade", { method: "POST" })
      await new Promise((r) => setTimeout(r, 3000))
      await fetchStatus()
    } finally {
      setForcing(false)
    }
  }

  const pos = status?.position
  const hasPosition = pos && Math.abs(pos.size) > 0 && pos.entry_price > 0
  const markPrice = status?.mark_price ?? pos?.mark_price ?? null

  if (loading) {
    return <div className="py-20 text-center text-zinc-500">Loading...</div>
  }

  return (
    <div className="space-y-4">
      <StatusCard running={status?.running ?? false} onToggle={handleToggle} loading={toggling} />

      {hasPosition && (
        <div className="flex items-center justify-between rounded-xl border border-zinc-800 bg-zinc-900/50 px-4 py-2">
          <div className="flex items-center gap-4 text-sm">
            <span className={`font-semibold ${pos.direction === "long" ? "text-green-400" : "text-red-400"}`}>
              {pos.direction?.toUpperCase()}
            </span>
            <span className="font-mono text-zinc-300">{Math.abs(pos.size)} DOGE</span>
            <span className="text-zinc-500">${pos.entry_price.toFixed(5)}</span>
            <span className={`font-mono ${(pos.unrealized_pnl || 0) >= 0 ? "text-green-400" : "text-red-400"}`}>
              ${(pos.unrealized_pnl || 0).toFixed(2)}
            </span>
          </div>
          <button
            onClick={handleClosePosition}
            disabled={closing}
            className="rounded-lg bg-red-600 px-3 py-1.5 text-xs font-medium text-white hover:bg-red-700 transition-colors disabled:opacity-50"
          >
            {closing ? "Closing..." : "Close"}
          </button>
        </div>
      )}

      <div className={`grid gap-4 ${hasPosition ? "lg:grid-cols-[1fr_280px]" : ""}`}>
        <TradingChart position={hasPosition ? pos : null} />

        {hasPosition && (
          <ProfitCalculator
            entryPrice={pos.entry_price}
            tpPrice={pos.tp_price}
            slPrice={pos.sl_price}
            size={Math.abs(pos.size)}
            leverage={pos.leverage || parseInt(status?.config.leverage || "10")}
          />
        )}
      </div>

      <div className="grid gap-4 md:grid-cols-2">
        <SignalDisplay
          signal={status?.last_signal ?? null}
          signalTimestamp={status?.last_signal?.timestamp}
          aiLoopInterval={parseInt(status?.config?.ai_loop_interval || "600")}
          running={status?.running ?? false}
        />
        <PnLSummary totalPnl={stats.total_pnl} winRate={stats.win_rate} totalTrades={stats.total_trades} />
      </div>

      <div className="flex gap-3">
        <button
          onClick={handleReAsk}
          disabled={reasking}
          className="flex-1 rounded-lg bg-zinc-700 px-4 py-2 text-sm font-medium text-white hover:bg-zinc-600 transition-colors disabled:opacity-50"
        >
          {reasking ? "Re-asking..." : "Re-ask AI"}
        </button>
        <button
          onClick={handleForceTrade}
          disabled={forcing}
          className="flex-1 rounded-lg bg-yellow-600 px-4 py-2 text-sm font-medium text-white hover:bg-yellow-700 transition-colors disabled:opacity-50"
        >
          {forcing ? "Forcing..." : "Force Trade"}
        </button>
      </div>

      <SettingsPanel
        config={status?.config ?? defaultConfig}
        onSaved={fetchStatus}
      />

      <AiModelsCard />
    </div>
  )
}
