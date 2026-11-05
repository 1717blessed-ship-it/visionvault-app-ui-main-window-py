import 'dart:io';
import 'dart:math' as math;

import 'package:flutter/material.dart';

/// Presenta todas las miniaturas dentro del mismo cuadrado.
///
/// [BoxFit.contain] hace que el lado más largo ocupe el espacio disponible sin
/// recortar la imagen. [showFrame] permite ocultar el marco en catálogos.
class UniformImagePreview extends StatelessWidget {
  final ImageProvider imageProvider;
  final String? semanticLabel;
  final bool showFrame;

  const UniformImagePreview({
    super.key,
    required this.imageProvider,
    this.semanticLabel,
    this.showFrame = true,
  });

  factory UniformImagePreview.network(
    String url, {
    Key? key,
    Map<String, String>? headers,
    String? semanticLabel,
    bool showFrame = true,
  }) =>
      UniformImagePreview(
        key: key,
        imageProvider: NetworkImage(url, headers: headers),
        semanticLabel: semanticLabel,
        showFrame: showFrame,
      );

  factory UniformImagePreview.file(
    File file, {
    Key? key,
    String? semanticLabel,
    bool showFrame = true,
  }) =>
      UniformImagePreview(
        key: key,
        imageProvider: FileImage(file),
        semanticLabel: semanticLabel,
        showFrame: showFrame,
      );

  @override
  Widget build(BuildContext context) => LayoutBuilder(
        builder: (context, constraints) {
          final side = math.min(constraints.maxWidth, constraints.maxHeight);
          final image = Image(
            image: imageProvider,
            width: double.infinity,
            height: double.infinity,
            fit: BoxFit.contain,
            filterQuality: FilterQuality.medium,
            semanticLabel: semanticLabel,
            frameBuilder: (context, child, frame, syncLoaded) {
              if (syncLoaded || frame != null) return child;
              return const Center(
                child: SizedBox.square(
                  dimension: 22,
                  child: CircularProgressIndicator(strokeWidth: 2),
                ),
              );
            },
            errorBuilder: (_, __, ___) => const Center(
              child: Icon(
                Icons.broken_image_outlined,
                color: Colors.black54,
                size: 36,
              ),
            ),
          );
          return Center(
            child: SizedBox.square(
              dimension: side.isFinite ? side : 160,
              child: showFrame
                  ? DecoratedBox(
                      decoration: BoxDecoration(
                        color: Colors.white,
                        border: Border.all(color: Colors.black, width: 2),
                        borderRadius: BorderRadius.circular(10),
                      ),
                      child: Padding(
                        padding: const EdgeInsets.all(3),
                        child: ClipRRect(
                          borderRadius: BorderRadius.circular(6),
                          child: image,
                        ),
                      ),
                    )
                  : image,
            ),
          );
        },
      );
}
