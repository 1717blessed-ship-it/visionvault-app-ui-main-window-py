import 'package:flutter/material.dart';
import 'package:flutter/services.dart';

import '../models/catalog_design.dart';

Future<void> showRealSizePreview(
  BuildContext context, {
  required CatalogDesign design,
  required ImageProvider imageProvider,
  double initialSizeCm = 5,
  bool designOnly = false,
}) {
  return Navigator.of(context).push(
    MaterialPageRoute<void>(
      fullscreenDialog: true,
      builder: (_) => RealSizePreviewScreen(
        design: design,
        imageProvider: imageProvider,
        initialSizeCm: initialSizeCm,
        designOnly: designOnly,
      ),
    ),
  );
}

/// Renders the design at its requested physical long-side size.
///
/// Flutter logical pixels follow the mobile density-independent convention of
/// 160 units per inch. The result is a useful 1:1 reference, although the final
/// physical accuracy still depends on the density reported by the device.
class RealSizePreviewScreen extends StatefulWidget {
  static const double logicalPixelsPerCentimeter = 160 / 2.54;

  final CatalogDesign design;
  final ImageProvider imageProvider;
  final double initialSizeCm;
  final bool designOnly;

  const RealSizePreviewScreen({
    super.key,
    required this.design,
    required this.imageProvider,
    this.initialSizeCm = 5,
    this.designOnly = false,
  });

  @override
  State<RealSizePreviewScreen> createState() => _RealSizePreviewScreenState();
}

class _RealSizePreviewScreenState extends State<RealSizePreviewScreen> {
  static double _calibration = 1;
  late final TextEditingController _sizeController;
  late double _longSideCm;

  @override
  void initState() {
    super.initState();
    _longSideCm = widget.initialSizeCm.clamp(1, 30).toDouble();
    _sizeController =
        TextEditingController(text: _formatCentimeters(_longSideCm));
  }

  @override
  void dispose() {
    _sizeController.dispose();
    super.dispose();
  }

  String _formatCentimeters(double value) => value == value.roundToDouble()
      ? value.toStringAsFixed(0)
      : value.toStringAsFixed(1);

  void _setSize(double value) {
    final safeValue = value.clamp(1, 30).toDouble();
    setState(() => _longSideCm = safeValue);
    final formatted = _formatCentimeters(safeValue);
    if (_sizeController.text != formatted) {
      _sizeController
        ..text = formatted
        ..selection = TextSelection.collapsed(offset: formatted.length);
    }
  }

  void _readSize(String raw) {
    final value = double.tryParse(raw.trim().replaceAll(',', '.'));
    if (value != null && value >= 1 && value <= 30) {
      setState(() => _longSideCm = value);
    }
  }

  @override
  Widget build(BuildContext context) {
    final ratio = widget.design.aspectRatio.clamp(.05, 20).toDouble();
    final logicalPixelsPerCm =
        RealSizePreviewScreen.logicalPixelsPerCentimeter * _calibration;
    final longSide = _longSideCm * logicalPixelsPerCm;
    final width = ratio >= 1 ? longSide : longSide * ratio;
    final height = ratio >= 1 ? longSide / ratio : longSide;
    final widthCm = width / logicalPixelsPerCm;
    final heightCm = height / logicalPixelsPerCm;

    if (widget.designOnly) {
      return Scaffold(
        backgroundColor: const Color(0xFFF1F1F1),
        body: SafeArea(
          child: Semantics(
            button: true,
            label:
                '${widget.design.name} a ${_longSideCm.toStringAsFixed(2)} centímetros. Tocar para cerrar.',
            onTap: () => Navigator.pop(context),
            child: InkWell(
              onTap: () => Navigator.pop(context),
              child: Column(
                children: [
                  if (widget.design.tags.isNotEmpty)
                    Padding(
                      padding: const EdgeInsets.fromLTRB(12, 10, 12, 4),
                      child: Wrap(
                        alignment: WrapAlignment.center,
                        spacing: 6,
                        runSpacing: 4,
                        children: widget.design.tags
                            .map(
                              (tag) => Chip(
                                label: Text('#$tag'),
                                visualDensity: VisualDensity.compact,
                                padding: EdgeInsets.zero,
                              ),
                            )
                            .toList(),
                      ),
                    ),
                  Expanded(
                    child: Center(
                      child: SizedBox(
                        key: const Key('real-size-design'),
                        width: width,
                        height: height,
                        child: Image(
                          image: widget.imageProvider,
                          fit: BoxFit.contain,
                          filterQuality: FilterQuality.high,
                          excludeFromSemantics: true,
                          errorBuilder: (_, __, ___) => const Center(
                            child: Icon(Icons.broken_image_outlined, size: 48),
                          ),
                        ),
                      ),
                    ),
                  ),
                ],
              ),
            ),
          ),
        ),
      );
    }

    return Scaffold(
      appBar: AppBar(
        title: const Text('Vista previa a tamaño real'),
        actions: [
          IconButton(
            onPressed: () => Navigator.pop(context),
            tooltip: 'Cerrar',
            icon: const Icon(Icons.close),
          ),
        ],
      ),
      body: SafeArea(
        child: Column(
          children: [
            Padding(
              padding: const EdgeInsets.fromLTRB(16, 8, 16, 10),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.stretch,
                children: [
                  Wrap(
                    spacing: 8,
                    runSpacing: 8,
                    crossAxisAlignment: WrapCrossAlignment.center,
                    children: [
                      SizedBox(
                        width: 132,
                        child: TextField(
                          key: const Key('real-size-input'),
                          controller: _sizeController,
                          keyboardType: const TextInputType.numberWithOptions(
                            decimal: true,
                          ),
                          inputFormatters: [
                            FilteringTextInputFormatter.allow(
                              RegExp(r'[0-9,.]'),
                            ),
                          ],
                          onChanged: _readSize,
                          decoration: const InputDecoration(
                            labelText: 'Lado mayor',
                            suffixText: 'cm',
                            isDense: true,
                          ),
                        ),
                      ),
                      for (final size in const [3.0, 5.0, 7.0])
                        ChoiceChip(
                          label: Text('${size.toInt()} cm'),
                          selected: (_longSideCm - size).abs() < .01,
                          onSelected: (_) => _setSize(size),
                        ),
                    ],
                  ),
                  const SizedBox(height: 8),
                  Text(
                    widget.design.hasVisibleDimensions
                        ? '${widthCm.toStringAsFixed(1)} × '
                            '${heightCm.toStringAsFixed(1)} cm · escala 1:1'
                        : 'Lado mayor: ${_longSideCm.toStringAsFixed(1)} cm '
                            '· escala 1:1',
                    style: Theme.of(context).textTheme.titleSmall,
                  ),
                  const SizedBox(height: 3),
                  Text(
                    'La precisión depende de la densidad informada por el celular.',
                    style: Theme.of(context).textTheme.bodySmall,
                  ),
                  const SizedBox(height: 6),
                  const Text(
                    'Calibrá con una regla: ajustá hasta que la línea mida 1 cm.',
                    style: TextStyle(fontSize: 12),
                  ),
                  Slider(
                    value: _calibration,
                    min: .75,
                    max: 1.25,
                    divisions: 100,
                    label: '${(_calibration * 100).round()}%',
                    onChanged: (value) => setState(() => _calibration = value),
                  ),
                ],
              ),
            ),
            const Divider(height: 1),
            Expanded(
              child: ColoredBox(
                color: const Color(0xFFF1F1F1),
                child: InteractiveViewer(
                  constrained: false,
                  minScale: 1,
                  maxScale: 1,
                  boundaryMargin: const EdgeInsets.all(160),
                  child: SizedBox(
                    key: const Key('real-size-design'),
                    width: width,
                    height: height,
                    child: Image(
                      image: widget.imageProvider,
                      fit: BoxFit.contain,
                      filterQuality: FilterQuality.high,
                      semanticLabel:
                          '${widget.design.name} a tamaño real aproximado',
                      errorBuilder: (_, __, ___) => const Center(
                        child: Icon(Icons.broken_image_outlined, size: 48),
                      ),
                    ),
                  ),
                ),
              ),
            ),
            Padding(
              padding: const EdgeInsets.symmetric(vertical: 10),
              child: Column(
                children: [
                  SizedBox(
                    width: logicalPixelsPerCm,
                    child: const Row(
                      children: [
                        SizedBox(height: 10, child: VerticalDivider(width: 1)),
                        Expanded(child: Divider(height: 1)),
                        SizedBox(height: 10, child: VerticalDivider(width: 1)),
                      ],
                    ),
                  ),
                  const Text('1 cm', style: TextStyle(fontSize: 11)),
                ],
              ),
            ),
          ],
        ),
      ),
    );
  }
}
