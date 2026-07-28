package com.rivenforge.companion.ui

import androidx.compose.material3.Typography
import androidx.compose.material3.darkColorScheme
import androidx.compose.ui.graphics.Color

// rivenforge brand palette (mirrors the desktop app's design tokens).
val BgBase = Color(0xFF0A0612)
val BgSurface = Color(0xFF15101F)
val BgElevated = Color(0xFF1F1830)
val BorderCol = Color(0xFF2D2340)
val Accent = Color(0xFFE879F9)      // magenta-pink
val Violet = Color(0xFFC084FC)
val TextHi = Color(0xFFF5F3FF)
val TextLo = Color(0xFFA1A1AA)
val Ok = Color(0xFF34D399)
val Warn = Color(0xFFFBBF24)
val Bad = Color(0xFFF87171)

val RivenColors = darkColorScheme(
    primary = Accent,
    onPrimary = Color(0xFF2A0A2E),
    primaryContainer = Color(0xFF3B0A45),
    onPrimaryContainer = Color(0xFFF7D5FE),
    secondary = Violet,
    onSecondary = Color(0xFF23103A),
    secondaryContainer = Color(0xFF241A38),
    onSecondaryContainer = Color(0xFFE7DDFB),
    background = BgBase,
    onBackground = TextHi,
    surface = BgSurface,
    onSurface = TextHi,
    surfaceVariant = BgElevated,
    onSurfaceVariant = Color(0xFFC7BBD9),
    outline = BorderCol,
    error = Bad,
    onError = Color(0xFF2A0A0A),
    errorContainer = Color(0xFF3A1414),
    onErrorContainer = Color(0xFFFECACA),
)

val RivenTypography = Typography()
