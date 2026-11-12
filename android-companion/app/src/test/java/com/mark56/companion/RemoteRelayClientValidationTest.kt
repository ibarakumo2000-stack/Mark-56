package com.mark56.companion

import org.junit.Assert.assertThrows
import org.junit.Test

class RemoteRelayClientValidationTest {
    private val channel = "1b2d2d52-8d75-4b56-8b8a-8f0c0d7e4f11"
    private val token = "rly_" + "a".repeat(56)
    private val state: (String) -> Unit = {}
    private val message: (org.json.JSONObject) -> Unit = {}

    @Test fun recognizesRelayControlFramesWithoutTreatingThemAsApplicationMessages() {
        org.junit.Assert.assertTrue(RemoteRelayProtocol.isControlFrame("ack"))
        org.junit.Assert.assertTrue(RemoteRelayProtocol.isControlFrame("error"))
        org.junit.Assert.assertFalse(RemoteRelayProtocol.isControlFrame("command"))
        org.junit.Assert.assertTrue(RemoteRelayProtocol.isMessageType("command"))
    }

    @Test fun reconnectsAfterServerCloseButNotAfterCredentialRejectionOrManualClose() {
        org.junit.Assert.assertTrue(RemoteRelayProtocol.shouldReconnect(1001, false))
        org.junit.Assert.assertTrue(RemoteRelayProtocol.shouldReconnect(4001, false))
        org.junit.Assert.assertFalse(RemoteRelayProtocol.shouldReconnect(4403, false))
        org.junit.Assert.assertFalse(RemoteRelayProtocol.shouldReconnect(1000, true))
    }

    @Test fun reconnectDelayUsesBoundedExponentialBackoff() {
        org.junit.Assert.assertEquals(1L, RemoteRelayProtocol.reconnectDelaySeconds(0))
        org.junit.Assert.assertEquals(2L, RemoteRelayProtocol.reconnectDelaySeconds(1))
        org.junit.Assert.assertEquals(60L, RemoteRelayProtocol.reconnectDelaySeconds(6))
        org.junit.Assert.assertEquals(60L, RemoteRelayProtocol.reconnectDelaySeconds(20))
    }

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
