import { useEffect, useRef, useState } from 'react'

/** 自绘 Canvas 实体图(亮色):
 *  白底画布 · 彩色填充节点(度数决定大小)· 贝塞尔曲线边(秘密=紫虚线)
 *  滚轮缩放 · 拖拽平移 · 悬停高亮邻域 · 点击选中 · 图例。 */

const TYPE_COLOR: Record<string, [string, string]> = {
  // [填充底色, 描边主色]
  Character: ['#dcebf9', '#3f74ad'],
  Faction: ['#f0e6f5', '#92519e'],
  Location: ['#e0f2e6', '#238551'],
  Artifact: ['#fbeed3', '#a86e10'],
  Item: ['#eceef2', '#69707d'],
  Power: ['#e9e4fa', '#7c4dbd'],
}
const TYPE_SHAPE: Record<string, 'circle' | 'rect' | 'hex' | 'diamond'> = {
  Character: 'circle', Faction: 'rect', Location: 'hex', Artifact: 'diamond', Item: 'diamond', Power: 'hex',
}

interface PNode { key: string; name: string; type: string; x: number; y: number; vx: number; vy: number; deg: number }
interface Edge { source: string; target: string; type: string; secret: boolean }

export default function GraphCanvas({ nodes, edges, onPick, focus }: {
  nodes: { key: string; name: string; type: string }[]
  edges: Edge[]
  onPick?: (key: string) => void
  focus?: string | null
}) {
  const cvs = useRef<HTMLCanvasElement>(null)
  const world = useRef<{ nodes: PNode[]; edges: Edge[] }>({ nodes: [], edges: [] })
  const view = useRef({ scale: 1, ox: 0, oy: 0 })
  const hover = useRef<string | null>(null)
  const drag = useRef<{ on: boolean; x: number; y: number }>({ on: false, x: 0, y: 0 })
  const [, force] = useState(0)

  const W = 900, H = 560

  useEffect(() => {
    const deg: Record<string, number> = {}
    for (const e of edges) { deg[e.source] = (deg[e.source] || 0) + 1; deg[e.target] = (deg[e.target] || 0) + 1 }
    const ns: PNode[] = nodes.map((n, i) => {
      const a = (i / Math.max(1, nodes.length)) * Math.PI * 2
      return { ...n, deg: deg[n.key] || 0, x: W / 2 + Math.cos(a) * (W / 3.6), y: H / 2 + Math.sin(a) * (H / 3.4), vx: 0, vy: 0 }
    })
    const byKey = new Map(ns.map((n) => [n.key, n]))
    const es = edges.filter((e) => byKey.has(e.source) && byKey.has(e.target))
    for (let it = 0; it < 220; it++) {
      for (let i = 0; i < ns.length; i++) for (let j = i + 1; j < ns.length; j++) {
        const a = ns[i], b = ns[j]
        const dx = b.x - a.x, dy = b.y - a.y
        const d2 = Math.max(64, dx * dx + dy * dy), d = Math.sqrt(d2), f = 3000 / d2
        a.vx -= (dx / d) * f; a.vy -= (dy / d) * f; b.vx += (dx / d) * f; b.vy += (dy / d) * f
      }
      for (const e of es) {
        const a = byKey.get(e.source)!, b = byKey.get(e.target)!
        const dx = b.x - a.x, dy = b.y - a.y, d = Math.max(1, Math.hypot(dx, dy)), f = (d - 150) * 0.022
        a.vx += (dx / d) * f; a.vy += (dy / d) * f; b.vx -= (dx / d) * f; b.vy -= (dy / d) * f
      }
      for (const n of ns) {
        n.vx += (W / 2 - n.x) * 0.0022; n.vy += (H / 2 - n.y) * 0.0022
        n.x += Math.max(-9, Math.min(9, n.vx)); n.y += Math.max(-9, Math.min(9, n.vy))
        n.vx *= 0.82; n.vy *= 0.82
      }
    }
    world.current = { nodes: ns, edges: es }
    view.current = { scale: 1, ox: 0, oy: 0 }
    draw()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [nodes, edges])

  useEffect(() => { draw() /* eslint-disable-next-line */ }, [focus])

  function radius(n: PNode) { return 10 + Math.min(12, n.deg * 1.6) }

  function toWorld(px: number, py: number) {
    const { scale, ox, oy } = view.current
    return { x: (px - ox) / scale, y: (py - oy) / scale }
  }

  function draw() {
    const cv = cvs.current
    if (!cv) return
    const ctx = cv.getContext('2d')!
    const { scale, ox, oy } = view.current
    const ns = world.current.nodes, es = world.current.edges
    const hi = hover.current || focus || null
    const neighbors = new Set<string>()
    if (hi) {
      neighbors.add(hi)
      for (const e of es) { if (e.source === hi) neighbors.add(e.target); if (e.target === hi) neighbors.add(e.source) }
    }
    ctx.clearRect(0, 0, W, H)
    ctx.save()
    ctx.translate(ox, oy); ctx.scale(scale, scale)

    // 网格底纹
    ctx.strokeStyle = 'rgba(59,127,196,.05)'; ctx.lineWidth = 1
    const step = 40
    for (let gx = 0; gx < W; gx += step) { ctx.beginPath(); ctx.moveTo(gx, 0); ctx.lineTo(gx, H); ctx.stroke() }
    for (let gy = 0; gy < H; gy += step) { ctx.beginPath(); ctx.moveTo(0, gy); ctx.lineTo(W, gy); ctx.stroke() }

    // 边(贝塞尔)
    for (const e of es) {
      const a = ns.find((n) => n.key === e.source), b = ns.find((n) => n.key === e.target)
      if (!a || !b) continue
      const dimmed = hi && !(e.source === hi || e.target === hi)
      const mx = (a.x + b.x) / 2 + (b.y - a.y) * 0.08, my = (a.y + b.y) / 2 - (b.x - a.x) * 0.08
      ctx.strokeStyle = e.secret ? `rgba(146,81,158,${dimmed ? 0.18 : 0.6})` : `rgba(105,112,125,${dimmed ? 0.12 : 0.34})`
      ctx.lineWidth = dimmed ? 1 : 1.4
      ctx.setLineDash(e.secret ? [6, 4] : [])
      ctx.beginPath(); ctx.moveTo(a.x, a.y); ctx.quadraticCurveTo(mx, my, b.x, b.y); ctx.stroke()
      ctx.setLineDash([])
      if (!dimmed && e.type) {
        ctx.fillStyle = e.secret ? '#92519e' : '#8a91a0'
        ctx.font = '10px ui-monospace'
        ctx.textAlign = 'center'
        ctx.fillText(e.type, mx, my - 4)
        ctx.textAlign = 'left'
      }
    }

    // 节点
    for (const n of ns) {
      const [fill, stroke] = TYPE_COLOR[n.type] || ['#eceef2', '#69707d']
      const r = radius(n)
      const dimmed = hi && !neighbors.has(n.key)
      const isFocus = n.key === focus
      ctx.globalAlpha = dimmed ? 0.3 : 1
      ctx.shadowColor = 'rgba(16,24,40,.14)'; ctx.shadowBlur = isFocus || hi === n.key ? 14 : 6
      ctx.shadowOffsetY = 2
      ctx.fillStyle = fill; ctx.strokeStyle = isFocus ? '#1f2430' : stroke
      ctx.lineWidth = isFocus ? 2.5 : 1.6
      ctx.beginPath()
      const shape = TYPE_SHAPE[n.type] || 'circle'
      if (shape === 'rect') { const w = r * 1.1, h = r * 0.85; if (ctx.roundRect) ctx.roundRect(n.x - w, n.y - h, w * 2, h * 2, 5); else ctx.rect(n.x - w, n.y - h, w * 2, h * 2) }
      else if (shape === 'diamond') { ctx.moveTo(n.x, n.y - r * 1.1); ctx.lineTo(n.x + r * 1.1, n.y); ctx.lineTo(n.x, n.y + r * 1.1); ctx.lineTo(n.x - r * 1.1, n.y) }
      else if (shape === 'hex') for (let i = 0; i < 6; i++) { const a = (Math.PI / 3) * i - Math.PI / 6; const px = n.x + r * Math.cos(a), py = n.y + r * Math.sin(a); i ? ctx.lineTo(px, py) : ctx.moveTo(px, py) }
      else ctx.arc(n.x, n.y, r, 0, Math.PI * 2)
      ctx.closePath(); ctx.fill(); ctx.stroke()
      ctx.shadowColor = 'transparent'; ctx.shadowBlur = 0; ctx.shadowOffsetY = 0
      // 度数角标
      if (n.deg > 0) {
        ctx.fillStyle = stroke
        ctx.beginPath(); ctx.arc(n.x + r * 0.85, n.y - r * 0.85, 7.5, 0, Math.PI * 2)
        ctx.fill()
        ctx.fillStyle = '#fff'; ctx.font = 'bold 9px ui-monospace'; ctx.textAlign = 'center'; ctx.textBaseline = 'middle'
        ctx.fillText(String(n.deg), n.x + r * 0.85, n.y - r * 0.85 + 0.5)
        ctx.textAlign = 'left'; ctx.textBaseline = 'alphabetic'
      }
      // 标签(白描边保证可读)
      ctx.font = `${isFocus ? 'bold ' : ''}11.5px -apple-system, "PingFang SC"`
      ctx.textAlign = 'center'
      ctx.lineWidth = 3; ctx.strokeStyle = 'rgba(255,255,255,.92)'
      ctx.strokeText(n.name, n.x, n.y + r + 14)
      ctx.fillStyle = '#1f2430'
      ctx.fillText(n.name, n.x, n.y + r + 14)
      ctx.textAlign = 'left'
      ctx.globalAlpha = 1
    }
    ctx.restore()
  }

  function localXY(ev: React.MouseEvent) {
    const rect = (ev.target as HTMLCanvasElement).getBoundingClientRect()
    return { x: ((ev.clientX - rect.left) / rect.width) * W, y: ((ev.clientY - rect.top) / rect.height) * H }
  }

  return (
    <div>
      <canvas
        ref={cvs} width={W} height={H}
        style={{ width: '100%', border: '1px solid var(--line)', borderRadius: 10, background: 'var(--panel)', cursor: drag.current.on ? 'grabbing' : 'pointer', display: 'block' }}
        onMouseDown={(ev) => { const { x, y } = localXY(ev); drag.current = { on: true, x, y } }}
        onMouseUp={() => { drag.current.on = false }}
        onMouseLeave={() => { drag.current.on = false; if (hover.current) { hover.current = null; draw() } }}
        onMouseMove={(ev) => {
          const { x, y } = localXY(ev)
          if (drag.current.on) {
            view.current.ox += x - drag.current.x; view.current.oy += y - drag.current.y
            drag.current = { on: true, x, y }; draw(); return
          }
          const w = toWorld(x, y)
          const hit = world.current.nodes.find((n) => Math.hypot(n.x - w.x, n.y - w.y) < radius(n) + 4)
          const h = hit?.key || null
          if (h !== hover.current) { hover.current = h; draw() }
        }}
        onClick={(ev) => {
          const { x, y } = localXY(ev)
          const w = toWorld(x, y)
          const hit = world.current.nodes.find((n) => Math.hypot(n.x - w.x, n.y - w.y) < radius(n) + 4)
          if (hit && onPick) onPick(hit.key)
        }}
        onWheel={(ev) => {
          ev.preventDefault()
          const { x, y } = localXY(ev)
          const k = ev.deltaY < 0 ? 1.12 : 0.89
          const v = view.current
          v.ox = x - (x - v.ox) * k; v.oy = y - (y - v.oy) * k
          v.scale = Math.max(0.4, Math.min(3, v.scale * k))
          draw(); force((n) => n + 1)
        }}
      />
      <div style={{ display: 'flex', justifyContent: 'space-between', marginTop: 8 }}>
        <div className="legend">
          {Object.entries(TYPE_COLOR).slice(0, 5).map(([t, [, c]]) => (
            <span className="k" key={t}><span className="dot" style={{ background: c }} />{t}</span>
          ))}
          <span className="k"><svg width="22" height="6"><line x1="0" y1="3" x2="22" y2="3" stroke="#92519e" strokeDasharray="5 3" strokeWidth="1.6" /></svg>秘密边</span>
        </div>
        <span style={{ fontSize: 11.5, color: 'var(--muted)' }}>滚轮缩放 · 拖拽平移 · 悬停聚焦邻域 · 角标=连接数</span>
      </div>
    </div>
  )
}
