package com.mark56.companion

import android.Manifest
import android.content.Intent
import android.content.pm.PackageManager
import android.speech.RecognizerIntent
import android.speech.RecognitionListener
import android.speech.SpeechRecognizer
import android.speech.tts.TextToSpeech
import androidx.core.content.ContextCompat
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
import java.util.Locale
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
    private lateinit var mic: TextView
    private lateinit var voiceOutput: TextView
    private var speechRecognizer: SpeechRecognizer? = null
    private var textToSpeech: TextToSpeech? = null
    private var voiceOutputEnabled = true
    private var listening = false
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
                            if (seenReplyIds.add(id)) addBubble(text, false, speak = true)
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
        initializeVoice()

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
        voiceOutput = TextView(this).apply {
            text = "VOICE REPLIES  ·  ON"
            textSize = 11f; typeface = Typeface.DEFAULT_BOLD
            setTextColor(Color.rgb(91, 205, 255))
            setPadding(0, dp(4), 0, dp(12))
            setOnClickListener {
                voiceOutputEnabled = !voiceOutputEnabled
                text = if (voiceOutputEnabled) "VOICE REPLIES  ·  ON" else "VOICE REPLIES  ·  OFF"
                if (!voiceOutputEnabled) textToSpeech?.stop()
            }
        }
        top.addView(voiceOutput)
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
        mic = TextView(this).apply {
            text = "🎙"; textSize = 19f; gravity = Gravity.CENTER
            setTextColor(Color.rgb(91, 205, 255))
            setPadding(dp(12), dp(12), dp(12), dp(12))
            setOnClickListener { toggleListening() }
        }
        send = TextView(this).apply {
            text = "➤"; textSize = 20f; gravity = Gravity.CENTER
            typeface = Typeface.DEFAULT_BOLD; setTextColor(Color.rgb(5, 18, 35))
            background = rounded(Color.rgb(67, 190, 255), dp(14), Color.TRANSPARENT)
            setPadding(dp(16), dp(12), dp(16), dp(12))
            setOnClickListener { sendMessage() }
        }
        composer.addView(input, LinearLayout.LayoutParams(0, LinearLayout.LayoutParams.WRAP_CONTENT, 1f))
        composer.addView(mic)
        composer.addView(send)
        root.addView(composer)
        setContentView(root)
        addBubble("Hello. Your phone is securely connected to the JARVIS companion bridge. Send a message to your desktop assistant.", false)
        handler.post(poll)
    }

    private fun initializeVoice() {
        if (!SpeechRecognizer.isRecognitionAvailable(this)) {
            state.text = "Secure chat connected · speech recognition unavailable on this device"
        } else {
            speechRecognizer = SpeechRecognizer.createSpeechRecognizer(this).apply {
                setRecognitionListener(object : RecognitionListener {
                    override fun onReadyForSpeech(params: Bundle?) { runOnUiThread { state.text = "Listening… speak now" } }
                    override fun onBeginningOfSpeech() { runOnUiThread { state.text = "Hearing you…" } }
                    override fun onRmsChanged(rmsdB: Float) {}
                    override fun onBufferReceived(buffer: ByteArray?) {}
                    override fun onEndOfSpeech() { runOnUiThread { state.text = "Processing your speech…" } }
                    override fun onError(error: Int) {
                        listening = false
                        runOnUiThread {
                            mic.text = "🎙"
                            state.text = "Voice input stopped · " + when (error) {
                                SpeechRecognizer.ERROR_NO_MATCH -> "no speech recognized"
                                SpeechRecognizer.ERROR_SPEECH_TIMEOUT -> "no speech detected"
                                SpeechRecognizer.ERROR_RECOGNIZER_BUSY -> "speech service busy"
                                SpeechRecognizer.ERROR_INSUFFICIENT_PERMISSIONS -> "microphone permission required"
                                else -> "try again"
                            }
                        }
                    }
                    override fun onResults(results: Bundle?) {
                        listening = false
                        val spoken = results?.getStringArrayList(SpeechRecognizer.RESULTS_RECOGNITION)?.firstOrNull()?.trim()
                        runOnUiThread {
                            mic.text = "🎙"
                            if (!spoken.isNullOrBlank()) {
                                input.setText(spoken)
                                state.text = "Speech recognized · sending to JARVIS"
                                sendMessage()
                            } else state.text = "No speech recognized · try again"
                        }
                    }
                    override fun onPartialResults(partialResults: Bundle?) {}
                    override fun onEvent(eventType: Int, params: Bundle?) {}
                })
            }
        }
        textToSpeech = TextToSpeech(this) { result ->
            if (result == TextToSpeech.SUCCESS) {
                textToSpeech?.language = Locale.getDefault()
                textToSpeech?.setSpeechRate(1.0f)
            } else runOnUiThread {
                voiceOutputEnabled = false
                if (::voiceOutput.isInitialized) voiceOutput.text = "VOICE REPLIES  ·  UNAVAILABLE"
            }
        }
    }

    private fun toggleListening() {
        if (listening) {
            speechRecognizer?.cancel()
            listening = false
            mic.text = "🎙"
            state.text = "Voice input cancelled"
            return
        }
        if (speechRecognizer == null) {
            state.text = "Speech recognition is not available on this device"
            return
        }
        if (ContextCompat.checkSelfPermission(this, Manifest.permission.RECORD_AUDIO) != PackageManager.PERMISSION_GRANTED) {
            requestPermissions(arrayOf(Manifest.permission.RECORD_AUDIO), 7401)
            return
        }
        val intent = Intent(RecognizerIntent.ACTION_RECOGNIZE_SPEECH).apply {
            putExtra(RecognizerIntent.EXTRA_LANGUAGE_MODEL, RecognizerIntent.LANGUAGE_MODEL_FREE_FORM)
            putExtra(RecognizerIntent.EXTRA_LANGUAGE, Locale.getDefault())
            putExtra(RecognizerIntent.EXTRA_PARTIAL_RESULTS, true)
            putExtra(RecognizerIntent.EXTRA_PREFER_OFFLINE, true)
            putExtra(RecognizerIntent.EXTRA_MAX_RESULTS, 3)
            putExtra(RecognizerIntent.EXTRA_PROMPT, "Speak to JARVIS")
        }
        try {
            listening = true
            mic.text = "■"
            speechRecognizer?.startListening(intent)
        } catch (error: Exception) {
            listening = false
            mic.text = "🎙"
            state.text = "Could not start microphone: " + (error.message ?: "try again")
        }
    }

    override fun onRequestPermissionsResult(requestCode: Int, permissions: Array<out String>, grantResults: IntArray) {
        super.onRequestPermissionsResult(requestCode, permissions, grantResults)
        if (requestCode == 7401) {
            if (grantResults.firstOrNull() == PackageManager.PERMISSION_GRANTED) toggleListening()
            else state.text = "Microphone permission denied · text chat remains available"
        }
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

    private fun addBubble(text: String, user: Boolean, speak: Boolean = false) {
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
        if (speak && !user && voiceOutputEnabled) {
            textToSpeech?.speak(text, TextToSpeech.QUEUE_FLUSH, null, "jarvis-reply")
        }
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
        speechRecognizer?.cancel()
        speechRecognizer?.destroy()
        speechRecognizer = null
        textToSpeech?.stop()
        textToSpeech?.shutdown()
        textToSpeech = null
        client = null
        super.onDestroy()
    }
}
