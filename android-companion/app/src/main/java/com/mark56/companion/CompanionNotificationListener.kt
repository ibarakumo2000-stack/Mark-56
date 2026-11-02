package com.mark56.companion

import android.service.notification.NotificationListenerService
import android.service.notification.StatusBarNotification
import android.util.Log
import java.util.concurrent.Executors

/**
 * Explicitly opt-in notification relay. Android only binds this service after
 * the user grants Notification Access in system settings. We additionally gate
 * forwarding on the app toggle and the desktop-approved notification.receive scope.
 */
class CompanionNotificationListener : NotificationListenerService() {
    private val worker = Executors.newSingleThreadExecutor()

    override fun onNotificationPosted(sbn: StatusBarNotification) {
        val settings = CompanionSettings(this)
        if (!settings.notificationRelayEnabled() || !settings.hasNotificationScope()) return
        val endpoint = settings.endpoint() ?: return
        val fingerprint = settings.fingerprint() ?: return
        val deviceId = settings.deviceId() ?: return
        val token = SecureTokenStore(getSharedPreferences("companion_secure", MODE_PRIVATE)).read() ?: return

        val extras = sbn.notification.extras
        val title = extras.getCharSequence(android.app.Notification.EXTRA_TITLE)?.toString().orEmpty()
        val text = extras.getCharSequence(android.app.Notification.EXTRA_TEXT)?.toString().orEmpty()
        if (title.isBlank() && text.isBlank()) return

        // Restrict the payload to app label and the displayed title/text; no icon,
        // URI, actions, person objects, or notification metadata is forwarded.
        val appLabel = try {
            packageManager.getApplicationLabel(packageManager.getApplicationInfo(sbn.packageName, 0)).toString()
        } catch (_: Exception) {
            sbn.packageName
        }.take(80)

        worker.execute {
            try {
                val client = CompanionEventClient(endpoint, fingerprint, token, deviceId)
                val result = client.postNotification(appLabel, title.take(512), text.take(512), sbn.postTime / 1000L)
                if (result !in 200..299) Log.w("Mark56Relay", "Desktop rejected notification event ($result)")
            } catch (e: Exception) {
                Log.w("Mark56Relay", "Notification relay delivery failed", e)
            }
        }
    }

    override fun onDestroy() {
        worker.shutdownNow()
        super.onDestroy()
    }
}
