import 'dart:io';

import 'package:doccione_mobile/models/mockup_reference.dart';
import 'package:flutter_test/flutter_test.dart';

void main() {
  test('serializa todos los datos que Studio necesita', () {
    final mockup = MockupReference(
      file: File('mockup.png'),
      designId: 'design-1',
      designName: 'Logo',
      sizeCm: 12,
      surface: MockupSurface.bottle,
      material: 'Vinilo transparente',
      comment: 'Centrar con la etiqueta',
      approval: MockupApproval.changesRequested,
      curved: true,
      createdAt: DateTime.utc(2026, 8, 13, 1, 2, 3),
    );

    expect(mockup.toUploadJson(), {
      'file_name': 'mockup.png',
      'design_id': 'design-1',
      'design_name': 'Logo',
      'size_cm': 12.0,
      'surface': 'bottle',
      'surface_label': 'Botella',
      'material': 'Vinilo transparente',
      'comment': 'Centrar con la etiqueta',
      'approval': 'changesRequested',
      'approval_label': 'Requiere cambios',
      'curved': true,
      'created_at': '2026-08-13T01:02:03.000Z',
    });
  });

  test('restaura un mockup de la cola sin conexion', () {
    final file = File('pending/mockup.jpg');
    final mockup = MockupReference.fromQueuedJson({
      'design_id': 'design-2',
      'design_name': 'Marca',
      'size_cm': 7,
      'surface': 'notebook',
      'material': 'Vinilo mate',
      'comment': 'Tapa frontal',
      'approval': 'approved',
      'curved': false,
      'created_at': '2026-08-13T03:00:00Z',
    }, file: file);

    expect(mockup.file.path, file.path);
    expect(mockup.surface, MockupSurface.notebook);
    expect(mockup.approval, MockupApproval.approved);
    expect(mockup.sizeCm, 7);
    expect(mockup.comment, 'Tapa frontal');
  });
}
