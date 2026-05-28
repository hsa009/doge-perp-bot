import type { Metadata } from "next"
import AuthGuard from "../components/AuthGuard"
import "./globals.css"

export const metadata: Metadata = {
  title: "DOGE Perp Bot",
  description: "AI-driven DOGE perpetual futures trading bot",
}

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body>
        <AuthGuard>
          <nav className="border-b border-zinc-800 bg-zinc-950 px-6 py-3">
            <div className="mx-auto flex max-w-5xl items-center justify-between">
              <a href="/" className="text-lg font-bold text-white">
                DOGE Perp Bot
              </a>
              <div className="flex gap-4 text-sm text-zinc-400">
                <a href="/" className="hover:text-white transition-colors">Dashboard</a>
                <a href="/trades" className="hover:text-white transition-colors">Trades</a>
                <a href="/logs" className="hover:text-white transition-colors">Logs</a>
              </div>
            </div>
          </nav>
          <main className="mx-auto max-w-5xl px-4 py-6">{children}</main>
        </AuthGuard>
      </body>
    </html>
  )
}
