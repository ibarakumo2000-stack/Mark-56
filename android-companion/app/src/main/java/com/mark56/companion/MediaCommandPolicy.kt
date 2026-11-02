package com.mark56.companion

/** Narrow allow-list for desktop-originated media commands. */
object MediaCommandPolicy {
    const val POLL_INTERVAL_MS = 5_000L
    private val allowed = setOf("play", "pause", "play_pause", "next", "previous", "stop")

    fun resolve(action: String, isPlaying: Boolean?): String? {
        if (action !in allowed) return null
        return when (action) {
            "play_pause" -> if (isPlaying == true) "pause" else "play"
            else -> action
        }
    }
}
