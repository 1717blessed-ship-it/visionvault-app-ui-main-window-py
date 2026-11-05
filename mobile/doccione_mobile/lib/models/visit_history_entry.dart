class VisitHistoryEntry {
  final int? id;
  final String eventUuid;
  final String clientUuid;
  final String action;
  final String? note;
  final DateTime createdAt;
  final bool syncDirty;

  const VisitHistoryEntry({
    this.id,
    required this.eventUuid,
    required this.clientUuid,
    required this.action,
    this.note,
    required this.createdAt,
    this.syncDirty = true,
  });

  Map<String, Object?> toMap() => {
        'id': id,
        'event_uuid': eventUuid,
        'client_uuid': clientUuid,
        'action': action,
        'note': note,
        'created_at': createdAt.toUtc().toIso8601String(),
        'sync_dirty': syncDirty ? 1 : 0,
      };

  Map<String, Object?> toJson() => {
        'event_uuid': eventUuid,
        'client_uuid': clientUuid,
        'action': action,
        'note': note,
        'created_at': createdAt.toUtc().toIso8601String(),
      };

  factory VisitHistoryEntry.fromMap(Map<String, Object?> map) =>
      VisitHistoryEntry(
        id: map['id'] as int?,
        eventUuid: map['event_uuid'] as String,
        clientUuid: map['client_uuid'] as String,
        action: map['action'] as String,
        note: map['note'] as String?,
        createdAt: DateTime.parse(map['created_at'] as String).toLocal(),
        syncDirty: (map['sync_dirty'] as int? ?? 0) == 1,
      );

  VisitHistoryEntry copyWith({bool? syncDirty}) => VisitHistoryEntry(
        id: id,
        eventUuid: eventUuid,
        clientUuid: clientUuid,
        action: action,
        note: note,
        createdAt: createdAt,
        syncDirty: syncDirty ?? this.syncDirty,
      );
}
