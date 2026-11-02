package com.mark56.companion

import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.Response
import okhttp3.WebSocket
import okhttp3.WebSocketListener
import okhttp3.HttpUrl.Companion.toHttpUrl
import org.json.JSONObject
import java.util.concurrent.TimeUnit

/** Explicit, TLS-only remote relay connection. No reconnect is hidden from the user. */
class RemoteRelayClient(
    baseUrl: String,
    private val channelId: String,
    private val principalId: String,
    token: String,
    private val onState: (String) -> Unit,
    private val onMessage: (JSONObject) -> Unit
) {
    private val client = OkHttpClient.Builder()
        .connectTimeout(10, TimeUnit.SECONDS)
        .readTimeout(0, TimeUnit.MILLISECONDS)
        .pingInterval(20, TimeUnit.SECONDS)
        .build()
    private val socket: WebSocket

    init {
        val base = baseUrl.toHttpUrl()
        require(base.isHttps && base.username.isEmpty() && base.password.isEmpty() &&
            base.encodedPath in listOf("", "/") && base.query == null && base.fragment == null)
        require(channelId.matches(Regex("[0-9a-fA-F-]{36}")))
        require(java.util.UUID.fromString(channelId).toString().equals(channelId, ignoreCase = true))
        require(principalId.matches(Regex("[A-Za-z0-9._-]{1,80}")))
        require(token.startsWith("rly_") && token.length in 32..160)
        val url = base.newBuilder().scheme("https")
            .addPathSegments("v1/connect/$channelId/$principalId").build()
        val request = Request.Builder().url(url)
            .header("Authorization", "Bearer $token")
            .build()
        socket = client.newWebSocket(request, object : WebSocketListener() {
            override fun onOpen(webSocket: WebSocket, response: Response) {
                onState("Connected securely to JARVIS relay")
            }
            override fun onMessage(webSocket: WebSocket, text: String) {
                try {
                    require(text.toByteArray(Charsets.UTF_8).size <= 32_768)
                    val message = JSONObject(text)
                    require(message.optString("type") in setOf(
                        "command", "notification", "media", "battery", "display", "voice", "camera"
                    ))
                    require(message.optJSONObject("payload") != null)
                    this@RemoteRelayClient.onMessage(message)
                } catch (_: Exception) {
                    onState("Relay sent an invalid message")
                }
            }
            override fun onClosed(webSocket: WebSocket, code: Int, reason: String) {
                onState("Relay disconnected")
            }
            override fun onFailure(webSocket: WebSocket, t: Throwable, response: Response?) {
                onState("Relay connection failed: " + t.javaClass.simpleName)
            }
        })
    }

    fun send(type: String, payload: JSONObject, targetDeviceId: String? = null): Boolean {
        require(type in setOf("command", "notification", "media", "battery", "display", "voice", "camera"))
        require(targetDeviceId == null ||
            targetDeviceId.matches(Regex("[A-Za-z0-9._-]{1,80}")))
        val envelope = JSONObject().put("type", type)
            .put("target_device_id", targetDeviceId)
            .put("payload", payload)
        val encoded = envelope.toString()
        require(encoded.toByteArray(Charsets.UTF_8).size <= 32_768) {
            "Relay message exceeds the 32 KB limit"
        }
        return socket.send(encoded)
    }

    fun close() {
        socket.close(1000, "User disconnected")
        client.dispatcher.executorService.shutdown()
    }
}
