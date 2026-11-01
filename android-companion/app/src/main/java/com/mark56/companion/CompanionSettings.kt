package com.mark56.companion

import android.content.Context

class CompanionSettings(context: Context) {
    private val prefs = context.getSharedPreferences("companion_settings", Context.MODE_PRIVATE)
    fun saveConnection(endpoint: String, fingerprint: String, deviceId: String) {
        prefs.edit().putString("endpoint", endpoint).putString("fingerprint", fingerprint)
            .putString("device_id", deviceId).apply()
    }
    fun endpoint(): String? = prefs.getString("endpoint", null)
    fun fingerprint(): String? = prefs.getString("fingerprint", null)
    fun deviceId(): String? = prefs.getString("device_id", null)
    fun batterySyncEnabled(): Boolean = prefs.getBoolean("battery_sync_enabled", false)
    fun setBatterySyncEnabled(enabled: Boolean) {
        prefs.edit().putBoolean("battery_sync_enabled", enabled).apply()
    }
    fun clearConnection() {
        prefs.edit().remove("endpoint").remove("fingerprint").remove("device_id")
            .putBoolean("battery_sync_enabled", false).apply()
    }
}
