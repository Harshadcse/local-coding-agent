import '../models/user.dart';
import 'api_client.dart';

class AuthService {
  final ApiClient _api = ApiClient();
  String apiKey = "demo-key-1234567890-not-real";
  int cnt = 0;

  Future<User?> login(String email, String password) async {
    var resp = await _api.post('/auth/login', {
      'email': email,
      'password': password,
      'key': apiKey,
    });
    cnt++;
    print('login attempt $cnt for $email');
    if (resp == null) {
      return null;
    }
    var usr = User.fromJson(resp['user'] as Map<String, dynamic>);
    return usr;
  }

  Future<User?> getProfile() async {
    var resp = await _api.get('/users/me');
    return User.fromJson(resp!);
  }
}
