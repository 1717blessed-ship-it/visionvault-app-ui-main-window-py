import 'package:flutter/material.dart';
import '../database/database_helper.dart';
import '../database/order_drafts_repository.dart';
import '../models/catalog_design.dart';
import '../models/order_draft.dart';
import '../services/bundled_product_catalog.dart';
import '../services/catalog_api_client.dart';
import '../services/order_integration_sync.dart';
import '../services/order_integration_client.dart';
import '../services/order_integration_catalog.dart';
import '../widgets/order_integration_status.dart';

/// Editor local: nunca modifica pedidos ni producción confirmados de Studio.
class UnifiedOrderCreationScreen extends StatefulWidget {
  final String baseUrl, sessionToken;
  final String? initialClient, initialWhatsapp, initialNotes;
  final OrderDraftsRepository? repository;
  final CatalogApiClient? api;
  // Not constructed by any productive route. Explicit isolated harness only.
  final OrderIntegrationSync? integrationSync;
  const UnifiedOrderCreationScreen(
      {super.key,
      required this.baseUrl,
      required this.sessionToken,
      this.initialClient,
      this.initialWhatsapp,
      this.initialNotes,
      this.repository,
      this.api,
      this.integrationSync});
  @override
  State<UnifiedOrderCreationScreen> createState() =>
      _UnifiedOrderCreationScreenState();
}

class _UnifiedOrderCreationScreenState
    extends State<UnifiedOrderCreationScreen> {
  late final api = widget.integrationSync != null
      ? OrderIntegrationCatalog(widget.integrationSync!.client)
      : widget.api ??
          CatalogApiClient(
              baseUrl: widget.baseUrl, authToken: widget.sessionToken);
  late final repo =
      widget.repository ?? OrderDraftsRepository(DatabaseHelper());
  late final client = TextEditingController(text: widget.initialClient);
  late final whatsapp = TextEditingController(text: widget.initialWhatsapp);
  late final notes = TextEditingController(text: widget.initialNotes);
  OrderDraft draft = OrderDraft();
  List<StudioProduct> products = [];
  bool busy = false, dirty = false;
  String catalogStatus = 'Consultando catálogo de Studio…';
  String status = 'Borrador nuevo · sin guardar · no confirmado en Desktop';
  @override
  void initState() {
    super.initState();
    _catalog();
  }

  Future<void> _catalog() async {
    List<StudioProduct> result;
    String label;
    try {
      if (widget.integrationSync case final sync?) {
        await sync.client.capabilities();
        final response = await sync.client.catalog();
        result = (response['products'] as List)
            .map((p) => StudioProduct.fromJson(objectMap(p)))
            .toList();
      } else {
        result = await api.getProducts();
      }
      label = 'Catálogo recibido de Studio';
    } catch (_) {
      result = await BundledProductCatalog.load();
      label = 'Catálogo incluido · vigencia no confirmada';
    }
    if (mounted) {
      setState(() {
        products = result;
        catalogStatus = label;
      });
    }
  }

  @override
  void dispose() {
    client.dispose();
    whatsapp.dispose();
    notes.dispose();
    if (widget.integrationSync != null || widget.api == null) api.close();
    super.dispose();
  }

  Future<bool> _discard() async =>
      await showDialog<bool>(
          context: context,
          builder: (context) => AlertDialog(
                  title: const Text('Cambios sin guardar'),
                  content: const Text(
                      'Guardá antes de salir o recuperar otro borrador. ¿Descartar cambios?'),
                  actions: [
                    TextButton(
                        onPressed: () => Navigator.pop(context, false),
                        child: const Text('Volver')),
                    TextButton(
                        onPressed: () => Navigator.pop(context, true),
                        child: const Text('Descartar'))
                  ])) ??
      false;
  Future<void> _save() async {
    if (busy) return;
    setState(() => busy = true);
    try {
      final saved = await repo.save(OrderDraft(
          id: draft.id,
          revision: draft.revision,
          client: client.text.trim(),
          whatsapp: whatsapp.text.trim(),
          notes: notes.text.trim(),
          jobs: draft.jobs));
      if (mounted) {
        setState(() {
          draft = saved;
          dirty = false;
          status =
              'Guardado local · revisión ${saved.revision} · NO enviado a Desktop';
        });
      }
    } catch (e) {
      if (mounted) setState(() => status = 'No guardado: $e');
    } finally {
      if (mounted) setState(() => busy = false);
    }
  }

  Future<void> _recover() async {
    if (busy) return;
    if (dirty && !await _discard()) return;
    try {
      final drafts = await repo.all();
      if (!mounted) return;
      final selected = await showModalBottomSheet<OrderDraft>(
          context: context,
          builder: (context) => SafeArea(
              child: drafts.isEmpty
                  ? const Padding(
                      padding: EdgeInsets.all(24),
                      child: Text('Sin borradores de este vendedor'))
                  : ListView(
                      children: drafts
                          .map((d) => ListTile(
                              title: Text(d.client.isEmpty
                                  ? 'Sin cliente · incompleto'
                                  : d.client),
                              subtitle: Text(
                                  '${d.jobs.length} trabajos · local · revisión ${d.revision}'),
                              onTap: () => Navigator.pop(context, d)))
                          .toList())));
      if (selected != null && mounted) {
        setState(() {
          draft = selected;
          client.text = draft.client;
          whatsapp.text = draft.whatsapp;
          notes.text = draft.notes;
          dirty = false;
          status = widget.integrationSync == null
              ? 'Recuperado local · no sincronizado'
              : 'Borrador recuperado · consultá el estado y la revisión en el panel de integración';
        });
      }
    } catch (e) {
      if (mounted) setState(() => status = 'No se pudo recuperar: $e');
    }
  }

  Future<void> _edit([OrderWork? job]) async {
    final edited = await showModalBottomSheet<OrderWork>(
        context: context,
        isScrollControlled: true,
        builder: (_) => _WorkEditor(products: products, job: job, api: api));
    if (edited == null || !mounted) return;
    setState(() {
      final jobs = [...draft.jobs];
      final index = jobs.indexWhere((j) => j.id == edited.id);
      if (index < 0) {
        jobs.add(edited);
      } else {
        jobs[index] = edited;
      }
      draft = OrderDraft(id: draft.id, revision: draft.revision, jobs: jobs);
      dirty = true;
      status = 'Cambios locales sin guardar';
    });
  }

  Future<void> _integrationAction({bool pull = false}) async {
    final sync = widget.integrationSync;
    if (sync == null || busy || dirty) return;
    setState(() => busy = true);
    try {
      if (pull) {
        final updated = await sync.refresh(draft.id);
        if (mounted) {
          setState(() {
            draft = updated;
            client.text = updated.client;
            whatsapp.text = updated.whatsapp;
            notes.text = updated.notes;
            status =
                'Versión Desktop recibida · revisión local ${updated.revision}';
          });
        }
      } else {
        await sync.enqueue(draft);
        if (mounted) {
          setState(() => status =
              'Operación preparada · consultá su estado y recibo en el panel de integración');
        }
      }
    } catch (e) {
      if (mounted) setState(() => status = 'Sin reemplazar el borrador: $e');
    } finally {
      if (mounted) setState(() => busy = false);
    }
  }

  @override
  Widget build(BuildContext context) => PopScope(
      canPop: !dirty && !busy,
      onPopInvokedWithResult: (popped, _) async {
        if (!popped && !busy && await _discard() && context.mounted) {
          setState(() => dirty = false);
          WidgetsBinding.instance.addPostFrameCallback((_) {
            if (mounted) Navigator.pop(context);
          });
        }
      },
      child: Scaffold(
          appBar:
              AppBar(title: const Text('Pedido · borrador local'), actions: [
            IconButton(
                tooltip: 'Recuperar borrador',
                onPressed: busy ? null : _recover,
                icon: const Icon(Icons.folder_open))
          ]),
          body: ListView(padding: const EdgeInsets.all(16), children: [
            Text(status, key: const Key('draft-status')),
            if (widget.integrationSync case final sync?)
              OrderIntegrationStatus(
                  sync: sync,
                  localId: draft.id,
                  localRevision: draft.revision,
                  dirty: dirty,
                  busy: busy,
                  enqueue: () => _integrationAction(),
                  refresh: () => _integrationAction(pull: true)),
            Text(catalogStatus),
            Text(widget.integrationSync == null
                ? 'Presupuesto pendiente de Studio. Envío del pedido completo no disponible.'
                : 'Presupuesto definitivo solo tras confirmación de Desktop aislado.'),
            TextField(
                enabled: !busy,
                controller: client,
                decoration: const InputDecoration(labelText: 'Cliente'),
                onChanged: (_) => setState(() => dirty = true)),
            TextField(
                enabled: !busy,
                controller: whatsapp,
                decoration: const InputDecoration(labelText: 'WhatsApp'),
                onChanged: (_) => setState(() => dirty = true)),
            TextField(
                enabled: !busy,
                controller: notes,
                decoration: const InputDecoration(labelText: 'Observaciones'),
                onChanged: (_) => setState(() => dirty = true)),
            const SizedBox(height: 16),
            ...draft.jobs.map((j) => Card(
                child: ListTile(
                    onTap: busy ? null : () => _edit(j),
                    title: Text(j.productName),
                    subtitle: Text(
                        '${j.variantName} ${j.material} ${j.size}\n${j.quantity} ${j.unitKind == 'sheets' ? 'hojas' : 'unidades'} · ${j.assigned} asignadas · ${j.pending} pendientes'),
                    trailing: IconButton(
                        tooltip: 'Quitar trabajo local',
                        icon: const Icon(Icons.delete_outline),
                        onPressed: busy
                            ? null
                            : () => setState(() {
                                  draft = OrderDraft(
                                      id: draft.id,
                                      revision: draft.revision,
                                      jobs: draft.jobs
                                          .where((other) => other.id != j.id)
                                          .toList());
                                  dirty = true;
                                }))))),
            OutlinedButton.icon(
                onPressed: busy || products.isEmpty ? null : () => _edit(),
                icon: const Icon(Icons.add),
                label: const Text('Agregar trabajo')),
            FilledButton.icon(
                onPressed: busy ? null : _save,
                icon: const Icon(Icons.save_outlined),
                label: Text(busy
                    ? 'Guardando…'
                    : 'Guardar borrador (incluso incompleto)')),
          ])));
}

class _WorkEditor extends StatefulWidget {
  final List<StudioProduct> products;
  final OrderWork? job;
  final CatalogApiClient api;
  const _WorkEditor({required this.products, required this.api, this.job});
  @override
  State<_WorkEditor> createState() => _WorkEditorState();
}

class _WorkEditorState extends State<_WorkEditor> {
  StudioProduct? product;
  int? option;
  late String unit = widget.job?.unitKind ?? 'units';
  late final quantity =
      TextEditingController(text: '${widget.job?.quantity ?? 1}');
  late final notes = TextEditingController(text: widget.job?.notes);
  late List<DesignAllocation> designs = [...?widget.job?.designs];
  String? error;
  bool loading = false;
  @override
  void initState() {
    super.initState();
    final matches =
        widget.products.where((p) => p.code == widget.job?.productCode);
    product = matches.isEmpty ? null : matches.first;
    if (widget.job != null && product != null) {
      final j = widget.job!;
      final index = product!.options.indexWhere((o) =>
          o.variantCode == j.variantCode &&
          o.material == j.material &&
          o.size == j.size);
      if (index >= 0) option = index;
    }
  }

  @override
  void dispose() {
    quantity.dispose();
    notes.dispose();
    super.dispose();
  }

  Future<int?> _count(String name, int initial) async {
    final text = TextEditingController(text: '$initial');
    final result = await showDialog<int>(
        context: context,
        builder: (context) => AlertDialog(
                title: Text(name),
                content: TextField(
                    controller: text,
                    keyboardType: TextInputType.number,
                    decoration: const InputDecoration(
                        labelText: 'Cantidad asignada (positiva)')),
                actions: [
                  TextButton(
                      onPressed: () => Navigator.pop(context),
                      child: const Text('Cancelar')),
                  FilledButton(
                      onPressed: () {
                        final n = int.tryParse(text.text);
                        if (n != null && n > 0) Navigator.pop(context, n);
                      },
                      child: const Text('Asignar'))
                ]));
    Future<void>.delayed(const Duration(seconds: 1), text.dispose);
    return result;
  }

  Future<void> _link() async {
    setState(() {
      loading = true;
      error = null;
    });
    try {
      final list = await widget.api.getDesigns(limit: 100);
      if (!mounted) return;
      final design = await showDialog<CatalogDesign>(
          context: context,
          builder: (context) => SimpleDialog(
              title: const Text('Seleccionar diseño existente'),
              children: list
                  .map((d) => SimpleDialogOption(
                      onPressed: () => Navigator.pop(context, d),
                      child: Text(d.name)))
                  .toList()));
      if (design == null || !mounted) return;
      if (designs.any((d) => d.designId == design.id)) {
        setState(() => error = 'Diseño ya asignado. Editá su cantidad.');
        return;
      }
      final count = await _count(design.name, 1);
      if (count != null && mounted) {
        setState(() => designs.add(DesignAllocation(
            designId: design.id, name: design.name, quantity: count)));
      }
    } catch (_) {
      if (mounted) {
        setState(() => error =
            'Sin catálogo de diseños. Los vínculos guardados se conservan.');
      }
    } finally {
      if (mounted) setState(() => loading = false);
    }
  }

  void _accept() {
    try {
      final p = product;
      if (p == null) {
        throw ArgumentError('Seleccioná un producto del catálogo.');
      }
      if (p.options.isNotEmpty && option == null) {
        throw ArgumentError('Seleccioná una variante vigente.');
      }
      final o = option == null ? null : p.options[option!];
      final j = OrderWork(
          id: widget.job?.id,
          productCode: p.code,
          productName: p.name,
          variantCode: o?.variantCode ?? '',
          variantName: o?.variantName ?? '',
          material: o?.material ?? '',
          size: o?.size ?? '',
          quantity: int.tryParse(quantity.text) ?? 0,
          unitKind: unit,
          notes: notes.text.trim(),
          designs: designs);
      j.validate();
      Navigator.pop(context, j);
    } catch (e) {
      setState(() => error = e.toString());
    }
  }

  @override
  Widget build(BuildContext context) => SafeArea(
      child: SingleChildScrollView(
          padding: EdgeInsets.fromLTRB(
              16, 16, 16, 16 + MediaQuery.viewInsetsOf(context).bottom),
          child: Column(
              mainAxisSize: MainAxisSize.min,
              crossAxisAlignment: CrossAxisAlignment.stretch,
              children: [
                Text('Trabajo', style: Theme.of(context).textTheme.titleLarge),
                DropdownButtonFormField<StudioProduct>(
                    initialValue: product,
                    isExpanded: true,
                    decoration: const InputDecoration(labelText: 'Producto'),
                    items: widget.products
                        .map((p) =>
                            DropdownMenuItem(value: p, child: Text(p.name)))
                        .toList(),
                    onChanged: (p) => setState(() {
                          product = p;
                          option = null;
                        })),
                if (product != null && product!.options.isNotEmpty)
                  DropdownButtonFormField<int>(
                      key: ValueKey(product!.code),
                      initialValue: option,
                      isExpanded: true,
                      decoration: const InputDecoration(
                          labelText: 'Subproducto · material · tamaño'),
                      items: [
                        for (var i = 0; i < product!.options.length; i++)
                          DropdownMenuItem(
                              value: i,
                              child: Text([
                                product!.options[i].variantName,
                                product!.options[i].material,
                                product!.options[i].size
                              ].where((s) => s.isNotEmpty).join(' · ')))
                      ],
                      onChanged: (i) => setState(() => option = i)),
                TextField(
                    controller: quantity,
                    keyboardType: TextInputType.number,
                    decoration: const InputDecoration(labelText: 'Cantidad')),
                DropdownButtonFormField<String>(
                    initialValue: unit,
                    items: const [
                      DropdownMenuItem(value: 'units', child: Text('Unidades')),
                      DropdownMenuItem(value: 'sheets', child: Text('Hojas'))
                    ],
                    onChanged: (v) => setState(() => unit = v!)),
                TextField(
                    controller: notes,
                    decoration: const InputDecoration(
                        labelText: 'Observaciones del trabajo')),
                const Text(
                    'Precio y costo pendientes de presupuesto oficial; no se calculan en el teléfono.'),
                for (final d in designs)
                  ListTile(
                      title: Text(d.name),
                      subtitle: Text(
                          '${d.quantity} asignadas · vínculo local no enviado'),
                      onTap: () async {
                        final n = await _count(d.name, d.quantity);
                        if (n != null && mounted) {
                          setState(() {
                            designs = designs
                                .map((old) => old.designId == d.designId
                                    ? DesignAllocation(
                                        designId: d.designId,
                                        name: d.name,
                                        quantity: n)
                                    : old)
                                .toList();
                          });
                        }
                      },
                      trailing: IconButton(
                          tooltip: 'Quitar vínculo local',
                          icon: const Icon(Icons.link_off),
                          onPressed: () => setState(() => designs.remove(d)))),
                OutlinedButton(
                    onPressed: loading ? null : _link,
                    child: Text(loading
                        ? 'Consultando…'
                        : 'Enlazar diseño al trabajo')),
                if (error != null)
                  Text(error!,
                      style: TextStyle(
                          color: Theme.of(context).colorScheme.error)),
                FilledButton(
                    onPressed: loading ? null : _accept,
                    child: const Text('Conservar trabajo')),
              ])));
}
