package com.mark56.companion

import org.json.JSONArray
import org.json.JSONObject
import java.net.URL
import java.security.MessageDigest
import java.security.SecureRandom
import javax.crypto.Mac
import javax.crypto.spec.SecretKeySpec
import javax.net.ssl.HttpsURLConnection
import javax.net.ssl.SSLContext
import javax.net.ssl.X509TrustManager
import java.security.cert.X509Certificate

/** Sends permission-scoped, HMAC-authenticated events over certificate-pinned HTTPS. */
class CompanionEventClient(
    private val endpoint: String,
    private val fingerprint: String,
    private val token: String,
    private val deviceId: String
) {
    private val pin = fingerprint.replace(":", "").lowercase()
    init {
        val parsedEndpoint = URL(endpoint)
        require(parsedEndpoint.protocol.equals("https", ignoreCase = true))
        require(parsedEndpoint.host.isNotBlank() && parsedEndpoint.userInfo == null)
        require(parsedEndpoint.path.isNullOrEmpty() || parsedEndpoint.path == "/")
        require(parsedEndpoint.query == null && parsedEndpoint.ref == null)
        require(pin.matches(Regex("[0-9a-f]{64}")))
        require(token.length >= 32 && deviceId.isNotBlank())
    }


    /** Sends a user chat message through the approved command.send scope. */
    fun sendChat(messageId: String, message: String): Boolean {
        require(messageId.length in 8..80 && message.isNotBlank() && message.length <= 4000)
        val body = JSONObject().put("message_id", messageId).put("message", message.trim())
        val connection = signedConnection("/v1/chat/send", body)
        return try {
            val status = connection.responseCode
            if (status !in 200..299) {
                val detail = connection.errorStream?.bufferedReader(Charsets.UTF_8)?.use { it.readText() }
                throw IllegalStateException("Chat send rejected ($status): " + (detail ?: "request failed"))
            }
            JSONObject(connection.inputStream.bufferedReader(Charsets.UTF_8).use { it.readText() })
                .optBoolean("accepted", false)
        } finally { connection.disconnect() }
    }

    /** Polls the secure desktop reply queue; null means no reply is ready yet. */
    fun pollChatReply(): JSONObject? {
        val connection = signedConnection("/v1/chat/poll", JSONObject())
        return try {
            val status = connection.responseCode
            if (status !in 200..299) {
                val detail = connection.errorStream?.bufferedReader(Charsets.UTF_8)?.use { it.readText() }
                throw IllegalStateException("Chat poll rejected ($status): " + (detail ?: "request failed"))
            }
            JSONObject(connection.inputStream.bufferedReader(Charsets.UTF_8).use { it.readText() })
                .optJSONObject("reply")
        } finally { connection.disconnect() }
    }

    fun postBattery(level: Int, charging: Boolean): Int {
        require(level in 0..100)
        return postEvent("/v1/battery", JSONObject().put("level", level).put("charging", charging))
    }

    /** Notification text is forwarded only when the user enables relay and scope is approved. */
    fun postNotification(app: String, title: String, text: String, occurredAt: Long): Int {
        require(app.length <= 80 && title.length <= 512 && text.length <= 512)
        require(app.none { it.code < 32 } && title.none { it.code < 32 && it != '\n' && it != '\t' })
        require(text.none { it.code < 32 && it != '\n' && it != '\t' })
        require(occurredAt >= 0)
        val body = JSONObject().put("kind", "notification").put("app", app)
            .put("title", title).put("text", text).put("occurred_at", occurredAt)
        return postEvent("/v1/notifications", body)
    }

    /** Forwards a narrowly allowlisted Wear OS action after desktop scope approval. */
    fun postWearableAction(action: String): Int {
        require(action in setOf("assistant.ping", "media.play_pause", "media.next", "media.previous"))
        val body = JSONObject().put("action", action).put("source", "wear_os")
        return postEvent("/v1/wearable/action", body)
    }

    /** Fetches at most one desktop-authorized media action; no arbitrary command data is accepted. */
    fun pollMediaCommand(): String? {
        val connection = signedConnection("/v1/media/next", JSONObject())
        return try {
            val status = connection.responseCode
            if (status !in 200..299) return null
            val response = connection.inputStream.bufferedReader(Charsets.UTF_8).use { it.readText() }
            val command = JSONObject(response).optJSONObject("command") ?: return null
            command.optString("action").takeIf { it in setOf("play", "pause", "play_pause", "next", "previous", "stop") }
        } finally {
            connection.disconnect()
        }
    }

    private fun postEvent(path: String, body: JSONObject): Int {
        val connection = signedConnection(path, body)
        return try {
            connection.responseCode
        } finally {
            connection.disconnect()
        }
    }

    private fun signedConnection(path: String, body: JSONObject): HttpsURLConnection {
        val timestamp = System.currentTimeMillis() / 1000L
        val random = ByteArray(24).also { SecureRandom().nextBytes(it) }
        val nonce = android.util.Base64.encodeToString(
            random, android.util.Base64.URL_SAFE or android.util.Base64.NO_WRAP or android.util.Base64.NO_PADDING
        )
        val canonical = JSONObject()
            .put("version", 1).put("device_id", deviceId).put("method", "POST")
            .put("path", path).put("timestamp", timestamp).put("nonce", nonce).put("body", body)
        val key = MessageDigest.getInstance("SHA-256")
            .digest(("mark56-companion-v1:" + token).toByteArray(Charsets.UTF_8))
        val mac = Mac.getInstance("HmacSHA256")
        mac.init(SecretKeySpec(key, "HmacSHA256"))
        val signature = mac.doFinal(canonicalJson(canonical).toByteArray(Charsets.UTF_8))
            .joinToString("") { "%02x".format(it) }
        val envelope = JSONObject(canonical.toString()).put("signature", signature)
        val connection = pinnedConnection(path)
        connection.setRequestProperty("Authorization", "Bearer $token")
        connection.outputStream.use { it.write(envelope.toString().toByteArray(Charsets.UTF_8)) }
        return connection
    }

    private fun canonicalJson(value: Any?): String = when (value) {
        null, JSONObject.NULL -> "null"
        is JSONObject -> {
            val keys = value.keys().asSequence().toList().sorted()
            keys.joinToString(prefix = "{", postfix = "}", separator = ",") { key ->
                JSONObject.quote(key) + ":" + canonicalJson(value.get(key))
            }
        }
        is JSONArray -> (0 until value.length()).joinToString(prefix = "[", postfix = "]", separator = ",") {
            canonicalJson(value.get(it))
        }
        is String -> JSONObject.quote(value)
        is Number, is Boolean -> value.toString()
        else -> throw IllegalArgumentException("Unsupported JSON value")
    }

    private fun pinnedConnection(path: String): HttpsURLConnection {
        val base = URL(endpoint.trimEnd('/'))
        val url = URL(base.toString() + path)
        require(url.protocol == "https" && url.host == base.host && url.port == base.port)
        val trust = object : X509TrustManager {
            override fun getAcceptedIssuers(): Array<X509Certificate> = emptyArray()
            override fun checkClientTrusted(chain: Array<X509Certificate>, authType: String) {}
            override fun checkServerTrusted(chain: Array<X509Certificate>, authType: String) {
                if (chain.isEmpty()) throw java.security.cert.CertificateException("Empty certificate chain")
                val actual = MessageDigest.getInstance("SHA-256").digest(chain[0].encoded)
                    .joinToString("") { "%02x".format(it) }
                if (actual != pin) throw java.security.cert.CertificateException("Companion certificate pin mismatch")
            }
        }
        val context = SSLContext.getInstance("TLS")
        context.init(null, arrayOf(trust), SecureRandom())
        return (url.openConnection() as HttpsURLConnection).apply {
            sslSocketFactory = context.socketFactory
            connectTimeout = 7000
            readTimeout = 7000
            instanceFollowRedirects = false
            useCaches = false
            requestMethod = "POST"
            doOutput = true
            setRequestProperty("Content-Type", "application/json")
            setRequestProperty("Accept", "application/json")
        }
    }
}
