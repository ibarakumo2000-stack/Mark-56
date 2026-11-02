package com.mark56.wear

import android.app.Activity
import android.graphics.Color
import android.graphics.Typeface
import android.graphics.drawable.GradientDrawable
import android.os.Bundle
import android.view.Gravity
import android.view.HapticFeedbackConstants
import android.widget.Button
import android.widget.LinearLayout
import android.widget.ScrollView
import android.widget.TextView
import com.google.android.gms.wearable.CapabilityClient
import com.google.android.gms.wearable.Node
import com.google.android.gms.wearable.Wearable

class WearMainActivity : Activity() {
    private lateinit var status: TextView
    private val actionButtons = mutableListOf<Button>()
    private var sending = false

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        window.statusBarColor = Color.rgb(5, 12, 28)
        window.navigationBarColor = Color.rgb(5, 12, 28)

        val root = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            gravity = Gravity.CENTER_HORIZONTAL
            setPadding(dp(16), dp(18), dp(16), dp(18))
            background = GradientDrawable(
                GradientDrawable.Orientation.TL_BR,
                intArrayOf(Color.rgb(5, 12, 28), Color.rgb(14, 30, 54))
            )
        }
        root.addView(TextView(this).apply {
            text = "JARVIS"
            textSize = 13f
            letterSpacing = .24f
            typeface = Typeface.DEFAULT_BOLD
            gravity = Gravity.CENTER
            setTextColor(Color.rgb(89, 224, 255))
            contentDescription = "JARVIS wearable companion"
        })
        root.addView(TextView(this).apply {
            text = "At a glance."
            textSize = 21f
            typeface = Typeface.DEFAULT_BOLD
            gravity = Gravity.CENTER
            setTextColor(Color.WHITE)
            setPadding(0, dp(8), 0, dp(2))
        })
        status = TextView(this).apply {
            text = "Finding your paired JARVIS phone…"
            textSize = 11f
            gravity = Gravity.CENTER
            setTextColor(Color.rgb(170, 190, 215))
            setPadding(dp(4), dp(8), dp(4), dp(12))
            accessibilityLiveRegion = TextView.ACCESSIBILITY_LIVE_REGION_POLITE
        }
        root.addView(status)
        root.addView(sectionLabel("QUICK ACTIONS"))
        listOf(
            action("PLAY / PAUSE", "media.play_pause"),
            action("NEXT TRACK", "media.next"),
            action("PREVIOUS", "media.previous"),
            action("PING JARVIS", "assistant.ping")
        ).forEach { button ->
            actionButtons += button
            root.addView(button, LinearLayout.LayoutParams(
                LinearLayout.LayoutParams.MATCH_PARENT, dp(46)
            ).apply { topMargin = dp(4); bottomMargin = dp(4) })
        }
        root.addView(TextView(this).apply {
            text = "Actions pass through your paired phone and its approved desktop permissions."
            textSize = 10f
            gravity = Gravity.CENTER
            setTextColor(Color.rgb(125, 150, 180))
            setPadding(dp(6), dp(12), dp(6), dp(4))
        })
        setContentView(ScrollView(this).apply {
            isFillViewport = true
            clipToPadding = false
            addView(root)
        })
        refreshPhoneConnection()
    }

    override fun onResume() {
        super.onResume()
        refreshPhoneConnection()
    }

    private fun sectionLabel(label: String) = TextView(this).apply {
        text = label
        textSize = 9f
        letterSpacing = .16f
        typeface = Typeface.DEFAULT_BOLD
        gravity = Gravity.CENTER
        setTextColor(Color.rgb(89, 224, 255))
        setPadding(0, dp(8), 0, dp(4))
    }

    private fun action(label: String, action: String): Button = Button(this).apply {
        text = label
        textSize = 10f
        isAllCaps = false
        typeface = Typeface.DEFAULT_BOLD
        setTextColor(Color.WHITE)
        contentDescription = label.lowercase().replace('/', ' ')
        background = GradientDrawable().apply {
            setColor(Color.rgb(27, 48, 76))
            cornerRadius = dp(24).toFloat()
            setStroke(dp(1), Color.rgb(48, 87, 126))
        }
        isEnabled = false
        alpha = .55f
        setOnClickListener {
            performHapticFeedback(HapticFeedbackConstants.VIRTUAL_KEY)
            sendAction(action)
        }
    }

    private fun dp(value: Int): Int = (value * resources.displayMetrics.density).toInt()

    private fun refreshPhoneConnection() {
        Wearable.getCapabilityClient(this)
            .getCapability("jarvis_phone_companion", CapabilityClient.FILTER_REACHABLE)
            .addOnSuccessListener { capability ->
                val phone = capability.nodes
                    .sortedByDescending(Node::isNearby)
                    .firstOrNull()
                setPhoneAvailable(phone != null)
            }
            .addOnFailureListener { setPhoneAvailable(false) }
    }

    private fun setPhoneAvailable(available: Boolean) {
        status.text = if (available) "Phone companion reachable · secure bridge ready"
            else "Open JARVIS on your paired Android phone to connect."
        actionButtons.forEach {
            it.isEnabled = available && !sending
            it.alpha = if (it.isEnabled) 1f else .55f
        }
    }

    private fun sendAction(action: String) {
        val payload = WearActionPolicy.encode(action) ?: run {
            status.text = "That action is not supported."
            return
        }
        if (sending) return
        sending = true
        setPhoneAvailable(true)
        status.text = "Sending securely…"
        Wearable.getCapabilityClient(this)
            .getCapability("jarvis_phone_companion", CapabilityClient.FILTER_REACHABLE)
            .addOnSuccessListener { capability ->
                val phone = capability.nodes.sortedByDescending(Node::isNearby).firstOrNull()
                if (phone == null) {
                    sending = false
                    setPhoneAvailable(false)
                    return@addOnSuccessListener
                }
                Wearable.getMessageClient(this)
                    .sendMessage(phone.id, WearActionPolicy.MESSAGE_PATH, payload)
                    .addOnSuccessListener {
                        sending = false
                        status.text = "Sent to your phone companion."
                        setPhoneAvailable(true)
                    }
                    .addOnFailureListener {
                        sending = false
                        status.text = "Phone bridge unavailable. Open JARVIS on your phone."
                        setPhoneAvailable(false)
                    }
            }
            .addOnFailureListener {
                sending = false
                setPhoneAvailable(false)
            }
    }
}
