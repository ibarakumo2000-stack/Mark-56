package com.mark56.companion

import org.junit.Assert.*
import org.junit.Test

class MediaCommandPolicyTest {
    @Test fun allowsOnlyExplicitMediaActions() {
        listOf("play", "pause", "play_pause", "next", "previous", "stop").forEach {
            assertNotNull(MediaCommandPolicy.resolve(it, false))
        }
        listOf("delete", "open_url", "launch_app", "volume", "").forEach {
            assertNull(MediaCommandPolicy.resolve(it, false))
        }
    }

    @Test fun resolvesPlayPauseFromPlaybackState() {
        assertEquals("pause", MediaCommandPolicy.resolve("play_pause", true))
        assertEquals("play", MediaCommandPolicy.resolve("play_pause", false))
        assertEquals("play", MediaCommandPolicy.resolve("play_pause", null))
    }

    @Test fun preservesExplicitCommands() {
        assertEquals("next", MediaCommandPolicy.resolve("next", true))
        assertEquals("previous", MediaCommandPolicy.resolve("previous", false))
        assertEquals("stop", MediaCommandPolicy.resolve("stop", null))
    }

    @Test fun pollingIsBoundedToFiveSeconds() {
        assertEquals(5_000L, MediaCommandPolicy.POLL_INTERVAL_MS)
    }
}
