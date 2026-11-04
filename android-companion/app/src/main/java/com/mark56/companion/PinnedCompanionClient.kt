package com.mark56.companion

import org.json.JSONObject
import java.net.URL
import java.security.MessageDigest
import java.security.cert.X509Certificate
import javax.net.ssl.HttpsURLConnection
import javax.net.ssl.X509TrustManager
import javax.net.ssl.SSLContext

class PinnedCompanionClient(endpoint: String, fingerprint: String) {
    private val base = endpoint.trimEnd('/')
    private val pin = fingerprint.replace(":", "").lowercase()
    init {
        require(base.startsWith("https://")) { "HTTPS is required" }
        require(pin.matches(Regex("[0-9a-f]{64}"))) { "Invalid SHA-256 certificate pin" }
        require(URL(base).userInfo == null) { "Credentials in endpoint are forbidden" }
    }
    private fun connection(path: String): HttpsURLConnection {
        val url = URL(base + path)
        require(url.protocol == "https" && url.host == URL(base).host)
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
        context.init(null, arrayOf(trust), java.security.SecureRandom())
        return (url.openConnection() as HttpsURLConnection).apply {
            sslSocketFactory = context.socketFactory
            // The desktop may receive a new private LAN IP after DHCP changes.
            // Trust is anchored to the SHA-256 certificate pin above, so use
            // the exact URL host here instead of requiring the self-signed
            // certificate's original IP SAN to remain unchanged.
            hostnameVerifier = javax.net.ssl.HostnameVerifier { host, _ ->
                host.equals(URL(base).host, ignoreCase = true)
            }
            connectTimeout = 7000; readTimeout = 7000
            requestMethod = "POST"; doOutput = true
            setRequestProperty("Content-Type", "application/json")
            setRequestProperty("Accept", "application/json")
        }
    }
    fun pair(code: String, deviceName: String, scopes: List<String>): JSONObject {
        require(code.matches(Regex("[A-HJ-NP-Z2-9]{8}")))
        val body = JSONObject().put("pairing_code", code).put("device_name", deviceName.take(64))
            .put("platform", "android").put("capabilities", org.json.JSONArray())
            .put("requested_scopes", org.json.JSONArray(scopes))
        val conn = connection("/v1/pair")
        return try {
            conn.outputStream.use { it.write(body.toString().toByteArray(Charsets.UTF_8)) }
            val status = conn.responseCode
            val stream = if (status in 200..299) conn.inputStream else conn.errorStream
            val response = stream.bufferedReader().use { it.readText() }
            if (status !in 200..299) throw IllegalStateException("Pairing rejected (" + status + ")")
            JSONObject(response)
        } finally { conn.disconnect() }
    }
}
