import 'dart:developer' as developer;

/// The project's logger (see coding_standard.md: never use print()).
class AppLogger {
  static void log(String message, {Object? error}) {
    developer.log(message, name: 'demo_app', error: error);
  }
}
