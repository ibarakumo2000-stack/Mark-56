package com.mark56.companion

import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.Response
import okhttp3.WebSocket
import okhttp3.WebSocketListener
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
        val base = okhttp3.HttpUrl.get(baseUrl)
        require(base.isHttps && base.encodedPath() in listOf("", "/") &&
            base.query() == null && base.fragment() == null)
        require(channelId.matches(Regex("[0-9a-fA-F-]{36}")))
        require(principalId.isNotBlank() && !principalId.contains("/"))
        require(token.startsWith("rly_") && token.length <= 160)
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
                    onMessage(JSONObject(text))
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
        val envelope = JSONObject().put("type", type)
            .put("target_device_id", targetDeviceId)
            .put("payload", payload)
        return socket.send(envelope.toString())
    }

    fun close() {
        socket.close(1000, "User disconnected")
        client.dispatcher.executorService.shutdown()
    }
}
