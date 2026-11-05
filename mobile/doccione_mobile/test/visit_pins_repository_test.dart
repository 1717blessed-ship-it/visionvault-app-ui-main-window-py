import 'package:doccione_mobile/database/visit_pins_repository.dart';
import 'package:doccione_mobile/models/visit_history_entry.dart';
import 'package:doccione_mobile/models/visit_pin.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:sqflite_common_ffi/sqflite_ffi.dart';

void main() {
  late Database db;
  late VisitPinsRepository repository;

  setUpAll(sqfliteFfiInit);

  setUp(() async {
    db = await databaseFactoryFfi.openDatabase(inMemoryDatabasePath);
    await db.execute('''CREATE TABLE visit_pins (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      title TEXT NOT NULL, note TEXT, latitude REAL NOT NULL,
      longitude REAL NOT NULL, created_at TEXT NOT NULL,
      status TEXT NOT NULL, scheduled_at TEXT, client_id TEXT,
      client_phone TEXT, client_uuid TEXT NOT NULL UNIQUE,
      sync_dirty INTEGER NOT NULL, deleted INTEGER NOT NULL,
      updated_at TEXT NOT NULL, server_version INTEGER NOT NULL,
      sync_conflict INTEGER NOT NULL, conflict_payload TEXT,
      zone TEXT, result TEXT, last_contact_at TEXT
    )''');
    await db.execute('''CREATE TABLE visit_history (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      event_uuid TEXT NOT NULL UNIQUE, client_uuid TEXT NOT NULL,
      action TEXT NOT NULL, note TEXT, created_at TEXT NOT NULL,
      sync_dirty INTEGER NOT NULL
    )''');
    await db.execute('''CREATE TABLE visit_attachments (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      attachment_uuid TEXT NOT NULL UNIQUE, client_uuid TEXT NOT NULL,
      local_path TEXT NOT NULL, file_name TEXT NOT NULL,
      mime_type TEXT NOT NULL, created_at TEXT NOT NULL,
      sync_dirty INTEGER NOT NULL, deleted INTEGER NOT NULL
    )''');
    await db.execute('''CREATE TABLE visit_reminder_state (
      key TEXT PRIMARY KEY, value TEXT NOT NULL
    )''');
    repository = VisitPinsRepository.forDatabase(db);
  });

  tearDown(() => db.close());

  VisitPin pin({int? id, int version = 0}) => VisitPin(
        id: id,
        title: 'Cliente Norte',
        latitude: -27.48,
        longitude: -55.11,
        createdAt: DateTime(2026, 8, 12),
        updatedAt: DateTime(2026, 8, 12),
        clientUuid: 'visit-1',
        serverVersion: version,
      );

  test('el borrado offline conserva un tombstone sucio hasta sincronizar',
      () async {
    await repository.add(pin());
    final stored = (await repository.getAll()).single;

    await repository.markDeleted(stored);

    expect(await repository.getAll(), isEmpty);
    final dirty = await repository.getDirty();
    expect(dirty, hasLength(1));
    expect(dirty.single.deleted, isTrue);
    expect(dirty.single.syncDirty, isTrue);
  });

  test('el historial se marca sincronizado y evita eventos duplicados',
      () async {
    final local = await repository.addHistory(
        'visit-1', 'Visita realizada', 'Pedido confirmado');
    expect(await repository.getDirtyHistory(), hasLength(1));

    await repository.markHistorySynced(local.eventUuid);
    expect(await repository.getDirtyHistory(), isEmpty);

    final remote = VisitHistoryEntry(
      eventUuid: 'remote-event-1',
      clientUuid: 'visit-1',
      action: 'Foto agregada',
      createdAt: DateTime(2026, 8, 12, 10),
      syncDirty: false,
    );
    await repository.upsertHistory(remote);
    await repository.upsertHistory(remote);
    expect(await repository.history('visit-1'), hasLength(2));
  });

  test('un conflicto conserva la copia local y expone la versión remota',
      () async {
    await repository.add(pin(version: 1));
    final local = (await repository.getAll()).single;
    final remote = pin(version: 2).copyWith(
      title: 'Cliente actualizado en otro teléfono',
      syncDirty: false,
    );

    await repository.markConflict(local, remote);

    final conflicted = (await repository.getAll()).single;
    expect(conflicted.syncConflict, isTrue);
    expect(conflicted.syncDirty, isTrue);
    expect(repository.conflictRemote(conflicted)?.serverVersion, 2);
    expect(repository.conflictRemote(conflicted)?.title,
        'Cliente actualizado en otro teléfono');
  });
}
