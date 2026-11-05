import 'dart:io';

import 'package:image_picker/image_picker.dart';
import 'package:path/path.dart' as path;
import 'package:path_provider/path_provider.dart';

import '../models/visit_attachment.dart';

class VisitAttachmentService {
  final ImagePicker _picker;
  VisitAttachmentService({ImagePicker? picker})
      : _picker = picker ?? ImagePicker();

  Future<VisitAttachment?> pick({
    required String clientUuid,
    required ImageSource source,
  }) async {
    final selected = await _picker.pickImage(
      source: source,
      imageQuality: 82,
      maxWidth: 2200,
    );
    if (selected == null) return null;
    final id = 'attachment-${DateTime.now().microsecondsSinceEpoch}';
    final extension = path.extension(selected.path).toLowerCase();
    final safeExtension = {'.jpg', '.jpeg', '.png', '.webp'}.contains(extension)
        ? extension
        : '.jpg';
    final directory = Directory(path.join(
      (await getApplicationDocumentsDirectory()).path,
      'visit_attachments',
    ));
    await directory.create(recursive: true);
    final stored = await File(selected.path)
        .copy(path.join(directory.path, '$id$safeExtension'));
    return VisitAttachment(
      attachmentUuid: id,
      clientUuid: clientUuid,
      localPath: stored.path,
      fileName: path.basename(stored.path),
      mimeType: _mimeType(safeExtension),
      createdAt: DateTime.now(),
    );
  }

  Future<String> storeDownloaded({
    required String attachmentUuid,
    required String fileName,
    required List<int> bytes,
  }) async {
    final directory = Directory(path.join(
      (await getApplicationDocumentsDirectory()).path,
      'visit_attachments',
    ));
    await directory.create(recursive: true);
    final extension = path.extension(fileName).toLowerCase();
    final stored = File(path.join(directory.path, '$attachmentUuid$extension'));
    await stored.writeAsBytes(bytes, flush: true);
    return stored.path;
  }

  String _mimeType(String extension) => switch (extension) {
        '.png' => 'image/png',
        '.webp' => 'image/webp',
        _ => 'image/jpeg',
      };
}
