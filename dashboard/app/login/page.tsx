"use client"

import { useState } from "react"
import { useRouter } from "next/navigation"

export default function Login() {
  const [password, setPassword] = useState("")
  const [error, setError] = useState("")
  const router = useRouter()

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    setError("")

    const resp = await fetch("/api/bot/status")
    if (resp.status === 401) {
      setError("Wrong password")
      return
    }

    sessionStorage.setItem("dashboard_token", "authed")
    router.replace("/")
  }

  return (
    <div className="flex min-h-[60vh] items-center justify-center">
      <form onSubmit={handleSubmit} className="w-full max-w-sm space-y-4">
        <h1 className="text-center text-2xl font-bold text-white">Login</h1>
        <input
          type="password"
          value={password}
          onChange={(e) => setPassword(e.target.value)}
          placeholder="Dashboard password"
          className="w-full rounded-lg border border-zinc-700 bg-zinc-900 px-4 py-2 text-white placeholder-zinc-500 focus:border-zinc-500 focus:outline-none"
          autoFocus
        />
        {error && <p className="text-sm text-red-400">{error}</p>}
        <button
          type="submit"
          className="w-full rounded-lg bg-blue-600 py-2 font-medium text-white hover:bg-blue-700 transition-colors"
        >
          Enter
        </button>
      </form>
    </div>
  )
}
