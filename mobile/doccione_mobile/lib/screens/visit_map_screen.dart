import 'dart:async';
import 'dart:io';

import 'package:flutter/material.dart';
import 'package:flutter_map/flutter_map.dart';
import 'package:geolocator/geolocator.dart';
import 'package:image_picker/image_picker.dart';
import 'package:latlong2/latlong.dart';
import 'package:url_launcher/url_launcher.dart';

import '../database/clients_repository.dart';
import '../database/database_helper.dart';
import '../database/visit_pins_repository.dart';
import '../models/client.dart';
import '../models/visit_attachment.dart';
import '../models/visit_history_entry.dart';
import '../models/visit_pin.dart';
import '../services/visit_address_search_service.dart';
import '../services/visit_attachment_service.dart';
import '../services/visit_clusterer.dart';
import '../services/visit_reminder_service.dart';
import '../services/visit_sync_api_client.dart';
import 'sticker_order_screen.dart';
import '../theme/doccione_palette.dart';

enum _VisitFilter { all, today, pending, completed, overdue, stale }

enum _MapAction { sync, route, metrics, headquarters, fit, agenda }

/// Agenda territorial local del vendedor. Las visitas se pueden relacionar con
/// un cliente y quedan disponibles aun sin conexión.
class VisitMapScreen extends StatefulWidget {
  final String? baseUrl;
  final String? sessionToken;
  const VisitMapScreen({super.key, this.baseUrl, this.sessionToken});

  @override
  State<VisitMapScreen> createState() => _VisitMapScreenState();
}

class _VisitMapScreenState extends State<VisitMapScreen>
    with SingleTickerProviderStateMixin {
  static const _obera = LatLng(-27.4871, -55.1196);
  static const _headquarters = LatLng(-27.4814047, -55.1174489);
  final _repository = VisitPinsRepository(DatabaseHelper());
  final _clientsRepository = ClientsRepository(DatabaseHelper());
  final _mapController = MapController();
  final _attachmentService = VisitAttachmentService();
  final _reminderService = VisitReminderService();
  List<VisitPin> _pins = [];
  List<Client> _clients = [];
  bool _loading = true;
  bool _saving = false;
  _VisitFilter _filter = _VisitFilter.all;
  LatLng? _currentLocation;
  bool _syncing = false;
  late final AnimationController _hqPulse;
  double _mapZoom = 13;
  String? _clientFilter;
  String? _zoneFilter;
  DateTimeRange? _dateFilter;
  int _staleDays = 0;

  @override
  void initState() {
    super.initState();
    _hqPulse = AnimationController(
      vsync: this,
      duration: const Duration(milliseconds: 1600),
    )..repeat(reverse: true);
    _load().then((_) => _syncRemote());
  }

  @override
  void dispose() {
    _hqPulse.dispose();
    super.dispose();
  }

  void _centerOnHeadquarters() => _mapController.move(_headquarters, 17);

  Future<void> _showHeadquarters() => showModalBottomSheet<void>(
        context: context,
        builder: (_) => SafeArea(
            child: Padding(
                padding: const EdgeInsets.all(20),
                child: Column(
                    mainAxisSize: MainAxisSize.min,
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Text('Central Doccione',
                          style: Theme.of(context).textTheme.titleLarge),
                      const SizedBox(height: 4),
                      const Text('Larrea 445 · Oberá, Misiones'),
                      const SizedBox(height: 16),
                      FilledButton.icon(
                          onPressed: () => _openMap(VisitPin(
                              title: 'Central Doccione',
                              latitude: _headquarters.latitude,
                              longitude: _headquarters.longitude,
                              createdAt: DateTime.now(),
                              clientUuid: 'headquarters')),
                          icon: const Icon(Icons.directions),
                          label: const Text('Cómo llegar')),
                    ]))),
      );

  void _fitRelevantPins() {
    final points = <LatLng>[
      _headquarters,
      ..._visiblePins.map((pin) => LatLng(pin.latitude, pin.longitude)),
    ];
    if (points.length == 1) {
      _centerOnHeadquarters();
      return;
    }
    _mapController.fitCamera(CameraFit.bounds(
      bounds: LatLngBounds.fromPoints(points),
      padding: const EdgeInsets.all(56),
    ));
  }

  Future<void> _load() async {
    final results = await Future.wait(
        [_repository.getAll(), _clientsRepository.getAllClients()]);
    if (!mounted) return;
    setState(() {
      _pins = results[0] as List<VisitPin>;
      _clients = results[1] as List<Client>;
      _loading = false;
    });
    await _refreshReminders(pins: _pins);
  }

  Future<void> _refreshReminders({required List<VisitPin> pins}) async {
    for (final pin in pins) {
      await _reminderService.schedule(pin);
    }
    final overdue = pins.where(_isOverdue).length;
    final now = DateTime.now();
    final dayKey = '${now.year}-${now.month}-${now.day}';
    if (overdue > 0 && await _repository.shouldShowOverdueReminder(dayKey)) {
      await _reminderService.showOverdueSummary(overdue);
      await _repository.markOverdueReminderShown(dayKey);
    }
  }

  Future<void> _syncRemote() async {
    final baseUrl = widget.baseUrl;
    final token = widget.sessionToken;
    if (baseUrl == null || token == null || _syncing) return;
    setState(() => _syncing = true);
    final api = VisitSyncApiClient(baseUrl: baseUrl, sessionToken: token);
    try {
      for (final pin in await _repository.getDirty()) {
        if (pin.deleted) {
          await api.delete(pin.clientUuid);
          if (pin.id != null) await _repository.delete(pin.id!);
        } else {
          try {
            await _repository.markSynced(await api.upsert(pin));
          } on VisitSyncConflict catch (conflict) {
            await _repository.markConflict(pin, conflict.remote);
          }
        }
      }
      for (final entry in await _repository.getDirtyHistory()) {
        await api.upsertHistory(entry);
        await _repository.markHistorySynced(entry.eventUuid);
      }
      for (final attachment in await _repository.dirtyAttachments()) {
        await api.uploadAttachment(attachment);
        await _repository.markAttachmentSynced(attachment.attachmentUuid);
      }
      for (final pin in await api.pull()) {
        await _repository.upsertByUuid(pin);
      }
      for (final entry in await api.pullHistory()) {
        await _repository.upsertHistory(entry);
      }
      for (final attachment in await api.pullAttachmentMetadata()) {
        if (await _repository.hasAttachment(attachment.attachmentUuid)) {
          continue;
        }
        final bytes = await api.downloadAttachment(attachment.attachmentUuid);
        final localPath = await _attachmentService.storeDownloaded(
          attachmentUuid: attachment.attachmentUuid,
          fileName: attachment.fileName,
          bytes: bytes,
        );
        await _repository.addAttachment(
            attachment.copyWith(localPath: localPath, syncDirty: false));
      }
      await _load();
    } catch (_) {
      // La agenda continúa funcionando sin conexión.
    } finally {
      api.close();
      if (mounted) setState(() => _syncing = false);
    }
  }

  List<VisitPin> get _visiblePins => _pins.where((pin) {
        final scheduled = pin.scheduledAt;
        if (_clientFilter != null && pin.clientId != _clientFilter) {
          return false;
        }
        if (_zoneFilter != null && pin.zone != _zoneFilter) return false;
        if (_dateFilter != null &&
            (scheduled == null ||
                scheduled.isBefore(_dateFilter!.start) ||
                scheduled.isAfter(_dateFilter!.end
                    .add(const Duration(hours: 23, minutes: 59))))) {
          return false;
        }
        if (_staleDays > 0 && !_isStale(pin, _staleDays)) return false;
        switch (_filter) {
          case _VisitFilter.today:
            return pin.scheduledAt != null &&
                DateUtils.isSameDay(pin.scheduledAt, DateTime.now());
          case _VisitFilter.pending:
            return pin.status == 'pending';
          case _VisitFilter.completed:
            return pin.status == 'completed';
          case _VisitFilter.overdue:
            return _isOverdue(pin);
          case _VisitFilter.stale:
            return _isStale(pin, 30);
          case _VisitFilter.all:
            return true;
        }
      }).toList();

  bool _isOverdue(VisitPin pin) =>
      pin.status == 'pending' &&
      pin.scheduledAt != null &&
      DateUtils.dateOnly(pin.scheduledAt!)
          .isBefore(DateUtils.dateOnly(DateTime.now()));

  bool _isStale(VisitPin pin, int days) {
    final threshold = DateTime.now().subtract(Duration(days: days));
    return pin.lastContactAt == null || pin.lastContactAt!.isBefore(threshold);
  }

  Future<Position> _currentPosition() async {
    if (!await Geolocator.isLocationServiceEnabled()) {
      throw StateError(
          'Activá la ubicación del teléfono para registrar la visita.');
    }
    var permission = await Geolocator.checkPermission();
    if (permission == LocationPermission.denied) {
      permission = await Geolocator.requestPermission();
    }
    if (permission == LocationPermission.denied ||
        permission == LocationPermission.deniedForever) {
      throw StateError(
          'Necesitás autorizar la ubicación para registrar la visita.');
    }
    return Geolocator.getCurrentPosition(
        locationSettings:
            const LocationSettings(accuracy: LocationAccuracy.high));
  }

  Future<void> _editPin(LatLng point, [VisitPin? existing]) async {
    final saved = await showModalBottomSheet<VisitPin>(
      context: context,
      isScrollControlled: true,
      builder: (_) =>
          _VisitEditor(point: point, pin: existing, clients: _clients),
    );
    if (saved == null) return;
    setState(() => _saving = true);
    try {
      if (existing == null) {
        await _repository.add(saved);
        await _repository.addHistory(
            saved.clientUuid, 'Visita creada', saved.note);
      } else {
        await _repository.update(saved);
        await _repository.addHistory(
            saved.clientUuid, 'Visita actualizada', saved.note);
      }
      await _reminderService.schedule(saved);
      await _load();
      await _syncRemote();
    } finally {
      if (mounted) setState(() => _saving = false);
    }
  }

  Future<void> _addAtCurrentLocation() async {
    setState(() => _saving = true);
    try {
      final position = await _currentPosition();
      final point = LatLng(position.latitude, position.longitude);
      if (!mounted) return;
      setState(() => _currentLocation = point);
      _mapController.move(point, 16);
      setState(() => _saving = false);
      await _editPin(point);
    } catch (error) {
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(SnackBar(
            content: Text('$error'),
            backgroundColor: Theme.of(context).colorScheme.error));
      }
    } finally {
      if (mounted && _saving) setState(() => _saving = false);
    }
  }

  Future<void> _centerOnCurrentLocation() async {
    try {
      final position = await _currentPosition();
      final point = LatLng(position.latitude, position.longitude);
      if (!mounted) return;
      setState(() => _currentLocation = point);
      _mapController.move(point, 16);
    } catch (error) {
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(
            content: Text('$error'),
            backgroundColor: Theme.of(context).colorScheme.error,
          ),
        );
      }
    }
  }

  Future<void> _markCompleted(VisitPin pin) async {
    final completed = pin.copyWith(
      status: 'completed',
      lastContactAt: DateTime.now(),
      updatedAt: DateTime.now(),
      syncDirty: true,
      syncConflict: false,
      clearConflictPayload: true,
    );
    await _repository.update(completed);
    await _reminderService.cancel(pin);
    await _repository.addHistory(pin.clientUuid, 'Visita realizada', pin.note);
    await _load();
    await _syncRemote();
    if (mounted) {
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(content: Text('${pin.title}: visita marcada como realizada.')),
      );
    }
  }

  Future<void> _openMap(VisitPin pin) async {
    final uri = Uri.parse(
        'geo:${pin.latitude},${pin.longitude}?q=${pin.latitude},${pin.longitude}(${Uri.encodeComponent(pin.title)})');
    if (!await launchUrl(uri) && mounted) {
      ScaffoldMessenger.of(context).showSnackBar(
          const SnackBar(content: Text('No se encontró una app de mapas.')));
    }
  }

  Future<void> _openWhatsapp(VisitPin pin) async {
    final phone = (pin.clientPhone ?? '').replaceAll(RegExp(r'[^0-9]'), '');
    if (phone.isEmpty) return;
    if (!await launchUrl(Uri.parse('https://wa.me/$phone')) && mounted) {
      ScaffoldMessenger.of(context).showSnackBar(
          const SnackBar(content: Text('No se pudo abrir WhatsApp.')));
    }
  }

  Future<void> _openDailyRoute() async {
    final stops = _pins.where((pin) => pin.status == 'pending').toList();
    if (stops.isEmpty) {
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(const SnackBar(
            content: Text('No hay visitas pendientes para recorrer.')));
      }
      return;
    }
    final origin = _currentLocation;
    if (origin != null) {
      const distance = Distance();
      stops.sort((a, b) => distance(origin, LatLng(a.latitude, a.longitude))
          .compareTo(distance(origin, LatLng(b.latitude, b.longitude))));
    }
    final destination = '${stops.last.latitude},${stops.last.longitude}';
    final waypoints = stops.length > 1
        ? stops
            .take(stops.length - 1)
            .map((pin) => '${pin.latitude},${pin.longitude}')
            .join('|')
        : null;
    final uri = Uri.https('www.google.com', '/maps/dir/', {
      if (origin != null) 'origin': '${origin.latitude},${origin.longitude}',
      'destination': destination,
      'travelmode': 'driving',
      if (waypoints != null) 'waypoints': waypoints,
    });
    if (!await launchUrl(uri, mode: LaunchMode.externalApplication) &&
        mounted) {
      ScaffoldMessenger.of(context).showSnackBar(
          const SnackBar(content: Text('No se pudo abrir la ruta.')));
    }
  }

  Future<void> _searchVisits() async {
    await showModalBottomSheet<void>(
      context: context,
      isScrollControlled: true,
      builder: (sheetContext) => Padding(
        padding: EdgeInsets.fromLTRB(
            20, 20, 20, 20 + MediaQuery.viewInsetsOf(sheetContext).bottom),
        child: _VisitSearch(
          pins: _pins.where((pin) => !pin.deleted).toList(),
          clients: _clients,
          onSelect: (pin) {
            _mapController.move(LatLng(pin.latitude, pin.longitude), 16);
            Navigator.pop(sheetContext);
          },
          onAddressSelect: (result) {
            _mapController.move(LatLng(result.latitude, result.longitude), 16);
            Navigator.pop(sheetContext);
          },
        ),
      ),
    );
  }

  Future<void> _createOrder(VisitPin pin) async {
    final baseUrl = widget.baseUrl;
    final token = widget.sessionToken;
    if (baseUrl == null || token == null) {
      ScaffoldMessenger.of(context).showSnackBar(const SnackBar(
          content:
              Text('Vinculá la app para crear pedidos desde una visita.')));
      return;
    }
    await Navigator.push(
        context,
        MaterialPageRoute(
            builder: (_) => StickerOrderScreen(
                  baseUrl: baseUrl,
                  sessionToken: token,
                  initialClient: pin.title,
                  initialWhatsapp: pin.clientPhone,
                  initialNotes: pin.note == null
                      ? 'Pedido creado desde mapa de visitas.'
                      : 'Visita: ${pin.note}',
                )));
  }

  Future<void> _delete(VisitPin pin) async {
    final confirmed = await showDialog<bool>(
      context: context,
      builder: (dialogContext) => AlertDialog(
        title: const Text('Eliminar visita'),
        content:
            Text('¿Eliminar “${pin.title}”? Esta acción no se puede deshacer.'),
        actions: [
          TextButton(
              onPressed: () => Navigator.pop(dialogContext, false),
              child: const Text('Cancelar')),
          FilledButton(
              onPressed: () => Navigator.pop(dialogContext, true),
              child: const Text('Eliminar')),
        ],
      ),
    );
    if (confirmed == true && pin.id != null) {
      await _reminderService.cancel(pin);
      await _repository.markDeleted(pin);
      await _repository.addHistory(pin.clientUuid, 'Visita eliminada');
      await _load();
      await _syncRemote();
    }
  }

  Future<void> _addPhoto(VisitPin pin, ImageSource source) async {
    final attachment = await _attachmentService.pick(
      clientUuid: pin.clientUuid,
      source: source,
    );
    if (attachment == null) return;
    await _repository.addAttachment(attachment);
    await _repository.addHistory(
        pin.clientUuid, 'Foto agregada', attachment.fileName);
    await _syncRemote();
  }

  Future<void> _showAttachments(VisitPin pin) => showModalBottomSheet<void>(
        context: context,
        isScrollControlled: true,
        builder: (sheetContext) => SafeArea(
          child: SizedBox(
            height: MediaQuery.sizeOf(sheetContext).height * .72,
            child: FutureBuilder<List<VisitAttachment>>(
              future: _repository.attachments(pin.clientUuid),
              builder: (_, snapshot) {
                final attachments = snapshot.data ?? const <VisitAttachment>[];
                return Column(children: [
                  ListTile(
                    title: const Text('Fotos y adjuntos'),
                    subtitle: Text('${attachments.length} archivo(s)'),
                    trailing: Wrap(children: [
                      IconButton(
                        tooltip: 'Tomar foto',
                        icon: const Icon(Icons.photo_camera_outlined),
                        onPressed: () async {
                          Navigator.pop(sheetContext);
                          await _addPhoto(pin, ImageSource.camera);
                          if (mounted) await _showAttachments(pin);
                        },
                      ),
                      IconButton(
                        tooltip: 'Elegir de galería',
                        icon: const Icon(Icons.photo_library_outlined),
                        onPressed: () async {
                          Navigator.pop(sheetContext);
                          await _addPhoto(pin, ImageSource.gallery);
                          if (mounted) await _showAttachments(pin);
                        },
                      ),
                    ]),
                  ),
                  Expanded(
                    child: snapshot.connectionState == ConnectionState.waiting
                        ? const Center(child: CircularProgressIndicator())
                        : attachments.isEmpty
                            ? const Center(
                                child: Text('Todavía no hay fotos adjuntas.'))
                            : GridView.builder(
                                padding: const EdgeInsets.all(12),
                                gridDelegate:
                                    const SliverGridDelegateWithFixedCrossAxisCount(
                                  crossAxisCount: 2,
                                  crossAxisSpacing: 10,
                                  mainAxisSpacing: 10,
                                ),
                                itemCount: attachments.length,
                                itemBuilder: (_, index) {
                                  final attachment = attachments[index];
                                  final file = File(attachment.localPath);
                                  return ClipRRect(
                                    borderRadius: BorderRadius.circular(12),
                                    child: file.existsSync()
                                        ? Image.file(file, fit: BoxFit.cover)
                                        : const ColoredBox(
                                            color: Color(0xFFE5E7EB),
                                            child: Icon(
                                                Icons.broken_image_outlined),
                                          ),
                                  );
                                },
                              ),
                  ),
                ]);
              },
            ),
          ),
        ),
      );

  Future<void> _resolveConflict(VisitPin pin) async {
    final remote = _repository.conflictRemote(pin);
    if (remote == null) return;
    final choice = await showDialog<String>(
      context: context,
      builder: (dialogContext) => AlertDialog(
        title: const Text('Cambios en dos teléfonos'),
        content: Column(mainAxisSize: MainAxisSize.min, children: [
          _conflictChoice('Este teléfono', pin),
          const Divider(),
          _conflictChoice('Otro teléfono', remote),
        ]),
        actions: [
          TextButton(
              onPressed: () => Navigator.pop(dialogContext),
              child: const Text('Más tarde')),
          OutlinedButton(
              onPressed: () => Navigator.pop(dialogContext, 'remote'),
              child: const Text('Conservar el otro')),
          FilledButton(
              onPressed: () => Navigator.pop(dialogContext, 'local'),
              child: const Text('Conservar este')),
        ],
      ),
    );
    if (choice == 'remote') {
      await _repository.markSynced(remote);
      await _repository.addHistory(pin.clientUuid, 'Conflicto resuelto',
          'Se conservó el cambio remoto.');
    } else if (choice == 'local') {
      final local = pin.copyWith(
        serverVersion: remote.serverVersion,
        updatedAt: DateTime.now(),
        syncDirty: true,
        syncConflict: false,
        clearConflictPayload: true,
      );
      final baseUrl = widget.baseUrl;
      final token = widget.sessionToken;
      if (baseUrl != null && token != null) {
        final api = VisitSyncApiClient(baseUrl: baseUrl, sessionToken: token);
        try {
          await _repository.markSynced(await api.upsert(local, force: true));
        } catch (_) {
          await _repository.update(local);
        } finally {
          api.close();
        }
      } else {
        await _repository.update(local);
      }
      await _repository.addHistory(
          pin.clientUuid, 'Conflicto resuelto', 'Se conservó este teléfono.');
    }
    await _load();
    await _syncRemote();
  }

  Widget _conflictChoice(String label, VisitPin pin) => ListTile(
        contentPadding: EdgeInsets.zero,
        title: Text(label, style: const TextStyle(fontWeight: FontWeight.w700)),
        subtitle: Text(
            '${pin.title}\n${pin.status == 'completed' ? 'Visitada' : 'Pendiente'} · ${_date(pin.updatedAt)}'),
      );

  Future<void> _showCommercialFilters() async {
    final zones = _pins
        .map((pin) => pin.zone?.trim())
        .whereType<String>()
        .where((zone) => zone.isNotEmpty)
        .toSet()
        .toList()
      ..sort();
    final selection = await showModalBottomSheet<_CommercialFilterSelection>(
      context: context,
      isScrollControlled: true,
      builder: (_) => _CommercialFiltersSheet(
        clients: _clients,
        zones: zones,
        clientId: _clientFilter,
        zone: _zoneFilter,
        dateRange: _dateFilter,
        staleDays: _staleDays,
      ),
    );
    if (selection == null) return;
    setState(() {
      _clientFilter = selection.clientId;
      _zoneFilter = selection.zone;
      _dateFilter = selection.dateRange;
      _staleDays = selection.staleDays;
    });
    WidgetsBinding.instance.addPostFrameCallback((_) => _fitRelevantPins());
  }

  bool get _hasCommercialFilters =>
      _clientFilter != null ||
      _zoneFilter != null ||
      _dateFilter != null ||
      _staleDays > 0;

  Future<void> _showPin(VisitPin pin) => showModalBottomSheet<void>(
        context: context,
        isScrollControlled: true,
        builder: (sheetContext) => SafeArea(
          child: SingleChildScrollView(
            child: Padding(
              padding: const EdgeInsets.fromLTRB(20, 16, 20, 24),
              child: Column(
                  mainAxisSize: MainAxisSize.min,
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Row(children: [
                      Expanded(
                          child: Text(pin.title,
                              style: Theme.of(context).textTheme.titleLarge)),
                      if (pin.syncConflict)
                        const Chip(
                            avatar: Icon(Icons.sync_problem, size: 18),
                            label: Text('Conflicto')),
                    ]),
                    const SizedBox(height: 4),
                    Text(_visitDetail(pin),
                        style: Theme.of(context).textTheme.bodyMedium),
                    if (pin.note != null) ...[
                      const SizedBox(height: 8),
                      Text(pin.note!)
                    ],
                    if ((pin.zone ?? '').isNotEmpty) Text('Zona: ${pin.zone!}'),
                    if ((pin.result ?? '').isNotEmpty)
                      Text('Resultado: ${pin.result!}'),
                    const SizedBox(height: 16),
                    Wrap(spacing: 8, runSpacing: 8, children: [
                      if (pin.syncConflict)
                        FilledButton.tonalIcon(
                            onPressed: () async {
                              Navigator.pop(sheetContext);
                              await _resolveConflict(pin);
                            },
                            icon: const Icon(Icons.sync_problem),
                            label: const Text('Resolver cambios')),
                      OutlinedButton.icon(
                          onPressed: () => _openMap(pin),
                          icon: const Icon(Icons.directions),
                          label: const Text('Cómo llegar')),
                      if ((pin.clientPhone ?? '').isNotEmpty)
                        OutlinedButton.icon(
                            onPressed: () => _openWhatsapp(pin),
                            icon: const Icon(Icons.chat_outlined),
                            label: const Text('WhatsApp')),
                      OutlinedButton.icon(
                          onPressed: () async {
                            Navigator.pop(sheetContext);
                            await _showHistory(pin);
                          },
                          icon: const Icon(Icons.history),
                          label: const Text('Historial')),
                      OutlinedButton.icon(
                          onPressed: () async {
                            Navigator.pop(sheetContext);
                            await _showAttachments(pin);
                          },
                          icon: const Icon(Icons.photo_library_outlined),
                          label: const Text('Fotos')),
                      OutlinedButton.icon(
                          onPressed: () async {
                            Navigator.pop(sheetContext);
                            await _createOrder(pin);
                          },
                          icon: const Icon(Icons.add_shopping_cart),
                          label: const Text('Crear pedido')),
                      if (pin.status != 'completed')
                        FilledButton.icon(
                            onPressed: () async {
                              Navigator.pop(sheetContext);
                              await _markCompleted(pin);
                            },
                            icon: const Icon(Icons.check),
                            label: const Text('Marcar visitada')),
                      IconButton(
                          onPressed: () async {
                            Navigator.pop(sheetContext);
                            await _editPin(
                                LatLng(pin.latitude, pin.longitude), pin);
                          },
                          icon: const Icon(Icons.edit_outlined),
                          tooltip: 'Editar'),
                      IconButton(
                          onPressed: () async {
                            Navigator.pop(sheetContext);
                            await _delete(pin);
                          },
                          icon: const Icon(Icons.delete_outline),
                          tooltip: 'Eliminar'),
                    ]),
                  ]),
            ),
          ),
        ),
      );

  Future<void> _showHistory(VisitPin pin) => showModalBottomSheet<void>(
        context: context,
        builder: (_) => SafeArea(
          child: FutureBuilder<List<VisitHistoryEntry>>(
            future: _repository.history(pin.clientUuid),
            builder: (_, snapshot) => SizedBox(
              height: 360,
              child: snapshot.hasData
                  ? ListView(children: [
                      const ListTile(title: Text('Historial de visita')),
                      ...snapshot.data!.map((entry) => ListTile(
                            leading: const Icon(Icons.history),
                            title: Text(entry.action),
                            subtitle: Text([
                              if ((entry.note ?? '').isNotEmpty) entry.note!,
                              _date(entry.createdAt),
                            ].join(' · ')),
                          )),
                    ])
                  : const Center(child: CircularProgressIndicator()),
            ),
          ),
        ),
      );

  String _visitDetail(VisitPin pin) {
    final status = pin.status == 'completed' ? 'Visitada' : 'Pendiente';
    final date = pin.scheduledAt == null ? '' : ' · ${_date(pin.scheduledAt!)}';
    return '$status$date';
  }

  String _date(DateTime value) =>
      '${value.day.toString().padLeft(2, '0')}/${value.month.toString().padLeft(2, '0')}/${value.year}';

  int get _todayCount => _pins
      .where((pin) =>
          pin.scheduledAt != null &&
          DateUtils.isSameDay(pin.scheduledAt, DateTime.now()))
      .length;
  int get _pendingCount => _pins.where((pin) => pin.status == 'pending').length;
  int get _completedCount =>
      _pins.where((pin) => pin.status == 'completed').length;
  int get _overdueCount => _pins
      .where((pin) =>
          pin.status == 'pending' &&
          pin.scheduledAt != null &&
          DateUtils.dateOnly(pin.scheduledAt!)
              .isBefore(DateUtils.dateOnly(DateTime.now())))
      .length;

  void _showMetrics() {
    showModalBottomSheet<void>(
      context: context,
      builder: (_) => SafeArea(
        child: Padding(
          padding: const EdgeInsets.all(20),
          child: Column(mainAxisSize: MainAxisSize.min, children: [
            Text('Resumen comercial',
                style: Theme.of(context).textTheme.titleLarge),
            const SizedBox(height: 16),
            Row(children: [
              _metric(Icons.today_outlined, 'Para hoy', _todayCount,
                  DoccionePalette.info),
              _metric(Icons.pending_actions_outlined, 'Pendientes',
                  _pendingCount, DoccionePalette.production),
            ]),
            const SizedBox(height: 12),
            Row(children: [
              _metric(Icons.check_circle_outline, 'Realizadas', _completedCount,
                  DoccionePalette.success),
              _metric(Icons.warning_amber_outlined, 'Vencidas', _overdueCount,
                  DoccionePalette.danger),
            ]),
          ]),
        ),
      ),
    );
  }

  Widget _metric(IconData icon, String label, int value, Color color) =>
      Expanded(
        child: Card(
            child: Padding(
                padding: const EdgeInsets.all(14),
                child: Column(children: [
                  Icon(icon, color: color),
                  const SizedBox(height: 6),
                  Text('$value',
                      style: Theme.of(context).textTheme.headlineSmall),
                  Text(label,
                      textAlign: TextAlign.center,
                      style: Theme.of(context).textTheme.bodySmall),
                ]))),
      );

  void _handleMapAction(_MapAction action) {
    switch (action) {
      case _MapAction.sync:
        _syncRemote();
        return;
      case _MapAction.route:
        _openDailyRoute();
        return;
      case _MapAction.metrics:
        _showMetrics();
        return;
      case _MapAction.headquarters:
        _centerOnHeadquarters();
        return;
      case _MapAction.fit:
        _fitRelevantPins();
        return;
      case _MapAction.agenda:
        _showAgenda();
        return;
    }
  }

  List<Marker> get _clusterMarkers =>
      VisitClusterer.cluster(_visiblePins, _mapZoom).map((cluster) {
        if (cluster.isSingle) return _marker(cluster.pins.single);
        return Marker(
          point: cluster.center,
          width: 58,
          height: 58,
          child: Tooltip(
            message: '${cluster.pins.length} visitas en esta zona',
            child: InkWell(
              onTap: () => _mapController.move(
                  cluster.center, (_mapZoom + 2).clamp(3, 18).toDouble()),
              customBorder: const CircleBorder(),
              child: DecoratedBox(
                decoration: BoxDecoration(
                  shape: BoxShape.circle,
                  color: DoccionePalette.wine,
                  border: Border.all(color: Colors.white, width: 3),
                  boxShadow: const [
                    BoxShadow(color: Colors.black26, blurRadius: 8),
                  ],
                ),
                child: Center(
                  child: Text('${cluster.pins.length}',
                      style: const TextStyle(
                          color: Colors.white, fontWeight: FontWeight.w800)),
                ),
              ),
            ),
          ),
        );
      }).toList();

  @override
  Widget build(BuildContext context) => Scaffold(
        appBar: AppBar(
          title: const Text('Mapa de visitas'),
          actions: [
            IconButton(
                onPressed: _searchVisits,
                icon: const Icon(Icons.search),
                tooltip: 'Buscar clientes, lugares o direcciones'),
            IconButton(
              onPressed: _showCommercialFilters,
              icon: Badge(
                isLabelVisible: _hasCommercialFilters,
                child: const Icon(Icons.tune),
              ),
              tooltip: 'Filtros comerciales',
            ),
            PopupMenuButton<_MapAction>(
              onSelected: _handleMapAction,
              itemBuilder: (_) => [
                PopupMenuItem(
                  value: _MapAction.sync,
                  enabled: !_syncing,
                  child: const ListTile(
                      leading: Icon(Icons.sync), title: Text('Sincronizar')),
                ),
                const PopupMenuItem(
                  value: _MapAction.route,
                  child: ListTile(
                      leading: Icon(Icons.route_outlined),
                      title: Text('Recorrido pendiente')),
                ),
                const PopupMenuItem(
                  value: _MapAction.metrics,
                  child: ListTile(
                      leading: Icon(Icons.insights_outlined),
                      title: Text('Resumen comercial')),
                ),
                const PopupMenuItem(
                  value: _MapAction.headquarters,
                  child: ListTile(
                      leading: Icon(Icons.storefront_outlined),
                      title: Text('Central Doccione')),
                ),
                const PopupMenuItem(
                  value: _MapAction.fit,
                  child: ListTile(
                      leading: Icon(Icons.zoom_out_map),
                      title: Text('Ver todos los puntos')),
                ),
                PopupMenuItem(
                  value: _MapAction.agenda,
                  child: ListTile(
                    leading: const Icon(Icons.list_alt_outlined),
                    title: Text('Agenda (${_visiblePins.length})'),
                  ),
                ),
              ],
            ),
          ],
        ),
        body: _loading
            ? const Center(child: CircularProgressIndicator())
            : Stack(children: [
                FlutterMap(
                  mapController: _mapController,
                  options: MapOptions(
                      initialCenter: _obera,
                      initialZoom: 13,
                      onPositionChanged: (camera, _) {
                        if ((camera.zoom - _mapZoom).abs() > .15) {
                          setState(() => _mapZoom = camera.zoom);
                        }
                      },
                      onTap: (_, point) {
                        if (!_saving) _editPin(point);
                      }),
                  children: [
                    TileLayer(
                        urlTemplate:
                            'https://tile.openstreetmap.org/{z}/{x}/{y}.png',
                        userAgentPackageName: 'com.doccione.mobile'),
                    MarkerLayer(markers: _clusterMarkers),
                    MarkerLayer(markers: [
                      Marker(
                        point: _headquarters,
                        width: 132,
                        height: 132,
                        child: GestureDetector(
                            onTap: _showHeadquarters,
                            child: _HeadquartersMarker(animation: _hqPulse)),
                      ),
                    ]),
                    if (_currentLocation != null)
                      MarkerLayer(markers: [
                        Marker(
                          point: _currentLocation!,
                          width: 44,
                          height: 44,
                          child: const Icon(
                            Icons.my_location,
                            color: DoccionePalette.info,
                            size: 32,
                          ),
                        ),
                      ]),
                  ],
                ),
                Positioned(
                    left: 12,
                    right: 12,
                    top: 12,
                    child: SingleChildScrollView(
                        scrollDirection: Axis.horizontal,
                        child: Row(
                            children: _VisitFilter.values
                                .map(_filterChip)
                                .toList()))),
                Positioned(
                  right: 16,
                  bottom: 90,
                  child: FloatingActionButton.small(
                    heroTag: 'visit-map-location',
                    tooltip: 'Ir a mi ubicación',
                    onPressed: _saving ? null : _centerOnCurrentLocation,
                    child: const Icon(Icons.gps_fixed),
                  ),
                ),
              ]),
        floatingActionButton: FloatingActionButton.extended(
          onPressed: _saving ? null : _addAtCurrentLocation,
          icon: _saving
              ? const SizedBox.square(
                  dimension: 18,
                  child: CircularProgressIndicator(strokeWidth: 2))
              : const Icon(Icons.my_location),
          label: const Text('Registrar visita actual'),
        ),
      );

  Marker _marker(VisitPin pin) => Marker(
        point: LatLng(pin.latitude, pin.longitude),
        width: 56,
        height: 56,
        child: Tooltip(
            message: '${pin.title}\n${_visitDetail(pin)}',
            child: IconButton(
                icon: Icon(Icons.location_on,
                    color: pin.syncConflict
                        ? DoccionePalette.danger
                        : pin.status == 'completed'
                            ? DoccionePalette.success
                            : DoccionePalette.wine,
                    size: 40),
                onPressed: () => _showPin(pin))),
      );

  Widget _filterChip(_VisitFilter filter) {
    const labels = {
      _VisitFilter.all: 'Todas',
      _VisitFilter.today: 'Hoy',
      _VisitFilter.pending: 'Pendientes',
      _VisitFilter.completed: 'Visitadas',
      _VisitFilter.overdue: 'Vencidas',
      _VisitFilter.stale: '+30 días sin contacto',
    };
    return Padding(
        padding: const EdgeInsets.only(right: 8),
        child: FilterChip(
            label: Text(labels[filter]!),
            selected: _filter == filter,
            onSelected: (_) => setState(() => _filter = filter)));
  }

  Future<void> _showAgenda() => showModalBottomSheet<void>(
        context: context,
        builder: (sheetContext) => SafeArea(
            child: SizedBox(
                height: 480,
                child: Column(children: [
                  ListTile(
                      title: Text('${_visiblePins.length} visitas'),
                      subtitle:
                          const Text('Tocá una visita para verla en el mapa')),
                  Expanded(
                      child: ListView.separated(
                          itemCount: _visiblePins.length,
                          separatorBuilder: (_, __) => const Divider(height: 1),
                          itemBuilder: (_, index) {
                            final pin = _visiblePins[index];
                            return ListTile(
                                leading: Icon(Icons.location_on,
                                    color: pin.status == 'completed'
                                        ? DoccionePalette.success
                                        : DoccionePalette.wine),
                                title: Text(pin.title),
                                subtitle: Text(_visitDetail(pin)),
                                onTap: () {
                                  _mapController.move(
                                      LatLng(pin.latitude, pin.longitude), 16);
                                  Navigator.pop(sheetContext);
                                },
                                trailing: const Icon(Icons.chevron_right));
                          })),
                ]))),
      );
}

class _CommercialFilterSelection {
  final String? clientId;
  final String? zone;
  final DateTimeRange? dateRange;
  final int staleDays;
  const _CommercialFilterSelection({
    this.clientId,
    this.zone,
    this.dateRange,
    this.staleDays = 0,
  });
}

class _CommercialFiltersSheet extends StatefulWidget {
  final List<Client> clients;
  final List<String> zones;
  final String? clientId;
  final String? zone;
  final DateTimeRange? dateRange;
  final int staleDays;
  const _CommercialFiltersSheet({
    required this.clients,
    required this.zones,
    this.clientId,
    this.zone,
    this.dateRange,
    required this.staleDays,
  });

  @override
  State<_CommercialFiltersSheet> createState() =>
      _CommercialFiltersSheetState();
}

class _CommercialFiltersSheetState extends State<_CommercialFiltersSheet> {
  String? _clientId;
  String? _zone;
  DateTimeRange? _dateRange;
  late int _staleDays;

  @override
  void initState() {
    super.initState();
    _clientId = widget.clientId;
    _zone = widget.zone;
    _dateRange = widget.dateRange;
    _staleDays = widget.staleDays;
  }

  Future<void> _pickRange() async {
    final range = await showDateRangePicker(
      context: context,
      firstDate: DateTime(2020),
      lastDate: DateTime(2100),
      initialDateRange: _dateRange,
    );
    if (range != null) setState(() => _dateRange = range);
  }

  void _returnSelection({bool clear = false}) => Navigator.pop(
        context,
        clear
            ? const _CommercialFilterSelection()
            : _CommercialFilterSelection(
                clientId: _clientId,
                zone: _zone,
                dateRange: _dateRange,
                staleDays: _staleDays,
              ),
      );

  @override
  Widget build(BuildContext context) => SafeArea(
        child: Padding(
          padding: const EdgeInsets.all(20),
          child: SingleChildScrollView(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.stretch,
              children: [
                Text('Filtros comerciales',
                    style: Theme.of(context).textTheme.titleLarge),
                const SizedBox(height: 16),
                DropdownButtonFormField<String?>(
                  initialValue: _clientId,
                  isExpanded: true,
                  decoration: const InputDecoration(labelText: 'Cliente'),
                  items: [
                    const DropdownMenuItem<String?>(
                        value: null, child: Text('Todos los clientes')),
                    ...widget.clients.map((client) => DropdownMenuItem<String?>(
                        value: client.id,
                        child: Text(client.name ?? 'Sin nombre'))),
                  ],
                  onChanged: (value) => setState(() => _clientId = value),
                ),
                const SizedBox(height: 12),
                DropdownButtonFormField<String?>(
                  initialValue: _zone,
                  decoration: const InputDecoration(labelText: 'Zona'),
                  items: [
                    const DropdownMenuItem<String?>(
                        value: null, child: Text('Todas las zonas')),
                    ...widget.zones.map((zone) => DropdownMenuItem<String?>(
                        value: zone, child: Text(zone))),
                  ],
                  onChanged: (value) => setState(() => _zone = value),
                ),
                const SizedBox(height: 12),
                OutlinedButton.icon(
                  onPressed: _pickRange,
                  icon: const Icon(Icons.date_range_outlined),
                  label: Text(_dateRange == null
                      ? 'Cualquier fecha programada'
                      : '${_shortDate(_dateRange!.start)} – ${_shortDate(_dateRange!.end)}'),
                ),
                if (_dateRange != null)
                  TextButton(
                    onPressed: () => setState(() => _dateRange = null),
                    child: const Text('Quitar rango de fechas'),
                  ),
                const SizedBox(height: 4),
                DropdownButtonFormField<int>(
                  initialValue: _staleDays,
                  decoration:
                      const InputDecoration(labelText: 'Sin contacto reciente'),
                  items: const [
                    DropdownMenuItem(value: 0, child: Text('Sin filtro')),
                    DropdownMenuItem(value: 15, child: Text('Más de 15 días')),
                    DropdownMenuItem(value: 30, child: Text('Más de 30 días')),
                    DropdownMenuItem(value: 60, child: Text('Más de 60 días')),
                    DropdownMenuItem(value: 90, child: Text('Más de 90 días')),
                  ],
                  onChanged: (value) => setState(() => _staleDays = value ?? 0),
                ),
                const SizedBox(height: 20),
                Row(children: [
                  Expanded(
                    child: OutlinedButton(
                      onPressed: () => _returnSelection(clear: true),
                      child: const Text('Limpiar'),
                    ),
                  ),
                  const SizedBox(width: 12),
                  Expanded(
                    child: FilledButton(
                      onPressed: _returnSelection,
                      child: const Text('Aplicar'),
                    ),
                  ),
                ]),
              ],
            ),
          ),
        ),
      );

  static String _shortDate(DateTime value) =>
      '${value.day.toString().padLeft(2, '0')}/${value.month.toString().padLeft(2, '0')}/${value.year}';
}

class _VisitSearch extends StatefulWidget {
  final List<VisitPin> pins;
  final List<Client> clients;
  final ValueChanged<VisitPin> onSelect;
  final ValueChanged<VisitAddressResult> onAddressSelect;
  const _VisitSearch({
    required this.pins,
    required this.clients,
    required this.onSelect,
    required this.onAddressSelect,
  });
  @override
  State<_VisitSearch> createState() => _VisitSearchState();
}

class _VisitSearchState extends State<_VisitSearch> {
  final _addressService = VisitAddressSearchService();
  Timer? _debounce;
  String _query = '';
  bool _searchingAddresses = false;
  List<VisitAddressResult> _addresses = const [];

  @override
  void dispose() {
    _debounce?.cancel();
    _addressService.close();
    super.dispose();
  }

  void _onQueryChanged(String value) {
    final query = value.trim();
    setState(() => _query = query);
    _debounce?.cancel();
    if (query.length < 3) {
      setState(() => _addresses = const []);
      return;
    }
    _debounce = Timer(const Duration(milliseconds: 500), () async {
      if (!mounted) return;
      setState(() => _searchingAddresses = true);
      try {
        final addresses = await _addressService.search(query);
        if (mounted && _query == query) setState(() => _addresses = addresses);
      } catch (_) {
        if (mounted && _query == query) setState(() => _addresses = const []);
      } finally {
        if (mounted) setState(() => _searchingAddresses = false);
      }
    });
  }

  Future<void> _selectClient(Client client) async {
    for (final pin in widget.pins) {
      if (pin.clientId == client.id) {
        widget.onSelect(pin);
        return;
      }
    }
    final address = client.address?.trim() ?? '';
    if (address.isEmpty) {
      ScaffoldMessenger.of(context).showSnackBar(
          const SnackBar(content: Text('Este cliente no tiene dirección.')));
      return;
    }
    setState(() => _searchingAddresses = true);
    try {
      final matches = await _addressService.search(address);
      if (matches.isNotEmpty) widget.onAddressSelect(matches.first);
    } finally {
      if (mounted) setState(() => _searchingAddresses = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final normalized = _query.toLowerCase();
    final matches = widget.pins
        .where((pin) => '${pin.title} ${pin.note ?? ''} ${pin.zone ?? ''}'
            .toLowerCase()
            .contains(normalized))
        .toList();
    final clients = widget.clients
        .where((client) =>
            '${client.name ?? ''} ${client.company ?? ''} ${client.address ?? ''}'
                .toLowerCase()
                .contains(normalized))
        .take(8)
        .toList();
    return SizedBox(
        height: MediaQuery.sizeOf(context).height * .68,
        child: Column(children: [
          TextField(
              autofocus: true,
              onChanged: _onQueryChanged,
              decoration: const InputDecoration(
                  labelText: 'Cliente, lugar o dirección',
                  prefixIcon: Icon(Icons.search))),
          if (_searchingAddresses) const LinearProgressIndicator(),
          Expanded(
            child: _query.isEmpty
                ? const Center(
                    child: Text('Escribí al menos tres letras para buscar.'))
                : ListView(children: [
                    if (matches.isNotEmpty)
                      const ListTile(
                          dense: true, title: Text('Visitas y lugares')),
                    ...matches.map((pin) => ListTile(
                          leading: const Icon(Icons.location_on_outlined),
                          title: Text(pin.title),
                          subtitle: Text(pin.note ?? pin.zone ?? 'Sin nota'),
                          onTap: () => widget.onSelect(pin),
                        )),
                    if (clients.isNotEmpty)
                      const ListTile(dense: true, title: Text('Clientes')),
                    ...clients.map((client) => ListTile(
                          leading: const Icon(Icons.person_search_outlined),
                          title: Text(client.name ?? 'Sin nombre'),
                          subtitle:
                              Text(client.address ?? client.company ?? ''),
                          onTap: () => _selectClient(client),
                        )),
                    if (_addresses.isNotEmpty)
                      const ListTile(dense: true, title: Text('Direcciones')),
                    ..._addresses.map((address) => ListTile(
                          leading: const Icon(Icons.map_outlined),
                          title: Text(address.label, maxLines: 2),
                          onTap: () => widget.onAddressSelect(address),
                        )),
                    if (!_searchingAddresses &&
                        matches.isEmpty &&
                        clients.isEmpty &&
                        _addresses.isEmpty)
                      const Padding(
                        padding: EdgeInsets.all(32),
                        child: Text('No encontramos coincidencias.',
                            textAlign: TextAlign.center),
                      ),
                  ]),
          ),
        ]));
  }
}

class _HeadquartersMarker extends StatelessWidget {
  final Animation<double> animation;
  const _HeadquartersMarker({required this.animation});

  @override
  Widget build(BuildContext context) => AnimatedBuilder(
        animation: animation,
        builder: (_, __) => Stack(
            alignment: Alignment.center,
            clipBehavior: Clip.none,
            children: [
              Container(
                  width: 76 + animation.value * 28,
                  height: 76 + animation.value * 28,
                  decoration: BoxDecoration(
                      shape: BoxShape.circle,
                      color: DoccionePalette.wine
                          .withValues(alpha: .10 + animation.value * .14))),
              Container(
                  width: 54,
                  height: 54,
                  decoration: BoxDecoration(
                      shape: BoxShape.circle,
                      color: DoccionePalette.wine,
                      border: Border.all(color: Colors.white, width: 3),
                      boxShadow: const [
                        BoxShadow(color: Colors.black45, blurRadius: 10)
                      ]),
                  child: const Icon(Icons.storefront,
                      color: Colors.white, size: 28)),
              const Positioned(
                  top: 88,
                  child: DecoratedBox(
                      decoration: BoxDecoration(
                          color: DoccionePalette.surface,
                          borderRadius: BorderRadius.all(Radius.circular(10))),
                      child: Padding(
                          padding:
                              EdgeInsets.symmetric(horizontal: 8, vertical: 4),
                          child: Text('Central Doccione',
                              style: TextStyle(
                                  fontSize: 11,
                                  fontWeight: FontWeight.w700))))),
            ]),
      );
}

class _VisitEditor extends StatefulWidget {
  final LatLng point;
  final VisitPin? pin;
  final List<Client> clients;
  const _VisitEditor({required this.point, required this.clients, this.pin});
  @override
  State<_VisitEditor> createState() => _VisitEditorState();
}

class _VisitEditorState extends State<_VisitEditor> {
  late final TextEditingController _title;
  late final TextEditingController _note;
  late final TextEditingController _zone;
  late final TextEditingController _result;
  Client? _client;
  late String _status;
  DateTime? _scheduledAt;

  @override
  void initState() {
    super.initState();
    final pin = widget.pin;
    _title = TextEditingController(text: pin?.title ?? '');
    _note = TextEditingController(text: pin?.note ?? '');
    _zone = TextEditingController(text: pin?.zone ?? '');
    _result = TextEditingController(text: pin?.result ?? '');
    _status = pin?.status ?? 'pending';
    _scheduledAt = pin?.scheduledAt;
    _client = widget.clients
        .where((client) => client.id == pin?.clientId)
        .cast<Client?>()
        .firstOrNull;
  }

  @override
  void dispose() {
    _title.dispose();
    _note.dispose();
    _zone.dispose();
    _result.dispose();
    super.dispose();
  }

  Future<void> _pickDate() async {
    final date = await showDatePicker(
        context: context,
        initialDate: _scheduledAt ?? DateTime.now(),
        firstDate: DateTime(2020),
        lastDate: DateTime(2100));
    if (date != null) setState(() => _scheduledAt = date);
  }

  void _save() {
    final title = _title.text.trim();
    if (title.isEmpty) return;
    Navigator.pop(
        context,
        VisitPin(
            id: widget.pin?.id,
            title: title,
            note: _note.text.trim().isEmpty ? null : _note.text.trim(),
            latitude: widget.point.latitude,
            longitude: widget.point.longitude,
            createdAt: widget.pin?.createdAt ?? DateTime.now(),
            updatedAt: DateTime.now(),
            status: _status,
            scheduledAt: _scheduledAt,
            clientId: _client?.id,
            clientPhone: _client?.phone,
            clientUuid: widget.pin?.clientUuid ??
                'visit-${DateTime.now().microsecondsSinceEpoch}',
            syncDirty: true,
            serverVersion: widget.pin?.serverVersion ?? 0,
            syncConflict: false,
            zone: _zone.text.trim().isEmpty ? null : _zone.text.trim(),
            result: _result.text.trim().isEmpty ? null : _result.text.trim(),
            lastContactAt: _status == 'completed'
                ? widget.pin?.lastContactAt ?? DateTime.now()
                : widget.pin?.lastContactAt));
  }

  @override
  Widget build(BuildContext context) => Padding(
      padding: EdgeInsets.fromLTRB(
          20, 20, 20, 20 + MediaQuery.viewInsetsOf(context).bottom),
      child: SingleChildScrollView(
          child: Column(
              mainAxisSize: MainAxisSize.min,
              crossAxisAlignment: CrossAxisAlignment.stretch,
              children: [
            Text(widget.pin == null ? 'Agendar visita' : 'Editar visita',
                style: Theme.of(context).textTheme.titleLarge),
            const SizedBox(height: 16),
            DropdownButtonFormField<Client?>(
                initialValue: _client,
                decoration:
                    const InputDecoration(labelText: 'Cliente (opcional)'),
                items: [
                  const DropdownMenuItem<Client?>(
                      value: null, child: Text('Sin asociar')),
                  ...widget.clients.map((client) => DropdownMenuItem<Client?>(
                      value: client, child: Text(client.name ?? 'Sin nombre')))
                ],
                onChanged: (client) => setState(() {
                      _client = client;
                      if (client?.name != null && _title.text.trim().isEmpty) {
                        _title.text = client!.name!;
                      }
                    })),
            const SizedBox(height: 12),
            TextField(
                controller: _title,
                autofocus: true,
                decoration:
                    const InputDecoration(labelText: 'Lugar o cliente *')),
            const SizedBox(height: 12),
            TextField(
                controller: _zone,
                decoration: const InputDecoration(
                    labelText: 'Zona comercial',
                    prefixIcon: Icon(Icons.map_outlined))),
            const SizedBox(height: 12),
            DropdownButtonFormField<String>(
                initialValue: _status,
                decoration: const InputDecoration(labelText: 'Estado'),
                items: const [
                  DropdownMenuItem(value: 'pending', child: Text('Pendiente')),
                  DropdownMenuItem(value: 'completed', child: Text('Visitada'))
                ],
                onChanged: (value) => setState(() => _status = value!)),
            const SizedBox(height: 12),
            OutlinedButton.icon(
                onPressed: _pickDate,
                icon: const Icon(Icons.calendar_today_outlined),
                label: Text(_scheduledAt == null
                    ? 'Programar para una fecha'
                    : 'Programada: ${_scheduledAt!.day.toString().padLeft(2, '0')}/${_scheduledAt!.month.toString().padLeft(2, '0')}/${_scheduledAt!.year}')),
            TextButton(
                onPressed: _scheduledAt == null
                    ? null
                    : () => setState(() => _scheduledAt = null),
                child: const Text('Quitar fecha programada')),
            TextField(
                controller: _note,
                maxLines: 3,
                decoration: const InputDecoration(
                    labelText: 'Resultado o próxima acción')),
            const SizedBox(height: 12),
            TextField(
                controller: _result,
                maxLines: 2,
                decoration:
                    const InputDecoration(labelText: 'Resultado comercial')),
            const SizedBox(height: 20),
            FilledButton(onPressed: _save, child: const Text('Guardar visita')),
          ])));
}
