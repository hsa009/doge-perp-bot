"use client"

import { useEffect, useState, useCallback } from "react"
import StatusCard from "../components/StatusCard"
import PnLSummary from "../components/PnLSummary"
import SettingsPanel from "../components/SettingsPanel"
import AiModelsCard from "../components/AiModelsCard"
import TradingChart from "../components/TradingChart"
import ProfitCalculator from "../components/ProfitCalculator"
import VoterHealth from "../components/VoterHealth"
import MultiCoinSignals from "../components/MultiCoinSignals"
import PromptViewer from "../components/PromptViewer"

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
  remaining_seconds?: number
  pending_asset?: string
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
    active_asset?: string
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
  const [selectedCoin, setSelectedCoin] = useState("DOGE")
  const [multiData, setMultiData] = useState<{ signals: Record<string, any> | null; prompts: Record<string, string> | null; winner: string }>({
    signals: null,
    prompts: null,
    winner: "",
  })

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

  const fetchMultiData = useCallback(async () => {
    try {
      const resp = await fetch("/api/bot/multi-asset-data")
      if (resp.ok) {
        const data = await resp.json()
        setMultiData({ signals: data.signals || null, prompts: data.prompts || null, winner: data.winner || "" })
      }
    } catch {}
  }, [])

  useEffect(() => {
    fetchStatus()
    fetchStats()
    fetchMultiData()
    const interval = setInterval(fetchStatus, 10_000)
    return () => clearInterval(interval)
  }, [fetchStatus, fetchStats, fetchMultiData])

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
  const activeAsset = status?.config?.active_asset ?? "DOGE"

  if (loading) {
    return <div className="py-20 text-center text-zinc-500">Loading...</div>
  }

  return (
    <div className="space-y-4">
      <StatusCard running={status?.running ?? false} onToggle={handleToggle} loading={toggling} />

      {status?.pending_asset && hasPosition && (
        <div className="rounded-xl border border-amber-700/50 bg-amber-900/20 px-4 py-3 text-sm text-amber-300">
          <span className="font-medium">⏳ Pending switch to {status.pending_asset}</span>
          <span className="ml-1 text-amber-400/80">— will auto-switch when current position closes</span>
        </div>
      )}

      {hasPosition && (
        <div className="flex items-center justify-between rounded-xl border border-zinc-800 bg-zinc-900/50 px-4 py-2">
          <div className="flex items-center gap-4 text-sm">
            <span className={`font-semibold ${pos.direction === "long" ? "text-green-400" : "text-red-400"}`}>
              {pos.direction?.toUpperCase()}
            </span>
            <span className="font-mono text-zinc-300">{Math.abs(pos.size)} {pos.coin || activeAsset}</span>
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
        <TradingChart position={hasPosition ? pos : null} coin={selectedCoin} />

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

      <MultiCoinSignals
        signals={multiData.signals}
        winner={multiData.winner}
        selectedCoin={selectedCoin}
        onSelectCoin={setSelectedCoin}
      />

      <PromptViewer prompts={multiData.prompts} selectedCoin={selectedCoin} />

      <div className="grid gap-4 md:grid-cols-2">
        <div className="rounded-xl border border-zinc-800 bg-zinc-900/50 p-4">
          <h3 className="text-xs font-semibold uppercase tracking-widest text-zinc-400 mb-2">Active Asset</h3>
          <p className="text-sm text-zinc-300">
            Trading: <span className="font-mono font-semibold text-zinc-100">{status?.config?.active_asset || "DOGE"}</span>
          </p>
        </div>
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
        pendingAsset={status?.pending_asset}
        onSaved={fetchStatus}
      />

      <AiModelsCard />
      <VoterHealth />
    </div>
  )
}
