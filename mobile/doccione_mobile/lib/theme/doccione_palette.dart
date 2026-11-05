import 'package:flutter/material.dart';
import 'package:flutter/services.dart';

/// Colores compartidos entre Doccione Studio y su consola móvil.
abstract final class DoccionePalette {
  static const wine = Color(0xFFE06A8E);
  static const wineDark = Color(0xFF8D123B);
  static const ink = Color(0xFFF2F2F4);
  static const muted = Color(0xFFB5B5BA);
  static const subtle = Color(0xFF8B8B93);

  static const canvas = Color(0xFF0E0E0F);
  static const surface = Color(0xFF1B1B1E);
  static const surfaceElevated = Color(0xFF242428);
  static const border = Color(0xFF3A3A40);

  static const production = Color(0xFFE3A24F);
  static const success = Color(0xFF59BF8B);
  static const info = Color(0xFF75ADE3);
  static const danger = Color(0xFFF06A78);
  static const violet = Color(0xFFC99AF1);

  static const wineSoft = Color(0xFF351722);
  static const productionSoft = Color(0xFF382713);
  static const successSoft = Color(0xFF173328);
  static const infoSoft = Color(0xFF172C40);
  static const dangerSoft = Color(0xFF3C1B21);
  static const violetSoft = Color(0xFF30223C);
  static const neutralSoft = Color(0xFF2A2A2F);
}

/// Tema oscuro único de la app móvil.
abstract final class DoccioneTheme {
  static ThemeData dark() {
    final scheme = ColorScheme.fromSeed(
      seedColor: DoccionePalette.wine,
      brightness: Brightness.dark,
    ).copyWith(
      primary: DoccionePalette.wine,
      onPrimary: const Color(0xFF2B0713),
      secondary: DoccionePalette.info,
      onSecondary: const Color(0xFF071B2B),
      error: DoccionePalette.danger,
      onError: const Color(0xFF2D060C),
      surface: DoccionePalette.surface,
      onSurface: DoccionePalette.ink,
      surfaceContainerLowest: DoccionePalette.canvas,
      surfaceContainerLow: DoccionePalette.surface,
      surfaceContainer: DoccionePalette.surfaceElevated,
      surfaceContainerHigh: const Color(0xFF2B2B30),
      surfaceContainerHighest: const Color(0xFF333339),
      onSurfaceVariant: DoccionePalette.muted,
      outline: DoccionePalette.border,
      outlineVariant: const Color(0xFF303036),
    );

    return ThemeData(
      brightness: Brightness.dark,
      colorScheme: scheme,
      useMaterial3: true,
      scaffoldBackgroundColor: DoccionePalette.canvas,
      canvasColor: DoccionePalette.surface,
      dividerColor: DoccionePalette.border,
      appBarTheme: const AppBarTheme(
        centerTitle: false,
        backgroundColor: DoccionePalette.canvas,
        foregroundColor: DoccionePalette.ink,
        elevation: 0,
        scrolledUnderElevation: 0,
        surfaceTintColor: Colors.transparent,
        systemOverlayStyle: SystemUiOverlayStyle(
          statusBarColor: DoccionePalette.canvas,
          statusBarIconBrightness: Brightness.light,
          statusBarBrightness: Brightness.dark,
          systemNavigationBarColor: DoccionePalette.canvas,
          systemNavigationBarIconBrightness: Brightness.light,
        ),
        titleTextStyle: TextStyle(
          color: DoccionePalette.ink,
          fontSize: 22,
          fontWeight: FontWeight.w700,
        ),
      ),
      cardTheme: CardThemeData(
        elevation: 0,
        margin: EdgeInsets.zero,
        color: DoccionePalette.surface,
        surfaceTintColor: Colors.transparent,
        shape: RoundedRectangleBorder(
          borderRadius: BorderRadius.circular(20),
          side: const BorderSide(color: DoccionePalette.border),
        ),
      ),
      dialogTheme: const DialogThemeData(
        backgroundColor: DoccionePalette.surface,
        surfaceTintColor: Colors.transparent,
      ),
      bottomSheetTheme: const BottomSheetThemeData(
        backgroundColor: DoccionePalette.surface,
        modalBackgroundColor: DoccionePalette.surface,
        surfaceTintColor: Colors.transparent,
      ),
      inputDecorationTheme: InputDecorationTheme(
        filled: true,
        fillColor: DoccionePalette.surfaceElevated,
        labelStyle: const TextStyle(color: DoccionePalette.muted),
        hintStyle: const TextStyle(color: DoccionePalette.subtle),
        border: OutlineInputBorder(
          borderRadius: BorderRadius.circular(14),
          borderSide: const BorderSide(color: DoccionePalette.border),
        ),
        enabledBorder: OutlineInputBorder(
          borderRadius: BorderRadius.circular(14),
          borderSide: const BorderSide(color: DoccionePalette.border),
        ),
        focusedBorder: OutlineInputBorder(
          borderRadius: BorderRadius.circular(14),
          borderSide: const BorderSide(
            color: DoccionePalette.wine,
            width: 1.5,
          ),
        ),
      ),
      chipTheme: ChipThemeData(
        backgroundColor: DoccionePalette.surfaceElevated,
        selectedColor: DoccionePalette.wine,
        secondarySelectedColor: DoccionePalette.wine,
        disabledColor: DoccionePalette.surface,
        labelStyle: const TextStyle(color: DoccionePalette.ink),
        secondaryLabelStyle: const TextStyle(color: Color(0xFF2B0713)),
        side: const BorderSide(color: DoccionePalette.border),
        shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(12)),
      ),
      popupMenuTheme: const PopupMenuThemeData(
        color: DoccionePalette.surfaceElevated,
        surfaceTintColor: Colors.transparent,
      ),
      navigationBarTheme: const NavigationBarThemeData(
        backgroundColor: DoccionePalette.surface,
        indicatorColor: DoccionePalette.wineSoft,
        surfaceTintColor: Colors.transparent,
      ),
      snackBarTheme: const SnackBarThemeData(
        backgroundColor: DoccionePalette.surfaceElevated,
        contentTextStyle: TextStyle(color: DoccionePalette.ink),
        behavior: SnackBarBehavior.floating,
      ),
      progressIndicatorTheme: const ProgressIndicatorThemeData(
        color: DoccionePalette.wine,
      ),
    );
  }
}
