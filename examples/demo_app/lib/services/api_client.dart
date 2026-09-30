import 'dart:convert';
import 'dart:io';

import '../config/app_config.dart';

/// Minimal JSON HTTP client used by the services.
class ApiClient {
  final HttpClient _client = HttpClient();

  Future<Map<String, dynamic>?> post(String path, Map<String, dynamic> body) async {
    final request = await _client.postUrl(Uri.parse(AppConfig.baseUrl + path));
    request.headers.contentType = ContentType.json;
    request.write(jsonEncode(body));
    final response = await request.close();
    if (response.statusCode != 200) return null;
    final text = await response.transform(utf8.decoder).join();
    return jsonDecode(text) as Map<String, dynamic>;
  }

  Future<Map<String, dynamic>?> get(String path) async {
    final request = await _client.getUrl(Uri.parse(AppConfig.baseUrl + path));
    final response = await request.close();
    if (response.statusCode != 200) return null;
    final text = await response.transform(utf8.decoder).join();
    return jsonDecode(text) as Map<String, dynamic>;
  }
}
