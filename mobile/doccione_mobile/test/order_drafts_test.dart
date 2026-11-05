import 'dart:convert';
import 'package:flutter_test/flutter_test.dart';
import 'package:sqflite_common_ffi/sqflite_ffi.dart';
import 'package:doccione_mobile/models/order_draft.dart';
import 'package:doccione_mobile/database/database_helper.dart';
import 'package:doccione_mobile/database/order_drafts_repository.dart';

OrderWork work(
        {int quantity = 100,
        String unit = 'units',
        List<DesignAllocation> designs = const []}) =>
    OrderWork(
        productCode: 'real-code-fixture',
        productName: 'Producto de prueba',
        quantity: quantity,
        unitKind: unit,
        designs: designs);
DesignAllocation design(String id, int quantity) =>
    DesignAllocation(designId: id, name: id, quantity: quantity);

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();
  setUpAll(() {
    sqfliteFfiInit();
    databaseFactory = databaseFactoryFfi;
  });
  group('Validación local, sin simular presupuesto ni producción', () {
    test('distribución completa 40/35/25', () {
      final job =
          work(designs: [design('a', 40), design('b', 35), design('c', 25)]);
      job.validate();
      expect(job.assigned, 100);
      expect(job.pending, 0);
    });
    test('distribución parcial conserva pendientes', () {
      final job = work(designs: [design('a', 20)]);
      job.validate();
      expect(job.pending, 80);
    });
    test('bloquea sobreasignación, duplicados y cero', () {
      expect(() => work(designs: [design('a', 101)]).validate(),
          throwsArgumentError);
      expect(() => work(designs: [design('a', 1), design('a', 1)]).validate(),
          throwsArgumentError);
      expect(() => work(designs: [design('a', 0)]).validate(),
          throwsArgumentError);
      expect(() => work(quantity: 0).validate(), throwsArgumentError);
      expect(() => work(unit: 'kg').validate(), throwsArgumentError);
    });
    test('mantiene hojas y unidades, sin conversión ni suma global', () {
      final draft = OrderDraft(
          jobs: [work(unit: 'sheets', quantity: 2), work(quantity: 100)]);
      final restored = OrderDraft.fromJson(
          jsonDecode(jsonEncode(draft.toJson())) as Map<String, dynamic>);
      expect(restored.jobs.map((j) => j.unitKind), ['sheets', 'units']);
      expect(restored.jobs.map((j) => j.quantity), [2, 100]);
      expect(restored.toJson()['desktop_confirmed'], false);
      expect(restored.jobs.first.toJson()['price_status'],
          'requires_desktop_quote');
    });
  });
  group('Persistencia atómica y privada por vendedor', () {
    late DatabaseHelper helper;
    late OrderDraftsRepository repo;
    setUp(() async {
      helper = DatabaseHelper();
      await helper.deleteDatabase();
      repo =
          OrderDraftsRepository(helper, ownerProvider: () async => 'user:test');
    });
    tearDown(() async {
      await helper.deleteDatabase();
    });
    test('guarda borrador incompleto', () async {
      await repo.save(OrderDraft());
      expect((await repo.all()).single.jobs, isEmpty);
    });
    test('recupera varios trabajos y diseños tras cerrar base', () async {
      final draft = await repo.save(OrderDraft(client: 'Cliente prueba', jobs: [
        work(designs: [design('a', 40), design('b', 35), design('c', 25)]),
        work(unit: 'sheets', quantity: 3)
      ]));
      await helper.close();
      final restored = (await repo.all()).single;
      expect(restored.toJson(), draft.toJson());
      final db = await helper.database;
      expect(await db.query('orders'), isEmpty);
      expect(await db.query('jobs'), isEmpty);
      expect(await db.query('pending_orders'), isEmpty);
    });
    test('edición mantiene identidad y no duplica al guardar de nuevo',
        () async {
      var draft = await repo.save(OrderDraft(jobs: [work()]));
      final id = draft.id;
      final jobId = draft.jobs.single.id;
      draft = await repo.save(draft);
      expect((await repo.all()).length, 1);
      expect(draft.id, id);
      expect(draft.jobs.single.id, jobId);
      expect(draft.revision, 2);
    });
    test('detecta conflicto y no pisa cambios más recientes', () async {
      final stale = await repo.save(OrderDraft(client: 'original'));
      await repo.save(OrderDraft(
          id: stale.id, revision: stale.revision, client: 'actualizado'));
      await expectLater(repo.save(stale), throwsStateError);
      expect((await repo.all()).single.client, 'actualizado');
    });
    test('aislamiento entre vendedores y sesión obligatoria', () async {
      await repo.save(OrderDraft(client: 'privado'));
      final other = OrderDraftsRepository(helper,
          ownerProvider: () async => 'user:other');
      expect(await other.all(), isEmpty);
      await expectLater(
          OrderDraftsRepository(helper, ownerProvider: () async => null).all(),
          throwsStateError);
    });
    test('sincronización y logout no destruyen borradores', () async {
      await repo.save(OrderDraft(client: 'pendiente'));
      await helper.clearSessionCaches();
      expect((await repo.all()).single.client, 'pendiente');
    });
    test('fallo de validación no altera documento guardado', () async {
      final saved = await repo.save(OrderDraft(client: 'seguro'));
      await expectLater(
          repo.save(OrderDraft(
              id: saved.id,
              revision: saved.revision,
              jobs: [work(quantity: -1)])),
          throwsArgumentError);
      expect((await repo.all()).single.toJson(), saved.toJson());
    });
    test('rechaza trabajos repetidos', () async {
      final job = work();
      await expectLater(
          repo.save(OrderDraft(jobs: [job, job])), throwsArgumentError);
    });
  });
}
