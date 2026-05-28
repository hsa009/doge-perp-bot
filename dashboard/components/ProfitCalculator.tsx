"use client"

import { useMemo, useState } from "react"

interface Props {
  entryPrice: number
  tpPrice: number | undefined
  slPrice: number | undefined
  size: number
  leverage: number
}

export default function ProfitCalculator({ entryPrice, tpPrice, slPrice, size, leverage }: Props) {
  const [feePct, setFeePct] = useState(0.1)

  const calc = useMemo(() => {
    const notional = size * entryPrice
    const margin = notional / leverage
    const feeRate = feePct / 100

    let tpProfit = null
    let tpProfitPct = null
    let slLoss = null
    let slLossPct = null
    let rr = null

    if (tpPrice) {
      const gross = (tpPrice - entryPrice) * size
      const fees = notional * feeRate * 2
      tpProfit = gross - fees
      tpProfitPct = (tpProfit / margin) * 100
    }

    if (slPrice) {
      const gross = (slPrice - entryPrice) * size
      const fees = notional * feeRate * 2
      slLoss = gross - fees
      slLossPct = (slLoss / margin) * 100
    }

    if (tpProfit != null && slLoss != null && slLoss !== 0) {
      rr = Math.abs(tpProfit / slLoss)
    }

    return { notional, margin, tpProfit, tpProfitPct, slLoss, slLossPct, rr }
  }, [entryPrice, tpPrice, slPrice, size, leverage, feePct])

  return (
    <div className="rounded-xl border border-zinc-800 bg-zinc-900 p-4 text-sm">
      <div className="flex items-center justify-between mb-3">
        <h3 className="text-xs font-semibold text-zinc-400 uppercase tracking-wider">Profit Calculator</h3>
        <div className="flex items-center gap-1.5">
          <span className="text-[10px] text-zinc-600">Fee</span>
          <input
            type="number"
            value={feePct}
            onChange={(e) => setFeePct(parseFloat(e.target.value) || 0)}
            className="w-14 rounded border border-zinc-700 bg-zinc-800 px-1.5 py-0.5 text-xs text-right text-zinc-300"
            step="0.05"
            min="0"
          />
          <span className="text-[10px] text-zinc-600">%</span>
        </div>
      </div>

      <div className="grid grid-cols-2 gap-x-4 gap-y-2 text-xs">
        <div className="text-zinc-500">Notional</div>
        <div className="text-right font-mono text-zinc-300">${calc.notional.toFixed(2)}</div>

        <div className="text-zinc-500">Margin</div>
        <div className="text-right font-mono text-zinc-300">${calc.margin.toFixed(2)}</div>

        {calc.tpProfit != null && (
          <>
            <div className="text-zinc-500">TP Profit</div>
            <div className="text-right font-mono text-green-400">
              +${calc.tpProfit.toFixed(2)}
              <span className="text-green-500/70 ml-1">({calc.tpProfitPct!.toFixed(1)}%)</span>
            </div>
          </>
        )}

        {calc.slLoss != null && (
          <>
            <div className="text-zinc-500">SL Loss</div>
            <div className="text-right font-mono text-red-400">
              {calc.slLoss.toFixed(2)}
              <span className="text-red-500/70 ml-1">({calc.slLossPct!.toFixed(1)}%)</span>
            </div>
          </>
        )}

        {calc.rr != null && (
          <>
            <div className="text-zinc-500">R:R Ratio</div>
            <div className="text-right font-mono text-zinc-300">
              {calc.rr >= 0 ? (
                <span className="text-green-400">{calc.rr.toFixed(2)}</span>
              ) : (
                <span className="text-red-400">{calc.rr.toFixed(2)}</span>
              )}
            </div>
          </>
        )}
      </div>
    </div>
  )
}
