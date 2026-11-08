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
    @Volatile private var listenerConnected = false

    private val mediaPoll = object : Runnable {
        private fun scheduleNext() {
            if (listenerConnected) handler.postDelayed(this, MediaCommandPolicy.POLL_INTERVAL_MS)
        }

        override fun run() {
            val settings = CompanionSettings(this@CompanionNotificationListener)
            if (!settings.mediaControlEnabled() || !settings.hasMediaScope()) {
                scheduleNext()
                return
            }
            val endpoint = settings.endpoint()
            val fingerprint = settings.fingerprint()
            val deviceId = settings.deviceId()
            val token = SecureTokenStore(
                getSharedPreferences("companion_secure", MODE_PRIVATE)
            ).read()
            if (endpoint == null || fingerprint == null || deviceId == null || token == null) {
                scheduleNext()
                return
            }

            val manager = getSystemService(MEDIA_SESSION_SERVICE) as MediaSessionManager
            val active = try {
                manager.getActiveSessions(ComponentName(this@CompanionNotificationListener,
                    CompanionNotificationListener::class.java)).filter { controller ->
                    val state = controller.playbackState?.state
                    state == android.media.session.PlaybackState.STATE_PLAYING ||
                        state == android.media.session.PlaybackState.STATE_PAUSED ||
                        state == android.media.session.PlaybackState.STATE_BUFFERING ||
                        state == android.media.session.PlaybackState.STATE_CONNECTING
                }
            } catch (e: SecurityException) {
                Log.w("Mark56Media", "Notification access is unavailable for media sessions")
                emptyList()
            }
            // Publish metadata only when one session is unambiguous. Never guess
            // between two active apps; an empty snapshot clears stale dashboard state.
            val snapshot = if (active.size == 1) {
                val controller = active.single()
                val metadata = controller.metadata
                val packageName = controller.packageName
                val appLabel = try {
                    packageManager.getApplicationLabel(packageManager.getApplicationInfo(packageName, 0)).toString()
                } catch (_: Exception) { packageName }
                val playback = controller.playbackState
                Triple(
                    appLabel,
                    metadata?.getString(android.media.MediaMetadata.METADATA_KEY_TITLE).orEmpty(),
                    metadata?.getString(android.media.MediaMetadata.METADATA_KEY_ARTIST).orEmpty()
                ) to listOf(
                    metadata?.getString(android.media.MediaMetadata.METADATA_KEY_ALBUM).orEmpty(),
                    playback?.state == android.media.session.PlaybackState.STATE_PLAYING,
                    (playback?.position ?: 0L).coerceIn(0L, 86_400_000L),
                    (metadata?.getLong(android.media.MediaMetadata.METADATA_KEY_DURATION) ?: 0L).coerceIn(0L, 86_400_000L)
                )
            } else null

            worker.execute {
                try {
                    val client = CompanionEventClient(endpoint, fingerprint, token, deviceId)
                    if (snapshot == null) {
                        client.postMediaState("", "", "", "", false, 0L, 0L)
                    } else {
                        val (identity, details) = snapshot
                        client.postMediaState(identity.first, identity.second, identity.third,
                            details[0] as String, details[1] as Boolean,
                            details[2] as Long, details[3] as Long)
                    }
                    val action = client.pollMediaCommand()
                    if (action != null) executeMediaAction(action)
                } catch (e: Exception) {
                    // Never log media metadata, credentials, or notification content.
                    Log.w("Mark56Media", "Media command poll failed (" + e.javaClass.simpleName + ")")
                } finally {
                    handler.post { scheduleNext() }
                }
            }
        }
    }

    override fun onListenerConnected() {
        super.onListenerConnected()
        listenerConnected = true
        handler.removeCallbacks(mediaPoll)
        handler.post(mediaPoll)
    }

    override fun onListenerDisconnected() {
        listenerConnected = false
        handler.removeCallbacks(mediaPoll)
        super.onListenerDisconnected()
    }

    override fun onNotificationPosted(sbn: StatusBarNotification) {
        val settings = CompanionSettings(this)
        if (!settings.notificationRelayEnabled() || !settings.hasNotificationScope()) return
        if (sbn.packageName == packageName) return // prevent forwarding JARVIS's own status notifications
        if (sbn.packageName in settings.excludedNotificationPackages()) return
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
        listenerConnected = false
        handler.removeCallbacks(mediaPoll)
        worker.shutdownNow()
        super.onDestroy()
    }
}
