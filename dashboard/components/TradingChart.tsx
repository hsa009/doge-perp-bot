"use client"

import { useEffect, useRef, useState, useCallback } from "react"
import {
  createChart, CandlestickSeries, LineSeries,
  ColorType, LineStyle, CrosshairMode,
} from "lightweight-charts"
import type { IChartApi, ISeriesApi } from "lightweight-charts"

interface PositionData {
  entry_price: number
  tp_price?: number
  sl_price?: number
  size: number
  leverage?: number
  direction?: string
}

interface Props {
  position: PositionData | null
  coin?: string
}

const HL_INFO = "https://api.hyperliquid.xyz/info"

export default function TradingChart({ position, coin = "DOGE" }: Props) {
  const containerRef = useRef<HTMLDivElement>(null)
  const zoneCanvasRef = useRef<HTMLCanvasElement>(null)
  const chartRef = useRef<IChartApi | null>(null)
  const candleSeriesRef = useRef<ISeriesApi<"Candlestick"> | null>(null)
  const liveLineRef = useRef<ISeriesApi<"Line"> | null>(null)
  const priceLinesRef = useRef<any[]>([])

  const [currentPrice, setCurrentPrice] = useState<number | null>(null)
  const [candles, setCandles] = useState<any[]>([])
  const [hitFlash, setHitFlash] = useState<"tp" | "sl" | null>(null)
  const drawZonesRef = useRef<() => void>(() => {})

  const entryPrice = position?.entry_price
  const tpPrice = position?.tp_price
  const slPrice = position?.sl_price
  const dir = position?.direction

  useEffect(() => {
    const container = containerRef.current
    if (!container) return

    const chart = createChart(container, {
      layout: {
        background: { type: ColorType.Solid, color: "#0a0a0a" },
        textColor: "#9ca3af",
      },
      grid: {
        vertLines: { color: "#1f2937" },
        horzLines: { color: "#1f2937" },
      },
      width: container.clientWidth,
      height: 450,
      crosshair: { mode: CrosshairMode.Normal },
      timeScale: {
        borderColor: "#1f2937",
        timeVisible: true,
        secondsVisible: false,
      },
      rightPriceScale: {
        borderColor: "#1f2937",
        scaleMargins: { top: 0.08, bottom: 0.15 },
      },
      handleScroll: { vertTouchDrag: false },
    })

    const candleSeries = chart.addSeries(CandlestickSeries, {
      upColor: "#22c55e",
      downColor: "#ef4444",
      borderDownColor: "#ef4444",
      borderUpColor: "#22c55e",
      wickDownColor: "#ef4444",
      wickUpColor: "#22c55e",
      priceFormat: { type: "price", precision: 5, minMove: 0.00001 },
    })

    const liveLine = chart.addSeries(LineSeries, {
      color: "#818cf8",
      lineWidth: 1,
      lastValueVisible: false,
      priceLineVisible: false,
      crosshairMarkerVisible: true,
      crosshairMarkerRadius: 4,
      crosshairMarkerBorderColor: "#818cf8",
      crosshairMarkerBackgroundColor: "#0a0a0a",
    })

    chartRef.current = chart
    candleSeriesRef.current = candleSeries
    liveLineRef.current = liveLine

    const ro = new ResizeObserver((entries) => {
      for (const e of entries) {
        chart.applyOptions({ width: e.contentRect.width })
      }
    })
    ro.observe(container)

    chart.subscribeCrosshairMove(() => {
      drawZonesRef.current()
    })

    return () => {
      ro.disconnect()
      chart.remove()
    }
  }, [])

  const drawZones = useCallback(() => {
    const chart = chartRef.current
    const series = candleSeriesRef.current
    const canvas = zoneCanvasRef.current
    if (!chart || !series || !canvas || !entryPrice) {
      canvas?.getContext("2d")?.clearRect(0, 0, canvas.width || 1, canvas.height || 1)
      return
    }

    const timeRange = chart.timeScale().getVisibleRange()
    if (!timeRange) return

    const left = chart.timeScale().timeToCoordinate(timeRange.from as any)
    const right = chart.timeScale().timeToCoordinate(timeRange.to as any)
    const entryY = series.priceToCoordinate(entryPrice)
    if (left == null || right == null || entryY == null) return

    const w = containerRef.current?.clientWidth ?? 0
    const h = containerRef.current?.clientHeight ?? 0
    canvas.width = w
    canvas.height = h
    const ctx = canvas.getContext("2d")
    if (!ctx) return
    ctx.clearRect(0, 0, w, h)

    if (tpPrice) {
      const tpY = series.priceToCoordinate(tpPrice)
      if (tpY != null) {
        ctx.fillStyle = "rgba(34,197,94,0.06)"
        ctx.fillRect(left, Math.min(tpY, entryY), right - left, Math.abs(entryY - tpY))
      }
    }
    if (slPrice) {
      const slY = series.priceToCoordinate(slPrice)
      if (slY != null) {
        ctx.fillStyle = "rgba(239,68,68,0.06)"
        ctx.fillRect(left, Math.min(entryY, slY), right - left, Math.abs(slY - entryY))
      }
    }
  }, [entryPrice, tpPrice, slPrice])

  const fetchCandles = useCallback(async (series: ISeriesApi<"Candlestick"> | null) => {
    try {
      const resp = await fetch(`/api/bot/chart?coin=${coin}&interval=1m&limit=200`)
      const data = await resp.json()
      if (data.candles && data.candles.length) {
        setCandles(data.candles)
        series?.setData(data.candles)
      }
    } catch {}
  }, [coin])

  const fetchPrice = useCallback(async () => {
    try {
      const resp = await fetch(HL_INFO, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ type: "allMids" }),
      })
      const data = await resp.json()
      const exName = coin
      const mid = data?.mids?.[exName]
      if (mid) {
        const px = parseFloat(mid)
        setCurrentPrice(px)

        const liveLine = liveLineRef.current
        if (liveLine) {
          const now = Math.floor(Date.now() / 1000)
          liveLine.update({ time: now as any, value: px })
        }
      }
    } catch {}
  }, [coin])

  useEffect(() => {
    const series = candleSeriesRef.current
    fetchCandles(series)
  }, [fetchCandles])

  useEffect(() => {
    const series = candleSeriesRef.current
    const interval = setInterval(() => fetchCandles(series), 60_000)
    return () => clearInterval(interval)
  }, [fetchCandles])

  useEffect(() => {
    fetchPrice()
    const interval = setInterval(fetchPrice, 2000)
    return () => clearInterval(interval)
  }, [fetchPrice])

  useEffect(() => {
    const chart = chartRef.current
    const series = candleSeriesRef.current
    if (!chart || !series) return

    priceLinesRef.current.forEach((pl) => series.removePriceLine(pl))
    priceLinesRef.current = []

    if (entryPrice) {
      priceLinesRef.current.push(
        series.createPriceLine({
          price: entryPrice,
          color: "#22c55e",
          lineStyle: LineStyle.Dashed,
          lineWidth: 1,
          axisLabelVisible: true,
          title: "Entry",
        })
      )
    }
    if (tpPrice) {
      priceLinesRef.current.push(
        series.createPriceLine({
          price: tpPrice,
          color: "#22c55e",
          lineStyle: LineStyle.Solid,
          lineWidth: 2,
          axisLabelVisible: true,
          title: "TP",
        })
      )
    }
    if (slPrice) {
      priceLinesRef.current.push(
        series.createPriceLine({
          price: slPrice,
          color: "#ef4444",
          lineStyle: LineStyle.Solid,
          lineWidth: 2,
          axisLabelVisible: true,
          title: "SL",
        })
      )
    }
  }, [entryPrice, tpPrice, slPrice])

  useEffect(() => {
    if (!currentPrice) return
    if (tpPrice && currentPrice >= tpPrice) {
      setHitFlash("tp")
      setTimeout(() => setHitFlash(null), 2500)
    }
    if (slPrice && currentPrice <= slPrice) {
      setHitFlash("sl")
      setTimeout(() => setHitFlash(null), 2500)
    }
  }, [currentPrice, tpPrice, slPrice])

  const pnl = currentPrice && entryPrice && dir
    ? (dir === "long" ? (currentPrice - entryPrice) / entryPrice : (entryPrice - currentPrice) / entryPrice) * 100
    : null

  return (
    <div className="relative rounded-xl border border-zinc-800 bg-zinc-950 overflow-hidden">
      <div ref={containerRef} style={{ height: 450 }} />

      <canvas
        ref={zoneCanvasRef}
        className="absolute pointer-events-none"
        style={{ top: 0, left: 0, zIndex: 5 }}
      />

      {currentPrice != null && (
        <div className="absolute top-2 left-3 flex flex-wrap gap-x-4 gap-y-1 text-xs z-10">
          <div className="flex items-center gap-1.5">
            <span className="w-2 h-2 rounded-full bg-indigo-400" />
            <span className="text-zinc-500">Price</span>
            <span className={`font-mono font-semibold ${pnl != null && pnl > 0 ? "text-green-400" : pnl != null && pnl < 0 ? "text-red-400" : "text-white"}`}>
              ${currentPrice.toFixed(5)}
            </span>
          </div>
          {entryPrice && (
            <div className="flex items-center gap-1.5">
              <span className="w-2 h-2 rounded-full bg-green-400" />
              <span className="text-zinc-500">Entry</span>
              <span className="font-mono text-green-400">${entryPrice.toFixed(5)}</span>
            </div>
          )}
          {tpPrice && (
            <div className="flex items-center gap-1.5">
              <span className="w-2 h-2 rounded-full bg-green-500" />
              <span className="text-zinc-500">TP</span>
              <span className="font-mono text-green-500">${tpPrice.toFixed(5)}</span>
            </div>
          )}
          {slPrice && (
            <div className="flex items-center gap-1.5">
              <span className="w-2 h-2 rounded-full bg-red-500" />
              <span className="text-zinc-500">SL</span>
              <span className="font-mono text-red-500">${slPrice.toFixed(5)}</span>
            </div>
          )}
        </div>
      )}

      {pnl != null && (
        <div className="absolute top-2 right-3 text-xs font-mono z-10">
          <span className={pnl >= 0 ? "text-green-400" : "text-red-400"}>
            {pnl >= 0 ? "+" : ""}{pnl.toFixed(2)}%
          </span>
        </div>
      )}

      {hitFlash === "tp" && (
        <div className="absolute inset-0 bg-green-500/10 animate-pulse pointer-events-none z-20" />
      )}
      {hitFlash === "sl" && (
        <div className="absolute inset-0 bg-red-500/10 animate-pulse pointer-events-none z-20" />
      )}

      <div className="absolute bottom-1.5 right-3 text-[10px] text-zinc-700 font-mono z-10">
        {coin} / USD · 1m
      </div>
    </div>
  )
}
