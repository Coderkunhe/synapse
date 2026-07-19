/** P10-B45: WebPush subscription management hook.
 *
 * Encapsulates ServiceWorker registration, push subscription lifecycle,
 * and backend API synchronization. Exposes a simple { isSubscribed, subscribe, unsubscribe }
 * interface for UI components.
 *
 * Usage:
 *   const { isSubscribed, isSupported, subscribe, unsubscribe, loading } = usePushNotification()
 */

import { useState, useEffect, useCallback } from 'react'
import { fetchVapidPublicKey, subscribePush, unsubscribePush } from './client'

export interface UsePushNotification {
  /** Whether the browser supports push notifications (SW + PushManager). */
  isSupported: boolean
  /** Whether currently subscribed and enabled. */
  isSubscribed: boolean
  /** Loading state (initial check or subscribe/unsubscribe in progress). */
  loading: boolean
  /** Subscribe to push notifications. Requests permission, registers SW, saves to backend. */
  subscribe: () => Promise<void>
  /** Unsubscribe from push notifications. Soft-deletes on backend, unsubscribes in browser. */
  unsubscribe: () => Promise<void>
}

/** Convert base64url string to Uint8Array for PushManager.subscribe(). */
function urlBase64ToUint8Array(base64String: string): Uint8Array {
  const padding = '='.repeat((4 - (base64String.length % 4)) % 4)
  const base64 = (base64String + padding).replace(/-/g, '+').replace(/_/g, '/')
  const rawData = window.atob(base64)
  const outputArray = new Uint8Array(rawData.length)
  for (let i = 0; i < rawData.length; i++) {
    outputArray[i] = rawData.charCodeAt(i)
  }
  return outputArray
}

const SW_PATH = '/service-worker.js'

export function usePushNotification(): UsePushNotification {
  const [isSupported, setIsSupported] = useState(false)
  const [isSubscribed, setIsSubscribed] = useState(false)
  const [loading, setLoading] = useState(true)
  const [swRegistration, setSwRegistration] = useState<ServiceWorkerRegistration | null>(null)

  // ── Check support + existing subscription on mount ──────────────
  useEffect(() => {
    const supported = 'serviceWorker' in navigator && 'PushManager' in window
    setIsSupported(supported)
    if (!supported) {
      setLoading(false)
      return
    }

    init()
  }, [])

  async function init() {
    try {
      // Register Service Worker
      const reg = await navigator.serviceWorker.register(SW_PATH)
      setSwRegistration(reg)

      // Check existing push subscription
      const existingSub = await reg.pushManager.getSubscription()
      setIsSubscribed(!!existingSub)
    } catch (err) {
      console.error('usePushNotification: init failed', err)
    } finally {
      setLoading(false)
    }
  }

  // ── Subscribe ──────────────────────────────────────────────────
  const subscribe = useCallback(async () => {
    if (!swRegistration) {
      console.warn('usePushNotification: SW not registered, cannot subscribe')
      return
    }

    setLoading(true)
    try {
      // Request browser permission
      const permission = await Notification.requestPermission()
      if (permission !== 'granted') {
        console.warn('usePushNotification: notification permission denied')
        return
      }

      // Get VAPID public key from backend
      const vapidResp = await fetchVapidPublicKey()
      if (!vapidResp.vapid_public_key) {
        console.warn('usePushNotification: VAPID not configured on server')
        return
      }

      const applicationServerKey = urlBase64ToUint8Array(vapidResp.vapid_public_key)

      // Subscribe to push
      const pushSub = await swRegistration.pushManager.subscribe({
        userVisibleOnly: true,
        applicationServerKey,
      })

      // Save to backend
      const subJSON = pushSub.toJSON()
      await subscribePush({
        endpoint: subJSON.endpoint!,
        keys: {
          p256dh: (subJSON.keys as Record<string, string>).p256dh || '',
          auth: (subJSON.keys as Record<string, string>).auth || '',
        },
        device_info: navigator.userAgent,
      })

      setIsSubscribed(true)
    } catch (err) {
      console.error('usePushNotification: subscribe failed', err)
    } finally {
      setLoading(false)
    }
  }, [swRegistration])

  // ── Unsubscribe ────────────────────────────────────────────────
  const unsubscribe = useCallback(async () => {
    if (!swRegistration) return

    setLoading(true)
    try {
      const pushSub = await swRegistration.pushManager.getSubscription()
      if (pushSub) {
        const subJSON = pushSub.toJSON()
        // Soft-delete on backend
        try {
          await unsubscribePush(subJSON.endpoint!)
        } catch (err) {
          console.error('usePushNotification: backend unsubscribe failed', err)
        }
        // Unsubscribe in browser
        await pushSub.unsubscribe()
      }
      setIsSubscribed(false)
    } catch (err) {
      console.error('usePushNotification: unsubscribe failed', err)
    } finally {
      setLoading(false)
    }
  }, [swRegistration])

  return { isSupported, isSubscribed, loading, subscribe, unsubscribe }
}
