"use client"

import { useEffect, useState } from "react"

interface Props {
  running: boolean
  onToggle: () => void
  loading: boolean
  remainingSeconds?: number
}

function formatTime(seconds: number): string {
  const m = Math.floor(seconds / 60)
  const s = Math.floor(seconds % 60)
  return `${m}:${s.toString().padStart(2, "0")}`
}

export default function StatusCard({ running, onToggle, loading, remainingSeconds }: Props) {
  const [display, setDisplay] = useState(remainingSeconds ?? 0)

  useEffect(() => {
    setDisplay(remainingSeconds ?? 0)
  }, [remainingSeconds])

  useEffect(() => {
    if (display <= 0) return
    const id = setInterval(() => {
      setDisplay((prev) => Math.max(0, prev - 1))
    }, 1000)
    return () => clearInterval(id)
  }, [display])

  return (
    <div className="rounded-xl border border-zinc-800 bg-zinc-900 p-6">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-6">
          <div>
            <p className="text-sm text-zinc-400">Bot Status</p>
            <div className="mt-1 flex items-center gap-2">
              <span
                className={`h-3 w-3 rounded-full ${running ? "bg-green-500" : "bg-red-500"}`}
              />
              <span className="text-lg font-semibold text-white">
                {running ? "Running" : "Stopped"}
              </span>
            </div>
          </div>
          {running && remainingSeconds !== undefined && (
            <div className="border-l border-zinc-700 pl-6">
              <p className="text-xs text-zinc-500">Next AI</p>
              <p className="mt-0.5 font-mono text-lg font-semibold text-zinc-200">
                {display > 0 ? formatTime(display) : "now"}
              </p>
            </div>
          )}
        </div>
        <button
          onClick={onToggle}
          disabled={loading}
          className={`rounded-lg px-4 py-2 text-sm font-medium transition-colors ${
            running
              ? "bg-red-600 text-white hover:bg-red-700"
              : "bg-green-600 text-white hover:bg-green-700"
          } disabled:opacity-50`}
        >
          {loading ? "..." : running ? "Stop" : "Start"}
        </button>
      </div>
    </div>
  )
}
