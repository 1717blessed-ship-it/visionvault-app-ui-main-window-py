class VisitAttachment {
  final int? id;
  final String attachmentUuid;
  final String clientUuid;
  final String localPath;
  final String fileName;
  final String mimeType;
  final DateTime createdAt;
  final bool syncDirty;
  final bool deleted;

  const VisitAttachment({
    this.id,
    required this.attachmentUuid,
    required this.clientUuid,
    required this.localPath,
    required this.fileName,
    required this.mimeType,
    required this.createdAt,
    this.syncDirty = true,
    this.deleted = false,
  });

  Map<String, Object?> toMap() => {
        'id': id,
        'attachment_uuid': attachmentUuid,
        'client_uuid': clientUuid,
        'local_path': localPath,
        'file_name': fileName,
        'mime_type': mimeType,
        'created_at': createdAt.toUtc().toIso8601String(),
        'sync_dirty': syncDirty ? 1 : 0,
        'deleted': deleted ? 1 : 0,
      };

  factory VisitAttachment.fromMap(Map<String, Object?> map) => VisitAttachment(
        id: map['id'] as int?,
        attachmentUuid: map['attachment_uuid'] as String,
        clientUuid: map['client_uuid'] as String,
        localPath: map['local_path'] as String? ?? '',
        fileName: map['file_name'] as String,
        mimeType: map['mime_type'] as String,
        createdAt: DateTime.parse(map['created_at'] as String).toLocal(),
        syncDirty: (map['sync_dirty'] as int? ?? 0) == 1,
        deleted: (map['deleted'] as int? ?? 0) == 1,
      );

  VisitAttachment copyWith({
    String? localPath,
    bool? syncDirty,
    bool? deleted,
  }) =>
      VisitAttachment(
        id: id,
        attachmentUuid: attachmentUuid,
        clientUuid: clientUuid,
        localPath: localPath ?? this.localPath,
        fileName: fileName,
        mimeType: mimeType,
        createdAt: createdAt,
        syncDirty: syncDirty ?? this.syncDirty,
        deleted: deleted ?? this.deleted,
      );
}
