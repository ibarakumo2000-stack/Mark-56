package com.mark56.companion

/** Human-readable readiness state; connected-node count is transport-only, not proof of app installation. */
internal object WearConnectionStatus {
    fun describe(
        paired: Boolean,
        commandScopeApproved: Boolean,
        bridgeEnabled: Boolean,
        connectedNodeCount: Int?,
        lookupFailed: Boolean = false,
    ): String {
        val gate = when {
            !paired -> "Desktop pairing: required."
            !commandScopeApproved -> "Desktop permission: command.send is not approved."
            !bridgeEnabled -> "Phone bridge: disabled."
            else -> "Phone bridge: enabled · command.send approved."
        }
        val transport = when {
            lookupFailed -> "Wear OS connection discovery is unavailable. Try again."
            connectedNodeCount == null -> "Checking connected Wear OS devices…"
            connectedNodeCount == 0 -> "No Wear OS Data Layer node is currently connected to this phone."
            connectedNodeCount == 1 -> "1 Wear OS Data Layer node is connected to this phone."
            else -> "$connectedNodeCount Wear OS Data Layer nodes are connected to this phone."
        }
        return "$gate\n$transport"
    }
}
