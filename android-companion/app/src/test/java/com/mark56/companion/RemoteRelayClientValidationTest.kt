package com.mark56.companion

import org.junit.Assert.assertThrows
import org.junit.Test

class RemoteRelayClientValidationTest {
    private val channel = "1b2d2d52-8d75-4b56-8b8a-8f0c0d7e4f11"
    private val token = "rly_" + "a".repeat(56)
    private val state: (String) -> Unit = {}
    private val message: (org.json.JSONObject) -> Unit = {}

    @Test fun rejectsPlainHttpRelay() {
        assertThrows(IllegalArgumentException::class.java) {
            RemoteRelayClient("http://relay.example.com", channel, "phone-1", token, state, message)
        }
    }

    @Test fun rejectsEmbeddedCredentialsAndPaths() {
        assertThrows(IllegalArgumentException::class.java) {
            RemoteRelayClient("https://user:pass@relay.example.com", channel, "phone-1", token, state, message)
        }
        assertThrows(IllegalArgumentException::class.java) {
            RemoteRelayClient("https://relay.example.com/private", channel, "phone-1", token, state, message)
        }
    }

    @Test fun rejectsMalformedIdentityAndWeakToken() {
        assertThrows(IllegalArgumentException::class.java) {
            RemoteRelayClient("https://relay.example.com", "not-a-uuid", "phone-1", token, state, message)
        }
        assertThrows(IllegalArgumentException::class.java) {
            RemoteRelayClient("https://relay.example.com", channel, "phone-1", "rly_short", state, message)
        }
    }
}
