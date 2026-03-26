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

// ── Sidebar ──────────────────────────────────────────────────────────────
function Sidebar({ page, setPage, queueCount }) {
  const items = [
    { id: 'queue', label: 'Review Queue', icon: '📝', badge: queueCount },
    { id: 'jobs', label: 'All Jobs', icon: '💼' },
    { id: 'memory', label: 'AI Memory', icon: '🧠' },
    { id: 'stats', label: 'Overview', icon: '📊' },
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

// ── Overview Page ────────────────────────────────────────────────────────
function OverviewPage() {
  const { data, loading, refetch } = useApi(`${API}/stats`)
  if (loading) return <div className="page-content empty"><div className="empty-icon spin">⚙️</div></div>
  if (!data) return null
  const cards = [
    { label: 'Total Sourced', value: data.total_sourced },
    { label: 'Analyzed', value: data.total_analyzed },
    { label: 'Pending Review', value: data.pending_review, cls: 'amber' },
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
      <div className="modal" onClick={e => e.stopPropagation()} style={{ maxWidth: '900px', width: '90%' }}>
        <div className="modal-header">
          <h3>Application Screenshots — Job #{jobId}</h3>
          <button className="btn btn-ghost" onClick={onClose}>✕</button>
        </div>
        {loading ? <div className="empty"><div className="empty-icon spin">⚙️</div></div> :
          screenshots.length === 0 ? <div className="empty"><p>No screenshots captured yet.</p></div> :
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(260px, 1fr))', gap: 16, padding: 24 }}>
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
      toast('✅ Rule saved — AI will follow this from now on', 'success')
      onClose()
    } catch (e) { toast('Error: ' + e.message, 'error') }
    setSaving(false)
  }

  return (
    <div className="modal-overlay" onClick={onClose}>
      <div className="modal" onClick={e => e.stopPropagation()} style={{ maxWidth: '560px' }}>
        <div className="modal-header">
          <h3>⚠️ Flag an AI Mistake</h3>
          <button className="btn btn-ghost" onClick={onClose}>✕</button>
        </div>
        <div style={{ padding: '24px', display: 'flex', flexDirection: 'column', gap: 16 }}>
          <p style={{ fontSize: 13, color: 'var(--text-muted)', margin: 0 }}>
            Describe what the AI did wrong. This will be stored and injected into every future prompt for that agent.
          </p>
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12 }}>
            <div>
              <label className="field-label">Agent</label>
              <select className="field-select" value={agent} onChange={e => setAgent(e.target.value)}>
                <option value="analyzer">Analyzer</option>
                <option value="cover_letter">Cover Letter</option>
                <option value="executor">Executor / Form Filler</option>
                <option value="sourcer">Sourcer</option>
              </select>
            </div>
            <div>
              <label className="field-label">Severity</label>
              <select className="field-select" value={severity} onChange={e => setSeverity(e.target.value)}>
                <option value="low">🔵 Low (note)</option>
                <option value="medium">🟡 Medium (important)</option>
                <option value="high">🔴 High (critical)</option>
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
              {saving ? '...' : '💾 Save Rule'}
            </button>
          </div>
        </div>
      </div>
    </div>
  )
}

// ── Cover Letter Queue Page ───────────────────────────────────────────────
function QueuePage({ onUpdate, toast }) {
  const { data: items, loading, refetch } = useApi(`${API}/queue`)
  const [selected, setSelected] = useState(null)
  const [editContent, setEditContent] = useState('')
  const [pasteOpen, setPasteOpen] = useState(false)
  const [pasteText, setPasteText] = useState('')
  const [saving, setSaving] = useState(false)
  const [showFlag, setShowFlag] = useState(false)

  const selectItem = (item) => { setSelected(item); setEditContent(item.draft_content); setPasteOpen(false); setPasteText('') }

  const copyPrompt = async () => {
    if (!selected?.prompt_content) {
      toast('No prompt available yet', 'error'); return
    }
    await navigator.clipboard.writeText(selected.prompt_content)
    toast('📋 Prompt copied! Paste into Gemini or Claude.', 'success')
  }

  const applyPaste = async () => {
    if (!pasteText.trim() || !selected) return
    setSaving(true)
    try {
      const r = await fetch(`${API}/queue/${selected.id}/paste`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ pasted_response: pasteText }),
      })
      if (!r.ok) throw new Error('Failed')
      const data = await r.json()
      setEditContent(data.draft_content)
      setPasteOpen(false)
      setPasteText('')
      toast(`✅ Applied ${data.sections_applied?.length || 0} section(s)`, 'success')
    } catch (e) { toast('Error: ' + e.message, 'error') }
    setSaving(false)
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
      toast(action === 'approve' ? '✅ Approved!' : '❌ Rejected', action === 'approve' ? 'success' : 'error')
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
          <div className="page-title">Review Queue</div>
          <div className="page-subtitle">{list.length} cover letter{list.length !== 1 ? 's' : ''} awaiting review</div>
        </div>
        <div style={{ display: 'flex', gap: 8 }}>
          <button className="btn btn-ghost" onClick={() => setShowFlag(true)}>⚠️ Flag AI Mistake</button>
          <button className="btn btn-ghost" onClick={refetch}>↻ Refresh</button>
        </div>
      </div>

      <div className="page-content">
        {list.length === 0 ? (
          <div className="empty">
            <div className="empty-icon">✨</div>
            <h3>Queue is clear!</h3>
            <p>No cover letters pending review.</p>
          </div>
        ) : (
          <div style={{ display: 'grid', gridTemplateColumns: selected ? '340px 1fr' : '1fr', gap: 24, alignItems: 'start' }}>
            <div className="queue-list">
              {list.map(item => (
                <div key={item.id} className={`queue-card ${selected?.id === item.id ? 'selected' : ''}`} onClick={() => selectItem(item)}>
                  <div className="queue-card-header">
                    <div>
                      <div className="queue-job-title">{item.job_title}</div>
                      <div className="queue-company">{item.job_company}</div>
                    </div>
                    <span className="tag tag-amber">Pending</span>
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
                    {selected.prompt_content && (
                      <button className="btn btn-ghost" style={{ fontSize: 13 }} onClick={copyPrompt}>
                        📋 Copy Prompt
                      </button>
                    )}
                    <button
                      className="btn btn-ghost"
                      style={{ fontSize: 13, color: pasteOpen ? 'var(--accent)' : undefined }}
                      onClick={() => setPasteOpen(p => !p)}
                    >
                      📥 Paste AI Response
                    </button>
                  </div>
                </div>

                {/* Paste-back area */}
                {pasteOpen && (
                  <div style={{ padding: '16px 24px', background: 'var(--surface)', borderBottom: '1px solid var(--border)' }}>
                    <p style={{ fontSize: 13, color: 'var(--text-muted)', marginBottom: 8 }}>
                      Paste the AI's response below. Sections will be automatically extracted and applied to the template.
                    </p>
                    <textarea
                      value={pasteText}
                      onChange={e => setPasteText(e.target.value)}
                      rows={6}
                      className="field-textarea"
                      placeholder="Paste the full response from Gemini / Claude here..."
                    />
                    <div style={{ display: 'flex', justifyContent: 'flex-end', gap: 8, marginTop: 8 }}>
                      <button className="btn btn-ghost" onClick={() => { setPasteOpen(false); setPasteText('') }}>Cancel</button>
                      <button className="btn btn-accent" disabled={saving || !pasteText.trim()} onClick={applyPaste}>
                        {saving ? '...' : '✓ Apply Sections'}
                      </button>
                    </div>
                  </div>
                )}

                <textarea
                  value={editContent}
                  onChange={e => setEditContent(e.target.value)}
                  style={{
                    width: '100%', minHeight: 380, background: 'transparent', border: 'none',
                    outline: 'none', fontFamily: 'var(--mono)', fontSize: 13.5, lineHeight: 1.8,
                    color: 'var(--text-primary)', padding: 24, resize: 'vertical', boxSizing: 'border-box',
                  }}
                />
                <div className="editor-actions">
                  <button className="btn btn-ghost" onClick={() => setSelected(null)}>Cancel</button>
                  <button className="btn btn-danger" disabled={saving} onClick={() => handleAction('reject')}>✕ Reject</button>
                  <button className="btn btn-success" disabled={saving} onClick={() => handleAction('approve')}>
                    {saving ? '...' : '✓ Approve & Queue'}
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
      <div className="page-content">
        {(jobs || []).length === 0 ? (
          <div className="empty"><div className="empty-icon">💼</div><h3>No jobs yet</h3><p>Start the agent to begin sourcing.</p></div>
        ) : (
          <div className="table-wrap">
            <table>
              <thead><tr>
                <th>Title</th><th>Company</th><th>Source</th><th>Resume</th>
                <th>Score</th><th>Status</th><th>Actions</th>
              </tr></thead>
              <tbody>
                {(jobs || []).map(job => (
                  <tr key={job.id}>
                    <td className="td-title" title={job.title}>{job.title}</td>
                    <td className="td-company">{job.company}</td>
                    <td><span className="tag tag-muted">{job.source}</span></td>
                    <td>{job.resume_type ? <span className="tag tag-purple">{job.resume_type}</span> : <span style={{ color: 'var(--text-muted)' }}>—</span>}</td>
                    <td>{job.relevance_score != null
                      ? <span style={{ fontFamily: 'var(--mono)', fontWeight: 700, color: job.relevance_score >= 0.7 ? 'var(--green)' : job.relevance_score >= 0.5 ? 'var(--amber)' : 'var(--red)' }}>
                          {(job.relevance_score * 100).toFixed(0)}%
                        </span>
                      : <span style={{ color: 'var(--text-muted)' }}>—</span>}
                    </td>
                    <td><Status s={job.status} /></td>
                    <td>
                      <div style={{ display: 'flex', gap: 6 }}>
                        <a href={job.url} target="_blank" rel="noreferrer" className="btn btn-ghost" style={{ padding: '5px 10px', fontSize: 12 }}>↗</a>
                        {job.status === 'applied' && (
                          <button className="btn btn-ghost" style={{ padding: '5px 10px', fontSize: 12 }} onClick={() => setScreenshotJobId(job.id)}>🖼️</button>
                        )}
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
      {screenshotJobId && <ScreenshotModal jobId={screenshotJobId} onClose={() => setScreenshotJobId(null)} />}
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
      toast('🗑️ Rule deleted', 'success')
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

  const agentLabels = { analyzer: '🔍 Analyzer', cover_letter: '✉️ Cover Letter', executor: '🤖 Executor', sourcer: '🌐 Sourcer' }
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
              <p>When you notice the AI making a mistake, click "Flag AI Mistake" in the queue or "+ Add Rule" here.<br />Rules are injected into every future prompt so the AI won't repeat the mistake.</p>
            </div>
          ) : (
            <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
              {allRules.map(rule => (
                <div key={rule.id} className="card" style={{
                  padding: 20, opacity: rule.enabled ? 1 : 0.5,
                  borderLeft: `3px solid ${severityColors[rule.severity] || 'var(--border)'}`,
                }}>
                  <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', gap: 16 }}>
                    <div style={{ flex: 1 }}>
                      <div style={{ display: 'flex', gap: 8, marginBottom: 8, flexWrap: 'wrap' }}>
                        <span className="tag tag-muted">{agentLabels[rule.agent] || rule.agent}</span>
                        <span className="tag" style={{ background: severityColors[rule.severity] + '22', color: severityColors[rule.severity], border: `1px solid ${severityColors[rule.severity]}44` }}>{rule.severity}</span>
                        {!rule.enabled && <span className="tag tag-muted">disabled</span>}
                        <span className="tag tag-muted">triggered {rule.times_triggered}×</span>
                      </div>
                      <div style={{ fontWeight: 600, marginBottom: 6, color: 'var(--text-primary)' }}>{rule.description}</div>
                      {rule.example_bad && <div style={{ fontSize: 13, color: 'var(--red)', marginBottom: 4 }}>❌ {rule.example_bad}</div>}
                      <div style={{ fontSize: 13, color: 'var(--green)' }}>✅ {rule.correction}</div>
                    </div>
                    <div style={{ display: 'flex', gap: 6, flexShrink: 0 }}>
                      <button className="btn btn-ghost" style={{ fontSize: 13, padding: '5px 10px' }} onClick={() => toggleRule(rule)}>
                        {rule.enabled ? '⏸ Disable' : '▶ Enable'}
                      </button>
                      <button className="btn btn-danger" style={{ fontSize: 13, padding: '5px 10px' }} disabled={deleting === rule.id} onClick={() => deleteRule(rule.id)}>
                        🗑️
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
        {page === 'jobs' && <JobsPage toast={toast} />}
        {page === 'memory' && <MemoryPage toast={toast} />}
        {page === 'stats' && <OverviewPage />}
      </main>
      <Toast toasts={toasts} />
    </div>
  )
}
