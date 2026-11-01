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

/** Sends small, signed companion events over the certificate-pinned desktop channel. */
class CompanionEventClient(
    private val endpoint: String,
    private val fingerprint: String,
    private val token: String,
    private val deviceId: String
) {
    private val pin = fingerprint.replace(":", "").lowercase()
    init {
        require(endpoint.startsWith("https://") && URL(endpoint).userInfo == null)
        require(pin.matches(Regex("[0-9a-f]{64}")))
        require(token.length >= 32 && deviceId.isNotBlank())
    }

    fun postBattery(level: Int, charging: Boolean): Boolean {
        require(level in 0..100)
        val body = JSONObject().put("level", level).put("charging", charging)
        val timestamp = System.currentTimeMillis() / 1000L
        val random = ByteArray(24).also { SecureRandom().nextBytes(it) }
        val nonce = android.util.Base64.encodeToString(
            random, android.util.Base64.URL_SAFE or android.util.Base64.NO_WRAP or android.util.Base64.NO_PADDING
        )
        val canonical = JSONObject()
            .put("version", 1).put("device_id", deviceId).put("method", "POST")
            .put("path", "/v1/battery").put("timestamp", timestamp)
            .put("nonce", nonce).put("body", body)
        val key = MessageDigest.getInstance("SHA-256")
            .digest(("mark56-companion-v1:" + token).toByteArray(Charsets.UTF_8))
        val mac = Mac.getInstance("HmacSHA256")
        mac.init(SecretKeySpec(key, "HmacSHA256"))
        val signature = mac.doFinal(canonicalJson(canonical).toByteArray(Charsets.UTF_8))
            .joinToString("") { "%02x".format(it) }
        val envelope = JSONObject(canonical.toString()).put("signature", signature)
        val connection = pinnedConnection("/v1/battery")
        return try {
            connection.setRequestProperty("Authorization", "Bearer $token")
            connection.outputStream.use { it.write(envelope.toString().toByteArray(Charsets.UTF_8)) }
            val status = connection.responseCode
            if (status in 200..299) true else false
        } finally {
            connection.disconnect()
        }
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
            requestMethod = "POST"
            doOutput = true
            setRequestProperty("Content-Type", "application/json")
            setRequestProperty("Accept", "application/json")
        }
    }
}
