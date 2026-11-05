class VisitPin {
  final int? id;
  final String title;
  final String? note;
  final double latitude;
  final double longitude;
  final DateTime createdAt;
  final String status;
  final DateTime? scheduledAt;
  final String? clientId;
  final String? clientPhone;
  final String clientUuid;
  final bool syncDirty;
  final bool deleted;
  final DateTime updatedAt;
  final int serverVersion;
  final bool syncConflict;
  final String? conflictPayload;
  final String? zone;
  final String? result;
  final DateTime? lastContactAt;

  const VisitPin({
    this.id,
    required this.title,
    this.note,
    required this.latitude,
    required this.longitude,
    required this.createdAt,
    this.status = 'pending',
    this.scheduledAt,
    this.clientId,
    this.clientPhone,
    required this.clientUuid,
    this.syncDirty = true,
    this.deleted = false,
    DateTime? updatedAt,
    this.serverVersion = 0,
    this.syncConflict = false,
    this.conflictPayload,
    this.zone,
    this.result,
    this.lastContactAt,
  }) : updatedAt = updatedAt ?? createdAt;

  Map<String, Object?> toMap() => {
        'id': id,
        'title': title,
        'note': note,
        'latitude': latitude,
        'longitude': longitude,
        'created_at': createdAt.toUtc().toIso8601String(),
        'status': status,
        'scheduled_at': scheduledAt?.toUtc().toIso8601String(),
        'client_id': clientId,
        'client_phone': clientPhone,
        'client_uuid': clientUuid,
        'sync_dirty': syncDirty ? 1 : 0,
        'deleted': deleted ? 1 : 0,
        'updated_at': updatedAt.toUtc().toIso8601String(),
        'server_version': serverVersion,
        'sync_conflict': syncConflict ? 1 : 0,
        'conflict_payload': conflictPayload,
        'zone': zone,
        'result': result,
        'last_contact_at': lastContactAt?.toUtc().toIso8601String(),
      };

  factory VisitPin.fromMap(Map<String, Object?> map) => VisitPin(
        id: map['id'] as int?,
        title: map['title'] as String,
        note: map['note'] as String?,
        latitude: (map['latitude'] as num).toDouble(),
        longitude: (map['longitude'] as num).toDouble(),
        createdAt: DateTime.parse(map['created_at'] as String).toLocal(),
        status: (map['status'] as String?) ?? 'pending',
        scheduledAt: map['scheduled_at'] == null
            ? null
            : DateTime.parse(map['scheduled_at'] as String).toLocal(),
        clientId: map['client_id'] as String?,
        clientPhone: map['client_phone'] as String?,
        clientUuid: (map['client_uuid'] as String?) ?? 'legacy-${map['id']}',
        syncDirty: (map['sync_dirty'] as int? ?? 1) == 1,
        deleted: (map['deleted'] as int? ?? 0) == 1,
        updatedAt: map['updated_at'] == null
            ? DateTime.parse(map['created_at'] as String).toLocal()
            : DateTime.parse(map['updated_at'] as String).toLocal(),
        serverVersion: (map['server_version'] as num?)?.toInt() ??
            (map['version'] as num?)?.toInt() ??
            0,
        syncConflict: (map['sync_conflict'] as int? ?? 0) == 1,
        conflictPayload: map['conflict_payload'] as String?,
        zone: map['zone'] as String?,
        result: map['result'] as String?,
        lastContactAt: map['last_contact_at'] == null
            ? null
            : DateTime.parse(map['last_contact_at'] as String).toLocal(),
      );

  VisitPin copyWith({
    String? title,
    String? note,
    String? status,
    DateTime? scheduledAt,
    bool clearScheduledAt = false,
    String? clientId,
    String? clientPhone,
    String? clientUuid,
    bool? syncDirty,
    bool? deleted,
    DateTime? updatedAt,
    int? serverVersion,
    bool? syncConflict,
    String? conflictPayload,
    bool clearConflictPayload = false,
    String? zone,
    String? result,
    DateTime? lastContactAt,
  }) =>
      VisitPin(
        id: id,
        title: title ?? this.title,
        note: note ?? this.note,
        latitude: latitude,
        longitude: longitude,
        createdAt: createdAt,
        status: status ?? this.status,
        scheduledAt: clearScheduledAt ? null : scheduledAt ?? this.scheduledAt,
        clientId: clientId ?? this.clientId,
        clientPhone: clientPhone ?? this.clientPhone,
        clientUuid: clientUuid ?? this.clientUuid,
        syncDirty: syncDirty ?? this.syncDirty,
        deleted: deleted ?? this.deleted,
        updatedAt: updatedAt ?? this.updatedAt,
        serverVersion: serverVersion ?? this.serverVersion,
        syncConflict: syncConflict ?? this.syncConflict,
        conflictPayload: clearConflictPayload
            ? null
            : conflictPayload ?? this.conflictPayload,
        zone: zone ?? this.zone,
        result: result ?? this.result,
        lastContactAt: lastContactAt ?? this.lastContactAt,
      );
}
