"use client"

import { type JSX } from "react"

interface CoinSignal {
  direction?: string
  confidence?: number
  reasoning?: string
}

interface MultiCoinSignalsProps {
  signals: Record<string, CoinSignal> | null
  winner: string
  selectedCoin: string
  onSelectCoin: (coin: string) => void
}

const COINS = ["PEPE", "BONK", "FLOKI", "BOME", "WIF", "POPCAT", "DOGE", "SUI", "JUP", "PYTH", "SOL"]

function DirectionBadge({ direction }: { direction?: string }) {
  if (!direction || direction === "wait") {
    return <span className="inline-flex items-center rounded px-1.5 py-0.5 text-[10px] font-semibold uppercase tracking-wider bg-zinc-800 text-zinc-500">WAIT</span>
  }
  const isLong = direction === "long"
  return (
    <span
      className={
        `inline-flex items-center rounded px-1.5 py-0.5 text-[10px] font-semibold uppercase tracking-wider ` +
        (isLong ? "bg-green-900/60 text-green-400" : "bg-red-900/60 text-red-400")
      }
    >
      {direction}
    </span>
  )
}

function ConfidenceBar({ confidence }: { confidence?: number }) {
  const pct = Math.min(Math.max((confidence ?? 0) * 100, 0), 100)
  return (
    <div className="flex items-center gap-1.5 min-w-[80px]">
      <div className="h-1.5 flex-1 rounded-full bg-zinc-800 overflow-hidden">
        <div
          className={`h-full rounded-full transition-all duration-500 ${pct >= 70 ? "bg-green-500" : pct >= 40 ? "bg-yellow-500" : "bg-zinc-600"}`}
          style={{ width: `${pct}%` }}
        />
      </div>
      <span className="font-mono text-[11px] text-zinc-400 w-8 text-right">{pct}%</span>
    </div>
  )
}

export default function MultiCoinSignals({ signals, winner, selectedCoin, onSelectCoin }: MultiCoinSignalsProps) {
  if (!signals) {
    return (
      <div className="rounded-xl border border-zinc-800 bg-zinc-900/50 p-4">
        <p className="text-sm text-zinc-500">No signal data yet — waiting for AI cycle</p>
      </div>
    )
  }

  return (
    <div className="rounded-xl border border-zinc-800 bg-zinc-900/50 overflow-hidden">
      <div className="px-4 py-2.5 border-b border-zinc-800">
        <h2 className="text-xs font-semibold uppercase tracking-widest text-zinc-400">Coin Signals</h2>
      </div>
      <div className="divide-y divide-zinc-800/60">
        {COINS.map((coin) => {
          const sig = signals[coin] || {}
          const isWinner = coin === winner
          const isSelected = coin === selectedCoin
          return (
            <button
              key={coin}
              onClick={() => onSelectCoin(coin)}
              className={`w-full flex items-center gap-3 px-4 py-2.5 text-left transition-colors hover:bg-zinc-800/40 ${
                isSelected ? "bg-zinc-800/60 ring-1 ring-inset ring-zinc-600" : ""
              } ${isWinner ? "border-l-2 border-amber-500" : "border-l-2 border-transparent"}`}
            >
              <span className={`font-mono text-sm font-semibold w-14 ${isWinner ? "text-amber-400" : "text-zinc-200"}`}>
                {coin}
                {isWinner && <span className="ml-1 text-[10px]">⭐</span>}
              </span>
              <DirectionBadge direction={sig.direction} />
              <ConfidenceBar confidence={sig.confidence} />
              <p className="flex-1 text-[11px] text-zinc-500 truncate hidden sm:block">
                {sig.reasoning || ""}
              </p>
            </button>
          )
        })}
      </div>
    </div>
  )
}
