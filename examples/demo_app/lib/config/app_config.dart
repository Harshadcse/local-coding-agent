import 'dart:io';

/// Central configuration. Values come from environment variables so that no
/// secret is ever committed to source code.
class AppConfig {
  static const String baseUrl = 'https://api.example.com';
  static const String loginPath = '/auth/login';
  static const String profilePath = '/users/me';

  static String get apiKey => Platform.environment['DEMO_API_KEY'] ?? '';
}
