package com.mark56.companion

import android.content.Context

class CompanionSettings(context: Context) {
    private val prefs = context.getSharedPreferences("companion_settings", Context.MODE_PRIVATE)
    fun saveConnection(endpoint: String, fingerprint: String, deviceId: String,
                       batteryScope: Boolean, notificationScope: Boolean, mediaScope: Boolean, commandScope: Boolean) {
        prefs.edit().putString("endpoint", endpoint).putString("fingerprint", fingerprint)
            .putString("device_id", deviceId).putBoolean("battery_scope", batteryScope)
            .putBoolean("notification_scope", notificationScope)
            .putBoolean("media_scope", mediaScope).putBoolean("command_scope", commandScope).apply()
    }
    fun endpoint(): String? = prefs.getString("endpoint", null)
    fun fingerprint(): String? = prefs.getString("fingerprint", null)
    fun deviceId(): String? = prefs.getString("device_id", null)
    fun hasBatteryScope(): Boolean = prefs.getBoolean("battery_scope", false)
    fun hasNotificationScope(): Boolean = prefs.getBoolean("notification_scope", false)
    fun hasMediaScope(): Boolean = prefs.getBoolean("media_scope", false)
    fun hasCommandScope(): Boolean = prefs.getBoolean("command_scope", false)
    fun wearBridgeRequested(): Boolean = prefs.getBoolean("wear_bridge_requested", false)
    fun setWearBridgeRequested(requested: Boolean) { prefs.edit().putBoolean("wear_bridge_requested", requested).apply() }
    fun wearBridgeEnabled(): Boolean = prefs.getBoolean("wear_bridge_enabled", false)
    fun setWearBridgeEnabled(enabled: Boolean) { prefs.edit().putBoolean("wear_bridge_enabled", enabled).apply() }
    fun batterySyncEnabled(): Boolean = prefs.getBoolean("battery_sync_enabled", false)
    fun setBatterySyncEnabled(enabled: Boolean) {
        prefs.edit().putBoolean("battery_sync_enabled", enabled).apply()
    }
    fun notificationRelayEnabled(): Boolean = prefs.getBoolean("notification_relay_enabled", false)
    fun setNotificationRelayEnabled(enabled: Boolean) {
        prefs.edit().putBoolean("notification_relay_enabled", enabled).apply()
    }
    fun notificationRelayRequested(): Boolean = prefs.getBoolean("notification_relay_requested", false)
    fun setNotificationRelayRequested(requested: Boolean) {
        prefs.edit().putBoolean("notification_relay_requested", requested).apply()
    }
    fun mediaControlRequested(): Boolean = prefs.getBoolean("media_control_requested", false)
    fun setMediaControlRequested(requested: Boolean) {
        prefs.edit().putBoolean("media_control_requested", requested).apply()
    }
    fun mediaControlEnabled(): Boolean = prefs.getBoolean("media_control_enabled", false)
    fun setMediaControlEnabled(enabled: Boolean) {
        prefs.edit().putBoolean("media_control_enabled", enabled).apply()
    }
    fun clearConnection() {
        prefs.edit().remove("endpoint").remove("fingerprint").remove("device_id")
            .remove("battery_scope").remove("notification_scope").remove("media_scope").remove("command_scope")
            .putBoolean("battery_sync_enabled", false)
            .putBoolean("notification_relay_enabled", false)
            .putBoolean("media_control_enabled", false).putBoolean("wear_bridge_enabled", false).apply()
    }
}
