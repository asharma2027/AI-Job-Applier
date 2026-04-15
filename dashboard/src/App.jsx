import { useState, useEffect, useCallback, useRef } from 'react'
import './index.css'

const API = 'http://localhost:8000/api'

// ── Hooks ──────────────────────────────────────────────────────────────
function useApi(url, deps = []) {
  const [data, setData] = useState(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)
  const fetch_ = useCallback(async () => {
    setLoading(true)
    try {
      const r = await fetch(url)
      if (!r.ok) throw new Error(`HTTP ${r.status}`)
      setData(await r.json())
      setError(null)
    } catch (e) { setError(e.message) }
    finally { setLoading(false) }
  }, [url])
  useEffect(() => { fetch_() }, [...deps, fetch_])
  return { data, loading, error, refetch: fetch_ }
}

// ── Toast ───────────────────────────────────────────────────────────────
function Toast({ toasts }) {
  return (
    <div className="toast-container">
      {toasts.map(t => <div key={t.id} className={`toast toast-${t.type}`}>{t.msg}</div>)}
    </div>
  )
}
function useToast() {
  const [toasts, setToasts] = useState([])
  const add = (msg, type = 'success') => {
    const id = Date.now()
    setToasts(p => [...p, { id, msg, type }])
    setTimeout(() => setToasts(p => p.filter(t => t.id !== id)), 3500)
  }
  return { toasts, toast: add }
}

// ── Desktop + Audio Notification ────────────────────────────────────────
function useNotifications(queueCount, toast) {
  const prevCount = useRef(queueCount)
  const audioCtx = useRef(null)

  useEffect(() => {
    if (queueCount > prevCount.current && prevCount.current !== null) {
      const newItems = queueCount - prevCount.current
      toast(`${newItems} new cover letter upload${newItems > 1 ? 's' : ''} pending`, 'success')

      // Desktop notification
      if ('Notification' in window && Notification.permission === 'granted') {
        new Notification('Cover Letter Needed', {
          body: `${newItems} job${newItems > 1 ? 's' : ''} require${newItems === 1 ? 's' : ''} a cover letter upload`,
          icon: '/favicon.svg',
        })
      } else if ('Notification' in window && Notification.permission === 'default') {
        Notification.requestPermission()
      }

      // Audio beep
      try {
        if (!audioCtx.current) audioCtx.current = new (window.AudioContext || window.webkitAudioContext)()
        const ctx = audioCtx.current
        const osc = ctx.createOscillator()
        const gain = ctx.createGain()
        osc.connect(gain)
        gain.connect(ctx.destination)
        osc.frequency.value = 880
        osc.type = 'sine'
        gain.gain.value = 0.15
        osc.start()
        gain.gain.exponentialRampToValueAtTime(0.001, ctx.currentTime + 0.4)
        osc.stop(ctx.currentTime + 0.4)
      } catch {}
    }
    prevCount.current = queueCount
  }, [queueCount, toast])
}

// ── Usage Gauge (persistent, all tabs) ──────────────────────────────────
function UsageGauge({ onClick }) {
  const [data, setData] = useState(null)

  useEffect(() => {
    const poll = async () => {
      try {
        const r = await fetch(`${API}/usage/gauge`)
        if (r.ok) setData(await r.json())
      } catch {}
    }
    poll()
    const interval = setInterval(poll, 15000)
    return () => clearInterval(interval)
  }, [])

  if (!data || (data.total_limit_today === 0 && data.monthly_budget_usd === 0)) return null

  const pct = data.pct_used || 0
  const color = pct >= 80 ? 'var(--red)' : pct >= 50 ? 'var(--amber)' : 'var(--green)'
  const models = data.models || {}

  return (
    <div className="usage-gauge-bar-wrap" onClick={onClick} title="Click to view API usage details">
      <div className="usage-gauge-label">
        <span style={{ fontSize: 14 }}>📊</span>
        <span>API</span>
        <span style={{ color: 'var(--text-primary)', fontFamily: 'var(--mono)' }}>
          {data.total_requests_today}/{data.total_limit_today}
        </span>
      </div>
      <div className="usage-gauge-track">
        <div className="usage-gauge-fill" style={{ width: `${Math.min(pct, 100)}%`, background: color }} />
      </div>
      <div className="usage-gauge-models">
        {Object.entries(models).map(([model, info]) => {
          const mPct = info.pct || 0
          const mColor = mPct >= 80 ? 'var(--red)' : mPct >= 50 ? 'var(--amber)' : 'var(--green)'
          const shortName = model.replace('gemini-2.5-', '').replace('gemini-', '')
          return (
            <span key={model} className="usage-gauge-model">
              <span className="usage-gauge-model-dot" style={{ background: mColor }} />
              {shortName} {info.requests}/{info.limit || '∞'}
            </span>
          )
        })}
      </div>
      {data.plan_type === 'pay_as_you_go' && data.monthly_cost_usd > 0 && (
        <span style={{ fontSize: 11, color: 'var(--amber)', fontWeight: 600 }}>
          ${data.monthly_cost_usd.toFixed(2)} this month
        </span>
      )}
    </div>
  )
}

// ── Sidebar ──────────────────────────────────────────────────────────────
function Sidebar({ page, setPage, queueCount }) {
  const items = [
    { id: 'source', label: 'Source Jobs', icon: '🔍' },
    { id: 'queue', label: 'Pending Uploads', icon: '📝', badge: queueCount },
    { id: 'jobs', label: 'All Jobs', icon: '💼' },
    { id: 'activity', label: 'Activity Log', icon: '📡' },
    { id: 'samples', label: 'CL Samples', icon: '✉️' },
    { id: 'profile', label: 'Profile', icon: '👤' },
    { id: 'memory', label: 'AI Memory', icon: '🧠' },
    { id: 'usage', label: 'API Usage', icon: '📈' },
    { id: 'stats', label: 'Overview', icon: '📊' },
    { id: 'settings', label: 'Settings', icon: '⚙️' },
  ]
  return (
    <aside className="sidebar">
      <div className="sidebar-logo">
        <div className="logo-icon">🤖</div>
        <div><div className="logo-text">Job Applier</div><div className="logo-sub">Agent</div></div>
      </div>
      <div className="nav-section">
        <div className="nav-label">Navigation</div>
        {items.map(item => (
          <button key={item.id} className={`nav-item ${page === item.id ? 'active' : ''}`} onClick={() => setPage(item.id)}>
            <span>{item.icon}</span><span>{item.label}</span>
            {item.badge > 0 && <span className="badge">{item.badge}</span>}
          </button>
        ))}
      </div>
    </aside>
  )
}

function Status({ s }) {
  return <span className={`status status-${s?.replace(/ /g, '_')}`}>{s?.replace(/_/g, ' ')}</span>
}

// ── Stop helper ─────────────────────────────────────────────────────────
async function stopAgentTask(taskId, toast) {
  try {
    const r = await fetch(`${API}/agents/stop/${taskId}`, { method: 'POST' })
    if (r.ok) toast(`Stopped: ${taskId}`, 'success')
    else toast('Could not stop task', 'error')
  } catch (e) { toast('Error stopping: ' + e.message, 'error') }
}

// ── Source Jobs Page ─────────────────────────────────────────────────────
const PLATFORM_META = {
  handshake: {
    label: 'Handshake',
    icon: '🤝',
    desc: 'UChicago SSO — internships from your university portal',
    enabled: true,
    color: 'var(--accent)',
  },
  linkedin: {
    label: 'LinkedIn',
    icon: '💼',
    desc: 'Coming soon — requires LinkedIn session cookies',
    enabled: false,
    color: 'var(--text-muted)',
  },
  indeed: {
    label: 'Indeed',
    icon: '🔎',
    desc: 'Coming soon — public board scraping',
    enabled: false,
    color: 'var(--text-muted)',
  },
  wellfound: {
    label: 'WellFound',
    icon: '🚀',
    desc: 'Coming soon — startup job board',
    enabled: false,
    color: 'var(--text-muted)',
  },
  glassdoor: {
    label: 'Glassdoor',
    icon: '🏢',
    desc: 'Coming soon — public board scraping',
    enabled: false,
    color: 'var(--text-muted)',
  },
}

function SourcePage({ toast }) {
  const [running, setRunning] = useState({})
  const { data: statusData, refetch: refetchStatus } = useApi(`${API}/source/status`)

  useEffect(() => {
    if (!statusData) return
    const serverRunning = statusData.running || []
    setRunning(prev => {
      const next = { ...prev }
      Object.keys(PLATFORM_META).forEach(p => {
        if (serverRunning.includes(p)) next[p] = true
      })
      serverRunning.forEach(p => { next[p] = true })
      Object.keys(next).forEach(p => {
        if (!serverRunning.includes(p) && next[p] === true) next[p] = false
      })
      return next
    })
  }, [statusData])

  useEffect(() => {
    const anyRunning = Object.values(running).some(Boolean)
    if (!anyRunning) return
    const interval = setInterval(refetchStatus, 2500)
    return () => clearInterval(interval)
  }, [running, refetchStatus])

  const triggerScrape = async (platform) => {
    if (running[platform]) return
    setRunning(p => ({ ...p, [platform]: true }))
    try {
      const r = await fetch(`${API}/source/${platform}`, { method: 'POST' })
      const data = await r.json()
      if (!r.ok) {
        toast(data.detail || 'Failed to start scrape', 'error')
        setRunning(p => ({ ...p, [platform]: false }))
        return
      }
      toast(`Scraping ${PLATFORM_META[platform]?.label || platform}… watch the Activity Log`, 'success')
      const poll = setInterval(async () => {
        try {
          const sr = await fetch(`${API}/source/status`)
          const sd = await sr.json()
          if (!sd.running.includes(platform)) {
            clearInterval(poll)
            setRunning(p => ({ ...p, [platform]: false }))
            toast(`${PLATFORM_META[platform]?.label || platform} scrape finished — check All Jobs`, 'success')
          }
        } catch { clearInterval(poll) }
      }, 2500)
    } catch (e) {
      toast('Error: ' + e.message, 'error')
      setRunning(p => ({ ...p, [platform]: false }))
    }
  }

  return (
    <div>
      <div className="page-header">
        <div>
          <div className="page-title">Source Jobs</div>
          <div className="page-subtitle">
            Click a platform button to start scraping. Each scrape runs in the background — watch the Activity Log for live progress.
          </div>
        </div>
      </div>

      <div className="page-content">
        <div style={{
          display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: 16, marginBottom: 32,
          padding: 20, background: 'var(--surface)', borderRadius: 12, border: '1px solid var(--border)',
        }}>
          {[
            { step: '1', label: 'Source', desc: 'Scrape a platform to find internship listings', active: true },
            { step: '2', label: 'Fill Form', desc: 'AI fills every field — stops before Submit', active: false },
            { step: '3', label: 'Review & Confirm', desc: 'Open the filled form, click Submit yourself, then confirm in the dashboard', active: false },
          ].map(s => (
            <div key={s.step} style={{ textAlign: 'center', opacity: s.active ? 1 : 0.45 }}>
              <div style={{
                width: 36, height: 36, borderRadius: '50%', margin: '0 auto 8px',
                background: s.active ? 'var(--accent)' : 'var(--border)',
                display: 'flex', alignItems: 'center', justifyContent: 'center',
                fontWeight: 700, fontSize: 15, color: s.active ? '#fff' : 'var(--text-muted)',
              }}>{s.step}</div>
              <div style={{ fontWeight: 600, fontSize: 14, marginBottom: 4 }}>{s.label}</div>
              <div style={{ fontSize: 12, color: 'var(--text-muted)' }}>{s.desc}</div>
            </div>
          ))}
        </div>

        <h3 style={{ marginTop: 0, marginBottom: 16, fontSize: 15 }}>Choose a platform to scrape</h3>
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(280px, 1fr))', gap: 16 }}>
          {Object.entries(PLATFORM_META).map(([id, meta]) => {
            const isRunning = !!running[id]
            return (
              <div key={id} className="card" style={{
                padding: 24, display: 'flex', flexDirection: 'column', gap: 12,
                opacity: meta.enabled ? 1 : 0.55,
                borderLeft: `3px solid ${meta.enabled ? meta.color : 'var(--border)'}`,
              }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
                  <span style={{ fontSize: 28 }}>{meta.icon}</span>
                  <div>
                    <div style={{ fontWeight: 700, fontSize: 15 }}>{meta.label}</div>
                    {!meta.enabled && <span className="tag tag-muted" style={{ fontSize: 11 }}>Coming soon</span>}
                  </div>
                </div>
                <div style={{ fontSize: 13, color: 'var(--text-muted)', lineHeight: 1.5 }}>{meta.desc}</div>
                <div style={{ marginTop: 'auto', display: 'flex', gap: 8 }}>
                  <button
                    className={`btn ${meta.enabled ? 'btn-accent' : 'btn-ghost'}`}
                    disabled={!meta.enabled || isRunning}
                    onClick={() => triggerScrape(id)}
                    style={{ flex: 1 }}
                  >
                    {isRunning
                      ? <><span className="spin" style={{ display: 'inline-block', marginRight: 6 }}>⚙️</span>Scraping…</>
                      : `Scrape ${meta.label}`
                    }
                  </button>
                  {isRunning && (
                    <button className="btn-stop" onClick={() => stopAgentTask(`source_${id}`, toast)}>
                      Stop
                    </button>
                  )}
                </div>
              </div>
            )
          })}
        </div>

        <div style={{
          marginTop: 24, padding: 16, background: 'var(--surface)', borderRadius: 10,
          border: '1px solid var(--border)', fontSize: 13, color: 'var(--text-muted)', lineHeight: 1.6,
        }}>
          <strong style={{ color: 'var(--text-primary)' }}>UChicago SSO + Duo Mobile:</strong> When scraping Handshake,
          the browser will navigate to the UChicago SSO page, enter your credentials, and wait on the Duo screen.{' '}
          <strong style={{ color: 'var(--text-primary)' }}>Approve the push notification on your phone</strong> — the agent
          continues automatically once approved. This can take up to 3 minutes. Watch the Activity Log for updates.
        </div>
      </div>
    </div>
  )
}

// ── Overview Page ────────────────────────────────────────────────────────
function OverviewPage() {
  const { data, loading, refetch } = useApi(`${API}/stats`)
  if (loading) return <div className="page-content empty"><div className="empty-icon spin">⚙️</div></div>
  if (!data) return null
  const cards = [
    { label: 'Total Sourced', value: data.total_sourced },
    { label: 'Analyzed', value: data.total_analyzed },
    { label: 'Pending CL Upload', value: data.pending_cl_upload, cls: 'amber' },
    { label: 'Queued', value: data.total_queued, cls: 'accent' },
    { label: 'Applied', value: data.total_applied, cls: 'green' },
    { label: 'Failed', value: data.total_failed, cls: 'red' },
    { label: 'Skipped', value: data.total_skipped },
  ]
  return (
    <div>
      <div className="page-header">
        <div><div className="page-title">Overview</div><div className="page-subtitle">Pipeline status at a glance</div></div>
        <button className="btn btn-ghost" onClick={refetch}>↻ Refresh</button>
      </div>
      <div className="page-content">
        <div className="stats-grid">
          {cards.map(c => (
            <div key={c.label} className={`stat-card ${c.cls || ''}`}>
              <div className="stat-value">{c.value ?? 0}</div>
              <div className="stat-label">{c.label}</div>
            </div>
          ))}
        </div>
      </div>
    </div>
  )
}

// ── Screenshot Modal ─────────────────────────────────────────────────────
function ScreenshotModal({ jobId, onClose }) {
  const { data, loading } = useApi(`${API}/jobs/${jobId}/screenshots`)
  const screenshots = data?.screenshots || []
  return (
    <div className="modal-overlay" onClick={onClose}>
      <div className="modal" onClick={e => e.stopPropagation()} style={{ maxWidth: 900, width: '90%' }}>
        <div className="modal-header">
          <h3>Application Screenshots — Job #{jobId}</h3>
          <button className="btn btn-ghost" onClick={onClose}>✕</button>
        </div>
        {loading ? <div className="empty"><div className="empty-icon spin">⚙️</div></div> :
          screenshots.length === 0
            ? <div className="empty"><p>No screenshots captured yet.</p></div>
            : <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(260px, 1fr))', gap: 16, padding: 24 }}>
                {screenshots.map((path, i) => (
                  <div key={i} style={{ background: 'var(--surface)', borderRadius: 12, overflow: 'hidden', border: '1px solid var(--border)' }}>
                    <img
                      src={`${API.replace('/api', '')}/api/screenshots/view?path=${encodeURIComponent(path)}`}
                      alt={`Page ${i + 1}`}
                      style={{ width: '100%', display: 'block' }}
                    />
                    <div style={{ padding: '8px 12px', fontSize: 12, color: 'var(--text-muted)' }}>
                      Page {i + 1} — {path.split('/').pop()}
                    </div>
                  </div>
                ))}
              </div>
        }
      </div>
    </div>
  )
}

// ── Flag Mistake Modal ────────────────────────────────────────────────────
function FlagMistakeModal({ onClose, toast }) {
  const [agent, setAgent] = useState('analyzer')
  const [description, setDescription] = useState('')
  const [correction, setCorrection] = useState('')
  const [exampleBad, setExampleBad] = useState('')
  const [severity, setSeverity] = useState('medium')
  const [saving, setSaving] = useState(false)

  const submit = async () => {
    if (!description.trim() || !correction.trim()) return
    setSaving(true)
    try {
      const r = await fetch(`${API}/memory`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ agent, description, correction, example_bad: exampleBad, severity }),
      })
      if (!r.ok) throw new Error('Failed')
      toast('Rule saved — AI will follow this from now on', 'success')
      onClose()
    } catch (e) { toast('Error: ' + e.message, 'error') }
    setSaving(false)
  }

  return (
    <div className="modal-overlay" onClick={onClose}>
      <div className="modal" onClick={e => e.stopPropagation()} style={{ maxWidth: 560 }}>
        <div className="modal-header">
          <h3>Flag an AI Mistake</h3>
          <button className="btn btn-ghost" onClick={onClose}>✕</button>
        </div>
        <div style={{ padding: 24, display: 'flex', flexDirection: 'column', gap: 16 }}>
          <p style={{ fontSize: 13, color: 'var(--text-muted)', margin: 0 }}>
            Describe what the AI did wrong. This will be injected into every future prompt for that agent.
          </p>
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12 }}>
            <div>
              <label className="field-label">Agent</label>
              <select className="field-select" value={agent} onChange={e => setAgent(e.target.value)}>
                <option value="analyzer">Analyzer</option>
                <option value="executor">Executor / Form Filler</option>
                <option value="sourcer">Sourcer</option>
              </select>
            </div>
            <div>
              <label className="field-label">Severity</label>
              <select className="field-select" value={severity} onChange={e => setSeverity(e.target.value)}>
                <option value="low">Low (note)</option>
                <option value="medium">Medium (important)</option>
                <option value="high">High (critical)</option>
              </select>
            </div>
          </div>
          <div>
            <label className="field-label">What went wrong?</label>
            <textarea className="field-textarea" rows={2} value={description} onChange={e => setDescription(e.target.value)}
              placeholder="e.g. It selected 'finance' resume for a software engineering role" />
          </div>
          <div>
            <label className="field-label">Example of the mistake (optional)</label>
            <textarea className="field-textarea" rows={2} value={exampleBad} onChange={e => setExampleBad(e.target.value)}
              placeholder="Paste the incorrect output here" />
          </div>
          <div>
            <label className="field-label">What should it do instead?</label>
            <textarea className="field-textarea" rows={2} value={correction} onChange={e => setCorrection(e.target.value)}
              placeholder="e.g. Use 'tech' resume for any software/engineering/data roles" />
          </div>
          <div style={{ display: 'flex', justifyContent: 'flex-end', gap: 8 }}>
            <button className="btn btn-ghost" onClick={onClose}>Cancel</button>
            <button className="btn btn-success" disabled={saving || !description || !correction} onClick={submit}>
              {saving ? '...' : 'Save Rule'}
            </button>
          </div>
        </div>
      </div>
    </div>
  )
}

// ── Pending Cover Letter Upload Queue ────────────────────────────────────
function QueuePage({ onUpdate, toast }) {
  const { data: items, loading, refetch } = useApi(`${API}/queue`)
  const [selected, setSelected] = useState(null)
  const [saving, setSaving] = useState(false)
  const [showFlag, setShowFlag] = useState(false)
  const [copied, setCopied] = useState(false)

  const copyPrompt = async () => {
    if (!selected?.prompt_content) { toast('No prompt available', 'error'); return }
    await navigator.clipboard.writeText(selected.prompt_content)
    setCopied(true)
    toast('Prompt copied to clipboard', 'success')
    setTimeout(() => setCopied(false), 2000)
  }

  const handleAction = async (action) => {
    if (!selected) return
    setSaving(true)
    try {
      const r = await fetch(`${API}/queue/${selected.id}`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ action }),
      })
      if (!r.ok) throw new Error('Failed')
      toast(action === 'done' ? 'Marked as done — job queued for filling' : 'Skipped', action === 'done' ? 'success' : 'error')
      setSelected(null); refetch(); onUpdate()
    } catch (e) { toast('Error: ' + e.message, 'error') }
    setSaving(false)
  }

  if (loading) return <div className="page-content empty"><div className="empty-icon spin">⚙️</div></div>
  const list = items || []

  return (
    <div>
      <div className="page-header">
        <div>
          <div className="page-title">Pending Cover Letter Uploads</div>
          <div className="page-subtitle">{list.length} job{list.length !== 1 ? 's' : ''} need a cover letter uploaded</div>
        </div>
        <div style={{ display: 'flex', gap: 8 }}>
          <button className="btn btn-ghost" onClick={() => setShowFlag(true)}>Flag AI Mistake</button>
          <button className="btn btn-ghost" onClick={refetch}>↻ Refresh</button>
        </div>
      </div>

      <div className="page-content">
        {list.length === 0 ? (
          <div className="empty">
            <div className="empty-icon">✨</div>
            <h3>No pending uploads</h3>
            <p>When a job requires a cover letter, it will appear here with a ready-to-copy prompt.</p>
          </div>
        ) : (
          <div style={{ display: 'grid', gridTemplateColumns: selected ? '340px 1fr' : '1fr', gap: 24, alignItems: 'start' }}>
            <div className="queue-list">
              {list.map(item => (
                <div key={item.id} className={`queue-card ${selected?.id === item.id ? 'selected' : ''}`}
                  onClick={() => { setSelected(item); setCopied(false) }}>
                  <div className="queue-card-header">
                    <div>
                      <div className="queue-job-title">{item.job_title}</div>
                      <div className="queue-company">{item.job_company}</div>
                    </div>
                    <span className="tag tag-amber">Pending Upload</span>
                  </div>
                  <div className="queue-meta">
                    <span className="tag tag-muted">Cover Letter</span>
                    <span className="tag tag-purple">{new Date(item.created_at).toLocaleDateString()}</span>
                  </div>
                </div>
              ))}
            </div>

            {selected && (
              <div className="editor-pane">
                <div className="editor-toolbar">
                  <strong style={{ fontSize: 14, color: 'var(--text-primary)' }}>
                    {selected.job_title} @ {selected.job_company}
                  </strong>
                  <div style={{ display: 'flex', gap: 8, marginLeft: 'auto' }}>
                    <a href={selected.job_url} target="_blank" rel="noreferrer"
                      className="btn btn-accent" style={{ fontSize: 13, padding: '6px 14px', textDecoration: 'none' }}>
                      Open Application ↗
                    </a>
                  </div>
                </div>

                {/* Prompt section */}
                <div style={{ padding: 24, borderBottom: '1px solid var(--border)' }}>
                  <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 12 }}>
                    <div style={{ fontWeight: 600, fontSize: 14, color: 'var(--text-primary)' }}>
                      Ready-to-Copy Prompt
                    </div>
                    <button className={`btn ${copied ? 'btn-success' : 'btn-accent'}`}
                      style={{ fontSize: 13, padding: '6px 16px' }} onClick={copyPrompt}>
                      {copied ? 'Copied!' : 'Copy Prompt'}
                    </button>
                  </div>
                  <p style={{ fontSize: 13, color: 'var(--text-muted)', margin: '0 0 12px' }}>
                    Copy this prompt and paste it into any AI (ChatGPT, Gemini, etc.) to generate your cover letter.
                    Then upload the result to the application website.
                  </p>
                  <div style={{
                    fontFamily: 'var(--mono)', fontSize: 12.5, lineHeight: 1.7,
                    color: 'var(--text-secondary)', background: 'var(--bg)', padding: 16,
                    borderRadius: 8, border: '1px solid var(--border)',
                    maxHeight: 350, overflow: 'auto', whiteSpace: 'pre-wrap', wordBreak: 'break-word',
                  }}>
                    {selected.prompt_content || '(No prompt generated — upload example cover letters first)'}
                  </div>
                </div>

                {/* Instructions */}
                <div style={{ padding: '16px 24px', background: 'var(--surface)' }}>
                  <div style={{ fontSize: 13, color: 'var(--text-muted)', lineHeight: 1.7 }}>
                    <strong style={{ color: 'var(--text-primary)' }}>Steps:</strong>
                    <ol style={{ margin: '8px 0 0', paddingLeft: 20 }}>
                      <li>Copy the prompt above</li>
                      <li>Paste into your preferred AI and generate the cover letter</li>
                      <li>Click "Open Application" to go to the job application page</li>
                      <li>Upload your generated cover letter to the application</li>
                      <li>Come back here and click "Mark as Done"</li>
                    </ol>
                  </div>
                </div>

                <div className="editor-actions">
                  <button className="btn btn-ghost" onClick={() => setSelected(null)}>Cancel</button>
                  <button className="btn btn-danger" disabled={saving} onClick={() => handleAction('skip')}>Skip</button>
                  <button className="btn btn-success" disabled={saving} onClick={() => handleAction('done')}>
                    {saving ? '...' : 'Mark as Done'}
                  </button>
                </div>
              </div>
            )}
          </div>
        )}
      </div>

      {showFlag && <FlagMistakeModal onClose={() => setShowFlag(false)} toast={toast} />}
    </div>
  )
}

// ── Jobs Table Page ──────────────────────────────────────────────────────
function JobsPage({ toast }) {
  const [statusFilter, setStatusFilter] = useState('')
  const [screenshotJobId, setScreenshotJobId] = useState(null)
  const [actionBusy, setActionBusy] = useState({})
  const [analyzeBusy, setAnalyzeBusy] = useState(false)
  const { data: jobs, loading, refetch } = useApi(
    `${API}/jobs${statusFilter ? `?status=${statusFilter}` : ''}`,
    [statusFilter]
  )
  const { data: pipelineStatus, refetch: refetchPipeline } = useApi(`${API}/pipeline/status`)
  const { data: statsData, refetch: refetchStats } = useApi(`${API}/stats`)

  const statuses = ['new', 'analyzed', 'queued', 'pending_cl_upload',
    'filling', 'filled', 'submitting', 'applying', 'applied', 'failed', 'skipped']

  const [browserOpen, setBrowserOpen] = useState([]) // job IDs with live browser windows

  useEffect(() => {
    if (!pipelineStatus) return
    const filling = pipelineStatus.filling || []
    const submitting = pipelineStatus.submitting || []
    setActionBusy(prev => {
      const next = { ...prev }
      filling.forEach(id => { next[id] = 'fill' })
      submitting.forEach(id => { next[id] = 'submit' })
      return next
    })
    setAnalyzeBusy(!!pipelineStatus.analyzing)
    setBrowserOpen(pipelineStatus.browser_open || [])
  }, [pipelineStatus])

  const anyBusy = Object.keys(actionBusy).length > 0 || analyzeBusy
  useEffect(() => {
    if (!anyBusy) return
    const interval = setInterval(() => { refetch(); refetchPipeline(); refetchStats() }, 3000)
    return () => clearInterval(interval)
  }, [anyBusy, refetch, refetchPipeline, refetchStats])

  const triggerAnalyze = async () => {
    setAnalyzeBusy(true)
    try {
      const r = await fetch(`${API}/analyze`, { method: 'POST' })
      const d = await r.json()
      if (!r.ok || !d.ok) { toast(d.detail || d.message || 'Failed', 'error'); setAnalyzeBusy(false); return }
      toast('Analyzing new jobs… watch Activity Log', 'success')
      const poll = setInterval(async () => {
        try {
          const sr = await fetch(`${API}/pipeline/status`)
          const sd = await sr.json()
          if (!sd.analyzing) {
            clearInterval(poll); setAnalyzeBusy(false); refetch(); refetchStats()
            toast('Analysis complete', 'success')
          }
        } catch { clearInterval(poll) }
      }, 3000)
    } catch (e) { toast('Error: ' + e.message, 'error'); setAnalyzeBusy(false) }
  }

  const triggerFill = async (job) => {
    if (actionBusy[job.id]) return
    setActionBusy(p => ({ ...p, [job.id]: 'fill' }))
    try {
      const r = await fetch(`${API}/jobs/${job.id}/fill`, { method: 'POST' })
      const data = await r.json()
      if (!r.ok) { toast(data.detail || 'Failed to start fill', 'error'); setActionBusy(p => { const n = { ...p }; delete n[job.id]; return n }); return }
      toast(`Filling form for "${job.title}"… watch Activity Log`, 'success')
      const poll = setInterval(async () => {
        try {
          const jr = await fetch(`${API}/jobs/${job.id}`)
          const jd = await jr.json()
          if (jd.status !== 'filling') {
            clearInterval(poll)
            setActionBusy(p => { const n = { ...p }; delete n[job.id]; return n })
            refetch()
            if (jd.status === 'filled') toast(`Form filled for "${job.title}" — ready to submit!`, 'success')
            else toast(`Fill finished: ${jd.status}`, jd.status === 'failed' ? 'error' : 'success')
          }
        } catch { clearInterval(poll) }
      }, 3000)
    } catch (e) {
      toast('Error: ' + e.message, 'error')
      setActionBusy(p => { const n = { ...p }; delete n[job.id]; return n })
    }
  }

  const confirmSubmit = async (job) => {
    if (actionBusy[job.id]) return
    setActionBusy(p => ({ ...p, [job.id]: 'confirm' }))
    try {
      const r = await fetch(`${API}/jobs/${job.id}/confirm-submitted`, { method: 'POST' })
      const data = await r.json()
      if (!r.ok) { toast(data.detail || 'Failed to confirm submission', 'error'); setActionBusy(p => { const n = { ...p }; delete n[job.id]; return n }); return }
      toast(`"${job.title}" marked as submitted!`, 'success')
      refetch(); refetchPipeline()
      setActionBusy(p => { const n = { ...p }; delete n[job.id]; return n })
    } catch (e) {
      toast('Error: ' + e.message, 'error')
      setActionBusy(p => { const n = { ...p }; delete n[job.id]; return n })
    }
  }

  const discardFill = async (job) => {
    if (actionBusy[job.id]) return
    if (!window.confirm(`Discard the filled form for "${job.title}"?\n\nThis will close the browser window and reset the job to queued so it can be re-filled.`)) return
    setActionBusy(p => ({ ...p, [job.id]: 'discard' }))
    try {
      const r = await fetch(`${API}/jobs/${job.id}/discard-fill`, { method: 'POST' })
      const data = await r.json()
      if (!r.ok) { toast(data.detail || 'Failed to discard', 'error'); setActionBusy(p => { const n = { ...p }; delete n[job.id]; return n }); return }
      toast(`Fill discarded — "${job.title}" reset to queued`, 'success')
      refetch(); refetchPipeline()
      setActionBusy(p => { const n = { ...p }; delete n[job.id]; return n })
    } catch (e) {
      toast('Error: ' + e.message, 'error')
      setActionBusy(p => { const n = { ...p }; delete n[job.id]; return n })
    }
  }

  if (loading) return <div className="page-content empty"><div className="empty-icon spin">⚙️</div></div>

  return (
    <div>
      <div className="page-header">
        <div>
          <div className="page-title">All Jobs</div>
          <div className="page-subtitle">{(jobs || []).length} jobs in the pipeline</div>
        </div>
        <div style={{ display: 'flex', gap: 12 }}>
          <select value={statusFilter} onChange={e => setStatusFilter(e.target.value)} style={{
            background: 'var(--surface)', border: '1px solid var(--border)', borderRadius: 8,
            color: 'var(--text-primary)', padding: '8px 12px', fontSize: 13, cursor: 'pointer',
          }}>
            <option value="">All Statuses</option>
            {statuses.map(s => <option key={s} value={s}>{s.replace(/_/g, ' ')}</option>)}
          </select>
          <button className="btn btn-ghost" onClick={refetch}>↻ Refresh</button>
        </div>
      </div>

      {/* Pipeline action buttons */}
      <div style={{ padding: '0 40px', marginBottom: 16 }}>
        <div className="pipeline-actions">
          <button
            className="btn btn-accent"
            disabled={analyzeBusy || !(statsData?.total_new > 0)}
            onClick={triggerAnalyze}
            style={{ fontSize: 13, padding: '8px 16px' }}
          >
            {analyzeBusy
              ? <><span className="spin" style={{ display: 'inline-block', marginRight: 4 }}>⚙️</span>Analyzing…</>
              : `Analyze ${statsData?.total_new || 0} New Jobs`}
          </button>
          {analyzeBusy && <button className="btn-stop" onClick={() => stopAgentTask('analyze', toast)}>Stop</button>}
        </div>
      </div>

        <div style={{ padding: '0 40px 16px' }}>
        <div style={{ display: 'flex', gap: 8, fontSize: 12, color: 'var(--text-muted)', flexWrap: 'wrap', alignItems: 'center' }}>
          <span style={{ fontWeight: 600, color: 'var(--text-primary)' }}>Stages:</span>
          <span className="tag tag-muted">new → analyzed → queued</span>
          <span>→</span>
          <span className="tag" style={{ background: 'rgba(59,130,246,.15)', color: '#60a5fa', border: '1px solid rgba(59,130,246,.25)' }}>Fill Form</span>
          <span>→</span>
          <span className="tag" style={{ background: 'rgba(139,92,246,.15)', color: '#a78bfa', border: '1px solid rgba(139,92,246,.25)' }}>filled</span>
          <span>→</span>
          <span className="tag" style={{ background: 'rgba(245,158,11,.15)', color: 'var(--amber)', border: '1px solid rgba(245,158,11,.25)' }}>Review ↗ (you submit)</span>
          <span>→</span>
          <span className="tag" style={{ background: 'rgba(16,185,129,.15)', color: 'var(--green)', border: '1px solid rgba(16,185,129,.25)' }}>Confirm Submitted</span>
          <span>→</span>
          <span className="tag tag-muted">applied</span>
        </div>
      </div>

      <div className="page-content">
        {(jobs || []).length === 0 ? (
          <div className="empty">
            <div className="empty-icon">💼</div>
            <h3>No jobs yet</h3>
            <p>Go to <strong>Source Jobs</strong> and scrape a platform to start.</p>
          </div>
        ) : (
          <div className="table-wrap">
            <table>
              <thead><tr>
                <th>Title</th><th>Company</th><th>Source</th><th>Score</th><th>Status</th>
                <th>Stage 2 — Fill</th><th>Stage 3 — You Submit</th><th></th>
              </tr></thead>
              <tbody>
                {(jobs || []).map(job => {
                  const busy = actionBusy[job.id]
                  const canFill = ['queued', 'failed', 'filled'].includes(job.status)
                  const canConfirm = job.status === 'filled'
                  const isFilling = busy === 'fill' || job.status === 'filling'
                  const isConfirming = busy === 'confirm'
                  const hasBrowserOpen = browserOpen.includes(job.id)
                  return (
                    <tr key={job.id}>
                      <td className="td-title" title={job.title}>{job.title}</td>
                      <td className="td-company">{job.company}</td>
                      <td><span className="tag tag-muted">{job.source}</span></td>
                      <td>{job.relevance_score != null
                        ? <span style={{ fontFamily: 'var(--mono)', fontWeight: 700, color: job.relevance_score >= 0.7 ? 'var(--green)' : job.relevance_score >= 0.5 ? 'var(--amber)' : 'var(--red)' }}>
                            {(job.relevance_score * 100).toFixed(0)}%
                          </span>
                        : <span style={{ color: 'var(--text-muted)' }}>—</span>}
                      </td>
                      <td><Status s={job.status} /></td>

                      <td>
                        {isFilling
                          ? <span style={{ fontSize: 12, color: '#60a5fa', display: 'flex', alignItems: 'center', gap: 4 }}>
                              <span className="spin" style={{ display: 'inline-block' }}>⚙️</span> Filling…
                              <button className="btn-stop" onClick={() => stopAgentTask(`fill_${job.id}`, toast)}>Stop</button>
                            </span>
                          : canFill
                            ? <button className="btn btn-ghost" style={{ padding: '5px 12px', fontSize: 12, borderColor: '#60a5fa', color: '#60a5fa' }}
                                onClick={() => triggerFill(job)} disabled={!!busy}>
                                Fill Form
                              </button>
                            : <span style={{ color: 'var(--text-muted)', fontSize: 12 }}>{job.status === 'applied' ? '✓ done' : '—'}</span>
                        }
                      </td>

                      <td>
                        {canConfirm
                          ? <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
                              {hasBrowserOpen
                                ? <div style={{ fontSize: 11, color: 'var(--amber)', fontWeight: 600, display: 'flex', alignItems: 'center', gap: 4 }}>
                                    <span>🌐</span> Browser open — switch to it, review &amp; submit
                                  </div>
                                : <div style={{ fontSize: 11, color: 'var(--text-muted)' }}>
                                    Form filled (browser closed — check screenshots)
                                  </div>
                              }
                              <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap' }}>
                                <button
                                  className="btn btn-success"
                                  style={{ padding: '5px 12px', fontSize: 12 }}
                                  onClick={() => confirmSubmit(job)}
                                  disabled={!!busy}
                                >
                                  {isConfirming ? '…' : 'Confirm Submitted'}
                                </button>
                                <button
                                  className="btn btn-danger"
                                  style={{ padding: '5px 10px', fontSize: 11 }}
                                  onClick={() => discardFill(job)}
                                  disabled={!!busy}
                                  title="Close browser window and reset job to queued"
                                >
                                  Discard
                                </button>
                              </div>
                            </div>
                          : <span style={{ color: 'var(--text-muted)', fontSize: 12 }}>{job.status === 'applied' ? '✓ submitted' : '—'}</span>
                        }
                      </td>

                      <td>
                        <div style={{ display: 'flex', gap: 6 }}>
                          <a href={job.url} target="_blank" rel="noreferrer" className="btn btn-ghost" style={{ padding: '5px 10px', fontSize: 12 }}>↗</a>
                          {['applied', 'filled', 'filling'].includes(job.status) && (
                            <button className="btn btn-ghost" style={{ padding: '5px 10px', fontSize: 12 }} onClick={() => setScreenshotJobId(job.id)}>🖼</button>
                          )}
                        </div>
                      </td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>
        )}
      </div>
      {screenshotJobId && <ScreenshotModal jobId={screenshotJobId} onClose={() => setScreenshotJobId(null)} />}
    </div>
  )
}

// ── Cover Letter Samples Page ────────────────────────────────────────────
function SamplesPage({ toast }) {
  const { data: examples, loading, refetch } = useApi(`${API}/cover-letter/examples`)
  const [uploading, setUploading] = useState(false)
  const [deleting, setDeleting] = useState(null)
  const fileInputRef = useRef(null)

  const handleUpload = async (e) => {
    const file = e.target.files?.[0]
    if (!file) return
    setUploading(true)
    try {
      const fd = new FormData()
      fd.append('file', file)
      const r = await fetch(`${API}/cover-letter/examples`, { method: 'POST', body: fd })
      if (!r.ok) { const err = await r.json(); throw new Error(err.detail || 'Upload failed') }
      toast('Cover letter sample uploaded', 'success')
      refetch()
    } catch (e) { toast('Error: ' + e.message, 'error') }
    setUploading(false)
    if (fileInputRef.current) fileInputRef.current.value = ''
  }

  const handleDelete = async (filename) => {
    setDeleting(filename)
    try {
      const r = await fetch(`${API}/cover-letter/examples/${encodeURIComponent(filename)}`, { method: 'DELETE' })
      if (!r.ok) throw new Error('Failed')
      toast('Sample deleted', 'success')
      refetch()
    } catch (e) { toast('Error: ' + e.message, 'error') }
    setDeleting(null)
  }

  return (
    <div>
      <div className="page-header">
        <div>
          <div className="page-title">Cover Letter Samples</div>
          <div className="page-subtitle">Upload your existing cover letters — the system picks the best one to modify for each job</div>
        </div>
        <button className="btn btn-ghost" onClick={refetch}>↻ Refresh</button>
      </div>
      <div className="page-content" style={{ maxWidth: 800 }}>
        <div style={{ marginBottom: 24 }}>
          <p style={{ fontSize: 13, color: 'var(--text-muted)', marginBottom: 16, marginTop: 0, lineHeight: 1.6 }}>
            Upload cover letters you have written before as PDFs. When a job requires a cover letter,
            a local AI model (Qwen3 8B via Ollama) picks the most relevant sample and includes it
            in a ready-to-copy prompt for you.
          </p>
          <input type="file" accept=".pdf" ref={fileInputRef} style={{ display: 'none' }} onChange={handleUpload} />
          <div className="upload-area" onClick={() => fileInputRef.current?.click()}>
            {uploading ? 'Uploading…' : 'Click to upload a PDF cover letter sample'}
          </div>
        </div>
        {loading ? <div className="empty" style={{ padding: 40 }}><div className="empty-icon spin">⚙️</div></div> : (
          <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
            {(examples || []).length === 0 && (
              <div className="empty" style={{ padding: 40 }}>
                <h3>No samples yet</h3>
                <p>Upload a PDF cover letter so the system can match it to future job applications.</p>
              </div>
            )}
            {(examples || []).map(ex => (
              <div key={ex.filename} className="example-card">
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: 12 }}>
                  <div>
                    <div style={{ fontWeight: 600, marginBottom: 4 }}>{ex.filename}</div>
                    <div style={{ fontSize: 12, color: 'var(--text-muted)' }}>{(ex.size_bytes / 1024).toFixed(1)} KB</div>
                  </div>
                  <button className="btn btn-danger" style={{ fontSize: 13, padding: '5px 10px' }}
                    disabled={deleting === ex.filename} onClick={() => handleDelete(ex.filename)}>
                    Delete
                  </button>
                </div>
                {ex.text_preview && (
                  <div style={{ fontSize: 12, color: 'var(--text-muted)', fontFamily: 'var(--mono)', lineHeight: 1.6,
                    background: 'var(--bg)', padding: 12, borderRadius: 8, whiteSpace: 'pre-wrap', maxHeight: 120, overflow: 'hidden' }}>
                    {ex.text_preview}
                  </div>
                )}
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  )
}

function setFormAtPath(setForm, path, value) {
  setForm(prev => {
    const next = JSON.parse(JSON.stringify(prev))
    const keys = path.split('.')
    let cur = next
    for (let i = 0; i < keys.length - 1; i++) { cur[keys[i]] = cur[keys[i]] || {}; cur = cur[keys[i]] }
    cur[keys[keys.length - 1]] = value
    return next
  })
}

function ProfileFormField({ label, path, type = 'text', placeholder = '', form, setForm }) {
  const v = path.split('.').reduce((o, k) => o?.[k], form)
  return (
    <div>
      <label className="field-label">{label}</label>
      {type === 'checkbox'
        ? <label style={{ display: 'flex', alignItems: 'center', gap: 8, cursor: 'pointer', fontSize: 14 }}>
            <input type="checkbox" checked={!!v} onChange={e => setFormAtPath(setForm, path, e.target.checked)} />
            Yes
          </label>
        : <input className="field-select" style={{ width: '100%', boxSizing: 'border-box' }}
            type={type} value={v ?? ''} onChange={e => setFormAtPath(setForm, path, e.target.value)} placeholder={placeholder} />
      }
    </div>
  )
}

// ── Profile Page ─────────────────────────────────────────────────────────
function ProfilePage({ toast }) {
  const { data: profile, loading, refetch } = useApi(`${API}/profile`)
  const { data: credSettings, refetch: refetchCreds } = useApi(`${API}/settings`)
  const [form, setForm] = useState({})
  const [credForm, setCredForm] = useState({})
  const [autoSaveStatus, setAutoSaveStatus] = useState('') // '' | 'saving' | 'saved' | 'error'
  const serverProfileRef = useRef(null)
  const serverCredRef = useRef(null)
  const formRef = useRef(form)
  const credFormRef = useRef(credForm)
  formRef.current = form
  credFormRef.current = credForm

  useEffect(() => {
    if (profile) {
      setForm(profile)
      serverProfileRef.current = JSON.stringify(profile)
    }
  }, [profile])

  useEffect(() => {
    if (credSettings) {
      const creds = {
        uchicago_cnet_id:   credSettings.uchicago_cnet_id   ?? '',
        uchicago_password:  credSettings.uchicago_password  ?? '',
        handshake_email:    credSettings.handshake_email    ?? '',
        handshake_password: credSettings.handshake_password ?? '',
      }
      setCredForm(creds)
      serverCredRef.current = JSON.stringify(creds)
    }
  }, [credSettings])

  // Autosave profile form
  const formStr = JSON.stringify(form)
  useEffect(() => {
    if (!serverProfileRef.current || formStr === serverProfileRef.current) {
      setAutoSaveStatus(s => s === 'saving' ? '' : s)
      return
    }
    setAutoSaveStatus('saving')
    const timer = setTimeout(async () => {
      try {
        const r = await fetch(`${API}/profile`, {
          method: 'PATCH',
          headers: { 'Content-Type': 'application/json' },
          body: formStr,
        })
        if (r.ok) {
          serverProfileRef.current = formStr
          setAutoSaveStatus('saved')
          setTimeout(() => setAutoSaveStatus(s => s === 'saved' ? '' : s), 3000)
        } else {
          setAutoSaveStatus('error')
          setTimeout(() => setAutoSaveStatus(s => s === 'error' ? '' : s), 4000)
        }
      } catch {
        setAutoSaveStatus('error')
        setTimeout(() => setAutoSaveStatus(s => s === 'error' ? '' : s), 4000)
      }
    }, 800)
    return () => clearTimeout(timer)
  }, [formStr])

  // Autosave credentials
  const credStr = JSON.stringify(credForm)
  useEffect(() => {
    if (!serverCredRef.current || credStr === serverCredRef.current) return
    const timer = setTimeout(async () => {
      try {
        const r = await fetch(`${API}/settings`, {
          method: 'PATCH',
          headers: { 'Content-Type': 'application/json' },
          body: credStr,
        })
        if (r.ok) serverCredRef.current = credStr
      } catch {}
    }, 800)
    return () => clearTimeout(timer)
  }, [credStr])

  // Emergency save on page unload (browser close/refresh)
  useEffect(() => {
    const flushSave = () => {
      const curProfile = JSON.stringify(formRef.current)
      if (serverProfileRef.current && curProfile !== serverProfileRef.current) {
        fetch(`${API}/profile`, {
          method: 'PATCH',
          headers: { 'Content-Type': 'application/json' },
          body: curProfile,
          keepalive: true,
        })
      }
      const curCreds = JSON.stringify(credFormRef.current)
      if (serverCredRef.current && curCreds !== serverCredRef.current) {
        fetch(`${API}/settings`, {
          method: 'PATCH',
          headers: { 'Content-Type': 'application/json' },
          body: curCreds,
          keepalive: true,
        })
      }
    }
    window.addEventListener('beforeunload', flushSave)
    return () => window.removeEventListener('beforeunload', flushSave)
  }, [])

  const set = (path, value) => setFormAtPath(setForm, path, value)

  if (loading) return <div className="page-content empty"><div className="empty-icon spin">⚙️</div></div>

  return (
    <div>
      <div className="page-header">
        <div><div className="page-title">Profile</div><div className="page-subtitle">Your info used by the AI to fill application forms</div></div>
        <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
          {autoSaveStatus === 'saving' && <span className="autosave-indicator autosave-saving">Auto-saving…</span>}
          {autoSaveStatus === 'saved' && <span className="autosave-indicator autosave-saved">✓ Saved</span>}
          {autoSaveStatus === 'error' && <span className="autosave-indicator autosave-error">Save failed</span>}
          <button className="btn btn-ghost" onClick={refetch}>↻ Reload</button>
        </div>
      </div>
      <div className="page-content" style={{ maxWidth: 800 }}>
        <div className="profile-section">
          <h4>Personal Information</h4>
          <div className="profile-grid">
            <ProfileFormField label="First Name" path="personal.first_name" form={form} setForm={setForm} />
            <ProfileFormField label="Last Name" path="personal.last_name" form={form} setForm={setForm} />
            <ProfileFormField label="Personal Email" path="personal.email" type="email" form={form} setForm={setForm} />
            <ProfileFormField label="University / Institutional Email" path="personal.university_email" type="email" form={form} setForm={setForm} />
            <ProfileFormField label="Phone" path="personal.phone" form={form} setForm={setForm} />
            <ProfileFormField label="LinkedIn URL" path="personal.linkedin" placeholder="https://linkedin.com/in/…" form={form} setForm={setForm} />
            <ProfileFormField label="GitHub URL" path="personal.github" placeholder="https://github.com/…" form={form} setForm={setForm} />
            <ProfileFormField label="Portfolio URL" path="personal.portfolio" form={form} setForm={setForm} />
            <ProfileFormField label="City" path="personal.address.city" form={form} setForm={setForm} />
            <ProfileFormField label="State" path="personal.address.state" form={form} setForm={setForm} />
            <ProfileFormField label="ZIP" path="personal.address.zip" form={form} setForm={setForm} />
            <ProfileFormField label="Country" path="personal.address.country" form={form} setForm={setForm} />
          </div>
        </div>

        <div className="profile-section">
          <h4>Education (most recent)</h4>
          <div className="profile-grid">
            <ProfileFormField label="Institution" path="education.0.institution" form={form} setForm={setForm} />
            <ProfileFormField label="Degree" path="education.0.degree" placeholder="e.g. Bachelor of Science" form={form} setForm={setForm} />
            <ProfileFormField label="Major" path="education.0.major" form={form} setForm={setForm} />
            <ProfileFormField label="Minor" path="education.0.minor" form={form} setForm={setForm} />
            <ProfileFormField label="GPA" path="education.0.gpa" form={form} setForm={setForm} />
            <ProfileFormField label="Graduation Year" path="education.0.graduation_year" form={form} setForm={setForm} />
            <ProfileFormField label="Graduation Month" path="education.0.graduation_month" form={form} setForm={setForm} />
            <ProfileFormField label="Start Year" path="education.0.start_year" form={form} setForm={setForm} />
          </div>
        </div>

        <div className="profile-section">
          <h4>Most Recent Work Experience</h4>
          <div className="profile-grid">
            <ProfileFormField label="Company" path="work_experience.0.company" form={form} setForm={setForm} />
            <ProfileFormField label="Job Title" path="work_experience.0.title" form={form} setForm={setForm} />
            <ProfileFormField label="Start Date" path="work_experience.0.start_date" placeholder="e.g. June 2024" form={form} setForm={setForm} />
            <ProfileFormField label="End Date" path="work_experience.0.end_date" placeholder="Present" form={form} setForm={setForm} />
            <ProfileFormField label="Location" path="work_experience.0.location" form={form} setForm={setForm} />
          </div>
        </div>

        <div className="profile-section">
          <h4>Skills</h4>
          <div className="profile-grid">
            <div>
              <label className="field-label">Technical Skills (comma-separated)</label>
              <input className="field-select" style={{ width: '100%', boxSizing: 'border-box' }}
                value={(form.skills?.technical || []).join(', ')}
                onChange={e => set('skills.technical', e.target.value.split(',').map(s => s.trim()).filter(Boolean))}
                placeholder="Python, SQL, Excel, React…" />
            </div>
            <div>
              <label className="field-label">Languages (comma-separated)</label>
              <input className="field-select" style={{ width: '100%', boxSizing: 'border-box' }}
                value={(form.skills?.languages || []).join(', ')}
                onChange={e => set('skills.languages', e.target.value.split(',').map(s => s.trim()).filter(Boolean))}
                placeholder="English (Native), Spanish (Conversational)…" />
            </div>
          </div>
        </div>

        <div className="profile-section">
          <h4>Eligibility & Screening Defaults</h4>
          <div className="profile-grid">
            <ProfileFormField label="Authorized to work in US" path="eligibility.authorized_to_work" type="checkbox" form={form} setForm={setForm} />
            <ProfileFormField label="Requires sponsorship" path="eligibility.requires_sponsorship" type="checkbox" form={form} setForm={setForm} />
            <ProfileFormField label="US Citizen" path="eligibility.us_citizen" type="checkbox" form={form} setForm={setForm} />
            <ProfileFormField label="Years of experience" path="screening_defaults.years_of_experience" placeholder="0-1" form={form} setForm={setForm} />
            <ProfileFormField label="Available start date" path="screening_defaults.available_start_date" placeholder="June 2025" form={form} setForm={setForm} />
            <ProfileFormField label="Salary expectation" path="screening_defaults.salary_expectation" placeholder="e.g. $80,000" form={form} setForm={setForm} />
            <ProfileFormField label="Willing to relocate" path="screening_defaults.willing_to_relocate" type="checkbox" form={form} setForm={setForm} />
          </div>
        </div>

        <div className="profile-section">
          <div style={{ marginBottom: 16 }}>
            <h4 style={{ margin: 0 }}>Login Credentials</h4>
            <p style={{ margin: '4px 0 0', fontSize: 13, color: 'var(--text-muted)' }}>Stored securely in your local .env file — auto-saved as you type</p>
          </div>
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 24 }}>
            <div style={{ padding: 16, background: 'var(--surface)', borderRadius: 'var(--radius)', border: '1px solid var(--border)' }}>
              <div style={{ fontWeight: 600, fontSize: 13, marginBottom: 4, color: 'var(--text-primary)' }}>UChicago SSO</div>
              <p style={{ fontSize: 12, color: 'var(--text-muted)', margin: '0 0 12px' }}>Used to log in to Handshake via UChicago SSO</p>
              <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
                <div>
                  <label className="field-label">CNet ID</label>
                  <input className="field-select" style={{ width: '100%', boxSizing: 'border-box' }}
                    value={credForm.uchicago_cnet_id ?? ''}
                    onChange={e => setCredForm(p => ({ ...p, uchicago_cnet_id: e.target.value }))} />
                </div>
                <div>
                  <label className="field-label">Password</label>
                  <input className="field-select" type="password" style={{ width: '100%', boxSizing: 'border-box' }}
                    value={credForm.uchicago_password ?? ''}
                    onChange={e => setCredForm(p => ({ ...p, uchicago_password: e.target.value }))} />
                </div>
              </div>
            </div>
            <div style={{ padding: 16, background: 'var(--surface)', borderRadius: 'var(--radius)', border: '1px solid var(--border)' }}>
              <div style={{ fontWeight: 600, fontSize: 13, marginBottom: 4, color: 'var(--text-primary)' }}>Standard Login</div>
              <p style={{ fontSize: 12, color: 'var(--text-muted)', margin: '0 0 12px' }}>Fallback for direct email/password login on other job boards</p>
              <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
                <div>
                  <label className="field-label">Email</label>
                  <input className="field-select" type="email" style={{ width: '100%', boxSizing: 'border-box' }}
                    value={credForm.handshake_email ?? ''}
                    onChange={e => setCredForm(p => ({ ...p, handshake_email: e.target.value }))} />
                </div>
                <div>
                  <label className="field-label">Password</label>
                  <input className="field-select" type="password" style={{ width: '100%', boxSizing: 'border-box' }}
                    value={credForm.handshake_password ?? ''}
                    onChange={e => setCredForm(p => ({ ...p, handshake_password: e.target.value }))} />
                </div>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  )
}

// ── AI Memory Page ─────────────────────────────────────────────────────
function MemoryPage({ toast }) {
  const { data, loading, refetch } = useApi(`${API}/memory`)
  const [showAdd, setShowAdd] = useState(false)
  const [deleting, setDeleting] = useState(null)

  const deleteRule = async (id) => {
    setDeleting(id)
    try {
      await fetch(`${API}/memory/${id}`, { method: 'DELETE' })
      toast('Rule deleted', 'success')
      refetch()
    } catch { toast('Error deleting', 'error') }
    setDeleting(null)
  }

  const toggleRule = async (rule) => {
    try {
      await fetch(`${API}/memory/${rule.id}`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ enabled: !rule.enabled }),
      })
      refetch()
    } catch { toast('Error updating', 'error') }
  }

  const agentLabels = { analyzer: 'Analyzer', executor: 'Executor', sourcer: 'Sourcer' }
  const severityColors = { high: 'var(--red)', medium: 'var(--amber)', low: 'var(--accent)' }
  const allRules = data ? Object.values(data).flat() : []

  return (
    <div>
      <div className="page-header">
        <div>
          <div className="page-title">AI Memory</div>
          <div className="page-subtitle">Correction rules injected into every prompt — the agent's long-term memory</div>
        </div>
        <div style={{ display: 'flex', gap: 8 }}>
          <button className="btn btn-accent" onClick={() => setShowAdd(true)}>+ Add Rule</button>
          <button className="btn btn-ghost" onClick={refetch}>↻ Refresh</button>
        </div>
      </div>
      <div className="page-content">
        {loading ? <div className="empty"><div className="empty-icon spin">⚙️</div></div> :
          allRules.length === 0 ? (
            <div className="empty">
              <div className="empty-icon">🧠</div>
              <h3>No rules yet</h3>
              <p>When you notice the AI making a mistake, click "Flag AI Mistake" in the queue or "+ Add Rule" here.<br />Rules are injected into every future prompt so the AI won't repeat it.</p>
            </div>
          ) : (
            <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
              {allRules.map(rule => (
                <div key={rule.id} className="card" style={{ padding: 20, opacity: rule.enabled ? 1 : 0.5, borderLeft: `3px solid ${severityColors[rule.severity] || 'var(--border)'}` }}>
                  <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', gap: 16 }}>
                    <div style={{ flex: 1 }}>
                      <div style={{ display: 'flex', gap: 8, marginBottom: 8, flexWrap: 'wrap' }}>
                        <span className="tag tag-muted">{agentLabels[rule.agent] || rule.agent}</span>
                        <span className="tag" style={{ background: severityColors[rule.severity] + '22', color: severityColors[rule.severity], border: `1px solid ${severityColors[rule.severity]}44` }}>{rule.severity}</span>
                        {!rule.enabled && <span className="tag tag-muted">disabled</span>}
                        <span className="tag tag-muted">triggered {rule.times_triggered}×</span>
                      </div>
                      <div style={{ fontWeight: 600, marginBottom: 6, color: 'var(--text-primary)' }}>{rule.description}</div>
                      {rule.example_bad && <div style={{ fontSize: 13, color: 'var(--red)', marginBottom: 4 }}>{rule.example_bad}</div>}
                      <div style={{ fontSize: 13, color: 'var(--green)' }}>{rule.correction}</div>
                    </div>
                    <div style={{ display: 'flex', gap: 6, flexShrink: 0 }}>
                      <button className="btn btn-ghost" style={{ fontSize: 13, padding: '5px 10px' }} onClick={() => toggleRule(rule)}>
                        {rule.enabled ? 'Disable' : 'Enable'}
                      </button>
                      <button className="btn btn-danger" style={{ fontSize: 13, padding: '5px 10px' }} disabled={deleting === rule.id} onClick={() => deleteRule(rule.id)}>
                        Delete
                      </button>
                    </div>
                  </div>
                </div>
              ))}
            </div>
          )
        }
      </div>
      {showAdd && <FlagMistakeModal onClose={() => { setShowAdd(false); refetch() }} toast={toast} />}
    </div>
  )
}

// ── Activity Log Page ────────────────────────────────────────────────────
function ActivityPage() {
  const [events, setEvents] = useState([])
  const [lastId, setLastId] = useState(0)
  const [paused, setPaused] = useState(false)
  const [agentFilter, setAgentFilter] = useState('')
  const [levelFilter, setLevelFilter] = useState('')
  const scrollRef = useRef(null)
  const autoScrollRef = useRef(true)

  const handleScroll = () => {
    const el = scrollRef.current
    if (!el) return
    const atBottom = el.scrollHeight - el.scrollTop - el.clientHeight < 40
    autoScrollRef.current = atBottom
  }

  useEffect(() => {
    if (paused) return
    let cancelled = false
    const poll = async () => {
      try {
        const r = await fetch(`${API}/activity?since_id=${lastId}&limit=300`)
        if (!r.ok) return
        const data = await r.json()
        if (cancelled) return
        if (data.events && data.events.length > 0) {
          setEvents(prev => [...prev, ...data.events].slice(-500))
          setLastId(data.events[data.events.length - 1].id)
        }
      } catch {}
    }
    poll()
    const interval = setInterval(poll, 2000)
    return () => { cancelled = true; clearInterval(interval) }
  }, [paused, lastId])

  useEffect(() => {
    if (autoScrollRef.current && scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight
    }
  }, [events])

  const agents = [...new Set(events.map(e => e.agent))].sort()
  const filtered = events.filter(e => {
    if (agentFilter && e.agent !== agentFilter) return false
    if (levelFilter && e.level !== levelFilter) return false
    return true
  })

  const formatTime = (ts) => {
    const d = new Date(ts * 1000)
    return d.toLocaleTimeString('en-US', { hour12: false, hour: '2-digit', minute: '2-digit', second: '2-digit' })
      + '.' + String(d.getMilliseconds()).padStart(3, '0')
  }

  return (
    <div>
      <div className="page-header">
        <div>
          <div className="page-title" style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
            Activity Log
            {!paused && <span className="activity-live-dot" title="Live" />}
          </div>
          <div className="page-subtitle">{filtered.length} event{filtered.length !== 1 ? 's' : ''} — {paused ? 'paused' : 'auto-updating every 2s'}</div>
        </div>
        <div style={{ display: 'flex', gap: 8 }}>
          <button className="btn btn-ghost" onClick={() => setPaused(p => !p)}>{paused ? '▶ Resume' : '⏸ Pause'}</button>
          <button className="btn btn-ghost" onClick={() => { setEvents([]); setLastId(0) }}>Clear</button>
        </div>
      </div>

      <div className="page-content">
        <div style={{ display: 'flex', gap: 16, marginBottom: 16, alignItems: 'center', flexWrap: 'wrap' }}>
          <div className="activity-filters">
            <button className={`activity-filter-btn ${agentFilter === '' ? 'active' : ''}`} onClick={() => setAgentFilter('')}>All Agents</button>
            {agents.map(a => (
              <button key={a} className={`activity-filter-btn ${agentFilter === a ? 'active' : ''}`}
                onClick={() => setAgentFilter(agentFilter === a ? '' : a)}>{a}</button>
            ))}
          </div>
          <div className="activity-filters">
            {['info', 'warn', 'error'].map(lvl => (
              <button key={lvl} className={`activity-filter-btn ${levelFilter === lvl ? 'active' : ''}`}
                onClick={() => setLevelFilter(levelFilter === lvl ? '' : lvl)}>{lvl}</button>
            ))}
          </div>
        </div>

        {filtered.length === 0 ? (
          <div className="empty">
            <div className="empty-icon">📡</div>
            <h3>No activity yet</h3>
            <p>Events appear here as the pipeline runs — sourcing, analysis, and applications.</p>
          </div>
        ) : (
          <div className="activity-log" ref={scrollRef} onScroll={handleScroll}>
            {filtered.map(e => (
              <div key={e.id} className={`activity-row level-${e.level}`}>
                <span className="activity-time">{formatTime(e.timestamp)}</span>
                <span className={`activity-level ${e.level}`}>{e.level}</span>
                <span className={`activity-agent ${e.agent}`}>{e.agent}</span>
                <span className="activity-msg">{e.message}</span>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  )
}

function SettingsFormSection({ title, desc, children }) {
  return (
    <div style={{ marginBottom: 32 }}>
      <h3 style={{ marginBottom: 4, marginTop: 0 }}>{title}</h3>
      {desc && <p style={{ fontSize: 13, color: 'var(--text-muted)', marginBottom: 16, marginTop: 0 }}>{desc}</p>}
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 16 }}>{children}</div>
    </div>
  )
}

function SettingsFormField({ label, name, type = 'text', placeholder = '', formData, onChange }) {
  return (
    <div>
      <label className="field-label">{label}</label>
      {type === 'checkbox'
        ? <label style={{ display: 'flex', alignItems: 'center', gap: 8, cursor: 'pointer', fontSize: 14 }}>
            <input type="checkbox" name={name} checked={!!formData[name]} onChange={onChange} />
            Enabled
          </label>
        : <input className="field-select" style={{ width: '100%', boxSizing: 'border-box' }}
            type={type} name={name} value={formData[name] ?? ''} onChange={onChange} placeholder={placeholder} />
      }
    </div>
  )
}

// ── Settings Page ───────────────────────────────────────────────────────
function SettingsPage({ toast }) {
  const { data: settings, loading, refetch } = useApi(`${API}/settings`)
  const [formData, setFormData] = useState({})
  const [autoSaveStatus, setAutoSaveStatus] = useState('') // '' | 'saving' | 'saved' | 'error'
  const serverSettingsRef = useRef(null)
  const formDataRef = useRef(formData)
  formDataRef.current = formData

  useEffect(() => {
    if (settings) {
      setFormData(settings)
      serverSettingsRef.current = JSON.stringify(settings)
    }
  }, [settings])

  const handleChange = (e) => {
    const { name, value, type, checked } = e.target
    setFormData(p => ({ ...p, [name]: type === 'checkbox' ? checked : value }))
  }

  // Autosave settings
  const formDataStr = JSON.stringify(formData)
  useEffect(() => {
    if (!serverSettingsRef.current || formDataStr === serverSettingsRef.current) {
      setAutoSaveStatus(s => s === 'saving' ? '' : s)
      return
    }
    setAutoSaveStatus('saving')
    const timer = setTimeout(async () => {
      try {
        const r = await fetch(`${API}/settings`, {
          method: 'PATCH',
          headers: { 'Content-Type': 'application/json' },
          body: formDataStr,
        })
        if (r.ok) {
          serverSettingsRef.current = formDataStr
          setAutoSaveStatus('saved')
          setTimeout(() => setAutoSaveStatus(s => s === 'saved' ? '' : s), 3000)
        } else {
          setAutoSaveStatus('error')
          setTimeout(() => setAutoSaveStatus(s => s === 'error' ? '' : s), 4000)
        }
      } catch {
        setAutoSaveStatus('error')
        setTimeout(() => setAutoSaveStatus(s => s === 'error' ? '' : s), 4000)
      }
    }, 800)
    return () => clearTimeout(timer)
  }, [formDataStr])

  // Emergency save on page unload (browser close/refresh)
  useEffect(() => {
    const flushSave = () => {
      const curSettings = JSON.stringify(formDataRef.current)
      if (serverSettingsRef.current && curSettings !== serverSettingsRef.current) {
        fetch(`${API}/settings`, {
          method: 'PATCH',
          headers: { 'Content-Type': 'application/json' },
          body: curSettings,
          keepalive: true,
        })
      }
    }
    window.addEventListener('beforeunload', flushSave)
    return () => window.removeEventListener('beforeunload', flushSave)
  }, [])

  if (loading) return <div className="page-content empty"><div className="empty-icon spin">⚙️</div></div>

  return (
    <div>
      <div className="page-header">
        <div><div className="page-title">Settings</div><div className="page-subtitle">Manage environment configuration — changes are auto-saved</div></div>
        <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
          {autoSaveStatus === 'saving' && <span className="autosave-indicator autosave-saving">Auto-saving…</span>}
          {autoSaveStatus === 'saved' && <span className="autosave-indicator autosave-saved">✓ Saved</span>}
          {autoSaveStatus === 'error' && <span className="autosave-indicator autosave-error">Save failed</span>}
          <button className="btn btn-ghost" onClick={refetch}>↻ Reload</button>
        </div>
      </div>
      <div className="page-content" style={{ maxWidth: 800 }}>
        <SettingsFormSection title="AI Providers" desc="API keys for LLM services">
          <SettingsFormField label="Google API Key" name="google_api_key" type="password" formData={formData} onChange={handleChange} />
          <SettingsFormField label="OpenAI API Key" name="openai_api_key" type="password" formData={formData} onChange={handleChange} />
          <SettingsFormField label="xAI API Key (Grok)" name="xai_api_key" type="password" formData={formData} onChange={handleChange} />
          <SettingsFormField label="xAI Base URL" name="xai_base_url" formData={formData} onChange={handleChange} />
        </SettingsFormSection>
        <SettingsFormSection title="Models" desc="Task-specific model routing (hybrid Grok + Gemini supported)">
          <div>
            <label className="field-label">LLM Provider</label>
            <select className="field-select" name="llm_provider" value={formData.llm_provider || 'google'} onChange={handleChange} style={{ width: '100%', boxSizing: 'border-box' }}>
              <option value="google">Google</option>
              <option value="openai">OpenAI</option>
              <option value="xai">xAI</option>
            </select>
          </div>
          <SettingsFormField label="Fast Model (fallback)" name="llm_model_fast" formData={formData} onChange={handleChange} />
          <SettingsFormField label="Quality Model (fallback)" name="llm_model_quality" formData={formData} onChange={handleChange} />
          <SettingsFormField label="Analyzer Model (JD parsing/routing)" name="llm_model_analyzer" formData={formData} onChange={handleChange} />
          <SettingsFormField label="Critic Model (self-refine pass)" name="llm_model_critic" formData={formData} onChange={handleChange} />
          <SettingsFormField label="Browser Fast Model (sourcer/executor)" name="llm_model_browser_fast" formData={formData} onChange={handleChange} />
          <SettingsFormField label="Browser Quality Model (optional)" name="llm_model_browser_quality" formData={formData} onChange={handleChange} />
        </SettingsFormSection>
        <SettingsFormSection title="Local Model (Cover Letter Matching)" desc="Ollama is used to pick the best cover letter sample for each job">
          <SettingsFormField label="Ollama Base URL" name="ollama_base_url" formData={formData} onChange={handleChange} placeholder="http://localhost:11434" />
          <SettingsFormField label="Ollama Model" name="ollama_model" formData={formData} onChange={handleChange} placeholder="qwen3:8b" />
        </SettingsFormSection>
        <SettingsFormSection title="Pipeline Behavior" desc="Configure how the agent runs">
          <SettingsFormField label="Dry Run (skip browser entirely — just log)" name="dry_run" type="checkbox" formData={formData} onChange={handleChange} />
          <SettingsFormField label="Scraping Interval (minutes)" name="scrape_interval_minutes" type="number" formData={formData} onChange={handleChange} />
          <SettingsFormField label="Minimum Relevance Score (0.0 – 1.0)" name="min_relevance_score" formData={formData} onChange={handleChange} />
          <SettingsFormField label="Max Applications Pending Your Review (filled, not yet submitted)" name="max_pending_submissions" type="number" formData={formData} onChange={handleChange} />
        </SettingsFormSection>
      </div>
    </div>
  )
}

// ── Usage Page ──────────────────────────────────────────────────────────
function UsagePage({ toast }) {
  const { data, loading, refetch } = useApi(`${API}/usage`)
  const [planType, setPlanType] = useState('')
  const [budget, setBudget] = useState('')
  const [saving, setSaving] = useState(false)

  useEffect(() => {
    if (data) {
      setPlanType(data.plan_type || 'free')
      setBudget(data.monthly_budget_usd || '')
    }
  }, [data])

  const savePlan = async () => {
    setSaving(true)
    try {
      const r = await fetch(`${API}/usage/plan`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ plan_type: planType, monthly_budget_usd: parseFloat(budget) || 0 }),
      })
      if (!r.ok) throw new Error('Failed')
      toast('Plan settings saved', 'success')
      refetch()
    } catch (e) { toast('Error: ' + e.message, 'error') }
    setSaving(false)
  }

  if (loading || !data) return <div className="page-content empty"><div className="empty-icon spin">⚙️</div></div>

  const modelsToday = data.today_usage || {}
  const monthlyUsage = data.monthly_usage || {}
  const history = data.daily_history || {}
  const maxHistoryReq = Math.max(1, ...Object.values(history).map(h => h.requests || 0))

  const formatTokens = (n) => {
    if (!n) return '0'
    if (n >= 1_000_000) return (n / 1_000_000).toFixed(1) + 'M'
    if (n >= 1_000) return (n / 1_000).toFixed(1) + 'K'
    return String(n)
  }

  return (
    <div>
      <div className="page-header">
        <div>
          <div className="page-title">API Usage</div>
            <div className="page-subtitle">LLM usage tracking across providers — {data.plan_label}</div>
        </div>
        <button className="btn btn-ghost" onClick={refetch}>↻ Refresh</button>
      </div>
      <div className="page-content" style={{ maxWidth: 900 }}>

        <div style={{ marginBottom: 32 }}>
          <h3 style={{ marginBottom: 4, marginTop: 0 }}>Plan Configuration</h3>
          <p style={{ fontSize: 13, color: 'var(--text-muted)', marginBottom: 16, marginTop: 0 }}>
            Select a plan profile to set request limits and cost tracking.
          </p>
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr 1fr', gap: 16, alignItems: 'end' }}>
            <div>
              <label className="field-label">Plan</label>
              <select className="field-select" value={planType} onChange={e => setPlanType(e.target.value)} style={{ width: '100%', boxSizing: 'border-box' }}>
                {Object.entries(data.available_plans || {}).map(([k, v]) => (
                  <option key={k} value={k}>{v}</option>
                ))}
              </select>
            </div>
            <div>
              <label className="field-label">Monthly Budget (USD)</label>
              <input className="field-select" type="number" step="0.01" value={budget}
                onChange={e => setBudget(e.target.value)}
                placeholder="0 = no limit"
                style={{ width: '100%', boxSizing: 'border-box' }} />
            </div>
            <button className="btn btn-success" disabled={saving} onClick={savePlan} style={{ height: 40 }}>
              {saving ? '...' : 'Save'}
            </button>
          </div>
        </div>

        <div style={{ marginBottom: 32 }}>
          <h3 style={{ marginBottom: 16, marginTop: 0 }}>Today — {data.today}</h3>
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(300px, 1fr))', gap: 16 }}>
            {Object.entries(modelsToday).map(([model, info]) => {
              const usage = info.usage || {}
              const limits = info.limits || {}
              const req = usage.requests || 0
              const reqLimit = limits.requests || 0
              const pct = reqLimit > 0 ? Math.min((req / reqLimit) * 100, 100) : 0
              const color = pct >= 80 ? 'var(--red)' : pct >= 50 ? 'var(--amber)' : 'var(--green)'
              const shortName = model.replace('gemini-2.5-', '').replace('grok-', 'GROK ').toUpperCase()
              return (
                <div key={model} className="usage-model-card" style={{ borderLeft: `3px solid ${color}` }}>
                  <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 8 }}>
                    <div>
                      <div style={{ fontWeight: 700, fontSize: 15 }}>{shortName}</div>
                      <div style={{ fontSize: 11, color: 'var(--text-muted)', fontFamily: 'var(--mono)' }}>{model}</div>
                    </div>
                    <div style={{ textAlign: 'right' }}>
                      <div style={{ fontFamily: 'var(--mono)', fontWeight: 800, fontSize: 22, color }}>{req}</div>
                      <div style={{ fontSize: 11, color: 'var(--text-muted)' }}>/ {reqLimit || '∞'} requests</div>
                    </div>
                  </div>
                  <div className="usage-progress-track">
                    <div className="usage-progress-fill" style={{ width: `${pct}%`, background: color }} />
                  </div>
                  <div style={{ display: 'flex', justifyContent: 'space-between', marginTop: 12, fontSize: 12, color: 'var(--text-muted)' }}>
                    <span>In: {formatTokens(usage.input_tokens)} tokens</span>
                    <span>Out: {formatTokens(usage.output_tokens)} tokens</span>
                    {usage.errors > 0 && <span style={{ color: 'var(--red)' }}>{usage.errors} errors</span>}
                  </div>
                </div>
              )
            })}
          </div>
          {Object.keys(modelsToday).length === 0 && (
            <div style={{ padding: 32, textAlign: 'center', color: 'var(--text-muted)', fontSize: 14 }}>
              No API calls recorded today yet.
            </div>
          )}
        </div>

        <div style={{ marginBottom: 32 }}>
          <h3 style={{ marginBottom: 16, marginTop: 0 }}>This Month</h3>
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(180px, 1fr))', gap: 16 }}>
            {Object.entries(monthlyUsage).map(([model, stats]) => {
              const shortName = model.replace('gemini-2.5-', '').toUpperCase()
              return (
                <div key={model} className="stat-card">
                  <div className="stat-value">{stats.requests}</div>
                  <div className="stat-label">{shortName} requests</div>
                  <div style={{ fontSize: 11, color: 'var(--text-muted)', marginTop: 4 }}>
                    {formatTokens(stats.input_tokens)} in / {formatTokens(stats.output_tokens)} out
                  </div>
                </div>
              )
            })}
            {data.monthly_cost_usd > 0 && (
              <div className="usage-cost-card">
                <div style={{ fontSize: 28, fontWeight: 800, color: 'var(--accent-light)', marginBottom: 4 }}>
                  ${data.monthly_cost_usd.toFixed(2)}
                </div>
                <div style={{ fontSize: 12, color: 'var(--text-secondary)' }}>estimated cost</div>
                {data.projected_monthly_cost_usd > 0 && (
                  <div style={{ fontSize: 11, color: 'var(--text-muted)', marginTop: 4 }}>
                    Projected: ${data.projected_monthly_cost_usd.toFixed(2)}
                    {data.monthly_budget_usd > 0 && ` / $${data.monthly_budget_usd} budget`}
                  </div>
                )}
              </div>
            )}
          </div>
        </div>

        <div style={{ marginBottom: 32 }}>
          <h3 style={{ marginBottom: 16, marginTop: 0 }}>Daily History (Last 30 Days)</h3>
          {Object.keys(history).length === 0 ? (
            <div style={{ padding: 32, textAlign: 'center', color: 'var(--text-muted)', fontSize: 14 }}>
              No usage history recorded yet. Requests will appear here as you use the agents.
            </div>
          ) : (
            <div style={{ borderRadius: 'var(--radius)', border: '1px solid var(--border)', overflow: 'hidden' }}>
              <div className="usage-history-row" style={{ background: 'rgba(255,255,255,.02)', fontWeight: 600, color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '.06em', fontSize: 10 }}>
                <span>Date</span><span>Usage</span><span>Requests</span><span>Input Tokens</span><span>Output Tokens</span>
              </div>
              {Object.entries(history).reverse().map(([day, h]) => (
                <div key={day} className="usage-history-row">
                  <span style={{ color: 'var(--text-secondary)' }}>{day.slice(5)}</span>
                  <div className="usage-history-bar">
                    <div className="usage-history-bar-fill" style={{ width: `${(h.requests / maxHistoryReq) * 100}%` }} />
                  </div>
                  <span style={{ color: 'var(--text-primary)', fontWeight: 600 }}>{h.requests}</span>
                  <span style={{ color: 'var(--text-muted)' }}>{formatTokens(h.input_tokens)}</span>
                  <span style={{ color: 'var(--text-muted)' }}>{formatTokens(h.output_tokens)}</span>
                </div>
              ))}
            </div>
          )}
        </div>

        <div style={{ padding: 20, background: 'var(--surface)', borderRadius: 12, border: '1px solid var(--border)' }}>
          <h4 style={{ marginTop: 0, marginBottom: 8, fontSize: 14 }}>Google AI Plan Details</h4>
          {planType === 'free' ? (
            <div style={{ fontSize: 13, color: 'var(--text-muted)', lineHeight: 1.7 }}>
              <strong style={{ color: 'var(--text-primary)' }}>Free Tier Limits:</strong>
              <ul style={{ paddingLeft: 20, margin: '8px 0 0' }}>
                <li>Gemini 2.5 Flash: 500 requests/day, ~1M tokens/min</li>
                <li>Gemini 2.5 Pro: 25 requests/day, ~1M tokens/min</li>
                <li>Limits reset daily at midnight Pacific Time</li>
                <li>No cost — completely free</li>
              </ul>
            </div>
          ) : (
            <div style={{ fontSize: 13, color: 'var(--text-muted)', lineHeight: 1.7 }}>
              <strong style={{ color: 'var(--text-primary)' }}>Pay-as-you-go Pricing:</strong>
              <ul style={{ paddingLeft: 20, margin: '8px 0 0' }}>
                <li>Flash: $0.15 / 1M input tokens, $0.60 / 1M output tokens</li>
                <li>Pro: $1.25 / 1M input tokens, $10.00 / 1M output tokens</li>
                <li>No daily request limits</li>
              </ul>
            </div>
          )}
        </div>

      </div>
    </div>
  )
}

// ── App ──────────────────────────────────────────────────────────────────
export default function App() {
  const [page, setPage] = useState('source')
  const [visited, setVisited] = useState(() => new Set(['source']))
  const { data: queueData, refetch: refetchQueue } = useApi(`${API}/queue`)
  const { data: settingsData } = useApi(`${API}/settings`)
  const { toasts, toast } = useToast()
  const queueCount = (queueData || []).length
  const isDryRun = settingsData?.dry_run

  useEffect(() => {
    setVisited(prev => {
      if (prev.has(page)) return prev
      return new Set([...prev, page])
    })
  }, [page])

  // Request notification permission on first load
  useEffect(() => {
    if ('Notification' in window && Notification.permission === 'default') {
      Notification.requestPermission()
    }
  }, [])

  // Poll queue more frequently to catch new items
  useEffect(() => {
    const interval = setInterval(refetchQueue, 10000)
    return () => clearInterval(interval)
  }, [refetchQueue])

  useNotifications(queueCount, toast)

  return (
    <div className="layout">
      <Sidebar page={page} setPage={setPage} queueCount={queueCount} />
      <main className="main">
        <UsageGauge onClick={() => setPage('usage')} />
        {isDryRun && (
          <div className="dry-run-banner">
            DRY RUN MODE — The executor will not open a browser or submit any applications. Disable in Settings to go live.
          </div>
        )}
        {page === 'source' && <SourcePage toast={toast} />}
        {page === 'queue' && <QueuePage onUpdate={refetchQueue} toast={toast} />}
        {page === 'jobs' && <JobsPage toast={toast} />}
        {page === 'activity' && <ActivityPage />}
        {page === 'samples' && <SamplesPage toast={toast} />}
        {visited.has('profile') && (
          <div style={{ display: page === 'profile' ? undefined : 'none' }}>
            <ProfilePage toast={toast} />
          </div>
        )}
        {page === 'memory' && <MemoryPage toast={toast} />}
        {page === 'usage' && <UsagePage toast={toast} />}
        {page === 'stats' && <OverviewPage />}
        {visited.has('settings') && (
          <div style={{ display: page === 'settings' ? undefined : 'none' }}>
            <SettingsPage toast={toast} />
          </div>
        )}
      </main>
      <Toast toasts={toasts} />
    </div>
  )
}
