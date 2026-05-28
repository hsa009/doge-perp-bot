"use client"

import { useEffect, useState } from "react"

interface Log {
  id: string
  level: string
  message: string
  created_at: string
}

export default function LogsPage() {
  const [logs, setLogs] = useState<Log[]>([])

  useEffect(() => {
    fetch("/api/logs")
      .then((r) => r.json())
      .then(setLogs)
  }, [])

  const levelColor: Record<string, string> = {
    INFO: "text-blue-400",
    WARN: "text-yellow-400",
    ERROR: "text-red-400",
    CRITICAL: "text-red-400 font-bold",
  }

  return (
    <div className="space-y-4">
      <h1 className="text-xl font-bold text-white">Bot Logs</h1>
      <div className="max-h-[70vh] overflow-y-auto rounded-xl border border-zinc-800 bg-zinc-900">
        {logs.map((log) => (
          <div key={log.id} className="border-b border-zinc-800 px-4 py-2 text-sm">
            <span className="text-zinc-500">
              {new Date(log.created_at).toLocaleTimeString()}
            </span>{" "}
            <span className={levelColor[log.level] || "text-white"}>
              [{log.level}]
            </span>{" "}
            <span className="text-zinc-300">{log.message}</span>
          </div>
        ))}
        {logs.length === 0 && (
          <div className="px-4 py-8 text-center text-zinc-500">No logs yet</div>
        )}
      </div>
    </div>
  )
}
