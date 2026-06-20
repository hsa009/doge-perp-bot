"use client"

import { useState } from "react"

interface PromptViewerProps {
  prompts: Record<string, string> | null
  selectedCoin: string
}

export default function PromptViewer({ prompts, selectedCoin }: PromptViewerProps) {
  const [expanded, setExpanded] = useState(false)
  const [copied, setCopied] = useState(false)

  if (!prompts || Object.keys(prompts).length === 0) {
    return null
  }

  const promptText = prompts[selectedCoin] || ""

  const handleCopy = async () => {
    if (!promptText) return
    try {
      await navigator.clipboard.writeText(promptText)
      setCopied(true)
      setTimeout(() => setCopied(false), 2000)
    } catch {}
  }

  return (
    <div className="rounded-xl border border-zinc-800 bg-zinc-900/50 overflow-hidden">
      <button
        onClick={() => setExpanded(!expanded)}
        className="w-full flex items-center justify-between px-4 py-2.5 text-left transition-colors hover:bg-zinc-800/40"
      >
        <span className="text-xs font-semibold uppercase tracking-widest text-zinc-400">
          AI Prompt — {selectedCoin}
        </span>
        <span className="text-zinc-500 text-xs transition-transform duration-200" style={{ transform: expanded ? "rotate(180deg)" : "rotate(0deg)" }}>
          ▼
        </span>
      </button>

      {expanded && (
        <div className="border-t border-zinc-800">
          <div className="relative">
            <pre className="overflow-x-auto p-4 text-[11px] leading-relaxed font-mono text-zinc-300 bg-black/40 max-h-[60vh] overflow-y-auto whitespace-pre-wrap break-words">
              {promptText || <span className="text-zinc-600 italic">No prompt available for this coin</span>}
            </pre>
            {promptText && (
              <button
                onClick={handleCopy}
                className="absolute top-2 right-2 rounded bg-zinc-800 px-2 py-1 text-[10px] font-medium text-zinc-400 hover:bg-zinc-700 hover:text-zinc-200 transition-colors"
              >
                {copied ? "Copied!" : "Copy"}
              </button>
            )}
          </div>
        </div>
      )}
    </div>
  )
}
