package com.rivenforge.companion.ui

import android.content.Context
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.compose.foundation.Image
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.ExperimentalLayoutApi
import androidx.compose.foundation.layout.FlowRow
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.systemBarsPadding
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.Button
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.DisposableEffect
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateListOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.res.painterResource
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.journeyapps.barcodescanner.ScanContract
import com.journeyapps.barcodescanner.ScanOptions
import com.rivenforge.companion.ConnState
import com.rivenforge.companion.Creds
import com.rivenforge.companion.Pairing
import com.rivenforge.companion.R
import com.rivenforge.companion.RivenforgeClient
import com.rivenforge.companion.RollItem
import com.rivenforge.companion.RollSettings
import kotlinx.coroutines.launch

@Composable
fun AppRoot() {
    val ctx = LocalContext.current
    var creds by remember { mutableStateOf(Pairing.load(ctx)) }

    val current = creds
    if (current == null) {
        PairScreen(onPaired = { creds = it })
    } else {
        LiveScreen(creds = current, onUnpair = { Pairing.clear(ctx); creds = null })
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
            .systemBarsPadding()
            .verticalScroll(rememberScrollState())
            .padding(28.dp),
        verticalArrangement = Arrangement.Center,
        horizontalAlignment = Alignment.CenterHorizontally
    ) {
        Image(
            painter = painterResource(R.drawable.logo),
            contentDescription = null,
            modifier = Modifier.size(96.dp)
        )
        Spacer(Modifier.height(16.dp))
        Text("rivenforge", fontSize = 30.sp, fontWeight = FontWeight.Bold, color = MaterialTheme.colorScheme.onBackground)
        Spacer(Modifier.height(6.dp))
        Text(
            "Watch your riven rolls live. On the PC open Settings → Phone Access, then scan the code.",
            color = MaterialTheme.colorScheme.onSurfaceVariant,
            fontSize = 14.sp
        )
        Spacer(Modifier.height(28.dp))

        Button(
            onClick = {
                error = null
                scanLauncher.launch(
                    ScanOptions()
                        .setDesiredBarcodeFormats(ScanOptions.QR_CODE)
                        .setPrompt("Scan the pairing code")
                        .setBeepEnabled(false)
                        .setOrientationLocked(false)
                )
            },
            shape = RoundedCornerShape(14.dp),
            modifier = Modifier.fillMaxWidth().height(52.dp)
        ) { Text("Scan QR code", fontWeight = FontWeight.SemiBold, fontSize = 16.sp) }

        Spacer(Modifier.height(22.dp))
        Text("or paste the code", color = MaterialTheme.colorScheme.onSurfaceVariant, fontSize = 13.sp)
        Spacer(Modifier.height(8.dp))
        OutlinedTextField(
            value = code,
            onValueChange = { code = it; error = null },
            placeholder = { Text("rivenforge://pair?host=…") },
            singleLine = true,
            shape = RoundedCornerShape(12.dp),
            modifier = Modifier.fillMaxWidth()
        )
        Spacer(Modifier.height(10.dp))
        OutlinedButton(
            onClick = { tryPair(ctx, code, onPaired) { error = it } },
            shape = RoundedCornerShape(12.dp),
            modifier = Modifier.fillMaxWidth().height(48.dp)
        ) { Text("Pair") }

        error?.let {
            Spacer(Modifier.height(14.dp))
            Text(it, color = MaterialTheme.colorScheme.error, fontSize = 14.sp)
        }
    }
}

@Composable
fun LiveScreen(creds: Creds, onUnpair: () -> Unit) {
    val scope = rememberCoroutineScope()
    val client = remember(creds) { RivenforgeClient(creds) }
    var conn by remember { mutableStateOf(ConnState.CONNECTING) }
    var running by remember { mutableStateOf(false) }
    var settings by remember { mutableStateOf<RollSettings?>(null) }
    var doneMsg by remember { mutableStateOf<String?>(null) }
    var actionMsg by remember { mutableStateOf<String?>(null) }
    var busy by remember { mutableStateOf(false) }
    val rolls = remember { mutableStateListOf<RollItem>() }

    DisposableEffect(creds) {
        client.connect(
            onState = { conn = it },
            onRoll = { rolls.add(0, it); running = true; doneMsg = null },
            onDone = {
                running = false
                doneMsg = it
                scope.launch { settings = client.fetchSettings() }
            }
        )
        onDispose { client.disconnect() }
    }
    LaunchedEffect(creds) {
        running = client.fetchSession()?.running == true
        settings = client.fetchSettings()
    }

    fun rollAgain() {
        busy = true; actionMsg = null
        scope.launch {
            val err = client.rollAgain()
            busy = false
            if (err == null) { rolls.clear(); running = true; doneMsg = null } else actionMsg = err
        }
    }
    fun stop() {
        busy = true
        scope.launch { client.stopSession(); running = false; busy = false }
    }

    Column(
        Modifier
            .fillMaxSize()
            .systemBarsPadding()
            .padding(horizontal = 16.dp)
    ) {
        BrandHeader(conn, "${creds.host}:${creds.port}")
        Spacer(Modifier.height(12.dp))

        StatePanel(
            running = running,
            settings = settings,
            doneMsg = doneMsg,
            actionMsg = actionMsg,
            busy = busy,
            onRollAgain = { rollAgain() },
            onStop = { stop() },
            onRefresh = {
                scope.launch {
                    running = client.fetchSession()?.running == true
                    settings = client.fetchSettings()
                }
            },
            onUnpair = onUnpair
        )

        Spacer(Modifier.height(16.dp))
        Text("LIVE ROLLS", color = MaterialTheme.colorScheme.onSurfaceVariant,
            fontSize = 12.sp, fontWeight = FontWeight.Bold, letterSpacing = 1.5.sp)
        Spacer(Modifier.height(8.dp))

        if (rolls.isEmpty()) {
            Box(Modifier.fillMaxWidth().padding(top = 40.dp), contentAlignment = Alignment.Center) {
                Text(
                    if (running) "Waiting for the next roll…" else "No rolls yet.",
                    color = MaterialTheme.colorScheme.onSurfaceVariant
                )
            }
        } else {
            LazyColumn(
                Modifier.fillMaxSize().padding(bottom = 8.dp),
                verticalArrangement = Arrangement.spacedBy(8.dp)
            ) {
                items(rolls) { RollCard(it) }
            }
        }
    }
}

@Composable
private fun BrandHeader(status: ConnState, host: String) {
    Row(Modifier.fillMaxWidth().padding(top = 8.dp), verticalAlignment = Alignment.CenterVertically) {
        Image(painterResource(R.drawable.logo), null, modifier = Modifier.size(34.dp))
        Spacer(Modifier.size(10.dp))
        Column {
            Text("rivenforge", fontWeight = FontWeight.Bold, fontSize = 18.sp,
                color = MaterialTheme.colorScheme.onBackground)
            Text(host, fontSize = 11.sp, color = MaterialTheme.colorScheme.onSurfaceVariant)
        }
        Spacer(Modifier.weight(1f))
        StatusPill(status)
    }
}

@Composable
private fun StatusPill(status: ConnState) {
    val (label, tint) = when (status) {
        ConnState.CONNECTED -> "live" to Ok
        ConnState.CONNECTING -> "connecting" to Warn
        ConnState.ERROR -> "error" to Bad
        ConnState.DISCONNECTED -> "offline" to TextLo
    }
    Row(
        Modifier
            .clip(RoundedCornerShape(50))
            .background(MaterialTheme.colorScheme.surface)
            .border(1.dp, MaterialTheme.colorScheme.outline, RoundedCornerShape(50))
            .padding(horizontal = 10.dp, vertical = 5.dp),
        verticalAlignment = Alignment.CenterVertically
    ) {
        Box(Modifier.size(8.dp).clip(RoundedCornerShape(50)).background(tint))
        Spacer(Modifier.size(6.dp))
        Text(label, fontSize = 12.sp, color = MaterialTheme.colorScheme.onSurfaceVariant)
    }
}

@Composable
private fun StatePanel(
    running: Boolean,
    settings: RollSettings?,
    doneMsg: String?,
    actionMsg: String?,
    busy: Boolean,
    onRollAgain: () -> Unit,
    onStop: () -> Unit,
    onRefresh: () -> Unit,
    onUnpair: () -> Unit
) {
    Column(
        Modifier
            .fillMaxWidth()
            .clip(RoundedCornerShape(16.dp))
            .background(MaterialTheme.colorScheme.surface)
            .border(1.dp, MaterialTheme.colorScheme.outline, RoundedCornerShape(16.dp))
            .padding(16.dp)
    ) {
        if (running) {
            Text("ROLLING", color = Ok, fontSize = 12.sp, fontWeight = FontWeight.Bold, letterSpacing = 1.5.sp)
            Spacer(Modifier.height(6.dp))
            Text(settings?.weapon?.ifBlank { "—" } ?: "—",
                fontSize = 22.sp, fontWeight = FontWeight.Bold,
                color = MaterialTheme.colorScheme.onBackground)
            Spacer(Modifier.height(10.dp))
            SettingsChips(settings)
            Spacer(Modifier.height(14.dp))
            OutlinedButton(onClick = onStop, enabled = !busy,
                shape = RoundedCornerShape(12.dp), modifier = Modifier.fillMaxWidth().height(48.dp)) {
                Text("Stop rolling")
            }
        } else {
            Text(if (doneMsg != null) "SESSION ENDED" else "READY",
                color = MaterialTheme.colorScheme.onSurfaceVariant,
                fontSize = 12.sp, fontWeight = FontWeight.Bold, letterSpacing = 1.5.sp)
            doneMsg?.let {
                Spacer(Modifier.height(6.dp))
                Text(it, fontSize = 13.sp, color = MaterialTheme.colorScheme.onBackground)
            }
            Spacer(Modifier.height(12.dp))
            Text("Current settings", fontSize = 13.sp, fontWeight = FontWeight.SemiBold,
                color = MaterialTheme.colorScheme.onBackground)
            Spacer(Modifier.height(4.dp))
            Text(settings?.weapon?.ifBlank { "No weapon selected" } ?: "Loading…",
                fontSize = 20.sp, fontWeight = FontWeight.Bold,
                color = MaterialTheme.colorScheme.onBackground)
            Spacer(Modifier.height(10.dp))
            SettingsChips(settings)
            settings?.statPriority?.takeIf { it.isNotEmpty() }?.let { prefs ->
                Spacer(Modifier.height(12.dp))
                Text("Preferred stats", fontSize = 11.sp, color = MaterialTheme.colorScheme.onSurfaceVariant)
                Spacer(Modifier.height(6.dp))
                StatChips(prefs, MaterialTheme.colorScheme.primaryContainer, MaterialTheme.colorScheme.onPrimaryContainer)
            }
            Spacer(Modifier.height(16.dp))
            Button(
                onClick = onRollAgain,
                enabled = !busy && (settings?.weapon?.isNotBlank() == true),
                shape = RoundedCornerShape(12.dp),
                modifier = Modifier.fillMaxWidth().height(52.dp)
            ) {
                if (busy) {
                    CircularProgressIndicator(Modifier.size(20.dp), strokeWidth = 2.dp,
                        color = MaterialTheme.colorScheme.onPrimary)
                } else {
                    Text("Roll again", fontWeight = FontWeight.SemiBold, fontSize = 16.sp)
                }
            }
            actionMsg?.let {
                Spacer(Modifier.height(8.dp))
                Text(it, color = MaterialTheme.colorScheme.error, fontSize = 13.sp)
            }
        }

        Spacer(Modifier.height(6.dp))
        Row {
            TextButton(onClick = onRefresh, enabled = !busy) { Text("Refresh") }
            Spacer(Modifier.weight(1f))
            TextButton(onClick = onUnpair) {
                Text("Unpair", color = MaterialTheme.colorScheme.onSurfaceVariant)
            }
        }
    }
}

@OptIn(ExperimentalLayoutApi::class)
@Composable
private fun SettingsChips(s: RollSettings?) {
    if (s == null) return
    FlowRow(horizontalArrangement = Arrangement.spacedBy(6.dp), verticalArrangement = Arrangement.spacedBy(6.dp)) {
        if (s.weaponType.isNotBlank()) Pill(s.weaponType)
        Pill(if (s.rollLimit == 0) "∞ rolls" else "${s.rollLimit} rolls")
        if (s.rollUntilMatch) Pill("until match", MaterialTheme.colorScheme.secondaryContainer, MaterialTheme.colorScheme.onSecondaryContainer)
    }
}

@OptIn(ExperimentalLayoutApi::class)
@Composable
private fun StatChips(items: List<String>, container: Color, content: Color) {
    FlowRow(horizontalArrangement = Arrangement.spacedBy(6.dp), verticalArrangement = Arrangement.spacedBy(6.dp)) {
        items.forEach { Pill(it, container, content) }
    }
}

@Composable
private fun Pill(
    text: String,
    container: Color = MaterialTheme.colorScheme.surfaceVariant,
    content: Color = MaterialTheme.colorScheme.onSurfaceVariant
) {
    Box(
        Modifier.clip(RoundedCornerShape(50)).background(container).padding(horizontal = 10.dp, vertical = 4.dp)
    ) {
        Text(text, color = content, fontSize = 12.sp, fontWeight = FontWeight.Medium)
    }
}

@OptIn(ExperimentalLayoutApi::class)
@Composable
private fun RollCard(item: RollItem) {
    val (accent, label) = when (item.decision) {
        "ACCEPTED" -> Ok to "ACCEPTED"
        "NEW BEST" -> MaterialTheme.colorScheme.primary to "NEW BEST"
        else -> TextLo to "REVERT"
    }
    Column(
        Modifier
            .fillMaxWidth()
            .clip(RoundedCornerShape(14.dp))
            .background(MaterialTheme.colorScheme.surface)
            .border(1.dp, MaterialTheme.colorScheme.outline, RoundedCornerShape(14.dp))
            .padding(14.dp)
    ) {
        Row(verticalAlignment = Alignment.CenterVertically) {
            Text("Roll #${item.rollNum}", fontWeight = FontWeight.Bold,
                color = MaterialTheme.colorScheme.onBackground)
            Spacer(Modifier.weight(1f))
            Box(Modifier.clip(RoundedCornerShape(50)).background(accent.copy(alpha = 0.18f))
                .padding(horizontal = 10.dp, vertical = 3.dp)) {
                Text(label, color = accent, fontSize = 11.sp, fontWeight = FontWeight.Bold)
            }
        }
        if (item.positives.isNotEmpty()) {
            Spacer(Modifier.height(8.dp))
            FlowRow(horizontalArrangement = Arrangement.spacedBy(6.dp), verticalArrangement = Arrangement.spacedBy(6.dp)) {
                item.positives.forEach { Pill(it, MaterialTheme.colorScheme.secondaryContainer, MaterialTheme.colorScheme.onSecondaryContainer) }
            }
        }
        if (item.negatives.isNotEmpty()) {
            Spacer(Modifier.height(6.dp))
            Text(item.negatives.joinToString("  •  "),
                color = MaterialTheme.colorScheme.error, fontSize = 13.sp)
        }
        if (item.score.isNotBlank()) {
            Spacer(Modifier.height(6.dp))
            Text("score ${item.score}", fontSize = 11.sp, fontFamily = FontFamily.Monospace,
                color = MaterialTheme.colorScheme.onSurfaceVariant)
        }
    }
}
