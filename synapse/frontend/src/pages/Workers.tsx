import { useSearchParams } from 'react-router-dom'
import { useI18n } from '../contexts/I18nContext'
import PageHeader from '../components/PageHeader'
import WorkerList from './WorkerList'
import Teams from './Teams'
import styles from './Workers.module.css'

const TABS = [
  { key: 'workers', i18nKey: 'workers.listTab' },
  { key: 'team', i18nKey: 'workers.teamTab' },
] as const

export default function Workers() {
  const { t } = useI18n()
  const [searchParams, setSearchParams] = useSearchParams()
  const activeTab = searchParams.get('tab') === 'team' ? 'team' : 'workers'

  const switchTab = (key: string) => {
    setSearchParams(key === 'workers' ? {} : { tab: key }, { replace: true })
  }

  return (
    <div>
      <PageHeader title={t('workers.heading')} />

      <div className={styles.tabBar}>
        {TABS.map(({ key, i18nKey }) => (
          <button
            key={key}
            type="button"
            className={`${styles.tab} ${activeTab === key ? styles.tabActive : ''}`}
            onClick={() => switchTab(key)}
          >
            {t(i18nKey)}
          </button>
        ))}
      </div>

      {activeTab === 'workers' ? <WorkerList /> : <Teams />}
    </div>
  )
}
