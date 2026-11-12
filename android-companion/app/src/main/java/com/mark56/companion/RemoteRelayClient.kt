package com.mark56.companion

import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.Response
import okhttp3.WebSocket
import okhttp3.WebSocketListener
import okhttp3.HttpUrl.Companion.toHttpUrl
import org.json.JSONObject
import java.util.concurrent.Executors
import java.util.concurrent.ThreadLocalRandom
import java.util.concurrent.TimeUnit

internal object RemoteRelayProtocol {
    private val messageTypes = setOf(
        "command", "notification", "media", "battery", "display", "voice", "camera"
    )

    fun isMessageType(type: String): Boolean = type in messageTypes
    fun isControlFrame(type: String): Boolean = type == "ack" || type == "error"
    fun shouldReconnect(closeCode: Int, manuallyClosed: Boolean): Boolean =
        !manuallyClosed && closeCode !in setOf(4401, 4403)

    fun reconnectDelaySeconds(attempt: Int): Long =
        (1L shl attempt.coerceIn(0, 6)).coerceAtMost(60L)
}

/**
 * Explicit TLS-only remote relay connection.
 *
 * Reconnects with bounded exponential backoff when Vercel closes a connection
 * at its function-duration limit. Authentication failures are terminal until
 * the owner updates the stored credentials.
 */
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
    private val reconnectExecutor = Executors.newSingleThreadScheduledExecutor { runnable ->
        Thread(runnable, "jarvis-relay-reconnect").apply { isDaemon = true }
    }
    private val reconnectLock = Any()
    private val request: Request
    private val bearerToken: String = token

    @Volatile private var socket: WebSocket? = null
    @Volatile private var manuallyClosed = false
    private var reconnectAttempt = 0
    private var reconnectPending = false

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
        request = Request.Builder().url(url)
            .header("Authorization", "Bearer $bearerToken")
            .build()
        connect()
    }

    private fun connect() {
        if (manuallyClosed) return
        val newSocket = client.newWebSocket(request, object : WebSocketListener() {
            override fun onOpen(webSocket: WebSocket, response: Response) {
                if (manuallyClosed) {
                    webSocket.close(1000, "User disconnected")
                    return
                }
                synchronized(reconnectLock) {
                    socket = webSocket
                    reconnectAttempt = 0
                    reconnectPending = false
                }
                onState("Connected securely to JARVIS relay")
            }

            override fun onMessage(webSocket: WebSocket, text: String) {
                try {
                    require(text.toByteArray(Charsets.UTF_8).size <= 32_768)
                    val message = JSONObject(text)
                    val type = message.optString("type")
                    when {
                        RemoteRelayProtocol.isControlFrame(type) -> {
                            if (type == "ack") {
                                onState(
                                    if (message.optBoolean("queued"))
                                        "Message accepted and queued for delivery"
                                    else "Message delivered by JARVIS relay"
                                )
                            } else {
                                onState("Relay rejected message: " +
                                    message.optString("error", "unknown_error"))
                            }
                        }
                        RemoteRelayProtocol.isMessageType(type) -> {
                            require(message.optJSONObject("payload") != null)
                            this@RemoteRelayClient.onMessage(message)
                        }
                        else -> onState("Relay sent an invalid message")
                    }
                } catch (_: Exception) {
                    onState("Relay sent an invalid message")
                }
            }

            override fun onClosed(webSocket: WebSocket, code: Int, reason: String) {
                synchronized(reconnectLock) {
                    if (socket === webSocket) socket = null
                }
                if (RemoteRelayProtocol.shouldReconnect(code, manuallyClosed)) {
                    scheduleReconnect()
                } else if (!manuallyClosed && code in setOf(4401, 4403)) {
                    onState("Relay authorization rejected; check the saved credentials")
                }
            }

            override fun onFailure(webSocket: WebSocket, t: Throwable, response: Response?) {
                synchronized(reconnectLock) {
                    if (socket === webSocket) socket = null
                }
                if (!manuallyClosed) {
                    onState("Relay connection failed: " + t.javaClass.simpleName)
                    scheduleReconnect()
                }
            }
        })
        synchronized(reconnectLock) {
            if (manuallyClosed) newSocket.cancel() else socket = newSocket
        }
    }

    private fun scheduleReconnect() {
        val delay: Long
        synchronized(reconnectLock) {
            if (manuallyClosed || reconnectPending) return
            reconnectPending = true
            delay = RemoteRelayProtocol.reconnectDelaySeconds(reconnectAttempt)
            reconnectAttempt = (reconnectAttempt + 1).coerceAtMost(6)
        }
        val jitter = ThreadLocalRandom.current().nextLong(0, maxOf(1L, delay / 4))
        onState("Relay disconnected; reconnecting in ${delay + jitter}s")
        reconnectExecutor.schedule({
            synchronized(reconnectLock) {
                reconnectPending = false
                if (manuallyClosed) return@schedule
            }
            connect()
        }, delay + jitter, TimeUnit.SECONDS)
    }

    fun send(type: String, payload: JSONObject, targetDeviceId: String? = null): Boolean {
        require(RemoteRelayProtocol.isMessageType(type))
        require(targetDeviceId == null ||
            targetDeviceId.matches(Regex("[A-Za-z0-9._-]{1,80}")))
        val envelope = JSONObject().put("type", type)
            .put("target_device_id", targetDeviceId)
            .put("payload", payload)
        val encoded = envelope.toString()
        require(encoded.toByteArray(Charsets.UTF_8).size <= 32_768) {
            "Relay message exceeds the 32 KB limit"
        }
        return socket?.send(encoded) ?: false
    }

    fun close() {
        manuallyClosed = true
        synchronized(reconnectLock) {
            reconnectPending = false
            socket?.close(1000, "User disconnected")
            socket = null
        }
        reconnectExecutor.shutdownNow()
        client.dispatcher.executorService.shutdown()
    }
}
