import { NavLink, Outlet } from 'react-router-dom'
import {
  LayoutDashboard,
  ListTodo,
  Users,
  LogOut,
  Zap,
  BookOpen,
  ShieldCheck,
  Bell,
  BellOff,
  FolderOpen,
} from 'lucide-react'
import { useAuth } from '../contexts/AuthContext'
import { useI18n } from '../contexts/I18nContext'
import { useWebSocket } from '../api/ws'
import { usePushNotification } from '../api/usePushNotification'
import WSStatus from './WSStatus'
import styles from './Layout.module.css'

const NAV_ITEMS = [
  { to: '/dashboard', i18nKey: 'nav.dashboard', icon: LayoutDashboard },
  { to: '/tasks', i18nKey: 'nav.tasks', icon: ListTodo },
  { to: '/workers', i18nKey: 'nav.workers', icon: Users },
  { to: '/projects', i18nKey: 'nav.projects', icon: FolderOpen },
]

export default function Layout() {
  const { token, displayName, logout } = useAuth()
  const { status } = useWebSocket(token, [], logout)
  const { t, lang, setLang } = useI18n()
  const push = usePushNotification()

  return (
    <div className={styles.shell}>
      <aside className={styles.sidebar}>
        <div className={styles.brand}>
          <span className={styles.logo}><Zap size={20} /></span>
          <span className={styles.brandName}>{t('brand.name')}</span>
          <span className={styles.slogan}>{t('brand.slogan')}</span>
        </div>
        <nav className={styles.nav}>
          {NAV_ITEMS.map(({ to, i18nKey, icon: Icon }) => (
            <NavLink
              key={to}
              to={to}
              className={({ isActive }) =>
                `${styles.navItem} ${isActive ? styles.navItemActive : ''}`
              }
            >
              <span className={styles.navIcon}><Icon size={16} /></span>
              {t(i18nKey)}
            </NavLink>
          ))}
          <div className={styles.navDivider} />
          <NavLink
            to="/approvals"
            className={({ isActive }) =>
              `${styles.navItem} ${styles.navItemSupport} ${isActive ? styles.navItemActive : ''}`
            }
          >
            <span className={styles.navIcon}><ShieldCheck size={16} /></span>
            {t('approvals.heading')}
          </NavLink>
          <NavLink
            to="/docs"
            className={({ isActive }) =>
              `${styles.navItem} ${styles.navItemSupport} ${isActive ? styles.navItemActive : ''}`
            }
          >
            <span className={styles.navIcon}><BookOpen size={16} /></span>
            {t('nav.docs')}
          </NavLink>
        </nav>
        <div className={styles.footer}>
          <div className={styles.langSwitch}>
            <button
              type="button"
              className={`${styles.langBtn} ${lang === 'en' ? styles.langActive : ''}`}
              onClick={() => setLang('en')}
            >
              EN
            </button>
            <button
              type="button"
              className={`${styles.langBtn} ${lang === 'zh' ? styles.langActive : ''}`}
              onClick={() => setLang('zh')}
            >
              中文
            </button>
          </div>
          {displayName && (
            <div className={styles.userRow}>
              <span className={styles.userAvatar}>
                {displayName.charAt(0).toUpperCase()}
              </span>
              <span className={styles.userName}>{displayName}</span>
            </div>
          )}
          <WSStatus status={status} />
          {push.isSupported && (
            <button
              type="button"
              className={`${styles.pushBtn} ${push.isSubscribed ? styles.pushActive : ''}`}
              onClick={push.isSubscribed ? push.unsubscribe : push.subscribe}
              disabled={push.loading}
              title={push.isSubscribed ? t('notifications.disable') : t('notifications.enable')}
            >
              <span className={styles.navIcon}>
                {push.isSubscribed ? <Bell size={16} /> : <BellOff size={16} />}
              </span>
              {push.loading
                ? t('common.loading')
                : push.isSubscribed
                  ? t('notifications.enabled')
                  : t('notifications.enable')}
            </button>
          )}
          <div className={styles.motto}>{t('brand.motto')}</div>
          <button
            type="button"
            className={styles.logoutBtn}
            onClick={logout}
          >
            <span className={styles.navIcon}><LogOut size={16} /></span>
            {t('nav.logout')}
          </button>
        </div>
      </aside>
      <main className={styles.main}>
        <Outlet />
      </main>
    </div>
  )
}
