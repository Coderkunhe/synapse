// P10-B45: WebPush Service Worker
// Handles push events and notification clicks.
// Path: frontend/public/service-worker.js (static, served by Vite)

self.addEventListener('push', (event) => {
  if (!event.data) return

  try {
    const payload = event.data.json()
    const { title = 'Synapse', body = '', icon = '/favicon.svg', data = {} } = payload

    event.waitUntil(
      self.registration.showNotification(title, {
        body,
        icon,
        badge: '/favicon.svg',
        data,
        tag: data.request_id ? `synapse-req-${data.request_id}` : 'synapse-notification',
        renotify: true,
        requireInteraction: true,
      })
    )
  } catch (err) {
    console.error('[Synapse SW] Push event error:', err)
  }
})

self.addEventListener('notificationclick', (event) => {
  event.notification.close()

  const url = '/approvals'

  event.waitUntil(
    clients.matchAll({ type: 'window', includeUncontrolled: true }).then((windowClients) => {
      // Focus existing /approvals tab
      for (const client of windowClients) {
        if (client.url.includes(url) && 'focus' in client) {
          return client.focus()
        }
      }
      // Open new tab
      return clients.openWindow(url)
    })
  )
})
