package com.mark56.companion

import org.junit.Assert.assertEquals
import org.junit.Test

class WearConnectionStatusTest {
    @Test fun pairingAndPermissionGatesAreReportedSeparately() {
        assertEquals(
            "Desktop pairing: required.\nNo Wear OS Data Layer node is currently connected to this phone.",
            WearConnectionStatus.describe(false, false, false, 0),
        )
        assertEquals(
            "Desktop permission: command.send is not approved.\n1 Wear OS Data Layer node is connected to this phone.",
            WearConnectionStatus.describe(true, false, true, 1),
        )
        assertEquals(
            "Phone bridge: disabled.\n2 Wear OS Data Layer nodes are connected to this phone.",
            WearConnectionStatus.describe(true, true, false, 2),
        )
    }

    @Test fun enabledBridgeAndLookupStatesAreAccurate() {
        assertEquals(
            "Phone bridge: enabled · command.send approved.\nChecking connected Wear OS devices…",
            WearConnectionStatus.describe(true, true, true, null),
        )
        assertEquals(
            "Phone bridge: enabled · command.send approved.\nWear OS connection discovery is unavailable. Try again.",
            WearConnectionStatus.describe(true, true, true, null, lookupFailed = true),
        )
    }
}
