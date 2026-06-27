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
  ai_loop_heartbeat?: string
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
  const [enabledCoins, setEnabledCoins] = useState<string[]>([])
  const [multiData, setMultiData] = useState<{ signals: Record<string, any> | null; prompts: Record<string, string> | null; winner: string }>({
    signals: null,
    prompts: null,
    winner: "",
  })

  const fetchStatus = useCallback(async () => {
    try {
      const resp = await fetch("/api/bot/status")
      if (resp.ok) {
        const data = await resp.json()
        setStatus(data)
        if (data.config?.enabled_coins) {
          setEnabledCoins(data.config.enabled_coins.split(",").filter(Boolean))
        }
      }
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
    const interval = setInterval(() => {
      fetchStatus()
      fetchMultiData()
    }, 10_000)
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

  const handleToggleCoin = async (coin: string, enable: boolean) => {
    const current = enabledCoins.length > 0 ? enabledCoins : ["WIF", "POPCAT", "DOGE", "SUI", "JUP", "PYTH", "SOL"]
    const updated = enable ? [...current, coin] : current.filter((c) => c !== coin)
    setEnabledCoins(updated)
    try {
      await fetch("/api/bot/settings", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ enabled_coins: updated.join(",") }),
      })
    } catch (e) {
      console.warn("Failed to update enabled_coins:", e)
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
      <StatusCard running={status?.running ?? false} onToggle={handleToggle} loading={toggling} remainingSeconds={status?.remaining_seconds} heartbeat={status?.ai_loop_heartbeat} />

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
        enabledCoins={enabledCoins}
        onToggleCoin={handleToggleCoin}
      />

      <PromptViewer prompts={multiData.prompts} selectedCoin={selectedCoin} />

      <div className="grid gap-4 md:grid-cols-2">
        <div className="rounded-xl border border-zinc-800 bg-zinc-900/50 p-4">
          <h3 className="text-xs font-semibold uppercase tracking-widest text-zinc-400 mb-2">Selected Asset</h3>
          {multiData.winner && multiData.signals?.[multiData.winner] ? (
            (() => {
              const ws = multiData.signals[multiData.winner]
              const dir = ws.direction
              const conf = ws.confidence ?? 0
              const confPct = Math.min(Math.max(conf * 100, 0), 100)
              return (
                <div className="space-y-2">
                  <div className="flex items-center gap-2">
                    <span className="font-mono text-lg font-bold text-amber-400">
                      {multiData.winner} ⭐
                    </span>
                    <span
                      className={
                        `inline-flex items-center rounded px-1.5 py-0.5 text-[10px] font-semibold uppercase tracking-wider ` +
                        (dir === "long" ? "bg-green-900/60 text-green-400" : dir === "short" ? "bg-red-900/60 text-red-400" : "bg-zinc-800 text-zinc-500")
                      }
                    >
                      {dir || "WAIT"}
                    </span>
                  </div>
                  <div className="flex items-center gap-1.5">
                    <div className="h-1.5 flex-1 rounded-full bg-zinc-800 overflow-hidden">
                      <div
                        className={`h-full rounded-full transition-all duration-500 ${confPct >= 70 ? "bg-green-500" : confPct >= 40 ? "bg-yellow-500" : "bg-zinc-600"}`}
                        style={{ width: `${confPct}%` }}
                      />
                    </div>
                    <span className="font-mono text-[11px] text-zinc-400 w-8 text-right">{confPct}%</span>
                  </div>
                  {ws.reasoning && (
                    <p className="text-[11px] text-zinc-500 leading-relaxed line-clamp-2">{ws.reasoning}</p>
                  )}
                </div>
              )
            })()
          ) : (
            <p className="text-sm text-zinc-500">Waiting for AI cycle...</p>
          )}
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
        onSaved={fetchStatus}
      />

      <AiModelsCard />
      <VoterHealth />
    </div>
  )
}
