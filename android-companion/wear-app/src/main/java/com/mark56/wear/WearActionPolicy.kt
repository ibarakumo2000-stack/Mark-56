package com.mark56.wear

/** Only actions with an explicit phone-side permission gate can leave the watch. */
object WearActionPolicy {
    const val MESSAGE_PATH = "/jarvis/v1/action"
    private val allowed = setOf(
        "assistant.ping",
        "media.play_pause",
        "media.next",
        "media.previous",
    )

    fun encode(action: String): ByteArray? {
        if (action !in allowed) return null
        // The action is drawn from a fixed allowlist containing no JSON-special
        // characters, so a tiny deterministic envelope avoids Android JSON APIs
        // in local JVM tests.
        return """{"action":"$action"}""".toByteArray(Charsets.UTF_8)
    }
}
