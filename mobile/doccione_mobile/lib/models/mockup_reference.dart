import 'dart:io';

import 'package:path/path.dart' as path;

enum MockupSurface {
  floor('Piso'),
  wall('Pared'),
  notebook('Cuaderno'),
  box('Caja'),
  glass('Vaso'),
  bottle('Botella'),
  other('Otra');

  const MockupSurface(this.label);
  final String label;
}

enum MockupApproval {
  pending('Pendiente'),
  approved('Aprobado'),
  changesRequested('Requiere cambios');

  const MockupApproval(this.label);
  final String label;
}

class MockupReference {
  const MockupReference({
    required this.file,
    required this.designId,
    required this.designName,
    required this.sizeCm,
    required this.surface,
    required this.material,
    required this.comment,
    required this.approval,
    required this.curved,
    required this.createdAt,
  });

  final File file;
  final String designId;
  final String designName;
  final double sizeCm;
  final MockupSurface surface;
  final String material;
  final String comment;
  final MockupApproval approval;
  final bool curved;
  final DateTime createdAt;

  MockupReference copyWith({
    File? file,
    String? designId,
    String? designName,
    double? sizeCm,
    MockupSurface? surface,
    String? material,
    String? comment,
    MockupApproval? approval,
    bool? curved,
    DateTime? createdAt,
  }) =>
      MockupReference(
        file: file ?? this.file,
        designId: designId ?? this.designId,
        designName: designName ?? this.designName,
        sizeCm: sizeCm ?? this.sizeCm,
        surface: surface ?? this.surface,
        material: material ?? this.material,
        comment: comment ?? this.comment,
        approval: approval ?? this.approval,
        curved: curved ?? this.curved,
        createdAt: createdAt ?? this.createdAt,
      );

  Map<String, Object?> toUploadJson({String? storedPath}) => {
        'file_name': path.basename(storedPath ?? file.path),
        'design_id': designId,
        'design_name': designName,
        'size_cm': sizeCm,
        'surface': surface.name,
        'surface_label': surface.label,
        'material': material,
        'comment': comment,
        'approval': approval.name,
        'approval_label': approval.label,
        'curved': curved,
        'created_at': createdAt.toUtc().toIso8601String(),
      };

  factory MockupReference.fromQueuedJson(
    Map<String, dynamic> json, {
    required File file,
  }) =>
      MockupReference(
        file: file,
        designId: json['design_id']?.toString() ?? '',
        designName: json['design_name']?.toString() ?? 'Diseño',
        sizeCm: (json['size_cm'] as num? ?? 10).toDouble(),
        surface: MockupSurface.values.firstWhere(
          (value) => value.name == json['surface'],
          orElse: () => MockupSurface.other,
        ),
        material: json['material']?.toString() ?? 'Sin especificar',
        comment: json['comment']?.toString() ?? '',
        approval: MockupApproval.values.firstWhere(
          (value) => value.name == json['approval'],
          orElse: () => MockupApproval.pending,
        ),
        curved: json['curved'] == true,
        createdAt: DateTime.tryParse(json['created_at']?.toString() ?? '') ??
            DateTime.now().toUtc(),
      );
}
