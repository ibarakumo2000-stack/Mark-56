package com.mark56.companion

import android.util.Log
import com.google.android.gms.wearable.MessageEvent
import com.google.android.gms.wearable.WearableListenerService
import org.json.JSONObject
import java.util.concurrent.Executors
import java.util.concurrent.ConcurrentHashMap

/** Receives allowlisted watch actions and forwards only with explicit local and desktop consent. */
class WearableBridgeListener : WearableListenerService() {
    private val worker = Executors.newSingleThreadExecutor()
    private val lastAcceptedAt = ConcurrentHashMap<String, Long>()
    private val allowed = setOf("assistant.ping", "media.play_pause", "media.next", "media.previous")

    override fun onMessageReceived(event: MessageEvent) {
        if (event.path != "/jarvis/v1/action" || event.data.size > 1024) return
        val source = event.sourceNodeId
        if (source.isBlank()) return
        val now = System.currentTimeMillis()
        val previous = lastAcceptedAt.put(source, now)
        if (previous != null && now - previous < 750L) return
        val settings = CompanionSettings(this)
        if (!settings.wearBridgeEnabled() || !settings.hasCommandScope()) {
            Log.i("Mark56Wear", "Watch action ignored: bridge or command scope is disabled")
            return
        }
        val token = SecureTokenStore(getSharedPreferences("companion_secure", MODE_PRIVATE)).read() ?: return
        val endpoint = settings.endpoint() ?: return
        val fingerprint = settings.fingerprint() ?: return
        val deviceId = settings.deviceId() ?: return
        val action = try {
            JSONObject(String(event.data, Charsets.UTF_8)).optString("action")
        } catch (_: Exception) { return }
        if (action !in allowed) return
        worker.execute {
            try {
                CompanionEventClient(endpoint, fingerprint, token, deviceId).postWearableAction(action)
            } catch (error: Exception) {
                Log.w("Mark56Wear", "Watch action forwarding failed (" + error.javaClass.simpleName + ")")
            }
        }
    }

    override fun onDestroy() {
        worker.shutdownNow()
        super.onDestroy()
    }
}
