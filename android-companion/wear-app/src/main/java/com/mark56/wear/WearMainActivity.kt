package com.mark56.wear

import android.app.Activity
import android.graphics.Color
import android.graphics.Typeface
import android.graphics.drawable.GradientDrawable
import android.os.Bundle
import android.view.Gravity
import android.widget.Button
import android.widget.LinearLayout
import android.widget.TextView
import com.google.android.gms.wearable.Wearable
import org.json.JSONObject

class WearMainActivity : Activity() {
    private lateinit var status: TextView

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        window.statusBarColor = Color.rgb(5, 12, 28)
        window.navigationBarColor = Color.rgb(5, 12, 28)
        val root = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            gravity = Gravity.CENTER
            setPadding(22, 22, 22, 22)
            background = GradientDrawable(
                GradientDrawable.Orientation.TL_BR,
                intArrayOf(Color.rgb(5, 12, 28), Color.rgb(14, 30, 54))
            )
        }
        root.addView(TextView(this).apply {
            text = "JARVIS"
            textSize = 15f
            letterSpacing = .24f
            typeface = Typeface.DEFAULT_BOLD
            gravity = Gravity.CENTER
            setTextColor(Color.rgb(89, 224, 255))
        })
        root.addView(TextView(this).apply {
            text = "At a glance."
            textSize = 24f
            typeface = Typeface.DEFAULT_BOLD
            gravity = Gravity.CENTER
            setTextColor(Color.WHITE)
            setPadding(0, 8, 0, 2)
        })
        status = TextView(this).apply {
            text = "Connect your watch to the JARVIS phone companion."
            textSize = 11f
            gravity = Gravity.CENTER
            setTextColor(Color.rgb(170, 190, 215))
            setPadding(4, 8, 4, 12)
        }
        root.addView(status)
        root.addView(action("PLAY / PAUSE", "media.play_pause"))
        root.addView(action("NEXT TRACK", "media.next"))
        root.addView(action("PREVIOUS", "media.previous"))
        root.addView(action("PING JARVIS", "assistant.ping"))
        setContentView(root)
    }

    private fun action(label: String, action: String): Button = Button(this).apply {
        text = label
        textSize = 10f
        isAllCaps = false
        setTextColor(Color.WHITE)
        background = GradientDrawable().apply {
            setColor(Color.rgb(27, 48, 76))
            cornerRadius = 24f
            setStroke(1, Color.rgb(48, 87, 126))
        }
        setOnClickListener { sendAction(action) }
    }

    private fun sendAction(action: String) {
        status.text = "Sending securely…"
        Wearable.getNodeClient(this).connectedNodes
            .addOnSuccessListener { nodes ->
                if (nodes.isEmpty()) {
                    status.text = "No paired phone is reachable."
                    return@addOnSuccessListener
                }
                val payload = JSONObject().put("action", action).toString().toByteArray(Charsets.UTF_8)
                val sends = nodes.map { node ->
                    Wearable.getMessageClient(this).sendMessage(node.id, "/jarvis/v1/action", payload)
                }
                sends.first().addOnSuccessListener {
                    status.text = "Sent to phone companion."
                }.addOnFailureListener {
                    status.text = "Phone bridge unavailable. Open JARVIS on your phone."
                }
            }.addOnFailureListener {
                status.text = "Could not find a paired phone."
            }
    }
}
