package com.rivenforge.companion

import android.os.Handler
import android.os.Looper
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.Response
import okhttp3.WebSocket
import okhttp3.WebSocketListener
import org.json.JSONArray
import org.json.JSONObject
import java.util.concurrent.TimeUnit

/**
 * Talks to a paired rivenforge desktop: the live event WebSocket plus a couple
 * of HTTP calls. All UI callbacks are marshalled onto the main thread.
 */
class RivenforgeClient(private val creds: Creds) {

    private val http = OkHttpClient.Builder()
        .pingInterval(20, TimeUnit.SECONDS)   // keep the WS alive through NAT/idle
        .readTimeout(0, TimeUnit.MILLISECONDS) // a streaming socket never "times out"
        .build()

    private val main = Handler(Looper.getMainLooper())
    private var socket: WebSocket? = null

    private fun bearer(req: Request.Builder): Request.Builder =
        req.header("Authorization", "Bearer ${creds.token}")

    // ── Live event stream ────────────────────────────────────────────────────

    fun connect(
        onState: (ConnState) -> Unit,
        onRoll: (RollItem) -> Unit,
        onDone: (String) -> Unit
    ) {
        onState(ConnState.CONNECTING)
        val req = bearer(Request.Builder().url(creds.wsEvents)).build()
        socket = http.newWebSocket(req, object : WebSocketListener() {
            override fun onOpen(webSocket: WebSocket, response: Response) =
                main.post { onState(ConnState.CONNECTED) }

            override fun onMessage(webSocket: WebSocket, text: String) {
                val item = runCatching { parseEvent(text) }.getOrNull()
                when (item) {
                    is RollItem -> main.post { onRoll(item) }
                    is String -> main.post { onDone(item) } // "done"/"error" reason
                }
            }

            override fun onFailure(webSocket: WebSocket, t: Throwable, response: Response?) =
                main.post { onState(ConnState.ERROR) }

            override fun onClosed(webSocket: WebSocket, code: Int, reason: String) =
                main.post { onState(ConnState.DISCONNECTED) }
        })
    }

    fun disconnect() {
        socket?.close(1000, "bye")
        socket = null
    }

    /** roll → RollItem; done/error → reason String; anything else → null. */
    private fun parseEvent(text: String): Any? {
        val o = JSONObject(text)
        return when (o.optString("kind")) {
            "roll" -> {
                val parsed = o.optJSONObject("parsed") ?: JSONObject()
                val rag = o.optJSONObject("rag_result") ?: JSONObject()
                RollItem(
                    rollNum = o.optInt("roll_num"),
                    decision = decisionOf(o, rag),
                    positives = statList(parsed.optJSONArray("positives")),
                    negatives = statList(parsed.optJSONArray("negatives")),
                    score = rag.opt("new_score")?.toString() ?: "",
                    accepted = o.optBoolean("accepted")
                )
            }
            "done" -> o.optString("reason", "Session ended.")
            "error" -> "Error: " + o.optString("message", "unknown").lineSequence().firstOrNull()
            else -> null
        }
    }

    private fun decisionOf(o: JSONObject, rag: JSONObject): String = when {
        o.optBoolean("accepted") -> "ACCEPTED"
        rag.optBoolean("is_better") -> "NEW BEST"
        else -> "REVERT"
    }

    /**
     * Stats arrive as objects; the exact key names vary, so pull the first
     * plausible name+value rather than assuming a schema.
     */
    private fun statList(arr: JSONArray?): List<String> {
        if (arr == null) return emptyList()
        val out = ArrayList<String>(arr.length())
        for (i in 0 until arr.length()) {
            val e = arr.opt(i)
            out.add(
                when (e) {
                    is JSONObject -> {
                        val name = firstNonEmpty(e, "stat", "name", "display", "label")
                        val value = firstNonEmpty(e, "value", "amount", "magnitude")
                        listOf(value, name).filter { it.isNotBlank() }.joinToString(" ").ifBlank { e.toString() }
                    }
                    else -> e?.toString().orEmpty()
                }
            )
        }
        return out
    }

    private fun firstNonEmpty(o: JSONObject, vararg keys: String): String {
        for (k in keys) {
            val v = o.opt(k)?.toString().orEmpty()
            if (v.isNotBlank() && v != "null") return v
        }
        return ""
    }

    // ── HTTP ─────────────────────────────────────────────────────────────────

    suspend fun fetchSession(): SessionInfo? = withContext(Dispatchers.IO) {
        runCatching {
            val req = bearer(Request.Builder().url("${creds.httpBase}/roll/session")).build()
            http.newCall(req).execute().use { r ->
                val o = JSONObject(r.body?.string().orEmpty())
                SessionInfo(
                    running = o.optBoolean("running"),
                    weapon = o.optString("weapon"),
                    weaponType = o.optString("weapon_type"),
                    rollLimit = o.optInt("roll_limit")
                )
            }
        }.getOrNull()
    }

    /** Reachability + token probe before we commit to the socket. */
    suspend fun ping(): Boolean = withContext(Dispatchers.IO) {
        runCatching {
            val req = bearer(Request.Builder().url("${creds.httpBase}/health")).build()
            http.newCall(req).execute().use { it.isSuccessful }
        }.getOrDefault(false)
    }

    suspend fun stopSession(): Boolean = withContext(Dispatchers.IO) {
        runCatching {
            val req = bearer(
                Request.Builder().url("${creds.httpBase}/roll/stop")
                    .post(okhttp3.RequestBody.create(null, ByteArray(0)))
            ).build()
            http.newCall(req).execute().use { it.isSuccessful }
        }.getOrDefault(false)
    }
}
