package com.mark56.companion

/**
 * Normalizes notification content to the minimal display-only relay contract.
 * This class is intentionally platform-free so its privacy boundary is unit tested.
 */
data class NotificationRelayPayload(
    val app: String,
    val title: String,
    val text: String,
    val occurredAt: Long
)

object NotificationRelayPolicy {
    private fun clean(value: String, limit: Int): String =
        value.filter { it == '\n' || it == '\t' || it.code >= 32 }
            .trim()
            .take(limit)

    fun create(app: String, title: String, text: String, occurredAt: Long): NotificationRelayPayload? {
        if (occurredAt < 0) return null
        val safeApp = clean(app, 80)
        val safeTitle = clean(title, 512)
        val safeText = clean(text, 512)
        if (safeApp.isBlank() || (safeTitle.isBlank() && safeText.isBlank())) return null
        return NotificationRelayPayload(safeApp, safeTitle, safeText, occurredAt)
    }
}
