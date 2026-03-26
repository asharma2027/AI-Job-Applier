import { useState, useEffect, useCallback } from 'react'
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
      {toasts.map(t => (
        <div key={t.id} className={`toast toast-${t.type}`}>{t.msg}</div>
      ))}
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

// ── Sidebar ──────────────────────────────────────────────────────────────
function Sidebar({ page, setPage, queueCount }) {
  const items = [
    { id: 'queue', label: 'Review Queue', icon: '📝', badge: queueCount },
    { id: 'jobs', label: 'All Jobs', icon: '💼' },
    { id: 'stats', label: 'Overview', icon: '📊' },
  ]
  return (
    <aside className="sidebar">
      <div className="sidebar-logo">
        <div className="logo-icon">🤖</div>
        <div>
          <div className="logo-text">Job Applier</div>
          <div className="logo-sub">Agent</div>
        </div>
      </div>
      <div className="nav-section">
        <div className="nav-label">Navigation</div>
        {items.map(item => (
          <button key={item.id} className={`nav-item ${page === item.id ? 'active' : ''}`} onClick={() => setPage(item.id)}>
            <span>{item.icon}</span>
            <span>{item.label}</span>
            {item.badge > 0 && <span className="badge">{item.badge}</span>}
          </button>
        ))}
      </div>
    </aside>
  )
}

// ── Status Pill ──────────────────────────────────────────────────────────
function Status({ s }) {
  return <span className={`status status-${s.replace(/ /g, '_')}`}>{s.replace(/_/g, ' ')}</span>
}

// ── Overview Page ────────────────────────────────────────────────────────
function OverviewPage() {
  const { data, loading, refetch } = useApi(`${API}/stats`)

  if (loading) return <div className="page-content empty"><div className="empty-icon spin">⚙️</div></div>
  if (!data) return null

  const cards = [
    { label: 'Total Sourced', value: data.total_sourced, cls: '' },
    { label: 'Analyzed', value: data.total_analyzed, cls: '' },
    { label: 'Pending Review', value: data.pending_review, cls: 'amber' },
    { label: 'Queued', value: data.total_queued, cls: 'accent' },
    { label: 'Applied', value: data.total_applied, cls: 'green' },
    { label: 'Failed', value: data.total_failed, cls: 'red' },
    { label: 'Skipped', value: data.total_skipped, cls: '' },
  ]

  return (
    <div>
      <div className="page-header">
        <div>
          <div className="page-title">Overview</div>
          <div className="page-subtitle">Pipeline status at a glance</div>
        </div>
        <button className="btn btn-ghost" onClick={refetch}>↻ Refresh</button>
      </div>
      <div className="page-content">
        <div className="stats-grid">
          {cards.map(c => (
            <div key={c.label} className={`stat-card ${c.cls}`}>
              <div className="stat-value">{c.value ?? 0}</div>
              <div className="stat-label">{c.label}</div>
            </div>
          ))}
        </div>
        <div className="card" style={{ padding: '24px' }}>
          <h3 style={{ marginBottom: '12px', fontSize: '16px' }}>Pipeline Flow</h3>
          <div style={{ display: 'flex', alignItems: 'center', gap: '8px', flexWrap: 'wrap' }}>
            {['Source', '→', 'Analyze', '→', 'Draft CL', '→', 'Review', '→', 'Execute', '→', 'Applied'].map((s, i) => (
              <span key={i} style={{
                padding: s === '→' ? '0 4px' : '6px 14px',
                borderRadius: '20px',
                fontSize: '13px',
                fontWeight: '600',
                background: s === '→' ? 'none' : 'var(--surface-hover)',
                color: s === '→' ? 'var(--text-muted)' : 'var(--text-secondary)',
                border: s === '→' ? 'none' : '1px solid var(--border)',
              }}>{s}</span>
            ))}
          </div>
        </div>
      </div>
    </div>
  )
}

// ── Simple editor (contenteditable textarea) ─────────────────────────────
function SimpleEditor({ content, onChange }) {
  return (
    <textarea
      value={content}
      onChange={e => onChange(e.target.value)}
      style={{
        width: '100%',
        minHeight: '420px',
        background: 'transparent',
        border: 'none',
        outline: 'none',
        fontFamily: 'var(--mono)',
        fontSize: '13.5px',
        lineHeight: '1.8',
        color: 'var(--text-primary)',
        padding: '24px',
        resize: 'vertical',
      }}
    />
  )
}

// ── Review Queue Page ────────────────────────────────────────────────────
function QueuePage({ onUpdate, toast }) {
  const { data: items, loading, refetch } = useApi(`${API}/queue`)
  const [selected, setSelected] = useState(null)
  const [editContent, setEditContent] = useState('')
  const [saving, setSaving] = useState(false)

  const selectItem = (item) => {
    setSelected(item)
    setEditContent(item.draft_content)
  }

  const handleAction = async (action) => {
    if (!selected) return
    setSaving(true)
    try {
      const r = await fetch(`${API}/queue/${selected.id}`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ content: editContent, action }),
      })
      if (!r.ok) throw new Error('Failed')
      toast(action === 'approve' ? '✅ Cover letter approved!' : '❌ Application rejected', action === 'approve' ? 'success' : 'error')
      setSelected(null)
      refetch()
      onUpdate()
    } catch (e) {
      toast('Error: ' + e.message, 'error')
    }
    setSaving(false)
  }

  if (loading) return <div className="page-content empty"><div className="empty-icon spin">⚙️</div></div>

  const list = items || []

  return (
    <div>
      <div className="page-header">
        <div>
          <div className="page-title">Review Queue</div>
          <div className="page-subtitle">{list.length} cover letter{list.length !== 1 ? 's' : ''} awaiting review</div>
        </div>
        <button className="btn btn-ghost" onClick={refetch}>↻ Refresh</button>
      </div>
      <div className="page-content">
        {list.length === 0 ? (
          <div className="empty">
            <div className="empty-icon">✨</div>
            <h3>Queue is clear!</h3>
            <p>No cover letters pending review. The agent is working in the background.</p>
          </div>
        ) : (
          <div style={{ display: 'grid', gridTemplateColumns: selected ? '360px 1fr' : '1fr', gap: '24px', alignItems: 'start' }}>
            <div className="queue-list">
              {list.map(item => (
                <div
                  key={item.id}
                  className={`queue-card ${selected?.id === item.id ? 'selected' : ''}`}
                  onClick={() => selectItem(item)}
                >
                  <div className="queue-card-header">
                    <div>
                      <div className="queue-job-title">{item.job_title}</div>
                      <div className="queue-company">{item.job_company}</div>
                    </div>
                    <span className="tag tag-amber">Pending</span>
                  </div>
                  <div className="queue-meta">
                    <span className="tag tag-muted">Cover Letter</span>
                    <span className="tag tag-purple">
                      {new Date(item.created_at).toLocaleDateString()}
                    </span>
                  </div>
                </div>
              ))}
            </div>

            {selected && (
              <div className="editor-pane">
                <div className="editor-toolbar">
                  <strong style={{ fontSize: '14px', color: 'var(--text-primary)' }}>
                    {selected.job_title} @ {selected.job_company}
                  </strong>
                </div>
                <SimpleEditor content={editContent} onChange={setEditContent} />
                <div className="editor-actions">
                  <button className="btn btn-ghost" onClick={() => setSelected(null)}>Cancel</button>
                  <button className="btn btn-danger" disabled={saving} onClick={() => handleAction('reject')}>
                    ✕ Reject
                  </button>
                  <button className="btn btn-success" disabled={saving} onClick={() => handleAction('approve')}>
                    {saving ? '...' : '✓ Approve & Queue'}
                  </button>
                </div>
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  )
}

// ── Jobs Table Page ──────────────────────────────────────────────────────
function JobsPage() {
  const [statusFilter, setStatusFilter] = useState('')
  const { data: jobs, loading, refetch } = useApi(
    `${API}/jobs${statusFilter ? `?status=${statusFilter}` : ''}`,
    [statusFilter]
  )

  const statuses = ['new', 'analyzed', 'queued', 'awaiting_review', 'applying', 'applied', 'failed', 'skipped']

  if (loading) return <div className="page-content empty"><div className="empty-icon spin">⚙️</div></div>

  return (
    <div>
      <div className="page-header">
        <div>
          <div className="page-title">All Jobs</div>
          <div className="page-subtitle">{(jobs || []).length} jobs in the pipeline</div>
        </div>
        <div style={{ display: 'flex', gap: '12px' }}>
          <select
            value={statusFilter}
            onChange={e => setStatusFilter(e.target.value)}
            style={{
              background: 'var(--surface)', border: '1px solid var(--border)',
              borderRadius: '8px', color: 'var(--text-primary)', padding: '8px 12px',
              fontSize: '13px', cursor: 'pointer',
            }}
          >
            <option value="">All Statuses</option>
            {statuses.map(s => <option key={s} value={s}>{s.replace(/_/g, ' ')}</option>)}
          </select>
          <button className="btn btn-ghost" onClick={refetch}>↻ Refresh</button>
        </div>
      </div>
      <div className="page-content">
        {(jobs || []).length === 0 ? (
          <div className="empty">
            <div className="empty-icon">💼</div>
            <h3>No jobs yet</h3>
            <p>Start the agent to begin sourcing internship listings.</p>
          </div>
        ) : (
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>Title</th>
                  <th>Company</th>
                  <th>Source</th>
                  <th>Resume</th>
                  <th>Score</th>
                  <th>Status</th>
                  <th>Link</th>
                </tr>
              </thead>
              <tbody>
                {(jobs || []).map(job => (
                  <tr key={job.id}>
                    <td className="td-title" title={job.title}>{job.title}</td>
                    <td className="td-company">{job.company}</td>
                    <td><span className="tag tag-muted td-source">{job.source}</span></td>
                    <td>
                      {job.resume_type
                        ? <span className="tag tag-purple">{job.resume_type}</span>
                        : <span style={{ color: 'var(--text-muted)' }}>—</span>}
                    </td>
                    <td>
                      {job.relevance_score != null
                        ? <span style={{ fontFamily: 'var(--mono)', fontWeight: '700', color: job.relevance_score >= 0.7 ? 'var(--green)' : job.relevance_score >= 0.5 ? 'var(--amber)' : 'var(--red)' }}>
                            {(job.relevance_score * 100).toFixed(0)}%
                          </span>
                        : <span style={{ color: 'var(--text-muted)' }}>—</span>}
                    </td>
                    <td><Status s={job.status} /></td>
                    <td>
                      <a href={job.url} target="_blank" rel="noreferrer" className="btn btn-ghost" style={{ padding: '6px 12px', fontSize: '12px' }}>
                        ↗ Open
                      </a>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  )
}

// ── App ──────────────────────────────────────────────────────────────────
export default function App() {
  const [page, setPage] = useState('queue')
  const { data: queueData, refetch: refetchQueue } = useApi(`${API}/queue`)
  const { toasts, toast } = useToast()
  const queueCount = (queueData || []).length

  return (
    <div className="layout">
      <Sidebar page={page} setPage={setPage} queueCount={queueCount} />
      <main className="main">
        {page === 'queue' && <QueuePage onUpdate={refetchQueue} toast={toast} />}
        {page === 'jobs' && <JobsPage />}
        {page === 'stats' && <OverviewPage />}
      </main>
      <Toast toasts={toasts} />
    </div>
  )
}
