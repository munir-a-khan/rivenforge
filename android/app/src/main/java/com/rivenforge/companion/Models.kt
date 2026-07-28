package com.rivenforge.companion

/** Where the desktop lives + the bearer token to reach it. */
data class Creds(val host: String, val port: Int, val token: String) {
    val httpBase: String get() = "http://$host:$port"
    val wsEvents: String get() = "ws://$host:$port/events?token=$token"
}

/** Connection state of the live event socket, surfaced in the UI. */
enum class ConnState { DISCONNECTED, CONNECTING, CONNECTED, ERROR }

/**
 * One roll as rendered in the live log. Built from a "roll" event on the
 * WebSocket. Kept as pre-formatted strings so the UI stays dumb.
 */
data class RollItem(
    val rollNum: Int,
    val decision: String,      // ACCEPTED / NEW BEST / REVERT
    val positives: List<String>,
    val negatives: List<String>,
    val score: String,         // new score, formatted
    val accepted: Boolean
)

/** What the desktop reports is running right now (GET /roll/session). */
data class SessionInfo(
    val running: Boolean,
    val weapon: String,
    val weaponType: String,
    val rollLimit: Int
)

/**
 * The desktop's current saved roll settings (GET /config), shown on the "Roll
 * Again" card and re-sent verbatim to restart the same session.
 */
data class RollSettings(
    val weapon: String,
    val weaponType: String,
    val rollLimit: Int,          // 0 = unlimited
    val rollUntilMatch: Boolean,
    val statPriority: List<String>,
    val negPriority: List<String>
)
