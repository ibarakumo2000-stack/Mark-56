package com.mark56.companion

import android.content.Context

class CompanionSettings(context: Context) {
    private val prefs = context.getSharedPreferences("companion_settings", Context.MODE_PRIVATE)
    fun saveConnection(endpoint: String, fingerprint: String, deviceId: String, batteryScope: Boolean) {
        prefs.edit().putString("endpoint", endpoint).putString("fingerprint", fingerprint)
            .putString("device_id", deviceId).putBoolean("battery_scope", batteryScope).apply()
    }
    fun endpoint(): String? = prefs.getString("endpoint", null)
    fun fingerprint(): String? = prefs.getString("fingerprint", null)
    fun deviceId(): String? = prefs.getString("device_id", null)
    fun hasBatteryScope(): Boolean = prefs.getBoolean("battery_scope", false)
    fun batterySyncEnabled(): Boolean = prefs.getBoolean("battery_sync_enabled", false)
    fun setBatterySyncEnabled(enabled: Boolean) {
        prefs.edit().putBoolean("battery_sync_enabled", enabled).apply()
    }
    fun clearConnection() {
        prefs.edit().remove("endpoint").remove("fingerprint").remove("device_id")
            .remove("battery_scope").putBoolean("battery_sync_enabled", false).apply()
    }
}
