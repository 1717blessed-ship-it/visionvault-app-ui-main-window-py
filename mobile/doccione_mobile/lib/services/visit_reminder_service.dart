import 'package:flutter_local_notifications/flutter_local_notifications.dart';
import 'package:timezone/data/latest.dart' as tz_data;
import 'package:timezone/timezone.dart' as tz;

import '../models/visit_pin.dart';

class VisitReminderService {
  static const _channelId = 'visit_reminders';
  static bool _initialized = false;
  final FlutterLocalNotificationsPlugin _notifications;

  VisitReminderService({FlutterLocalNotificationsPlugin? notifications})
      : _notifications = notifications ?? FlutterLocalNotificationsPlugin();

  Future<void> initialize() async {
    if (_initialized) return;
    tz_data.initializeTimeZones();
    tz.setLocalLocation(tz.getLocation('America/Argentina/Buenos_Aires'));
    await _notifications.initialize(const InitializationSettings(
      android: AndroidInitializationSettings('@mipmap/ic_launcher'),
      iOS: DarwinInitializationSettings(),
    ));
    await _notifications
        .resolvePlatformSpecificImplementation<
            AndroidFlutterLocalNotificationsPlugin>()
        ?.requestNotificationsPermission();
    _initialized = true;
  }

  Future<void> schedule(VisitPin pin) async {
    await initialize();
    await cancel(pin);
    if (pin.status != 'pending' || pin.scheduledAt == null || pin.deleted) {
      return;
    }
    final date = pin.scheduledAt!;
    var scheduled = tz.TZDateTime(tz.local, date.year, date.month, date.day, 9);
    if (!scheduled.isAfter(tz.TZDateTime.now(tz.local))) return;
    await _notifications.zonedSchedule(
      _id(pin),
      'Visita programada',
      '${pin.title} · hoy',
      scheduled,
      _details,
      androidScheduleMode: AndroidScheduleMode.inexactAllowWhileIdle,
      uiLocalNotificationDateInterpretation:
          UILocalNotificationDateInterpretation.absoluteTime,
    );
  }

  Future<void> cancel(VisitPin pin) => _notifications.cancel(_id(pin));

  Future<void> showOverdueSummary(int count) async {
    if (count < 1) return;
    await initialize();
    await _notifications.show(
      909090,
      'Visitas vencidas',
      'Tenés $count visita${count == 1 ? '' : 's'} pendiente${count == 1 ? '' : 's'} para reprogramar.',
      _details,
    );
  }

  int _id(VisitPin pin) => pin.clientUuid.hashCode & 0x7fffffff;

  NotificationDetails get _details => const NotificationDetails(
        android: AndroidNotificationDetails(
          _channelId,
          'Recordatorios de visitas',
          channelDescription: 'Agenda y visitas comerciales vencidas',
          importance: Importance.high,
          priority: Priority.high,
        ),
        iOS: DarwinNotificationDetails(),
      );
}
