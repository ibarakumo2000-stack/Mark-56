package com.mark56.companion

import android.content.Context
import android.content.Intent
import android.content.IntentFilter
import android.os.BatteryManager
import androidx.work.Worker
import androidx.work.WorkerParameters

class BatterySyncWorker(context: Context, params: WorkerParameters) : Worker(context, params) {
    override fun doWork(): Result {
        val settings = CompanionSettings(applicationContext)
        if (!settings.batterySyncEnabled()) return Result.success()
        val token = SecureTokenStore(
            applicationContext.getSharedPreferences("companion_secure", Context.MODE_PRIVATE)
        ).read() ?: return Result.failure()
        val endpoint = settings.endpoint() ?: return Result.failure()
        val pin = settings.fingerprint() ?: return Result.failure()
        val deviceId = settings.deviceId() ?: return Result.failure()
        val battery = applicationContext.registerReceiver(null, IntentFilter(Intent.ACTION_BATTERY_CHANGED))
            ?: return Result.retry()
        val level = battery.getIntExtra(BatteryManager.EXTRA_LEVEL, -1)
        val scale = battery.getIntExtra(BatteryManager.EXTRA_SCALE, -1)
        val status = battery.getIntExtra(BatteryManager.EXTRA_STATUS, -1)
        if (level < 0 || scale <= 0) return Result.retry()
        val percent = (level * 100 / scale).coerceIn(0, 100)
        val charging = status == BatteryManager.BATTERY_STATUS_CHARGING ||
            status == BatteryManager.BATTERY_STATUS_FULL
        return try {
            val status = CompanionEventClient(endpoint, pin, token, deviceId).postBattery(percent, charging)
            when {
                status in 200..299 -> Result.success()
                status in 400..499 -> Result.failure()
                else -> Result.retry()
            }
        } catch (_: javax.net.ssl.SSLException) {
            // A pin or TLS validation error must not be bypassed by a fallback transport.
            Result.failure()
        } catch (_: Exception) {
            Result.retry()
        }
    }
}
