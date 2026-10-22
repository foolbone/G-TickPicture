/// 轻量 Result 类型。
///
/// 用途：领域层的"可预期失败"（校验不通过、文件格式不对、目标不存在）
/// 用 Result 返回，而不是抛异常。异常只留给"不该发生的事"。
///
/// 用法：
/// ```dart
/// final r = await importer.parse(file);
/// switch (r) {
///   case Ok(:final value):  ...
///   case Err(:final message): ...
/// }
/// ```
sealed class Result<T> {
  const Result();

  bool get isOk => this is Ok<T>;
  bool get isErr => this is Err<T>;

  /// 成功时返回值，失败时返回 null。
  T? get valueOrNull => switch (this) { Ok<T>(:final value) => value, Err<T>() => null };

  /// 成功时返回错误信息 null，失败时返回信息。
  String? get errorOrNull => switch (this) { Ok<T>() => null, Err<T>(:final message) => message };
}

final class Ok<T> extends Result<T> {
  const Ok(this.value);
  final T value;

  @override
  String toString() => 'Ok($value)';
}

final class Err<T> extends Result<T> {
  const Err(this.message, {this.cause});
  final String message;
  final Object? cause;

  @override
  String toString() => cause == null ? 'Err($message)' : 'Err($message) <- $cause';
}
