"use client"

interface Props {
  running: boolean
  onToggle: () => void
  loading: boolean
}

export default function StatusCard({ running, onToggle, loading }: Props) {
  return (
    <div className="rounded-xl border border-zinc-800 bg-zinc-900 p-6">
      <div className="flex items-center justify-between">
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
