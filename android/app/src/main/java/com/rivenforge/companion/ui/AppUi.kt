package com.rivenforge.companion.ui

import android.content.Context
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.material3.Button
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.DisposableEffect
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.mutableStateListOf
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.platform.LocalContext
import com.journeyapps.barcodescanner.ScanContract
import com.journeyapps.barcodescanner.ScanOptions
import com.rivenforge.companion.ConnState
import com.rivenforge.companion.Creds
import com.rivenforge.companion.Pairing
import com.rivenforge.companion.RivenforgeClient
import com.rivenforge.companion.RollItem
import com.rivenforge.companion.SessionInfo
import kotlinx.coroutines.launch

@Composable
fun AppRoot() {
    val ctx = LocalContext.current
    var creds by remember { mutableStateOf(Pairing.load(ctx)) }

    val current = creds
    if (current == null) {
        PairScreen(onPaired = { creds = it })
    } else {
        LiveScreen(
            creds = current,
            onUnpair = {
                Pairing.clear(ctx)
                creds = null
            }
        )
    }
}

private fun tryPair(ctx: Context, code: String, onPaired: (Creds) -> Unit, onError: (String) -> Unit) {
    val parsed = Pairing.parse(code)
    if (parsed == null) {
        onError("That doesn't look like a rivenforge pairing code.")
        return
    }
    Pairing.save(ctx, parsed)
    onPaired(parsed)
}

@Composable
fun PairScreen(onPaired: (Creds) -> Unit) {
    val ctx = LocalContext.current
    var code by remember { mutableStateOf("") }
    var error by remember { mutableStateOf<String?>(null) }

    val scanLauncher = rememberLauncherForActivityResult(ScanContract()) { result ->
        result.contents?.let { scanned ->
            code = scanned
            tryPair(ctx, scanned, onPaired) { error = it }
        }
    }

    Column(
        Modifier
            .fillMaxSize()
            .padding(24.dp),
        verticalArrangement = Arrangement.Center
    ) {
        Text("rivenforge", style = MaterialTheme.typography.headlineMedium, fontWeight = FontWeight.Bold)
        Spacer(Modifier.height(6.dp))
        Text(
            "Pair with your PC to watch your riven rolls live. Open the desktop app → " +
                "Settings → Phone Access, then scan the code.",
            style = MaterialTheme.typography.bodyMedium
        )
        Spacer(Modifier.height(24.dp))

        Button(
            onClick = {
                error = null
                scanLauncher.launch(
                    ScanOptions()
                        .setDesiredBarcodeFormats(ScanOptions.QR_CODE)
                        .setPrompt("Scan the pairing code")
                        .setBeepEnabled(false)
                )
            },
            modifier = Modifier.fillMaxWidth()
        ) { Text("Scan QR code") }

        Spacer(Modifier.height(20.dp))
        Text("…or paste the code", style = MaterialTheme.typography.labelLarge)
        OutlinedTextField(
            value = code,
            onValueChange = { code = it; error = null },
            placeholder = { Text("rivenforge://pair?host=…") },
            singleLine = true,
            modifier = Modifier.fillMaxWidth()
        )
        Spacer(Modifier.height(8.dp))
        OutlinedButton(
            onClick = { tryPair(ctx, code, onPaired) { error = it } },
            modifier = Modifier.fillMaxWidth()
        ) { Text("Pair") }

        error?.let {
            Spacer(Modifier.height(12.dp))
            Text(it, color = MaterialTheme.colorScheme.error, style = MaterialTheme.typography.bodyMedium)
        }
    }
}

@Composable
fun LiveScreen(creds: Creds, onUnpair: () -> Unit) {
    val scope = rememberCoroutineScope()
    val client = remember(creds) { RivenforgeClient(creds) }
    var conn by remember { mutableStateOf(ConnState.CONNECTING) }
    var session by remember { mutableStateOf<SessionInfo?>(null) }
    var doneMsg by remember { mutableStateOf<String?>(null) }
    val rolls = remember { mutableStateListOf<RollItem>() }

    DisposableEffect(creds) {
        client.connect(
            onState = { conn = it },
            onRoll = { rolls.add(0, it) },
            onDone = { doneMsg = it }
        )
        onDispose { client.disconnect() }
    }
    LaunchedEffect(creds) { session = client.fetchSession() }

    Column(Modifier.fillMaxSize().padding(16.dp)) {
        Row(Modifier.fillMaxWidth(), verticalAlignment = Alignment.CenterVertically) {
            Text("rivenforge", style = MaterialTheme.typography.titleLarge, fontWeight = FontWeight.Bold)
            Spacer(Modifier.weight(1f))
            Text(conn.label(), style = MaterialTheme.typography.labelMedium, color = conn.tint())
        }
        Text("${creds.host}:${creds.port}", style = MaterialTheme.typography.labelSmall)

        Spacer(Modifier.height(12.dp))
        Card(Modifier.fillMaxWidth()) {
            Column(Modifier.padding(14.dp)) {
                val s = session
                if (s != null && s.running) {
                    Text("Rolling: ${s.weapon.ifBlank { "—" }}", fontWeight = FontWeight.SemiBold)
                    Text("${s.weaponType} · limit ${if (s.rollLimit == 0) "∞" else s.rollLimit}",
                        style = MaterialTheme.typography.bodySmall)
                } else {
                    Text(doneMsg ?: "No session running.", fontWeight = FontWeight.SemiBold)
                }
                Spacer(Modifier.height(10.dp))
                Row(horizontalArrangement = Arrangement.spacedBy(10.dp)) {
                    OutlinedButton(onClick = { scope.launch { session = client.fetchSession() } }) {
                        Text("Refresh")
                    }
                    OutlinedButton(onClick = { scope.launch { client.stopSession() } }) { Text("Stop") }
                    TextButton(onClick = onUnpair) { Text("Unpair") }
                }
            }
        }

        Spacer(Modifier.height(12.dp))
        Text("Live rolls", style = MaterialTheme.typography.titleMedium)
        Spacer(Modifier.height(6.dp))
        LazyColumn(Modifier.fillMaxSize(), verticalArrangement = Arrangement.spacedBy(8.dp)) {
            items(rolls) { RollRow(it) }
        }
    }
}

@Composable
private fun RollRow(item: RollItem) {
    Card(
        Modifier.fillMaxWidth(),
        colors = CardDefaults.cardColors(
            containerColor = when {
                item.decision == "ACCEPTED" -> MaterialTheme.colorScheme.primaryContainer
                item.decision == "NEW BEST" -> MaterialTheme.colorScheme.secondaryContainer
                else -> MaterialTheme.colorScheme.surfaceVariant
            }
        )
    ) {
        Column(Modifier.padding(12.dp)) {
            Row(Modifier.fillMaxWidth(), verticalAlignment = Alignment.CenterVertically) {
                Text("Roll #${item.rollNum}", fontWeight = FontWeight.Bold)
                Spacer(Modifier.weight(1f))
                Text(item.decision, fontWeight = FontWeight.SemiBold)
            }
            if (item.positives.isNotEmpty()) {
                Spacer(Modifier.height(4.dp))
                Text(item.positives.joinToString("  •  "), style = MaterialTheme.typography.bodyMedium)
            }
            if (item.negatives.isNotEmpty()) {
                Text(
                    item.negatives.joinToString("  •  "),
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.error
                )
            }
            if (item.score.isNotBlank()) {
                Text("score ${item.score}", style = MaterialTheme.typography.labelSmall,
                    fontFamily = FontFamily.Monospace)
            }
        }
    }
}

private fun ConnState.label(): String = when (this) {
    ConnState.CONNECTING -> "connecting…"
    ConnState.CONNECTED -> "● live"
    ConnState.DISCONNECTED -> "disconnected"
    ConnState.ERROR -> "connection error"
}

@Composable
private fun ConnState.tint() = when (this) {
    ConnState.CONNECTED -> MaterialTheme.colorScheme.primary
    ConnState.ERROR -> MaterialTheme.colorScheme.error
    else -> MaterialTheme.colorScheme.onSurfaceVariant
}
