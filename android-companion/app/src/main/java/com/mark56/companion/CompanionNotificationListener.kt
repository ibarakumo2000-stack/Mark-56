package com.mark56.companion

import android.content.ComponentName
import android.media.session.MediaController
import android.media.session.MediaSessionManager
import android.os.Handler
import android.os.Looper
import android.service.notification.NotificationListenerService
import android.service.notification.StatusBarNotification
import android.util.Log
import java.util.concurrent.Executors

/**
 * Opt-in notification relay and desktop-authorized media controls.
 * Media actions require the Android notification-listener grant, a local toggle,
 * and the desktop-approved media.control scope.
 */
class CompanionNotificationListener : NotificationListenerService() {
    private val worker = Executors.newSingleThreadExecutor()
    private val handler = Handler(Looper.getMainLooper())

    private val mediaPoll = object : Runnable {
        override fun run() {
            val settings = CompanionSettings(this@CompanionNotificationListener)
            if (!settings.mediaControlEnabled() || !settings.hasMediaScope()) return
            val endpoint = settings.endpoint() ?: return
            val fingerprint = settings.fingerprint() ?: return
            val deviceId = settings.deviceId() ?: return
            val token = SecureTokenStore(
                getSharedPreferences("companion_secure", MODE_PRIVATE)
            ).read() ?: return

            worker.execute {
                try {
                    val client = CompanionEventClient(endpoint, fingerprint, token, deviceId)
                    val action = client.pollMediaCommand()
                    if (action != null) executeMediaAction(action)
                } catch (e: Exception) {
                    // Never log media metadata, credentials, or notification content.
                    Log.w("Mark56Media", "Media command poll failed (" + e.javaClass.simpleName + ")")
                } finally {
                    handler.post {
                        val current = CompanionSettings(this@CompanionNotificationListener)
                        if (current.mediaControlEnabled() && current.hasMediaScope()) {
                            handler.postDelayed(this, MediaCommandPolicy.POLL_INTERVAL_MS)
                        }
                    }
                }
            }
        }
    }

    override fun onListenerConnected() {
        super.onListenerConnected()
        handler.removeCallbacks(mediaPoll)
        handler.post(mediaPoll)
    }

    override fun onListenerDisconnected() {
        handler.removeCallbacks(mediaPoll)
        super.onListenerDisconnected()
    }

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
        val appLabel = try {
            packageManager.getApplicationLabel(packageManager.getApplicationInfo(sbn.packageName, 0)).toString()
        } catch (_: Exception) {
            sbn.packageName
        }
        val payload = NotificationRelayPolicy.create(appLabel, title, text, sbn.postTime / 1000L) ?: return

        worker.execute {
            try {
                val client = CompanionEventClient(endpoint, fingerprint, token, deviceId)
                val result = client.postNotification(payload.app, payload.title, payload.text, payload.occurredAt)
                if (result !in 200..299) Log.w("Mark56Relay", "Desktop rejected notification event ($result)")
            } catch (e: Exception) {
                Log.w("Mark56Relay", "Notification relay delivery failed (" + e.javaClass.simpleName + ")")
            }
        }
    }

    private fun executeMediaAction(action: String) {
        val settings = CompanionSettings(this)
        if (!settings.mediaControlEnabled() || !settings.hasMediaScope()) return
        val manager = getSystemService(MEDIA_SESSION_SERVICE) as MediaSessionManager
        val sessions = manager.getActiveSessions(
            ComponentName(this, CompanionNotificationListener::class.java)
        )
        val eligible = sessions.filter { controller ->
            val state = controller.playbackState?.state
            state == android.media.session.PlaybackState.STATE_PLAYING ||
                state == android.media.session.PlaybackState.STATE_PAUSED ||
                state == android.media.session.PlaybackState.STATE_BUFFERING ||
                state == android.media.session.PlaybackState.STATE_CONNECTING
        }
        // Never guess which app to control when more than one media session is active.
        if (eligible.size != 1) return
        val controller: MediaController = eligible.single()
        val state = controller.playbackState?.state
        val resolved = MediaCommandPolicy.resolve(
            action, state == android.media.session.PlaybackState.STATE_PLAYING
        ) ?: return
        try {
            when (resolved) {
                "play" -> controller.transportControls.play()
                "pause" -> controller.transportControls.pause()
                "next" -> controller.transportControls.skipToNext()
                "previous" -> controller.transportControls.skipToPrevious()
                "stop" -> controller.transportControls.stop()
            }
        } catch (e: SecurityException) {
            Log.w("Mark56Media", "Android rejected media action (" + e.javaClass.simpleName + ")")
        }
    }

    override fun onDestroy() {
        handler.removeCallbacks(mediaPoll)
        worker.shutdownNow()
        super.onDestroy()
    }
}
