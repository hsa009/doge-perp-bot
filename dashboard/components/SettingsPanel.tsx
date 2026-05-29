"use client"

import { useState } from "react"

interface Props {
  config: {
    tp_usd: string
    sl_usd: string
    trade_amount: string
    leverage: string
    min_confidence: string
    max_daily_loss: string
    max_daily_loss_enabled: string
    groq_api_key: string
    active_asset?: string
  }
  onSaved: () => void
}

export default function SettingsPanel({ config, onSaved }: Props) {
  const [tp, setTp] = useState(config.tp_usd)
  const [sl, setSl] = useState(config.sl_usd)
  const [amount, setAmount] = useState(config.trade_amount)
  const [leverage, setLeverage] = useState(config.leverage)
  const [minConf, setMinConf] = useState(config.min_confidence)
  const [maxLoss, setMaxLoss] = useState(config.max_daily_loss)
  const [maxLossEnabled, setMaxLossEnabled] = useState(config.max_daily_loss_enabled === "1")
  const [groqKey, setGroqKey] = useState(config.groq_api_key)
  const [activeAsset, setActiveAsset] = useState(config.active_asset ?? "DOGE")
  const [saving, setSaving] = useState(false)

  const handleSave = async () => {
    setSaving(true)
    try {
      await fetch("/api/bot/settings", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          tp_usd: tp,
          sl_usd: sl,
          trade_amount: amount,
          leverage,
          min_confidence: minConf,
          max_daily_loss: maxLoss,
          max_daily_loss_enabled: maxLossEnabled ? "1" : "0",
          groq_api_key: groqKey,
          active_asset: activeAsset,
        }),
      })
      onSaved()
    } finally {
      setSaving(false)
    }
  }

  const inputClass = "mt-1 w-full rounded-lg border border-zinc-700 bg-zinc-800 px-3 py-2 text-sm text-white focus:border-zinc-500 focus:outline-none"

  return (
    <div className="rounded-xl border border-zinc-800 bg-zinc-900 p-6">
      <p className="mb-4 text-sm font-medium text-zinc-400">Trading Settings</p>
      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
        <div>
          <label className="block text-xs text-zinc-500">Take Profit ($)</label>
          <input type="number" step="1" value={tp} onChange={(e) => setTp(e.target.value)} className={inputClass} />
        </div>
        <div>
          <label className="block text-xs text-zinc-500">Stop Loss ($)</label>
          <input type="number" step="0.1" value={sl} onChange={(e) => setSl(e.target.value)} className={inputClass} />
        </div>
        <div>
          <label className="block text-xs text-zinc-500">Trade Amount ($)</label>
          <input type="number" min="1" step="0.5" value={amount} onChange={(e) => setAmount(e.target.value)} className={inputClass} />
        </div>
        <div>
          <label className="block text-xs text-zinc-500">Leverage (x)</label>
          <select value={leverage} onChange={(e) => setLeverage(e.target.value)} className={inputClass}>
            {[3, 5, 10, 15, 20, 25, 30].map((n) => (
              <option key={n} value={n}>{n}x</option>
            ))}
          </select>
        </div>
        <div>
          <label className="block text-xs text-zinc-500">Target Asset</label>
          <div className="mt-1 flex rounded-lg border border-zinc-700 overflow-hidden">
            <button
              className={`flex-1 px-3 py-2 text-sm font-medium transition-colors ${activeAsset === "DOGE" ? "bg-blue-600 text-white" : "bg-zinc-800 text-zinc-400"}`}
              onClick={() => setActiveAsset("DOGE")}
            >DOGE</button>
            <button
              className={`flex-1 px-3 py-2 text-sm font-medium transition-colors ${activeAsset === "SOL" ? "bg-blue-600 text-white" : "bg-zinc-800 text-zinc-400"}`}
              onClick={() => setActiveAsset("SOL")}
            >SOL</button>
          </div>
        </div>
        <div>
          <label className="block text-xs text-zinc-500">Min Confidence</label>
          <input type="number" step="0.05" min="0" max="1" value={minConf} onChange={(e) => setMinConf(e.target.value)} className={inputClass} />
        </div>
        <div>
          <label className="block text-xs text-zinc-500">Max Daily Loss ($)</label>
          <div className="mt-1 flex items-center gap-3">
            <input type="number" step="0.5" value={maxLoss} onChange={(e) => setMaxLoss(e.target.value)}
              className={`${inputClass} flex-1`} disabled={!maxLossEnabled} />
            <button
              onClick={() => setMaxLossEnabled(!maxLossEnabled)}
              className={`relative inline-flex h-6 w-11 shrink-0 cursor-pointer rounded-full border-2 border-transparent transition-colors ${maxLossEnabled ? "bg-blue-600" : "bg-zinc-700"}`}
            >
              <span className={`inline-block h-5 w-5 rounded-full bg-white transition-transform ${maxLossEnabled ? "translate-x-5" : "translate-x-0"}`} />
            </button>
          </div>
        </div>
        <div className="flex items-end">
          <button
            onClick={handleSave}
            disabled={saving}
            className="w-full rounded-lg bg-blue-600 px-4 py-2 text-sm font-medium text-white hover:bg-blue-700 transition-colors disabled:opacity-50"
          >
            {saving ? "Saving..." : "Save Settings"}
          </button>
        </div>
      </div>
      <div className="mt-3">
        <label className="block text-xs text-zinc-500">Groq API Key</label>
        <input type="text" value={groqKey} onChange={(e) => setGroqKey(e.target.value)}
          placeholder="gsk_..."
          className={`${inputClass} mt-1`} />
      </div>
    </div>
  )
}
