import { useState, useEffect } from 'react'
import DOMPurify from 'dompurify'
import { BookOpen, FileText, ExternalLink, Download } from 'lucide-react'
import { useAuth } from '../contexts/AuthContext'
import { useI18n } from '../contexts/I18nContext'
import { fetchDocList, fetchDocContent, API_BASE } from '../api/client'
import type { DocItem, DocGroup, DocContent } from '../api/client'
import PageHeader from '../components/PageHeader'
import EmptyState from '../components/EmptyState'
import styles from './Docs.module.css'

/** Human-readable labels for known doc files. */
const DOC_LABELS: Record<string, string> = {
  'onboarding.md': 'Onboarding Guide',
  'prd.md': 'PRD',
  'architecture.md': 'Architecture',
  'protocol.md': 'Protocol',
  'data-model.md': 'Data Model',
  'security-model.md': 'Security Model',
  'methodology.md': 'Methodology',
  'mvp-boundary.md': 'MVP Boundary',
  'phase-criteria.md': 'Phase Criteria',
  'CHANGELOG.md': 'CHANGELOG',
}

/** Optional short descriptions for the doc list. */
const DOC_DESCRIPTIONS: Record<string, string> = {
  'onboarding.md': 'Agent & human onboarding guide — how to connect workers, download Skills, and start collaborating.',
  'prd.md': 'Product requirements — the vision, scope, and feature roadmap for Synapse.',
  'architecture.md': 'System architecture & technology stack decisions.',
  'protocol.md': 'Human-AI coordination protocol — event types, state transitions, handshake flow.',
  'data-model.md': 'Core data entities, relationships, and schema design.',
}

export default function Docs() {
  const { t } = useI18n()
  const { token } = useAuth()
  const [docs, setDocs] = useState<DocItem[]>([])
  const [groups, setGroups] = useState<DocGroup[]>([])
  const [selected, setSelected] = useState<string | null>(null)
  const [content, setContent] = useState<DocContent | null>(null)
  const [loading, setLoading] = useState(true)
  const [loadingContent, setLoadingContent] = useState(false)
  const [error, setError] = useState<string | null>(null)

  // Fetch doc list
  useEffect(() => {
    if (!token) return
    fetchDocList(token)
      .then(data => {
        const allItems = (data.groups || []).flatMap((g: DocGroup) => g.items)
        setDocs(allItems.filter((d: DocItem) => d.exists))
        setGroups(data.groups || [])
        setLoading(false)
      })
      .catch(err => {
        setError(err.message)
        setLoading(false)
      })
  }, [token])

  // Fetch selected doc content
  useEffect(() => {
    if (!selected || !token) return
    setLoadingContent(true)
    fetchDocContent(selected, token)
      .then(data => {
        setContent(data)
        setLoadingContent(false)
      })
      .catch(err => {
        setError(err.message)
        setLoadingContent(false)
      })
  }, [selected, token])

  const label = (filename: string) => DOC_LABELS[filename] || filename
  const description = (filename: string) => DOC_DESCRIPTIONS[filename] || ''

  if (!token) {
    return (
      <EmptyState icon={BookOpen} title={t('auth.connectToSynapse')} description={t('auth.setTokenHint')} />
    )
  }

  return (
    <div>
      <PageHeader title={t('docs.heading')} />

      {loading && (
        <div className={styles.skeleton}>
          <div className={styles.skeletonSidebar}>
            <div className={styles.skeletonGroup}>
              <div className={styles.skeletonTitle} />
              <div className={styles.skeletonItem} />
              <div className={styles.skeletonItem} />
              <div className={styles.skeletonItem} />
            </div>
            <div className={styles.skeletonGroup}>
              <div className={styles.skeletonTitle} />
              <div className={styles.skeletonItem} />
              <div className={styles.skeletonItem} />
            </div>
          </div>
          <div className={styles.skeletonContent}>
            <div className={styles.skeletonContentBlock} />
          </div>
        </div>
      )}
      {error && <p className={styles.error}>{t('common.error')}: {error}</p>}

      {!loading && !error && docs.length === 0 && (
        <EmptyState icon={FileText} title={t('docs.noDocs')} description={t('docs.noDocsDesc')} />
      )}

      {docs.length > 0 && (
        <div className={styles.layout}>
          {/* ── Sidebar list ─────────────────────────────────── */}
          <aside className={styles.sidebar}>
            <h3 className={styles.sidebarTitle}>{t('docs.availableDocs')}</h3>
            {groups.map(group => {
              const visibleItems = group.items.filter((d: DocItem) => d.exists)
              if (visibleItems.length === 0) return null
              return (
                <div key={group.key} className={styles.docGroup}>
                  <h4 className={styles.docGroupTitle}>{t(group.labelKey)}</h4>
                  <ul className={styles.docList}>
                    {visibleItems.map(doc => (
                      <li key={doc.filename}>
                        <button
                          type="button"
                          className={`${styles.docItem} ${selected === doc.filename ? styles.docItemActive : ''}`}
                          onClick={() => setSelected(doc.filename)}
                        >
                          <FileText size={14} className={styles.docIcon} />
                          <div className={styles.docItemText}>
                            <span className={styles.docLabel}>{label(doc.filename)}</span>
                            {description(doc.filename) && (
                              <span className={styles.docDesc}>{description(doc.filename)}</span>
                            )}
                          </div>
                        </button>
                      </li>
                    ))}
                  </ul>
                </div>
              )
            })}
            <div className={styles.sidebarFooter}>
              <a
                href={`${API_BASE}/docs`}
                target="_blank"
                rel="noopener noreferrer"
                className={styles.externalLink}
              >
                <ExternalLink size={12} />
                {t('docs.apiDocsLink')}
              </a>
            </div>
          </aside>

          {/* ── Content area ─────────────────────────────────── */}
          <main className={styles.contentArea}>
            {!selected && (
              <div className={styles.placeholder}>
                <BookOpen size={48} className={styles.placeholderIcon} />
                <h2>{t('docs.selectDoc')}</h2>
                <p>{t('docs.selectDocDesc')}</p>
              </div>
            )}

            {selected && loadingContent && (
              <p className={styles.loading}>{t('common.loading')}</p>
            )}

            {selected && content && (
              <div className={styles.docContent}>
                <div className={styles.docHeader}>
                  <h2 className={styles.docTitle}>{label(content.filename)}</h2>
                  <div className={styles.docActions}>
                    <a
                      href={`${API_BASE}/v1/docs/${content.filename}`}
                      target="_blank"
                      rel="noopener noreferrer"
                      className={styles.actionBtn}
                    >
                      <Download size={14} />
                      {t('docs.rawBtn')}
                    </a>
                  </div>
                </div>
                <div
                  className={styles.rendered}
                  dangerouslySetInnerHTML={{ __html: DOMPurify.sanitize(content.content) }}
                />
              </div>
            )}
          </main>
        </div>
      )}
    </div>
  )
}
