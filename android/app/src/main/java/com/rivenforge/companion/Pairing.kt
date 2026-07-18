package com.rivenforge.companion

import android.content.Context
import android.net.Uri

/**
 * Parse the desktop's pairing code and persist the resulting credentials.
 *
 * The code is a URI the desktop shows as a QR (and as copyable text):
 *
 *     rivenforge://pair?host=192.168.0.227&port=47321&token=<base64url>
 *
 * TODO (hardening): the token is a bearer secret. For production, store it in
 * EncryptedSharedPreferences (androidx.security:security-crypto) so it's sealed
 * by the Android Keystore rather than plain SharedPreferences.
 */
object Pairing {
    private const val PREFS = "rivenforge_pairing"
    private const val K_HOST = "host"
    private const val K_PORT = "port"
    private const val K_TOKEN = "token"

    /** Parse a `rivenforge://pair?...` code. Returns null if it isn't valid. */
    fun parse(code: String): Creds? {
        val trimmed = code.trim()
        val uri = runCatching { Uri.parse(trimmed) }.getOrNull() ?: return null
        if (uri.scheme != "rivenforge" || uri.host != "pair") return null
        val host = uri.getQueryParameter("host")?.takeIf { it.isNotBlank() } ?: return null
        val port = uri.getQueryParameter("port")?.toIntOrNull() ?: 47321
        val token = uri.getQueryParameter("token")?.takeIf { it.isNotBlank() } ?: return null
        return Creds(host, port, token)
    }

    fun save(ctx: Context, creds: Creds) {
        ctx.getSharedPreferences(PREFS, Context.MODE_PRIVATE).edit()
            .putString(K_HOST, creds.host)
            .putInt(K_PORT, creds.port)
            .putString(K_TOKEN, creds.token)
            .apply()
    }

    fun load(ctx: Context): Creds? {
        val p = ctx.getSharedPreferences(PREFS, Context.MODE_PRIVATE)
        val host = p.getString(K_HOST, null) ?: return null
        val token = p.getString(K_TOKEN, null) ?: return null
        return Creds(host, p.getInt(K_PORT, 47321), token)
    }

    fun clear(ctx: Context) {
        ctx.getSharedPreferences(PREFS, Context.MODE_PRIVATE).edit().clear().apply()
    }
}
