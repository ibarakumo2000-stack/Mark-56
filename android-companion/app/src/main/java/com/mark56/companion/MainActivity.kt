package com.mark56.companion

import android.graphics.Color
import android.graphics.Typeface
import android.graphics.drawable.GradientDrawable
import android.os.Bundle
import android.view.Gravity
import android.view.View
import android.widget.Button
import android.widget.LinearLayout
import android.widget.TextView
import androidx.appcompat.app.AppCompatActivity
import com.journeyapps.barcodescanner.ScanContract
import com.journeyapps.barcodescanner.ScanOptions
import org.json.JSONObject
import java.util.concurrent.Executors

class MainActivity : AppCompatActivity() {
    private val worker = Executors.newSingleThreadExecutor()
    private lateinit var status: TextView
    private lateinit var batterySyncButton: Button
    private lateinit var tokenStore: SecureTokenStore
    private lateinit var settings: CompanionSettings

    private val scanner = registerForActivityResult(ScanContract()) { result ->
        if (result.contents.isNullOrBlank()) {
            status.text = "Scan cancelled"
            return@registerForActivityResult
        }
        handleQr(result.contents)
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        tokenStore = SecureTokenStore(getSharedPreferences("companion_secure", MODE_PRIVATE))
        settings = CompanionSettings(this)

        val root = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            gravity = Gravity.CENTER_HORIZONTAL
            setPadding(dp(24), dp(30), dp(24), dp(24))
            background = GradientDrawable(
                GradientDrawable.Orientation.TL_BR,
                intArrayOf(Color.rgb(5, 12, 28), Color.rgb(12, 24, 48), Color.rgb(7, 10, 22))
            )
        }
        val brand = TextView(this).apply {
            text = "J A R V I S"
            textSize = 13f
            letterSpacing = 0.22f
            typeface = Typeface.create("sans-serif-medium", Typeface.BOLD)
            setTextColor(Color.rgb(89, 224, 255))
            gravity = Gravity.CENTER
        }
        val title = TextView(this).apply {
            text = "Your AI.\nEverywhere."
            textSize = 34f
            typeface = Typeface.create("sans-serif", Typeface.BOLD)
            setTextColor(Color.WHITE)
            gravity = Gravity.CENTER
            setPadding(0, dp(12), 0, dp(8))
        }
        val subtitle = TextView(this).apply {
            text = "A secure companion for your desktop, phone and connected wearables."
            textSize = 14f
            setTextColor(Color.rgb(169, 187, 211))
            gravity = Gravity.CENTER
            setPadding(dp(8), 0, dp(8), dp(22))
        }
        val connectionCard = card()
        val sectionLabel = TextView(this).apply {
            text = "CONNECTION STATUS"
            textSize = 11f
            letterSpacing = 0.12f
            typeface = Typeface.DEFAULT_BOLD
            setTextColor(Color.rgb(89, 224, 255))
        }
        status = TextView(this).apply {
            text = if (tokenStore.read() == null) "Not paired yet\nConnect securely to your JARVIS desktop."
            else "Credential stored securely\nYour phone is paired with JARVIS."
            textSize = 15f
            setTextColor(Color.WHITE)
            setPadding(0, dp(10), 0, dp(8))
        }
        connectionCard.addView(sectionLabel)
        connectionCard.addView(status)

        val pair = actionButton("PAIR WITH DESKTOP  ·  SCAN QR", true).apply {
            setOnClickListener {
                scanner.launch(
                    ScanOptions().setDesiredBarcodeFormats(ScanOptions.QR_CODE)
                        .setPrompt("Scan the secure pairing QR displayed by JARVIS")
                        .setBeepEnabled(false).setOrientationLocked(false)
                )
            }
        }
        val featuresCard = card().apply {
            addView(TextView(this@MainActivity).apply {
                text = "CONNECTED ECOSYSTEM"
                textSize = 11f
                letterSpacing = 0.12f
                typeface = Typeface.DEFAULT_BOLD
                setTextColor(Color.rgb(89, 224, 255))
            })
            addView(featureLine("✦", "Wearables-ready", "Connect compatible watches and smart glasses through supported device protocols."))
            addView(featureLine("◈", "Privacy-first pairing", "One-time QR · certificate pinning · encrypted device credential"))
            addView(featureLine("⌁", "Background sync", "Battery updates are optional and remain disabled until you enable them."))
        }

        batterySyncButton = actionButton("ENABLE BATTERY SYNC", false).apply {
            setOnClickListener { toggleBatterySync() }
        }
        val disconnect = actionButton("DISCONNECT DEVICE", false).apply {
            setOnClickListener {
                BatterySync.disable(this@MainActivity)
                tokenStore.clear()
                settings.clearConnection()
                refreshBatteryButton()
                status.text = "Local credential cleared. Revoke this device in JARVIS desktop to invalidate server access."
            }
        }
        root.addView(brand)
        root.addView(title)
        root.addView(subtitle)
        root.addView(connectionCard, matchWidth())
        root.addView(pair, matchWidth())
        root.addView(featuresCard, matchWidth())
        root.addView(batterySyncButton, matchWidth())
        root.addView(disconnect, matchWidth())
        root.addView(TextView(this).apply {
            text = "MARK 56  /  COMPANION"
            textSize = 10f
            letterSpacing = 0.15f
            setTextColor(Color.rgb(91, 111, 143))
            gravity = Gravity.CENTER
            setPadding(0, dp(14), 0, 0)
        })
        setContentView(root)
        refreshBatteryButton()
    }

    private fun card(): LinearLayout = LinearLayout(this).apply {
        orientation = LinearLayout.VERTICAL
        setPadding(dp(18), dp(18), dp(18), dp(18))
        background = GradientDrawable().apply {
            setColor(Color.argb(225, 17, 31, 54))
            cornerRadius = dp(20).toFloat()
            setStroke(dp(1), Color.rgb(39, 67, 99))
        }
    }

    private fun actionButton(label: String, primary: Boolean): Button = Button(this).apply {
        text = label
        textSize = 12f
        letterSpacing = 0.04f
        typeface = Typeface.DEFAULT_BOLD
        isAllCaps = false
        setTextColor(if (primary) Color.rgb(4, 18, 32) else Color.WHITE)
        background = GradientDrawable(
            GradientDrawable.Orientation.LEFT_RIGHT,
            if (primary) intArrayOf(Color.rgb(86, 225, 255), Color.rgb(104, 170, 255))
            else intArrayOf(Color.rgb(29, 48, 75), Color.rgb(23, 37, 60))
        ).apply {
            cornerRadius = dp(15).toFloat()
            if (!primary) setStroke(dp(1), Color.rgb(45, 71, 102))
        }
        minimumHeight = dp(54)
        stateListAnimator = null
    }

    private fun featureLine(symbol: String, heading: String, detail: String): View {
        val line = LinearLayout(this).apply {
            orientation = LinearLayout.HORIZONTAL
            gravity = Gravity.CENTER_VERTICAL
            setPadding(0, dp(14), 0, 0)
        }
        val glyph = TextView(this).apply {
            text = symbol
            textSize = 22f
            setTextColor(Color.rgb(89, 224, 255))
            gravity = Gravity.CENTER
        }
        val copy = LinearLayout(this).apply { orientation = LinearLayout.VERTICAL; setPadding(dp(12), 0, 0, 0) }
        copy.addView(TextView(this).apply {
            text = heading
            textSize = 14f
            typeface = Typeface.DEFAULT_BOLD
            setTextColor(Color.WHITE)
        })
        copy.addView(TextView(this).apply {
            text = detail
            textSize = 12f
            setTextColor(Color.rgb(161, 181, 207))
            setPadding(0, dp(3), 0, 0)
        })
        line.addView(glyph, LinearLayout.LayoutParams(dp(30), dp(44)))
        line.addView(copy, LinearLayout.LayoutParams(0, LinearLayout.LayoutParams.WRAP_CONTENT, 1f))
        return line
    }

    private fun matchWidth() = LinearLayout.LayoutParams(
        LinearLayout.LayoutParams.MATCH_PARENT, LinearLayout.LayoutParams.WRAP_CONTENT
    ).apply { bottomMargin = dp(12) }

    private fun dp(value: Int): Int = (value * resources.displayMetrics.density).toInt()

    private fun refreshBatteryButton() {
        batterySyncButton.text = if (settings.batterySyncEnabled()) "DISABLE BATTERY SYNC"
        else "ENABLE BATTERY SYNC  ·  15-MINUTE UPDATES"
        batterySyncButton.isEnabled = tokenStore.read() != null &&
            settings.deviceId() != null && settings.endpoint() != null &&
            settings.fingerprint() != null && settings.hasBatteryScope()
        batterySyncButton.alpha = if (batterySyncButton.isEnabled) 1f else 0.55f
    }

    private fun toggleBatterySync() {
        if (settings.batterySyncEnabled()) {
            BatterySync.disable(this)
            status.text = "Battery sharing disabled."
        } else {
            BatterySync.enable(this)
            status.text = "Battery sharing enabled. Updates run periodically when network is available."
        }
        refreshBatteryButton()
    }

    private fun handleQr(raw: String) {
        try {
            val qr = JSONObject(raw)
            require(qr.optString("protocol") == "mark56-companion" && qr.optInt("version") == 1)
            val endpoint = qr.getString("endpoint")
            val code = qr.getString("pairing_code")
            val fingerprint = qr.getString("certificate_sha256")
            require(qr.getLong("expires_at") > System.currentTimeMillis() / 1000) {
                "Pairing QR has expired"
            }
            status.text = "Connecting securely to JARVIS…"
            worker.execute {
                try {
                    val response = PinnedCompanionClient(endpoint, fingerprint).pair(
                        code, android.os.Build.MODEL ?: "Android device",
                        listOf("battery.read")
                    )
                    val token = response.getString("token")
                    val deviceId = response.getString("device_id")
                    val scopes = response.optJSONArray("scopes")
                    val hasBatteryScope = scopes?.let { array ->
                        (0 until array.length()).any { array.optString(it) == "battery.read" }
                    } ?: false
                    runOnUiThread {
                        tokenStore.save(token)
                        settings.saveConnection(endpoint, fingerprint, deviceId, hasBatteryScope)
                        BatterySync.disable(this)
                        refreshBatteryButton()
                        status.text = "Paired with " + response.optString("device_name", "JARVIS desktop") +
                            ". Battery sharing is off until you enable it."
                        if (!hasBatteryScope) status.text =
                            "Paired, but battery.read was not approved on desktop. Battery sync is unavailable."
                    }
                } catch (e: Exception) {
                    runOnUiThread { status.text = "Pairing failed: " + (e.message ?: "connection error") }
                }
            }
        } catch (e: Exception) {
            status.text = "Invalid pairing QR: " + e.message
        }
    }

    override fun onDestroy() {
        worker.shutdownNow()
        super.onDestroy()
    }
}
