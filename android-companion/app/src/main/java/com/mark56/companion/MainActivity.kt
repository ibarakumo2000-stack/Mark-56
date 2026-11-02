package com.mark56.companion

import android.graphics.Color
import android.graphics.Typeface
import android.graphics.drawable.GradientDrawable
import android.os.Bundle
import android.content.Intent
import android.content.ComponentName
import android.provider.Settings
import android.view.Gravity
import android.view.View
import android.widget.Button
import android.widget.LinearLayout
import android.widget.TextView
import android.widget.EditText
import android.text.InputType
import androidx.appcompat.app.AlertDialog
import android.content.res.ColorStateList
import com.google.android.material.button.MaterialButton
import androidx.appcompat.app.AppCompatActivity
import com.journeyapps.barcodescanner.ScanContract
import com.journeyapps.barcodescanner.ScanOptions
import org.json.JSONObject
import java.util.concurrent.Executors

class MainActivity : AppCompatActivity() {
    private val worker = Executors.newSingleThreadExecutor()
    private lateinit var status: TextView
    private lateinit var batterySyncButton: Button
    private lateinit var notificationRelayButton: Button
    private lateinit var mediaControlButton: Button
    private lateinit var wearBridgeButton: Button
    private lateinit var remoteRelayButton: Button
    private var remoteRelayClient: RemoteRelayClient? = null
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
        notificationRelayButton = actionButton("ENABLE NOTIFICATION RELAY", false).apply {
            setOnClickListener { toggleNotificationRelay() }
        }
        mediaControlButton = actionButton("REQUEST MEDIA CONTROL SCOPE", false).apply {
            setOnClickListener { toggleMediaControl() }
        }
        wearBridgeButton = actionButton("REQUEST WEAR OS BRIDGE", false).apply {
            setOnClickListener { toggleWearBridge() }
        }
        remoteRelayButton = actionButton("CONFIGURE SECURE REMOTE RELAY", false).apply {
            setOnClickListener { configureOrToggleRemoteRelay() }
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
        root.addView(notificationRelayButton, matchWidth())
        root.addView(mediaControlButton, matchWidth())
        root.addView(wearBridgeButton, matchWidth())
        root.addView(remoteRelayButton, matchWidth())
        root.addView(disconnect, matchWidth())
        root.addView(TextView(this).apply {
            text = "MARK 56  /  COMPANION"
            textSize = 10f
            letterSpacing = 0.15f
            setTextColor(Color.rgb(91, 111, 143))
            gravity = Gravity.CENTER
            setPadding(0, dp(14), 0, 0)
        })
        val scroll = android.widget.ScrollView(this).apply {
            isFillViewport = true
            clipToPadding = false
            setPadding(0, 0, 0, dp(12))
            addView(root)
        }
        window.statusBarColor = Color.rgb(5, 12, 28)
        window.navigationBarColor = Color.rgb(5, 12, 28)
        setContentView(scroll)
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

    private fun actionButton(label: String, primary: Boolean): Button = MaterialButton(this).apply {
        text = label
        textSize = 12f
        letterSpacing = 0.035f
        typeface = Typeface.DEFAULT_BOLD
        isAllCaps = false
        setTextColor(if (primary) Color.rgb(4, 18, 32) else Color.rgb(235, 243, 255))
        backgroundTintList = ColorStateList.valueOf(
            if (primary) Color.rgb(88, 225, 255) else Color.rgb(25, 43, 69)
        )
        rippleColor = ColorStateList.valueOf(Color.argb(65, 115, 215, 255))
        cornerRadius = dp(15)
        insetTop = 0
        insetBottom = 0
        if (!primary) {
            strokeWidth = dp(1)
            strokeColor = ColorStateList.valueOf(Color.rgb(48, 76, 110))
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
        refreshNotificationRelayButton()
        refreshMediaControlButton()
        refreshWearBridgeButton()
    }

    private fun refreshNotificationRelayButton() {
        val paired = tokenStore.read() != null && settings.deviceId() != null
        val approved = paired && settings.hasNotificationScope()
        notificationRelayButton.text = when {
            approved && settings.notificationRelayEnabled() -> "DISABLE NOTIFICATION RELAY"
            approved -> "ENABLE NOTIFICATION RELAY  ·  NOTIFICATION ACCESS"
            settings.notificationRelayRequested() -> "NOTIFICATION SCOPE REQUESTED  ·  TAP TO CANCEL"
            else -> "REQUEST NOTIFICATION SCOPE  ·  PAIR AGAIN"
        }
        notificationRelayButton.isEnabled = true
        notificationRelayButton.alpha = 1f
    }

    private fun refreshMediaControlButton() {
        val paired = tokenStore.read() != null && settings.deviceId() != null
        val approved = paired && settings.hasMediaScope()
        mediaControlButton.text = when {
            approved && settings.mediaControlEnabled() -> "DISABLE MEDIA CONTROLS"
            approved -> "ENABLE MEDIA CONTROLS  ·  ACTIVE SESSION ONLY"
            settings.mediaControlRequested() -> "MEDIA SCOPE REQUESTED  ·  TAP TO CANCEL"
            else -> "REQUEST MEDIA CONTROL SCOPE  ·  PAIR AGAIN"
        }
        mediaControlButton.isEnabled = true
        mediaControlButton.alpha = 1f
    }

    private fun refreshWearBridgeButton() {
        val paired = tokenStore.read() != null && settings.deviceId() != null
        val approved = paired && settings.hasCommandScope()
        wearBridgeButton.text = when {
            approved && settings.wearBridgeEnabled() -> "DISABLE WEAR OS BRIDGE"
            approved -> "ENABLE WEAR OS BRIDGE  ·  PHONE RELAY"
            settings.wearBridgeRequested() -> "WEAR OS SCOPE REQUESTED  ·  TAP TO CANCEL"
            else -> "REQUEST WEAR OS BRIDGE  ·  PAIR AGAIN"
        }
        wearBridgeButton.isEnabled = true
        wearBridgeButton.alpha = 1f
    }

    private fun toggleWearBridge() {
        val paired = tokenStore.read() != null && settings.deviceId() != null
        if (paired && settings.hasCommandScope()) {
            val enabled = !settings.wearBridgeEnabled()
            settings.setWearBridgeEnabled(enabled)
            status.text = if (enabled)
                "Wear OS bridge enabled. Watch actions are limited to the approved quick-action list."
            else "Wear OS bridge disabled. Watch actions will be ignored."
        } else {
            val requested = !settings.wearBridgeRequested()
            settings.setWearBridgeRequested(requested)
            status.text = if (requested)
                "Wear OS command scope requested. Disconnect and pair again after the desktop owner approves command.send."
            else "Wear OS bridge request cancelled."
        }
        refreshWearBridgeButton()
    }

    private fun configureOrToggleRemoteRelay() {
        if (remoteRelayClient != null) {
            remoteRelayClient?.close()
            remoteRelayClient = null
            remoteRelayButton.text = "CONNECT SECURE REMOTE RELAY"
            status.text = "Remote relay disconnected."
            return
        }
        val endpoint = settings.relayEndpoint()
        val channel = settings.relayChannel()
        val principal = settings.relayPrincipal()
        val token = tokenStore.readRelayToken()
        if (!endpoint.isNullOrBlank() && !channel.isNullOrBlank() &&
            !principal.isNullOrBlank() && !token.isNullOrBlank()) {
            connectRemoteRelay(endpoint, channel, principal, token)
            return
        }
        val form = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            setPadding(dp(20), dp(8), dp(20), 0)
        }
        fun field(hint: String, inputType: Int = InputType.TYPE_CLASS_TEXT): EditText =
            EditText(this).apply {
                this.hint = hint
                this.inputType = inputType
                setTextColor(Color.WHITE)
                setHintTextColor(Color.rgb(145, 165, 190))
                setSingleLine(true)
            }
        val urlField = field("Relay HTTPS URL (https://relay.example.com)", InputType.TYPE_CLASS_TEXT or InputType.TYPE_TEXT_VARIATION_URI)
        val channelField = field("Channel UUID")
        val principalField = field("Device principal ID")
        val tokenField = field("One-time relay token")
        tokenField.inputType = InputType.TYPE_CLASS_TEXT or InputType.TYPE_TEXT_VARIATION_PASSWORD
        listOf(urlField, channelField, principalField, tokenField).forEach { form.addView(it) }
        AlertDialog.Builder(this)
            .setTitle("Connect a remote JARVIS relay")
            .setMessage("Create a device credential with relay/provision.py on your trusted relay host. The token is encrypted with Android Keystore on this phone.")
            .setView(form)
            .setNegativeButton("Cancel", null)
            .setPositiveButton("Save & connect") { _, _ ->
                val url = urlField.text.toString().trim()
                val channelId = channelField.text.toString().trim()
                val principalId = principalField.text.toString().trim()
                val relayToken = tokenField.text.toString().trim()
                try {
                    settings.saveRelayConfig(url, channelId, principalId)
                    tokenStore.saveRelayToken(relayToken)
                    connectRemoteRelay(url, channelId, principalId, relayToken)
                } catch (error: Exception) {
                    status.text = "Relay configuration invalid: " + (error.message ?: "check the values")
                }
            }.show()
    }

    private fun connectRemoteRelay(endpoint: String, channel: String, principal: String, token: String) {
        try {
            remoteRelayButton.text = "CONNECTING TO REMOTE RELAY…"
            remoteRelayClient = RemoteRelayClient(
                endpoint, channel, principal, token,
                onState = { message ->
                    runOnUiThread {
                        status.text = message
                        remoteRelayButton.text = if (message.startsWith("Connected")) "DISCONNECT REMOTE RELAY"
                            else "REMOTE RELAY · TAP TO RECONNECT"
                    }
                },
                onMessage = { message ->
                    runOnUiThread {
                        status.text = "Remote JARVIS message received · " + message.optString("type", "message")
                    }
                }
            )
        } catch (error: Exception) {
            remoteRelayClient = null
            remoteRelayButton.text = "REMOTE RELAY · CONFIGURE AGAIN"
            status.text = "Could not connect to relay: " + (error.message ?: "invalid configuration")
        }
    }

    private fun hasNotificationAccess(): Boolean {
        val enabled = Settings.Secure.getString(contentResolver, "enabled_notification_listeners") ?: return false
        val component = ComponentName(this, CompanionNotificationListener::class.java).flattenToString()
        return enabled.split(':').contains(component)
    }

    private fun toggleMediaControl() {
        val paired = tokenStore.read() != null && settings.deviceId() != null
        if (paired && settings.hasMediaScope()) {
            val enabled = !settings.mediaControlEnabled()
            settings.setMediaControlEnabled(enabled)
            if (enabled && !hasNotificationAccess()) {
                status.text = "Media control needs Android Notification Access to discover active media sessions. Enable JARVIS access in Settings."
                startActivity(Intent(Settings.ACTION_NOTIFICATION_LISTENER_SETTINGS))
            } else {
                status.text = if (enabled)
                    "Media controls enabled. Desktop commands will target a single unambiguous active media session."
                else "Media controls disabled. No desktop media commands will be executed."
            }
        } else {
            val requested = !settings.mediaControlRequested()
            settings.setMediaControlRequested(requested)
            status.text = if (requested)
                "Media scope requested for your next pairing. Disconnect, then scan a fresh desktop QR with media.control approved."
            else "Media scope request cancelled."
        }
        refreshMediaControlButton()
    }

    private fun toggleNotificationRelay() {
        val paired = tokenStore.read() != null && settings.deviceId() != null
        if (paired && settings.hasNotificationScope()) {
            val enabled = !settings.notificationRelayEnabled()
            settings.setNotificationRelayEnabled(enabled)
            status.text = if (enabled)
                "Enable JARVIS notification access in Android Settings. Notification text is forwarded only while both approvals and this toggle remain enabled."
            else "Notification relay disabled. No notification content will be forwarded."
            refreshNotificationRelayButton()
            if (enabled) startActivity(Intent(Settings.ACTION_NOTIFICATION_LISTENER_SETTINGS))
        } else {
            val requested = !settings.notificationRelayRequested()
            settings.setNotificationRelayRequested(requested)
            status.text = if (requested)
                "Notification scope requested for your next pairing. Disconnect, then scan a fresh desktop QR with notification.receive approved."
            else "Notification scope request cancelled."
            refreshNotificationRelayButton()
        }
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
                    val requestedScopes = mutableListOf("battery.read")
                    if (settings.notificationRelayRequested()) requestedScopes.add("notification.receive")
                    if (settings.mediaControlRequested()) requestedScopes.add("media.control")
                    if (settings.wearBridgeRequested()) requestedScopes.add("command.send")
                    val response = PinnedCompanionClient(endpoint, fingerprint).pair(
                        code, android.os.Build.MODEL ?: "Android device", requestedScopes
                    )
                    val token = response.getString("token")
                    val deviceId = response.getString("device_id")
                    val scopes = response.optJSONArray("scopes")
                    fun hasScope(scope: String): Boolean = scopes?.let { array ->
                        (0 until array.length()).any { array.optString(it) == scope }
                    } ?: false
                    val hasNotificationScope = hasScope("notification.receive")
                    val hasBatteryScope = hasScope("battery.read")
                    val hasMediaScope = hasScope("media.control")
                    runOnUiThread {
                        tokenStore.save(token)
                        settings.saveConnection(endpoint, fingerprint, deviceId,
                            hasBatteryScope, hasNotificationScope, hasMediaScope,
                            hasScope("command.send"))
                        BatterySync.disable(this)
                        settings.setMediaControlEnabled(false)
                        settings.setWearBridgeEnabled(false)
                        refreshBatteryButton()
                        status.text = "Paired with " + response.optString("device_name", "JARVIS desktop") +
                            ". Battery sharing is off. Notification relay and media controls remain off until separately enabled."
                        if (settings.mediaControlRequested() && !hasMediaScope) {
                            status.text = status.text.toString() + " Desktop did not approve media.control; pair again after approval."
                        }
                        if (settings.wearBridgeRequested() && !hasScope("command.send")) {
                            status.text = status.text.toString() + " Desktop did not approve command.send; Wear OS bridge is unavailable."
                        }
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
        remoteRelayClient?.close()
        remoteRelayClient = null
        super.onDestroy()
    }
}
