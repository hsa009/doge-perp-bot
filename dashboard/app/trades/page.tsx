"use client"

import { useEffect, useState } from "react"

interface Trade {
  id: string
  direction: string
  entry_price: number
  exit_price: number | null
  net_pnl_usd: number | null
  status: string
  opened_at: string
  closed_at: string | null
}

export default function TradesPage() {
  const [trades, setTrades] = useState<Trade[]>([])

  useEffect(() => {
    fetch("/api/trades")
      .then((r) => r.json())
      .then(setTrades)
  }, [])

  return (
    <div className="space-y-4">
      <h1 className="text-xl font-bold text-white">Trade History</h1>
      <div className="overflow-x-auto rounded-xl border border-zinc-800">
        <table className="w-full text-sm">
          <thead className="bg-zinc-900">
            <tr className="text-left text-zinc-400">
              <th className="px-4 py-3">Direction</th>
              <th className="px-4 py-3">Entry</th>
              <th className="px-4 py-3">Exit</th>
              <th className="px-4 py-3">PnL</th>
              <th className="px-4 py-3">Status</th>
              <th className="px-4 py-3">Opened</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-zinc-800">
            {trades.map((t) => (
              <tr key={t.id} className="text-white">
                <td className={`px-4 py-3 font-medium ${t.direction === "long" ? "text-green-400" : "text-red-400"}`}>
                  {t.direction?.toUpperCase() ?? "—"}
                </td>
                <td className="px-4 py-3">${t.entry_price?.toFixed(5)}</td>
                <td className="px-4 py-3">{t.exit_price ? `$${t.exit_price.toFixed(5)}` : "—"}</td>
                <td className={`px-4 py-3 font-medium ${(t.net_pnl_usd || 0) >= 0 ? "text-green-400" : "text-red-400"}`}>
                  {t.net_pnl_usd ? `$${t.net_pnl_usd.toFixed(2)}` : "—"}
                </td>
                <td className="px-4 py-3">{t.status}</td>
                <td className="px-4 py-3 text-zinc-500">
                  {t.opened_at ? new Date(t.opened_at).toLocaleDateString() : "—"}
                </td>
              </tr>
            ))}
            {trades.length === 0 && (
              <tr>
                <td colSpan={6} className="px-4 py-8 text-center text-zinc-500">
                  No trades yet
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
    </div>
  )
}
