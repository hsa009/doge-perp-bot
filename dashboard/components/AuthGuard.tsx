"use client"

import { useEffect, useState } from "react"
import { useRouter, usePathname } from "next/navigation"

export default function AuthGuard({ children }: { children: React.ReactNode }) {
  const router = useRouter()
  const pathname = usePathname()
  const [authed, setAuthed] = useState(false)

  useEffect(() => {
    const token = sessionStorage.getItem("dashboard_token")
    if (token === "authed") {
      setAuthed(true)
    } else if (pathname !== "/login") {
      router.replace("/login")
    }
  }, [pathname, router])

  if (!authed && pathname !== "/login") return null

  return <>{children}</>
}
