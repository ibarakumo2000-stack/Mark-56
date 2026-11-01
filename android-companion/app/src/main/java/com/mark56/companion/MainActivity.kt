package com.mark56.companion

import android.os.Bundle
import android.view.Gravity
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
    private lateinit var tokenStore: SecureTokenStore
    private val scanner = registerForActivityResult(ScanContract()) { result ->
        if (result.contents.isNullOrBlank()) { status.text = "Scan cancelled"; return@registerForActivityResult }
        handleQr(result.contents)
    }
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        tokenStore = SecureTokenStore(getSharedPreferences("companion_secure", MODE_PRIVATE))
        val layout = LinearLayout(this).apply { orientation = LinearLayout.VERTICAL; gravity = Gravity.CENTER; setPadding(32, 48, 32, 48) }
        val title = TextView(this).apply { text = "MARK 56 COMPANION"; textSize = 24f; gravity = Gravity.CENTER }
        status = TextView(this).apply {
            text = if (tokenStore.read() == null) "Not paired — scan the QR code shown by Jarvis." else "A device credential is stored securely on this phone."
            textSize = 16f; gravity = Gravity.CENTER; setPadding(0, 32, 0, 32)
        }
        val scan = Button(this).apply { text = "Scan pairing QR"; setOnClickListener {
            scanner.launch(ScanOptions().setDesiredBarcodeFormats(ScanOptions.QR_CODE).setPrompt("Scan the QR code displayed by Mark 56").setBeepEnabled(false).setOrientationLocked(false))
        } }
        val disconnect = Button(this).apply { text = "Disconnect this phone"; setOnClickListener {
            tokenStore.clear(); status.text = "Local credential cleared. Revoke the device in Jarvis to disable server access."
        } }
        layout.addView(title); layout.addView(status); layout.addView(scan); layout.addView(disconnect)
        setContentView(layout)
    }
    private fun handleQr(raw: String) {
        try {
            val qr = JSONObject(raw)
            require(qr.optString("protocol") == "mark56-companion" && qr.optInt("version") == 1)
            val endpoint = qr.getString("endpoint")
            val code = qr.getString("pairing_code")
            val fingerprint = qr.getString("certificate_sha256")
            require(qr.getLong("expires_at") > System.currentTimeMillis() / 1000) { "Pairing QR has expired" }
            status.text = "Connecting securely to Mark 56…"
            worker.execute {
                try {
                    val response = PinnedCompanionClient(endpoint, fingerprint).pair(code,
                        android.os.Build.MODEL ?: "Android device",
                        listOf("notification.receive", "battery.read", "media.control"))
                    val token = response.getString("token")
                    runOnUiThread {
                        tokenStore.save(token)
                        status.text = "Paired with " + response.optString("device_name", "Mark 56") +
                            ". Permissions: " + response.optJSONArray("scopes")
                    }
                } catch (e: Exception) {
                    runOnUiThread { status.text = "Pairing failed: " + (e.message ?: "connection error") }
                }
            }
        } catch (e: Exception) { status.text = "Invalid pairing QR: " + e.message }
    }
    override fun onDestroy() { worker.shutdownNow(); super.onDestroy() }
}
