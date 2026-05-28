"use client"

interface Props {
  totalPnl: number
  winRate: number
  totalTrades: number
}

export default function PnLSummary({ totalPnl, winRate, totalTrades }: Props) {
  return (
    <div className="rounded-xl border border-zinc-800 bg-zinc-900 p-6">
      <p className="mb-3 text-sm text-zinc-400">Performance</p>
      <div className="grid grid-cols-3 gap-4">
        <div>
          <p className="text-xs text-zinc-500">Total PnL</p>
          <p className={`text-xl font-bold ${totalPnl >= 0 ? "text-green-400" : "text-red-400"}`}>
            ${totalPnl.toFixed(2)}
          </p>
        </div>
        <div>
          <p className="text-xs text-zinc-500">Win Rate</p>
          <p className="text-xl font-bold text-white">{(winRate * 100).toFixed(0)}%</p>
        </div>
        <div>
          <p className="text-xs text-zinc-500">Trades</p>
          <p className="text-xl font-bold text-white">{totalTrades}</p>
        </div>
      </div>
    </div>
  )
}
