import 'package:flutter/material.dart';
import 'package:firebase_core/firebase_core.dart';
import 'package:firebase_messaging/firebase_messaging.dart';
import 'screens/home_screen.dart';
import 'theme/doccione_palette.dart';
import 'config/app_identity.dart';

@pragma('vm:entry-point')
Future<void> firebaseMessagingBackgroundHandler(RemoteMessage message) async {
  // Inicializa Firebase para mensajes data-only. La UI se actualiza al abrir
  // la app mediante getInitialMessage/onMessageOpenedApp.
  await Firebase.initializeApp();
}

void main() async {
  WidgetsFlutterBinding.ensureInitialized();
  FirebaseMessaging.onBackgroundMessage(firebaseMessagingBackgroundHandler);
  try {
    await AppIdentity.initialize();
  } catch (error) {
    debugPrint('No se pudo leer la versión instalada: $error');
  }
  // La gestión operativa no depende de Firebase. Si el servicio de push no
  // está disponible, la app debe abrir igual y permitir vincularse a Studio.
  try {
    await Firebase.initializeApp();
  } catch (error, stackTrace) {
    debugPrint('Firebase no disponible al iniciar: $error\n$stackTrace');
  }
  runApp(const DoccioneMobileApp());
}

class DoccioneMobileApp extends StatelessWidget {
  const DoccioneMobileApp({super.key});

  @override
  Widget build(BuildContext context) {
    return MaterialApp(
      title: 'Doccione Mobile',
      theme: DoccioneTheme.dark(),
      themeMode: ThemeMode.dark,
      home: const HomePage(),
    );
  }
}
