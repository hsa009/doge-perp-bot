"use client"

interface Props {
  signals: Record<string, { secondary_provider?: string | null; disabled?: boolean }> | null
}

const COINS = ["WIF", "POPCAT", "DOGE", "SUI", "JUP", "PYTH", "SOL"]

const PROVIDER_LABELS: Record<string, string> = {
  SambaNova: "text-purple-400",
  Cerebras: "text-cyan-400",
  Groq: "text-orange-400",
}

export default function ProviderOverview({ signals }: Props) {
  return (
    <div className="rounded-xl border border-zinc-800 bg-zinc-900 p-6">
      <p className="mb-4 text-sm font-medium text-zinc-400">Provider Architecture</p>
      <div className="space-y-2">
        {COINS.map((coin) => {
          const sig = signals?.[coin] || {}
          const provider = sig.secondary_provider
          const disabled = sig.disabled === true
          return (
            <div key={coin} className={`flex items-center gap-3 text-sm ${disabled ? "opacity-50" : ""}`}>
              <span className={`font-mono font-semibold w-14 ${disabled ? "text-zinc-600" : "text-zinc-200"}`}>
                {coin}
              </span>
              <span className="text-zinc-500">Gemini</span>
              <span className="text-zinc-600">+</span>
              {provider ? (
                <span className={`font-mono ${PROVIDER_LABELS[provider] || "text-zinc-400"}`}>
                  {provider}
                </span>
              ) : (
                <span className="text-zinc-600">—</span>
              )}
              {disabled && (
                <span className="rounded bg-zinc-800 px-1.5 py-0.5 text-[10px] uppercase text-zinc-600 ml-auto">Disabled</span>
              )}
            </div>
          )
        })}
      </div>
    </div>
  )
}
