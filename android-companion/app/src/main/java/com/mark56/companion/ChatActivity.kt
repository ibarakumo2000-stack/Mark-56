package com.mark56.companion

import android.graphics.Color
import android.graphics.Typeface
import android.graphics.drawable.GradientDrawable
import android.os.Bundle
import android.os.Handler
import android.os.Looper
import android.view.Gravity
import android.view.View
import android.widget.EditText
import android.widget.LinearLayout
import android.widget.ScrollView
import android.widget.TextView
import androidx.appcompat.app.AppCompatActivity
import androidx.core.view.WindowCompat
import org.json.JSONObject
import java.util.UUID
import java.util.concurrent.Executors

/** Secure phone-to-desktop JARVIS chat surface. Messages use the enrolled command.send scope. */
class ChatActivity : AppCompatActivity() {
    private val worker = Executors.newSingleThreadExecutor()
    private val handler = Handler(Looper.getMainLooper())
    private lateinit var messages: LinearLayout
    private lateinit var scroll: ScrollView
    private lateinit var input: EditText
    private lateinit var send: TextView
    private lateinit var state: TextView
    private var client: CompanionEventClient? = null
    private val seenReplyIds = mutableSetOf<String>()
    private val poll = object : Runnable {
        override fun run() {
            val active = client
            if (active != null) worker.execute {
                try {
                    val reply = active.pollChatReply()
                    if (reply != null) {
                        val id = reply.optString("message_id")
                        val text = reply.optString("reply")
                        if (id.isNotBlank() && text.isNotBlank()) runOnUiThread {
                            if (seenReplyIds.add(id)) addBubble(text, false)
                            state.text = "JARVIS connected · reply received"
                        }
                    }
                } catch (_: Exception) {
                    runOnUiThread { state.text = "Secure bridge reconnecting…" }
                }
            }
            handler.postDelayed(this, 2500)
        }
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        WindowCompat.setDecorFitsSystemWindows(window, true)
        val settings = CompanionSettings(this)
        val token = SecureTokenStore(getSharedPreferences("companion_secure", MODE_PRIVATE)).read()
        val endpoint = settings.endpoint()
        val pin = settings.fingerprint()
        val deviceId = settings.deviceId()
        if (token.isNullOrBlank() || endpoint.isNullOrBlank() || pin.isNullOrBlank() ||
            deviceId.isNullOrBlank() || !settings.hasCommandScope()) {
            finish()
            return
        }
        client = CompanionEventClient(endpoint, pin, token, deviceId)

        val root = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            setPadding(dp(18), dp(14), dp(18), dp(16))
            background = GradientDrawable(GradientDrawable.Orientation.TL_BR,
                intArrayOf(Color.rgb(5, 12, 28), Color.rgb(12, 24, 48), Color.rgb(7, 10, 22)))
        }
        val top = LinearLayout(this).apply { orientation = LinearLayout.VERTICAL }
        top.addView(TextView(this).apply {
            text = "✧  J A R V I S  /  CHAT"
            textSize = 12f; letterSpacing = .18f
            typeface = Typeface.DEFAULT_BOLD; setTextColor(Color.rgb(91, 205, 255))
        })
        top.addView(TextView(this).apply {
            text = "Talk to your desktop AI"
            textSize = 27f; typeface = Typeface.create("sans-serif", Typeface.BOLD)
            setTextColor(Color.WHITE); setPadding(0, dp(8), 0, dp(3))
        })
        state = TextView(this).apply {
            text = "Securely paired · waiting for desktop response"
            textSize = 12f; setTextColor(Color.rgb(144, 199, 224))
            setPadding(0, 0, 0, dp(12))
        }
        top.addView(state)
        root.addView(top)

        scroll = ScrollView(this).apply {
            isFillViewport = false
            clipToPadding = false
            setPadding(0, dp(4), 0, dp(8))
        }
        messages = LinearLayout(this).apply { orientation = LinearLayout.VERTICAL }
        scroll.addView(messages)
        root.addView(scroll, LinearLayout.LayoutParams(
            LinearLayout.LayoutParams.MATCH_PARENT, 0, 1f))

        val composer = LinearLayout(this).apply {
            orientation = LinearLayout.HORIZONTAL
            gravity = Gravity.CENTER_VERTICAL
            setPadding(dp(10), dp(6), dp(6), dp(6))
            background = rounded(Color.rgb(17, 35, 62), dp(18), Color.rgb(48, 88, 130))
        }
        input = EditText(this).apply {
            hint = "Message JARVIS…"; setTextColor(Color.WHITE)
            setHintTextColor(Color.rgb(139, 164, 195)); textSize = 15f
            maxLines = 4; setPadding(dp(8), dp(6), dp(8), dp(6))
            background = null
        }
        send = TextView(this).apply {
            text = "➤"; textSize = 20f; gravity = Gravity.CENTER
            typeface = Typeface.DEFAULT_BOLD; setTextColor(Color.rgb(5, 18, 35))
            background = rounded(Color.rgb(67, 190, 255), dp(14), Color.TRANSPARENT)
            setPadding(dp(16), dp(12), dp(16), dp(12))
            setOnClickListener { sendMessage() }
        }
        composer.addView(input, LinearLayout.LayoutParams(0, LinearLayout.LayoutParams.WRAP_CONTENT, 1f))
        composer.addView(send)
        root.addView(composer)
        setContentView(root)
        addBubble("Hello. Your phone is securely connected to the JARVIS companion bridge. Send a message to your desktop assistant.", false)
        handler.post(poll)
    }

    private fun sendMessage() {
        val text = input.text.toString().trim()
        if (text.isEmpty()) return
        val active = client ?: return
        val id = UUID.randomUUID().toString()
        input.setText("")
        addBubble(text, true)
        send.isEnabled = false
        state.text = "Sending securely to your desktop…"
        worker.execute {
            try {
                val accepted = active.sendChat(id, text)
                runOnUiThread {
                    send.isEnabled = true
                    state.text = if (accepted) "Delivered to companion bridge · waiting for JARVIS"
                        else "Desktop bridge did not accept the message"
                }
            } catch (error: Exception) {
                runOnUiThread {
                    send.isEnabled = true
                    state.text = "Send failed: " + (error.message ?: "bridge unavailable")
                    addBubble("Message could not be delivered. Check that the desktop bridge is running and this device has command.send approval.", false)
                }
            }
        }
    }

    private fun addBubble(text: String, user: Boolean) {
        val bubble = TextView(this).apply {
            this.text = text; textSize = 15f; setTextColor(Color.WHITE)
            setPadding(dp(14), dp(11), dp(14), dp(11))
            background = rounded(if (user) Color.rgb(28, 102, 157) else Color.rgb(18, 37, 67),
                dp(17), if (user) Color.rgb(57, 158, 224) else Color.rgb(49, 91, 139))
        }
        val row = LinearLayout(this).apply {
            orientation = LinearLayout.HORIZONTAL
            gravity = if (user) Gravity.END else Gravity.START
            setPadding(dp(2), dp(5), dp(2), dp(5))
            addView(bubble, LinearLayout.LayoutParams(
                (resources.displayMetrics.widthPixels * .78f).toInt(),
                LinearLayout.LayoutParams.WRAP_CONTENT))
        }
        messages.addView(row)
        scroll.post { scroll.fullScroll(View.FOCUS_DOWN) }
    }

    private fun rounded(fill: Int, radius: Int, stroke: Int): GradientDrawable =
        GradientDrawable().apply {
            setColor(fill); cornerRadius = radius.toFloat()
            if (stroke != Color.TRANSPARENT) setStroke(dp(1), stroke)
        }

    private fun dp(value: Int) = (value * resources.displayMetrics.density).toInt()

    override fun onDestroy() {
        handler.removeCallbacks(poll)
        worker.shutdownNow()
        client = null
        super.onDestroy()
    }
}
