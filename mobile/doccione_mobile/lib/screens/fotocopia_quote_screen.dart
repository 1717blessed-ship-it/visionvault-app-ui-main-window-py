import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:file_picker/file_picker.dart';

import '../services/catalog_api_client.dart';
import '../services/fotocopia_pricing_service.dart';

class FotocopiaQuoteScreen extends StatefulWidget {
  final String baseUrl;
  final String sessionToken;

  const FotocopiaQuoteScreen({
    super.key,
    required this.baseUrl,
    required this.sessionToken,
  });

  @override
  State<FotocopiaQuoteScreen> createState() => _FotocopiaQuoteScreenState();
}

class _FotocopiaQuoteScreenState extends State<FotocopiaQuoteScreen> {
  final _sheetsController = TextEditingController(text: '1');
  final _copiesController = TextEditingController(text: '1');
  final _manualPriceController = TextEditingController();
  bool _color = false;
  bool _doubleSided = false;
  bool _urgent = false;
  bool _analyzingPdf = false;
  Map<String, dynamic>? _automaticQuote;
  String? _pdfPath;
  String? _pdfName;

  @override
  void dispose() {
    _sheetsController.dispose();
    _copiesController.dispose();
    _manualPriceController.dispose();
    super.dispose();
  }

  int _positiveInt(String value) {
    final parsed = int.tryParse(value.trim()) ?? 1;
    if (parsed < 1) return 1;
    return parsed > 999999 ? 999999 : parsed;
  }

  double? get _manualPrice {
    final text = _manualPriceController.text
        .trim()
        .replaceAll('.', '')
        .replaceAll(',', '.');
    return text.isEmpty ? null : double.tryParse(text);
  }

  FotocopiaQuote get _quote => FotocopiaPricingService.calculate(
        color: _color,
        doubleSided: _doubleSided,
        physicalSheets: _positiveInt(_sheetsController.text),
        copies: _positiveInt(_copiesController.text),
        urgent: _urgent,
        manualPrice: _manualPrice,
      );

  String _money(double value) =>
      '\$ ${value.toStringAsFixed(0).replaceAllMapped(RegExp(r'(?<=\d)(?=(\d{3})+(?!\d))'), (_) => '.')}';

  Future<void> _pickAndAnalyzePdf() async {
    final file = await FilePicker.platform.pickFiles(
      type: FileType.custom,
      allowedExtensions: const ['pdf'],
    );
    final path = file?.files.single.path;
    if (path == null) return;
    _pdfPath = path;
    _pdfName = file!.files.single.name;
    await _analyzeSelectedPdf();
  }

  Future<void> _analyzeSelectedPdf() async {
    final path = _pdfPath;
    if (path == null) return;
    setState(() => _analyzingPdf = true);
    final api = CatalogApiClient(
      baseUrl: widget.baseUrl,
      authToken: widget.sessionToken,
    );
    try {
      final result = await api.analyzeFotocopiaPdf(
        path: path,
        copies: _positiveInt(_copiesController.text),
        duplex: _doubleSided,
      );
      if (!mounted) return;
      setState(() => _automaticQuote = result);
    } catch (error) {
      if (!mounted) return;
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(content: Text('No se pudo cotizar el PDF: $error')),
      );
    } finally {
      api.close();
      if (mounted) setState(() => _analyzingPdf = false);
    }
  }

  void _refreshPdfQuote() {
    setState(() {});
    if (_pdfPath != null && !_analyzingPdf) {
      _analyzeSelectedPdf();
    }
  }

  @override
  Widget build(BuildContext context) {
    final quote = _quote;
    return Scaffold(
      appBar: AppBar(title: const Text('Presupuestar fotocopias')),
      body: ListView(
        padding: const EdgeInsets.all(16),
        children: [
          Text('Cotización rápida',
              style: Theme.of(context)
                  .textTheme
                  .titleLarge
                  ?.copyWith(fontWeight: FontWeight.bold)),
          const SizedBox(height: 4),
          const Text('No crea pedidos ni guarda datos del cliente.'),
          const SizedBox(height: 20),
          OutlinedButton.icon(
            onPressed: _analyzingPdf ? null : _pickAndAnalyzePdf,
            icon: _analyzingPdf
                ? const SizedBox.square(
                    dimension: 18,
                    child: CircularProgressIndicator(strokeWidth: 2))
                : const Icon(Icons.picture_as_pdf_outlined),
            label: Text(_analyzingPdf
                ? 'Analizando PDF...'
                : 'Presupuestar automáticamente desde PDF'),
          ),
          if (_automaticQuote != null) ...[
            const SizedBox(height: 12),
            Card(
              child: ListTile(
                leading: const Icon(Icons.auto_awesome_outlined),
                onTap: _showAutomaticQuoteDetails,
                title: Text(
                    'PDF: ${_automaticQuote!['pages']} páginas · ${_automaticQuote!['color_pages']} color'),
                subtitle:
                    Text(_automaticDetail(_automaticQuote!['quantities'])),
                trailing: Text(
                    _money((_automaticQuote!['total'] as num).toDouble()),
                    style: const TextStyle(fontWeight: FontWeight.bold)),
              ),
            ),
          ],
          const SizedBox(height: 20),
          SegmentedButton<bool>(
            segments: const [
              ButtonSegment(
                  value: false,
                  label: Text('Blanco y negro'),
                  icon: Icon(Icons.print_outlined)),
              ButtonSegment(
                  value: true,
                  label: Text('Color'),
                  icon: Icon(Icons.palette_outlined)),
            ],
            selected: {_color},
            onSelectionChanged: (value) => setState(() => _color = value.first),
          ),
          const SizedBox(height: 12),
          SegmentedButton<bool>(
            segments: const [
              ButtonSegment(value: false, label: Text('Simple')),
              ButtonSegment(value: true, label: Text('Doble faz')),
            ],
            selected: {_doubleSided},
            onSelectionChanged: (value) {
              _doubleSided = value.first;
              _refreshPdfQuote();
            },
          ),
          const SizedBox(height: 16),
          TextField(
            controller: _sheetsController,
            keyboardType: TextInputType.number,
            inputFormatters: [FilteringTextInputFormatter.digitsOnly],
            onChanged: (_) => _refreshPdfQuote(),
            decoration: const InputDecoration(
                labelText: 'Hojas físicas', border: OutlineInputBorder()),
          ),
          const SizedBox(height: 12),
          TextField(
            controller: _copiesController,
            keyboardType: TextInputType.number,
            inputFormatters: [FilteringTextInputFormatter.digitsOnly],
            onChanged: (_) => setState(() {}),
            decoration: const InputDecoration(
                labelText: 'Juegos / copias', border: OutlineInputBorder()),
          ),
          const SizedBox(height: 8),
          SwitchListTile(
            contentPadding: EdgeInsets.zero,
            title: const Text('Trabajo urgente'),
            subtitle: const Text('Recargo de 30%'),
            value: _urgent,
            onChanged: (value) => setState(() => _urgent = value),
          ),
          TextField(
            controller: _manualPriceController,
            keyboardType: const TextInputType.numberWithOptions(decimal: true),
            onChanged: (_) => setState(() {}),
            decoration: const InputDecoration(
                labelText: 'Precio manual (opcional)',
                prefixText: '\$ ',
                border: OutlineInputBorder()),
          ),
          const SizedBox(height: 20),
          Card(
            color: Theme.of(context).colorScheme.primaryContainer,
            child: Padding(
              padding: const EdgeInsets.all(18),
              child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text('PRESUPUESTO',
                        style: Theme.of(context)
                            .textTheme
                            .labelLarge
                            ?.copyWith(fontWeight: FontWeight.bold)),
                    const SizedBox(height: 12),
                    _line('Precio por hoja', _money(quote.unitPrice)),
                    _line('Cantidad total', '${quote.totalSheets} hoja(s)'),
                    _line('Subtotal', _money(quote.basePrice)),
                    if (quote.urgent)
                      _line('Urgente (+30%)', _money(quote.surcharge)),
                    if (_manualPrice != null)
                      _line('Precio manual', _money(_manualPrice!)),
                    const Divider(),
                    _line('TOTAL', _money(quote.total), bold: true),
                  ]),
            ),
          ),
          const SizedBox(height: 12),
          FilledButton.icon(
            onPressed: () async {
              final messenger = ScaffoldMessenger.of(context);
              final type =
                  '${_color ? 'Color' : 'Blanco y negro'} ${_doubleSided ? 'doble faz' : 'simple'}';
              await Clipboard.setData(ClipboardData(
                  text:
                      'PRESUPUESTO DOCCIONE\n\nFotocopias $type\n${quote.physicalSheets} hojas × ${quote.copies} juego(s)\n\nTotal: ${_money(quote.total)}'));
              if (!mounted) return;
              messenger.showSnackBar(const SnackBar(
                  content: Text('Presupuesto copiado al portapapeles.')));
            },
            icon: const Icon(Icons.copy_outlined),
            label: const Text('Copiar presupuesto'),
          ),
        ],
      ),
    );
  }

  Widget _line(String label, String value, {bool bold = false}) => Padding(
        padding: const EdgeInsets.symmetric(vertical: 3),
        child: Row(children: [
          Text(label,
              style: TextStyle(fontWeight: bold ? FontWeight.bold : null)),
          const Spacer(),
          Text(value,
              style: TextStyle(fontWeight: bold ? FontWeight.bold : null))
        ]),
      );

  Widget _automaticQuoteCard() {
    final result = _automaticQuote!;
    final pages = result['page_analysis'] as List<dynamic>? ?? const [];
    final total = _money((result['total'] as num).toDouble());
    return Card(
      color: Theme.of(context).colorScheme.primaryContainer,
      child: Padding(
        padding: const EdgeInsets.all(16),
        child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          Text('COTIZADOR INTELIGENTE DE PDF',
              style: Theme.of(context)
                  .textTheme
                  .titleSmall
                  ?.copyWith(fontWeight: FontWeight.bold)),
          const SizedBox(height: 6),
          Text(_pdfName ?? 'PDF seleccionado'),
          const SizedBox(height: 10),
          Text(
              '${result['pages']} páginas · ${result['color_pages']} con color · ${result['pages'] - result['color_pages']} B/N'),
          Text(_automaticDetail(result['quantities'])),
          const SizedBox(height: 8),
          Text('TOTAL ESTIMADO: $total',
              style: Theme.of(context)
                  .textTheme
                  .titleMedium
                  ?.copyWith(fontWeight: FontWeight.bold)),
          const Divider(),
          ...pages.map((raw) {
            final page = raw as Map<String, dynamic>;
            final ink = (page['ink_coverage_percent'] as num).toDouble();
            final color = (page['color_coverage_percent'] as num).toDouble();
            final kind = ink == 0
                ? 'Hoja en blanco'
                : page['is_color'] == true
                    ? 'Color'
                    : 'B/N';
            return ListTile(
                dense: true,
                contentPadding: EdgeInsets.zero,
                leading: Text('Pág. ${page['page_number']}'),
                title: Text(kind),
                subtitle: Text(
                    'Color ${color.toStringAsFixed(1)}% · Tinta ${ink.toStringAsFixed(1)}%'));
          }),
          Align(
              alignment: Alignment.centerRight,
              child: TextButton.icon(
                  onPressed: () async {
                    final messenger = ScaffoldMessenger.of(context);
                    final mode = _doubleSided ? 'doble faz' : 'simple faz';
                    await Clipboard.setData(ClipboardData(
                        text:
                            'Hola, te compartimos el presupuesto de impresión de ${_pdfName ?? 'tu PDF'}.\n\n• Cantidad: ${result['copies']} copia(s)\n• Modalidad: impresión $mode\n• Documento: ${result['pages']} página(s)\n• Detalle: ${_automaticDetail(result['quantities'])}\n\nTotal estimado: $total\n\nEl importe se calculó según la cobertura de tinta y color de cada página.'));
                    if (!mounted) return;
                    messenger.showSnackBar(const SnackBar(
                        content: Text('Mensaje para el cliente copiado.')));
                  },
                  icon: const Icon(Icons.copy_outlined),
                  label: const Text('Copiar mensaje para cliente'))),
        ]),
      ),
    );
  }

  Future<void> _showAutomaticQuoteDetails() => showDialog<void>(
        context: context,
        builder: (context) => AlertDialog(
          title: const Text('Cotizador inteligente de PDF'),
          content: SingleChildScrollView(child: _automaticQuoteCard()),
          actions: [
            TextButton(
              onPressed: () => Navigator.pop(context),
              child: const Text('Cerrar'),
            ),
          ],
        ),
      );

  String _automaticDetail(dynamic quantities) {
    if (quantities is! Map) return 'Sin detalle';
    const labels = {
      'hoja_simple': 'hoja en blanco',
      'fotocopia_bn_simple': 'B/N simple',
      'fotocopia_bn_doble': 'B/N doble faz',
      'fotocopia_color_simple': 'color simple',
      'fotocopia_color_doble': 'color doble faz',
    };
    return quantities.entries
        .map((entry) => '${entry.value} ${labels[entry.key] ?? entry.key}')
        .join(' · ');
  }
}
