import 'dart:async';

import 'package:flutter/material.dart';

import '../theme/doccione_palette.dart';
import 'uniform_image_preview.dart';

/// Miniatura compacta del catálogo, sin textos ni controles superpuestos.
class StickerCatalogTile extends StatefulWidget {
  /// Ventana breve que permite distinguir dos toques de tres.
  static const multiTapTimeout = Duration(milliseconds: 320);

  final ImageProvider imageProvider;
  final String semanticLabel;
  final bool selected;
  final VoidCallback? onTap;
  final VoidCallback? onDoubleTap;
  final VoidCallback? onTripleTap;
  final VoidCallback? onLongPress;

  const StickerCatalogTile({
    super.key,
    required this.imageProvider,
    required this.semanticLabel,
    this.onTap,
    this.onDoubleTap,
    this.onTripleTap,
    this.onLongPress,
    this.selected = false,
  });

  @override
  State<StickerCatalogTile> createState() => _StickerCatalogTileState();
}

class _StickerCatalogTileState extends State<StickerCatalogTile> {
  Timer? _tapTimer;
  int _tapCount = 0;

  @override
  void dispose() {
    _tapTimer?.cancel();
    super.dispose();
  }

  void _resetTapSequence() {
    _tapTimer?.cancel();
    _tapTimer = null;
    _tapCount = 0;
  }

  void _registerTap() {
    _tapTimer?.cancel();
    _tapCount++;

    if (_tapCount >= 3) {
      _resetTapSequence();
      widget.onTripleTap?.call();
      return;
    }

    _tapTimer = Timer(StickerCatalogTile.multiTapTimeout, () {
      if (!mounted) return;
      final completedTaps = _tapCount;
      _resetTapSequence();
      if (completedTaps == 2) {
        widget.onDoubleTap?.call();
      } else if (completedTaps == 1) {
        widget.onTap?.call();
      }
    });
  }

  void _handleLongPress() {
    _resetTapSequence();
    widget.onLongPress?.call();
  }

  @override
  Widget build(BuildContext context) => Semantics(
        button: true,
        selected: widget.selected,
        label: widget.semanticLabel,
        child: Material(
          color: widget.selected
              ? DoccionePalette.surfaceElevated
              : DoccionePalette.surface,
          shape: RoundedRectangleBorder(
            borderRadius: BorderRadius.circular(6),
            side: widget.selected
                ? const BorderSide(color: DoccionePalette.wine, width: 2)
                : BorderSide.none,
          ),
          clipBehavior: Clip.antiAlias,
          child: InkWell(
            onTap: widget.onTripleTap == null ? widget.onTap : _registerTap,
            onDoubleTap: widget.onTripleTap == null ? widget.onDoubleTap : null,
            onLongPress: widget.onLongPress == null ? null : _handleLongPress,
            child: Padding(
              padding: EdgeInsets.all(widget.selected ? 4 : 6),
              child: UniformImagePreview(
                imageProvider: widget.imageProvider,
                semanticLabel: widget.semanticLabel,
                showFrame: false,
              ),
            ),
          ),
        ),
      );
}
