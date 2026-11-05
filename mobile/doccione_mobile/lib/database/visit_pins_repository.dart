import 'dart:convert';

import 'package:sqflite/sqflite.dart';

import '../models/visit_attachment.dart';
import '../models/visit_history_entry.dart';
import '../models/visit_pin.dart';
import 'database_helper.dart';

class VisitPinsRepository {
  final DatabaseHelper? _dbHelper;
  final Database? _databaseOverride;

  VisitPinsRepository(DatabaseHelper dbHelper)
      : _dbHelper = dbHelper,
        _databaseOverride = null;

  VisitPinsRepository.forDatabase(Database database)
      : _dbHelper = null,
        _databaseOverride = database;

  Future<Database> get _database async =>
      _databaseOverride ?? await _dbHelper!.database;

  Future<List<VisitPin>> getAll() async {
    final db = await _database;
    final rows = await db.query('visit_pins',
        where: 'deleted = 0', orderBy: 'created_at DESC');
    return rows.map((row) => VisitPin.fromMap(row)).toList();
  }

  Future<void> add(VisitPin pin) async {
    final db = await _database;
    final values = pin.toMap()..remove('id');
    await db.insert('visit_pins', values);
  }

  Future<void> update(VisitPin pin) async {
    final db = await _database;
    final values = pin.toMap()..remove('id');
    await db.update('visit_pins', values, where: 'id = ?', whereArgs: [pin.id]);
  }

  Future<VisitPin?> getByUuid(String clientUuid) async {
    final db = await _database;
    final rows = await db.query('visit_pins',
        where: 'client_uuid = ?', whereArgs: [clientUuid], limit: 1);
    return rows.isEmpty ? null : VisitPin.fromMap(rows.first);
  }

  Future<List<VisitPin>> getDirty() async {
    final db = await _database;
    final rows = await db.query('visit_pins', where: 'sync_dirty = 1');
    return rows.map((row) => VisitPin.fromMap(row)).toList();
  }

  Future<void> upsertByUuid(VisitPin pin) async {
    final db = await _database;
    final existing = await db.query('visit_pins',
        columns: ['id', 'sync_dirty', 'sync_conflict'],
        where: 'client_uuid = ?',
        whereArgs: [pin.clientUuid],
        limit: 1);
    if (existing.isEmpty) {
      await add(pin.copyWith(syncDirty: false));
      return;
    }
    if ((existing.first['sync_dirty'] as int? ?? 0) == 1 ||
        (existing.first['sync_conflict'] as int? ?? 0) == 1) {
      return;
    }
    final values = pin.copyWith(syncDirty: false).toMap()..remove('id');
    await db.update('visit_pins', values,
        where: 'id = ?', whereArgs: [existing.first['id']]);
  }

  Future<void> markSynced(VisitPin remote) async {
    final db = await _database;
    final existing = await db.query('visit_pins',
        columns: ['id'],
        where: 'client_uuid = ?',
        whereArgs: [remote.clientUuid],
        limit: 1);
    final clean = remote.copyWith(
      syncDirty: false,
      syncConflict: false,
      clearConflictPayload: true,
    );
    if (existing.isEmpty) {
      await add(clean);
      return;
    }
    final values = clean.toMap()..remove('id');
    await db.update('visit_pins', values,
        where: 'id = ?', whereArgs: [existing.first['id']]);
  }

  Future<void> markConflict(VisitPin local, VisitPin remote) async {
    await update(local.copyWith(
      syncConflict: true,
      conflictPayload: jsonEncode(remote.toMap()),
    ));
  }

  VisitPin? conflictRemote(VisitPin pin) {
    if (pin.conflictPayload == null) return null;
    try {
      return VisitPin.fromMap(
          Map<String, Object?>.from(jsonDecode(pin.conflictPayload!) as Map));
    } catch (_) {
      return null;
    }
  }

  Future<void> delete(int id) async {
    final db = await _database;
    await db.delete('visit_pins', where: 'id = ?', whereArgs: [id]);
  }

  Future<void> markDeleted(VisitPin pin) async {
    await update(pin.copyWith(deleted: true, syncDirty: true));
  }

  Future<VisitHistoryEntry> addHistory(String clientUuid, String action,
      [String? note]) async {
    final db = await _database;
    final entry = VisitHistoryEntry(
      eventUuid: 'history-${DateTime.now().microsecondsSinceEpoch}',
      clientUuid: clientUuid,
      action: action,
      note: note,
      createdAt: DateTime.now(),
    );
    final values = entry.toMap()..remove('id');
    await db.insert('visit_history', values);
    return entry;
  }

  Future<List<VisitHistoryEntry>> history(String clientUuid) async {
    final db = await _database;
    final rows = await db.query('visit_history',
        where: 'client_uuid = ?',
        whereArgs: [clientUuid],
        orderBy: 'created_at DESC');
    return rows.map(VisitHistoryEntry.fromMap).toList();
  }

  Future<List<VisitHistoryEntry>> getDirtyHistory() async {
    final db = await _database;
    final rows = await db.query('visit_history', where: 'sync_dirty = 1');
    return rows.map(VisitHistoryEntry.fromMap).toList();
  }

  Future<void> markHistorySynced(String eventUuid) async {
    final db = await _database;
    await db.update('visit_history', {'sync_dirty': 0},
        where: 'event_uuid = ?', whereArgs: [eventUuid]);
  }

  Future<void> upsertHistory(VisitHistoryEntry entry) async {
    final db = await _database;
    final values = entry.copyWith(syncDirty: false).toMap()..remove('id');
    await db.insert('visit_history', values,
        conflictAlgorithm: ConflictAlgorithm.ignore);
  }

  Future<List<VisitAttachment>> attachments(String clientUuid) async {
    final db = await _database;
    final rows = await db.query('visit_attachments',
        where: 'client_uuid = ? AND deleted = 0',
        whereArgs: [clientUuid],
        orderBy: 'created_at DESC');
    return rows.map(VisitAttachment.fromMap).toList();
  }

  Future<List<VisitAttachment>> dirtyAttachments() async {
    final db = await _database;
    final rows = await db.query('visit_attachments', where: 'sync_dirty = 1');
    return rows.map(VisitAttachment.fromMap).toList();
  }

  Future<void> addAttachment(VisitAttachment attachment) async {
    final db = await _database;
    final values = attachment.toMap()..remove('id');
    await db.insert('visit_attachments', values,
        conflictAlgorithm: ConflictAlgorithm.replace);
  }

  Future<void> markAttachmentSynced(String attachmentUuid) async {
    final db = await _database;
    await db.update('visit_attachments', {'sync_dirty': 0},
        where: 'attachment_uuid = ?', whereArgs: [attachmentUuid]);
  }

  Future<bool> hasAttachment(String attachmentUuid) async {
    final db = await _database;
    final rows = await db.query('visit_attachments',
        columns: ['id'],
        where: 'attachment_uuid = ?',
        whereArgs: [attachmentUuid],
        limit: 1);
    return rows.isNotEmpty;
  }

  Future<bool> shouldShowOverdueReminder(String dayKey) async {
    final db = await _database;
    final rows = await db.query('visit_reminder_state',
        where: 'key = ?', whereArgs: ['overdue_last_day'], limit: 1);
    return rows.isEmpty || rows.first['value'] != dayKey;
  }

  Future<void> markOverdueReminderShown(String dayKey) async {
    final db = await _database;
    await db.insert(
        'visit_reminder_state', {'key': 'overdue_last_day', 'value': dayKey},
        conflictAlgorithm: ConflictAlgorithm.replace);
  }
}
