package com.mark56.companion

import org.junit.Assert.*
import org.junit.Test

class NotificationRelayPolicyTest {
    @Test fun rejectsNegativeTimestamp() {
        assertNull(NotificationRelayPolicy.create("Mail", "Subject", "Body", -1))
    }

    @Test fun rejectsEmptyDisplayContent() {
        assertNull(NotificationRelayPolicy.create("Mail", "  ", "\u0000", 10))
    }

    @Test fun stripsControlsAndBoundsDisplayFields() {
        val result = NotificationRelayPolicy.create("  Mail\u0000App  ", "  Subject\u0001  ", " Body\u0002\ncontinued ", 123)
        assertNotNull(result)
        assertEquals("MailApp", result!!.app)
        assertEquals("Subject", result.title)
        assertEquals("Body\ncontinued", result.text)
        assertEquals(123L, result.occurredAt)
    }

    @Test fun boundsEachFieldToContractLimits() {
        val result = NotificationRelayPolicy.create("a".repeat(100), "t".repeat(600), "x".repeat(600), 1)!!
        assertEquals(80, result.app.length)
        assertEquals(512, result.title.length)
        assertEquals(512, result.text.length)
    }

    @Test fun permitsTextOnlyNotifications() {
        val result = NotificationRelayPolicy.create("Chat", "", "Message", 5)
        assertNotNull(result)
        assertEquals("", result!!.title)
        assertEquals("Message", result.text)
    }
}
