package com.mark56.wear

import org.junit.Assert.assertArrayEquals
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test
import org.json.JSONObject

class WearActionPolicyTest {
    @Test fun onlyAllowlistedActionsAreEncoded() {
        listOf("assistant.ping", "media.play_pause", "media.next", "media.previous").forEach {
            assertTrue(WearActionPolicy.encode(it) != null)
        }
        listOf("shell.exec", "open_url", "camera.capture", "").forEach {
            assertNull(WearActionPolicy.encode(it))
        }
    }

    @Test fun payloadContainsOnlyTheAction() {
        val payload = WearActionPolicy.encode("assistant.ping")!!
        val decoded = JSONObject(String(payload, Charsets.UTF_8))
        assertTrue(decoded.keys().asSequence().toList() == listOf("action"))
        assertTrue(decoded.getString("action") == "assistant.ping")
    }
}
