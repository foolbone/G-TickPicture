// GENERATED CODE - DO NOT MODIFY BY HAND

part of 'database.dart';

// ignore_for_file: type=lint
class $ProjectsTable extends Projects with TableInfo<$ProjectsTable, Project> {
  @override
  final GeneratedDatabase attachedDatabase;
  final String? _alias;
  $ProjectsTable(this.attachedDatabase, [this._alias]);
  static const VerificationMeta _idMeta = const VerificationMeta('id');
  @override
  late final GeneratedColumn<String> id = GeneratedColumn<String>(
      'id', aliasedName, false,
      type: DriftSqlType.string, requiredDuringInsert: true);
  static const VerificationMeta _nameMeta = const VerificationMeta('name');
  @override
  late final GeneratedColumn<String> name = GeneratedColumn<String>(
      'name', aliasedName, false,
      type: DriftSqlType.string, requiredDuringInsert: true);
  static const VerificationMeta _clientMeta = const VerificationMeta('client');
  @override
  late final GeneratedColumn<String> client = GeneratedColumn<String>(
      'client', aliasedName, true,
      type: DriftSqlType.string, requiredDuringInsert: false);
  static const VerificationMeta _createdAtMeta =
      const VerificationMeta('createdAt');
  @override
  late final GeneratedColumn<int> createdAt = GeneratedColumn<int>(
      'created_at', aliasedName, false,
      type: DriftSqlType.int, requiredDuringInsert: true);
  static const VerificationMeta _statusMeta = const VerificationMeta('status');
  @override
  late final GeneratedColumn<String> status = GeneratedColumn<String>(
      'status', aliasedName, false,
      type: DriftSqlType.string,
      requiredDuringInsert: false,
      defaultValue: const Constant('collecting'));
  static const VerificationMeta _checklistFileMeta =
      const VerificationMeta('checklistFile');
  @override
  late final GeneratedColumn<String> checklistFile = GeneratedColumn<String>(
      'checklist_file', aliasedName, true,
      type: DriftSqlType.string, requiredDuringInsert: false);
  static const VerificationMeta _settingsJsonMeta =
      const VerificationMeta('settingsJson');
  @override
  late final GeneratedColumn<String> settingsJson = GeneratedColumn<String>(
      'settings_json', aliasedName, true,
      type: DriftSqlType.string, requiredDuringInsert: false);
  static const VerificationMeta _deletedAtMeta =
      const VerificationMeta('deletedAt');
  @override
  late final GeneratedColumn<int> deletedAt = GeneratedColumn<int>(
      'deleted_at', aliasedName, true,
      type: DriftSqlType.int, requiredDuringInsert: false);
  @override
  List<GeneratedColumn> get $columns => [
        id,
        name,
        client,
        createdAt,
        status,
        checklistFile,
        settingsJson,
        deletedAt
      ];
  @override
  String get aliasedName => _alias ?? actualTableName;
  @override
  String get actualTableName => $name;
  static const String $name = 'projects';
  @override
  VerificationContext validateIntegrity(Insertable<Project> instance,
      {bool isInserting = false}) {
    final context = VerificationContext();
    final data = instance.toColumns(true);
    if (data.containsKey('id')) {
      context.handle(_idMeta, id.isAcceptableOrUnknown(data['id']!, _idMeta));
    } else if (isInserting) {
      context.missing(_idMeta);
    }
    if (data.containsKey('name')) {
      context.handle(
          _nameMeta, name.isAcceptableOrUnknown(data['name']!, _nameMeta));
    } else if (isInserting) {
      context.missing(_nameMeta);
    }
    if (data.containsKey('client')) {
      context.handle(_clientMeta,
          client.isAcceptableOrUnknown(data['client']!, _clientMeta));
    }
    if (data.containsKey('created_at')) {
      context.handle(_createdAtMeta,
          createdAt.isAcceptableOrUnknown(data['created_at']!, _createdAtMeta));
    } else if (isInserting) {
      context.missing(_createdAtMeta);
    }
    if (data.containsKey('status')) {
      context.handle(_statusMeta,
          status.isAcceptableOrUnknown(data['status']!, _statusMeta));
    }
    if (data.containsKey('checklist_file')) {
      context.handle(
          _checklistFileMeta,
          checklistFile.isAcceptableOrUnknown(
              data['checklist_file']!, _checklistFileMeta));
    }
    if (data.containsKey('settings_json')) {
      context.handle(
          _settingsJsonMeta,
          settingsJson.isAcceptableOrUnknown(
              data['settings_json']!, _settingsJsonMeta));
    }
    if (data.containsKey('deleted_at')) {
      context.handle(_deletedAtMeta,
          deletedAt.isAcceptableOrUnknown(data['deleted_at']!, _deletedAtMeta));
    }
    return context;
  }

  @override
  Set<GeneratedColumn> get $primaryKey => {id};
  @override
  Project map(Map<String, dynamic> data, {String? tablePrefix}) {
    final effectivePrefix = tablePrefix != null ? '$tablePrefix.' : '';
    return Project(
      id: attachedDatabase.typeMapping
          .read(DriftSqlType.string, data['${effectivePrefix}id'])!,
      name: attachedDatabase.typeMapping
          .read(DriftSqlType.string, data['${effectivePrefix}name'])!,
      client: attachedDatabase.typeMapping
          .read(DriftSqlType.string, data['${effectivePrefix}client']),
      createdAt: attachedDatabase.typeMapping
          .read(DriftSqlType.int, data['${effectivePrefix}created_at'])!,
      status: attachedDatabase.typeMapping
          .read(DriftSqlType.string, data['${effectivePrefix}status'])!,
      checklistFile: attachedDatabase.typeMapping
          .read(DriftSqlType.string, data['${effectivePrefix}checklist_file']),
      settingsJson: attachedDatabase.typeMapping
          .read(DriftSqlType.string, data['${effectivePrefix}settings_json']),
      deletedAt: attachedDatabase.typeMapping
          .read(DriftSqlType.int, data['${effectivePrefix}deleted_at']),
    );
  }

  @override
  $ProjectsTable createAlias(String alias) {
    return $ProjectsTable(attachedDatabase, alias);
  }
}

class Project extends DataClass implements Insertable<Project> {
  final String id;
  final String name;
  final String? client;
  final int createdAt;

  /// ProjectStatus.code
  final String status;

  /// 清单来源文件名，便于回溯
  final String? checklistFile;

  /// 项目级设置（JSON）：每品张数、画质、是否启用 OCR 等
  final String? settingsJson;
  final int? deletedAt;
  const Project(
      {required this.id,
      required this.name,
      this.client,
      required this.createdAt,
      required this.status,
      this.checklistFile,
      this.settingsJson,
      this.deletedAt});
  @override
  Map<String, Expression> toColumns(bool nullToAbsent) {
    final map = <String, Expression>{};
    map['id'] = Variable<String>(id);
    map['name'] = Variable<String>(name);
    if (!nullToAbsent || client != null) {
      map['client'] = Variable<String>(client);
    }
    map['created_at'] = Variable<int>(createdAt);
    map['status'] = Variable<String>(status);
    if (!nullToAbsent || checklistFile != null) {
      map['checklist_file'] = Variable<String>(checklistFile);
    }
    if (!nullToAbsent || settingsJson != null) {
      map['settings_json'] = Variable<String>(settingsJson);
    }
    if (!nullToAbsent || deletedAt != null) {
      map['deleted_at'] = Variable<int>(deletedAt);
    }
    return map;
  }

  ProjectsCompanion toCompanion(bool nullToAbsent) {
    return ProjectsCompanion(
      id: Value(id),
      name: Value(name),
      client:
          client == null && nullToAbsent ? const Value.absent() : Value(client),
      createdAt: Value(createdAt),
      status: Value(status),
      checklistFile: checklistFile == null && nullToAbsent
          ? const Value.absent()
          : Value(checklistFile),
      settingsJson: settingsJson == null && nullToAbsent
          ? const Value.absent()
          : Value(settingsJson),
      deletedAt: deletedAt == null && nullToAbsent
          ? const Value.absent()
          : Value(deletedAt),
    );
  }

  factory Project.fromJson(Map<String, dynamic> json,
      {ValueSerializer? serializer}) {
    serializer ??= driftRuntimeOptions.defaultSerializer;
    return Project(
      id: serializer.fromJson<String>(json['id']),
      name: serializer.fromJson<String>(json['name']),
      client: serializer.fromJson<String?>(json['client']),
      createdAt: serializer.fromJson<int>(json['createdAt']),
      status: serializer.fromJson<String>(json['status']),
      checklistFile: serializer.fromJson<String?>(json['checklistFile']),
      settingsJson: serializer.fromJson<String?>(json['settingsJson']),
      deletedAt: serializer.fromJson<int?>(json['deletedAt']),
    );
  }
  @override
  Map<String, dynamic> toJson({ValueSerializer? serializer}) {
    serializer ??= driftRuntimeOptions.defaultSerializer;
    return <String, dynamic>{
      'id': serializer.toJson<String>(id),
      'name': serializer.toJson<String>(name),
      'client': serializer.toJson<String?>(client),
      'createdAt': serializer.toJson<int>(createdAt),
      'status': serializer.toJson<String>(status),
      'checklistFile': serializer.toJson<String?>(checklistFile),
      'settingsJson': serializer.toJson<String?>(settingsJson),
      'deletedAt': serializer.toJson<int?>(deletedAt),
    };
  }

  Project copyWith(
          {String? id,
          String? name,
          Value<String?> client = const Value.absent(),
          int? createdAt,
          String? status,
          Value<String?> checklistFile = const Value.absent(),
          Value<String?> settingsJson = const Value.absent(),
          Value<int?> deletedAt = const Value.absent()}) =>
      Project(
        id: id ?? this.id,
        name: name ?? this.name,
        client: client.present ? client.value : this.client,
        createdAt: createdAt ?? this.createdAt,
        status: status ?? this.status,
        checklistFile:
            checklistFile.present ? checklistFile.value : this.checklistFile,
        settingsJson:
            settingsJson.present ? settingsJson.value : this.settingsJson,
        deletedAt: deletedAt.present ? deletedAt.value : this.deletedAt,
      );
  Project copyWithCompanion(ProjectsCompanion data) {
    return Project(
      id: data.id.present ? data.id.value : this.id,
      name: data.name.present ? data.name.value : this.name,
      client: data.client.present ? data.client.value : this.client,
      createdAt: data.createdAt.present ? data.createdAt.value : this.createdAt,
      status: data.status.present ? data.status.value : this.status,
      checklistFile: data.checklistFile.present
          ? data.checklistFile.value
          : this.checklistFile,
      settingsJson: data.settingsJson.present
          ? data.settingsJson.value
          : this.settingsJson,
      deletedAt: data.deletedAt.present ? data.deletedAt.value : this.deletedAt,
    );
  }

  @override
  String toString() {
    return (StringBuffer('Project(')
          ..write('id: $id, ')
          ..write('name: $name, ')
          ..write('client: $client, ')
          ..write('createdAt: $createdAt, ')
          ..write('status: $status, ')
          ..write('checklistFile: $checklistFile, ')
          ..write('settingsJson: $settingsJson, ')
          ..write('deletedAt: $deletedAt')
          ..write(')'))
        .toString();
  }

  @override
  int get hashCode => Object.hash(id, name, client, createdAt, status,
      checklistFile, settingsJson, deletedAt);
  @override
  bool operator ==(Object other) =>
      identical(this, other) ||
      (other is Project &&
          other.id == this.id &&
          other.name == this.name &&
          other.client == this.client &&
          other.createdAt == this.createdAt &&
          other.status == this.status &&
          other.checklistFile == this.checklistFile &&
          other.settingsJson == this.settingsJson &&
          other.deletedAt == this.deletedAt);
}

class ProjectsCompanion extends UpdateCompanion<Project> {
  final Value<String> id;
  final Value<String> name;
  final Value<String?> client;
  final Value<int> createdAt;
  final Value<String> status;
  final Value<String?> checklistFile;
  final Value<String?> settingsJson;
  final Value<int?> deletedAt;
  final Value<int> rowid;
  const ProjectsCompanion({
    this.id = const Value.absent(),
    this.name = const Value.absent(),
    this.client = const Value.absent(),
    this.createdAt = const Value.absent(),
    this.status = const Value.absent(),
    this.checklistFile = const Value.absent(),
    this.settingsJson = const Value.absent(),
    this.deletedAt = const Value.absent(),
    this.rowid = const Value.absent(),
  });
  ProjectsCompanion.insert({
    required String id,
    required String name,
    this.client = const Value.absent(),
    required int createdAt,
    this.status = const Value.absent(),
    this.checklistFile = const Value.absent(),
    this.settingsJson = const Value.absent(),
    this.deletedAt = const Value.absent(),
    this.rowid = const Value.absent(),
  })  : id = Value(id),
        name = Value(name),
        createdAt = Value(createdAt);
  static Insertable<Project> custom({
    Expression<String>? id,
    Expression<String>? name,
    Expression<String>? client,
    Expression<int>? createdAt,
    Expression<String>? status,
    Expression<String>? checklistFile,
    Expression<String>? settingsJson,
    Expression<int>? deletedAt,
    Expression<int>? rowid,
  }) {
    return RawValuesInsertable({
      if (id != null) 'id': id,
      if (name != null) 'name': name,
      if (client != null) 'client': client,
      if (createdAt != null) 'created_at': createdAt,
      if (status != null) 'status': status,
      if (checklistFile != null) 'checklist_file': checklistFile,
      if (settingsJson != null) 'settings_json': settingsJson,
      if (deletedAt != null) 'deleted_at': deletedAt,
      if (rowid != null) 'rowid': rowid,
    });
  }

  ProjectsCompanion copyWith(
      {Value<String>? id,
      Value<String>? name,
      Value<String?>? client,
      Value<int>? createdAt,
      Value<String>? status,
      Value<String?>? checklistFile,
      Value<String?>? settingsJson,
      Value<int?>? deletedAt,
      Value<int>? rowid}) {
    return ProjectsCompanion(
      id: id ?? this.id,
      name: name ?? this.name,
      client: client ?? this.client,
      createdAt: createdAt ?? this.createdAt,
      status: status ?? this.status,
      checklistFile: checklistFile ?? this.checklistFile,
      settingsJson: settingsJson ?? this.settingsJson,
      deletedAt: deletedAt ?? this.deletedAt,
      rowid: rowid ?? this.rowid,
    );
  }

  @override
  Map<String, Expression> toColumns(bool nullToAbsent) {
    final map = <String, Expression>{};
    if (id.present) {
      map['id'] = Variable<String>(id.value);
    }
    if (name.present) {
      map['name'] = Variable<String>(name.value);
    }
    if (client.present) {
      map['client'] = Variable<String>(client.value);
    }
    if (createdAt.present) {
      map['created_at'] = Variable<int>(createdAt.value);
    }
    if (status.present) {
      map['status'] = Variable<String>(status.value);
    }
    if (checklistFile.present) {
      map['checklist_file'] = Variable<String>(checklistFile.value);
    }
    if (settingsJson.present) {
      map['settings_json'] = Variable<String>(settingsJson.value);
    }
    if (deletedAt.present) {
      map['deleted_at'] = Variable<int>(deletedAt.value);
    }
    if (rowid.present) {
      map['rowid'] = Variable<int>(rowid.value);
    }
    return map;
  }

  @override
  String toString() {
    return (StringBuffer('ProjectsCompanion(')
          ..write('id: $id, ')
          ..write('name: $name, ')
          ..write('client: $client, ')
          ..write('createdAt: $createdAt, ')
          ..write('status: $status, ')
          ..write('checklistFile: $checklistFile, ')
          ..write('settingsJson: $settingsJson, ')
          ..write('deletedAt: $deletedAt, ')
          ..write('rowid: $rowid')
          ..write(')'))
        .toString();
  }
}

class $ItemsTable extends Items with TableInfo<$ItemsTable, Item> {
  @override
  final GeneratedDatabase attachedDatabase;
  final String? _alias;
  $ItemsTable(this.attachedDatabase, [this._alias]);
  static const VerificationMeta _idMeta = const VerificationMeta('id');
  @override
  late final GeneratedColumn<String> id = GeneratedColumn<String>(
      'id', aliasedName, false,
      type: DriftSqlType.string, requiredDuringInsert: true);
  static const VerificationMeta _projectIdMeta =
      const VerificationMeta('projectId');
  @override
  late final GeneratedColumn<String> projectId = GeneratedColumn<String>(
      'project_id', aliasedName, false,
      type: DriftSqlType.string,
      requiredDuringInsert: true,
      defaultConstraints:
          GeneratedColumn.constraintIsAlways('REFERENCES projects (id)'));
  static const VerificationMeta _seqMeta = const VerificationMeta('seq');
  @override
  late final GeneratedColumn<int> seq = GeneratedColumn<int>(
      'seq', aliasedName, false,
      type: DriftSqlType.int, requiredDuringInsert: true);
  static const VerificationMeta _codeMeta = const VerificationMeta('code');
  @override
  late final GeneratedColumn<String> code = GeneratedColumn<String>(
      'code', aliasedName, false,
      type: DriftSqlType.string, requiredDuringInsert: true);
  static const VerificationMeta _codeSafeMeta =
      const VerificationMeta('codeSafe');
  @override
  late final GeneratedColumn<String> codeSafe = GeneratedColumn<String>(
      'code_safe', aliasedName, false,
      type: DriftSqlType.string, requiredDuringInsert: true);
  static const VerificationMeta _nameMeta = const VerificationMeta('name');
  @override
  late final GeneratedColumn<String> name = GeneratedColumn<String>(
      'name', aliasedName, true,
      type: DriftSqlType.string, requiredDuringInsert: false);
  static const VerificationMeta _specMeta = const VerificationMeta('spec');
  @override
  late final GeneratedColumn<String> spec = GeneratedColumn<String>(
      'spec', aliasedName, true,
      type: DriftSqlType.string, requiredDuringInsert: false);
  static const VerificationMeta _qtyMeta = const VerificationMeta('qty');
  @override
  late final GeneratedColumn<double> qty = GeneratedColumn<double>(
      'qty', aliasedName, true,
      type: DriftSqlType.double, requiredDuringInsert: false);
  static const VerificationMeta _unitMeta = const VerificationMeta('unit');
  @override
  late final GeneratedColumn<String> unit = GeneratedColumn<String>(
      'unit', aliasedName, true,
      type: DriftSqlType.string, requiredDuringInsert: false);
  static const VerificationMeta _requiredPhotosMeta =
      const VerificationMeta('requiredPhotos');
  @override
  late final GeneratedColumn<int> requiredPhotos = GeneratedColumn<int>(
      'required_photos', aliasedName, false,
      type: DriftSqlType.int,
      requiredDuringInsert: false,
      defaultValue: const Constant(2));
  static const VerificationMeta _containerSummaryMeta =
      const VerificationMeta('containerSummary');
  @override
  late final GeneratedColumn<String> containerSummary = GeneratedColumn<String>(
      'container_summary', aliasedName, true,
      type: DriftSqlType.string, requiredDuringInsert: false);
  static const VerificationMeta _sourceLineCountMeta =
      const VerificationMeta('sourceLineCount');
  @override
  late final GeneratedColumn<int> sourceLineCount = GeneratedColumn<int>(
      'source_line_count', aliasedName, false,
      type: DriftSqlType.int,
      requiredDuringInsert: false,
      defaultValue: const Constant(1));
  static const VerificationMeta _stateMeta = const VerificationMeta('state');
  @override
  late final GeneratedColumn<String> state = GeneratedColumn<String>(
      'state', aliasedName, false,
      type: DriftSqlType.string,
      requiredDuringInsert: false,
      defaultValue: const Constant('normal'));
  static const VerificationMeta _notFoundReasonMeta =
      const VerificationMeta('notFoundReason');
  @override
  late final GeneratedColumn<String> notFoundReason = GeneratedColumn<String>(
      'not_found_reason', aliasedName, true,
      type: DriftSqlType.string, requiredDuringInsert: false);
  static const VerificationMeta _remarkMeta = const VerificationMeta('remark');
  @override
  late final GeneratedColumn<String> remark = GeneratedColumn<String>(
      'remark', aliasedName, true,
      type: DriftSqlType.string, requiredDuringInsert: false);
  static const VerificationMeta _deletedAtMeta =
      const VerificationMeta('deletedAt');
  @override
  late final GeneratedColumn<int> deletedAt = GeneratedColumn<int>(
      'deleted_at', aliasedName, true,
      type: DriftSqlType.int, requiredDuringInsert: false);
  @override
  List<GeneratedColumn> get $columns => [
        id,
        projectId,
        seq,
        code,
        codeSafe,
        name,
        spec,
        qty,
        unit,
        requiredPhotos,
        containerSummary,
        sourceLineCount,
        state,
        notFoundReason,
        remark,
        deletedAt
      ];
  @override
  String get aliasedName => _alias ?? actualTableName;
  @override
  String get actualTableName => $name;
  static const String $name = 'items';
  @override
  VerificationContext validateIntegrity(Insertable<Item> instance,
      {bool isInserting = false}) {
    final context = VerificationContext();
    final data = instance.toColumns(true);
    if (data.containsKey('id')) {
      context.handle(_idMeta, id.isAcceptableOrUnknown(data['id']!, _idMeta));
    } else if (isInserting) {
      context.missing(_idMeta);
    }
    if (data.containsKey('project_id')) {
      context.handle(_projectIdMeta,
          projectId.isAcceptableOrUnknown(data['project_id']!, _projectIdMeta));
    } else if (isInserting) {
      context.missing(_projectIdMeta);
    }
    if (data.containsKey('seq')) {
      context.handle(
          _seqMeta, seq.isAcceptableOrUnknown(data['seq']!, _seqMeta));
    } else if (isInserting) {
      context.missing(_seqMeta);
    }
    if (data.containsKey('code')) {
      context.handle(
          _codeMeta, code.isAcceptableOrUnknown(data['code']!, _codeMeta));
    } else if (isInserting) {
      context.missing(_codeMeta);
    }
    if (data.containsKey('code_safe')) {
      context.handle(_codeSafeMeta,
          codeSafe.isAcceptableOrUnknown(data['code_safe']!, _codeSafeMeta));
    } else if (isInserting) {
      context.missing(_codeSafeMeta);
    }
    if (data.containsKey('name')) {
      context.handle(
          _nameMeta, name.isAcceptableOrUnknown(data['name']!, _nameMeta));
    }
    if (data.containsKey('spec')) {
      context.handle(
          _specMeta, spec.isAcceptableOrUnknown(data['spec']!, _specMeta));
    }
    if (data.containsKey('qty')) {
      context.handle(
          _qtyMeta, qty.isAcceptableOrUnknown(data['qty']!, _qtyMeta));
    }
    if (data.containsKey('unit')) {
      context.handle(
          _unitMeta, unit.isAcceptableOrUnknown(data['unit']!, _unitMeta));
    }
    if (data.containsKey('required_photos')) {
      context.handle(
          _requiredPhotosMeta,
          requiredPhotos.isAcceptableOrUnknown(
              data['required_photos']!, _requiredPhotosMeta));
    }
    if (data.containsKey('container_summary')) {
      context.handle(
          _containerSummaryMeta,
          containerSummary.isAcceptableOrUnknown(
              data['container_summary']!, _containerSummaryMeta));
    }
    if (data.containsKey('source_line_count')) {
      context.handle(
          _sourceLineCountMeta,
          sourceLineCount.isAcceptableOrUnknown(
              data['source_line_count']!, _sourceLineCountMeta));
    }
    if (data.containsKey('state')) {
      context.handle(
          _stateMeta, state.isAcceptableOrUnknown(data['state']!, _stateMeta));
    }
    if (data.containsKey('not_found_reason')) {
      context.handle(
          _notFoundReasonMeta,
          notFoundReason.isAcceptableOrUnknown(
              data['not_found_reason']!, _notFoundReasonMeta));
    }
    if (data.containsKey('remark')) {
      context.handle(_remarkMeta,
          remark.isAcceptableOrUnknown(data['remark']!, _remarkMeta));
    }
    if (data.containsKey('deleted_at')) {
      context.handle(_deletedAtMeta,
          deletedAt.isAcceptableOrUnknown(data['deleted_at']!, _deletedAtMeta));
    }
    return context;
  }

  @override
  Set<GeneratedColumn> get $primaryKey => {id};
  @override
  List<Set<GeneratedColumn>> get uniqueKeys => [
        {projectId, code},
      ];
  @override
  Item map(Map<String, dynamic> data, {String? tablePrefix}) {
    final effectivePrefix = tablePrefix != null ? '$tablePrefix.' : '';
    return Item(
      id: attachedDatabase.typeMapping
          .read(DriftSqlType.string, data['${effectivePrefix}id'])!,
      projectId: attachedDatabase.typeMapping
          .read(DriftSqlType.string, data['${effectivePrefix}project_id'])!,
      seq: attachedDatabase.typeMapping
          .read(DriftSqlType.int, data['${effectivePrefix}seq'])!,
      code: attachedDatabase.typeMapping
          .read(DriftSqlType.string, data['${effectivePrefix}code'])!,
      codeSafe: attachedDatabase.typeMapping
          .read(DriftSqlType.string, data['${effectivePrefix}code_safe'])!,
      name: attachedDatabase.typeMapping
          .read(DriftSqlType.string, data['${effectivePrefix}name']),
      spec: attachedDatabase.typeMapping
          .read(DriftSqlType.string, data['${effectivePrefix}spec']),
      qty: attachedDatabase.typeMapping
          .read(DriftSqlType.double, data['${effectivePrefix}qty']),
      unit: attachedDatabase.typeMapping
          .read(DriftSqlType.string, data['${effectivePrefix}unit']),
      requiredPhotos: attachedDatabase.typeMapping
          .read(DriftSqlType.int, data['${effectivePrefix}required_photos'])!,
      containerSummary: attachedDatabase.typeMapping.read(
          DriftSqlType.string, data['${effectivePrefix}container_summary']),
      sourceLineCount: attachedDatabase.typeMapping
          .read(DriftSqlType.int, data['${effectivePrefix}source_line_count'])!,
      state: attachedDatabase.typeMapping
          .read(DriftSqlType.string, data['${effectivePrefix}state'])!,
      notFoundReason: attachedDatabase.typeMapping.read(
          DriftSqlType.string, data['${effectivePrefix}not_found_reason']),
      remark: attachedDatabase.typeMapping
          .read(DriftSqlType.string, data['${effectivePrefix}remark']),
      deletedAt: attachedDatabase.typeMapping
          .read(DriftSqlType.int, data['${effectivePrefix}deleted_at']),
    );
  }

  @override
  $ItemsTable createAlias(String alias) {
    return $ItemsTable(attachedDatabase, alias);
  }
}

class Item extends DataClass implements Insertable<Item> {
  final String id;
  final String projectId;

  /// 清单行序。决定交付目录的 3 位序号，也是缺口视图的排序依据。
  final int seq;

  /// 原始编码 —— **永不改写**，用于匹配与显示
  final String code;

  /// 文件名安全版本 —— 仅用于交付目录/文件命名
  final String codeSafe;
  final String? name;
  final String? spec;
  final double? qty;
  final String? unit;

  /// 每品要求张数，用于"张数未达标"提醒
  final int requiredPhotos;

  /// 所在包装箱（P4 诉求 1，语义甲）。
  ///
  /// 客户清单里同一件货可能分散在多个箱子里，被列成多行
  /// （如「BOX-0012 / 3 件 / 箱 A」「BOX-0012 / 5 件 / 箱 B」）。
  /// 业务上这是**同一件货**，所以导入时合并为一条记录：
  ///   · [qty] 累加（3 + 5 = 8）
  ///   · 各行的箱号在此**汇总成列表**，用 `、` 连接
  ///
  /// 存文本而不是关联表：箱号只用于**显示**，
  /// 没有任何按箱查询的需求（预检是"按货品"作业，不是"按箱"）。
  /// 为它建一张表只会增加连接与迁移成本。
  ///
  /// null / 空串 = 清单没提供箱号信息（多数清单如此），
  /// 界面必须能优雅地什么都不显示。
  final String? containerSummary;

  /// 该货品在清单里占了几行（P4 诉求 1）。
  ///
  /// 用于两件事：
  ///   1. 导入校验报告里说明"编码 X 由 3 行合并而来"，让人能回原表核对；
  ///   2. manifest 里体现"这件货分布在几个箱"。
  /// 默认 1 = 清单里正常的单行货品。
  final int sourceLineCount;

  /// ItemState.code: normal / not_found / extra
  final String state;

  /// 缺口原因（压在垛底 / 已被提走 / 客户取消 / 其他）。
  /// 措辞纪律：界面一律说「缺口」，不说「现场未见」（§原则 13）。
  final String? notFoundReason;
  final String? remark;
  final int? deletedAt;
  const Item(
      {required this.id,
      required this.projectId,
      required this.seq,
      required this.code,
      required this.codeSafe,
      this.name,
      this.spec,
      this.qty,
      this.unit,
      required this.requiredPhotos,
      this.containerSummary,
      required this.sourceLineCount,
      required this.state,
      this.notFoundReason,
      this.remark,
      this.deletedAt});
  @override
  Map<String, Expression> toColumns(bool nullToAbsent) {
    final map = <String, Expression>{};
    map['id'] = Variable<String>(id);
    map['project_id'] = Variable<String>(projectId);
    map['seq'] = Variable<int>(seq);
    map['code'] = Variable<String>(code);
    map['code_safe'] = Variable<String>(codeSafe);
    if (!nullToAbsent || name != null) {
      map['name'] = Variable<String>(name);
    }
    if (!nullToAbsent || spec != null) {
      map['spec'] = Variable<String>(spec);
    }
    if (!nullToAbsent || qty != null) {
      map['qty'] = Variable<double>(qty);
    }
    if (!nullToAbsent || unit != null) {
      map['unit'] = Variable<String>(unit);
    }
    map['required_photos'] = Variable<int>(requiredPhotos);
    if (!nullToAbsent || containerSummary != null) {
      map['container_summary'] = Variable<String>(containerSummary);
    }
    map['source_line_count'] = Variable<int>(sourceLineCount);
    map['state'] = Variable<String>(state);
    if (!nullToAbsent || notFoundReason != null) {
      map['not_found_reason'] = Variable<String>(notFoundReason);
    }
    if (!nullToAbsent || remark != null) {
      map['remark'] = Variable<String>(remark);
    }
    if (!nullToAbsent || deletedAt != null) {
      map['deleted_at'] = Variable<int>(deletedAt);
    }
    return map;
  }

  ItemsCompanion toCompanion(bool nullToAbsent) {
    return ItemsCompanion(
      id: Value(id),
      projectId: Value(projectId),
      seq: Value(seq),
      code: Value(code),
      codeSafe: Value(codeSafe),
      name: name == null && nullToAbsent ? const Value.absent() : Value(name),
      spec: spec == null && nullToAbsent ? const Value.absent() : Value(spec),
      qty: qty == null && nullToAbsent ? const Value.absent() : Value(qty),
      unit: unit == null && nullToAbsent ? const Value.absent() : Value(unit),
      requiredPhotos: Value(requiredPhotos),
      containerSummary: containerSummary == null && nullToAbsent
          ? const Value.absent()
          : Value(containerSummary),
      sourceLineCount: Value(sourceLineCount),
      state: Value(state),
      notFoundReason: notFoundReason == null && nullToAbsent
          ? const Value.absent()
          : Value(notFoundReason),
      remark:
          remark == null && nullToAbsent ? const Value.absent() : Value(remark),
      deletedAt: deletedAt == null && nullToAbsent
          ? const Value.absent()
          : Value(deletedAt),
    );
  }

  factory Item.fromJson(Map<String, dynamic> json,
      {ValueSerializer? serializer}) {
    serializer ??= driftRuntimeOptions.defaultSerializer;
    return Item(
      id: serializer.fromJson<String>(json['id']),
      projectId: serializer.fromJson<String>(json['projectId']),
      seq: serializer.fromJson<int>(json['seq']),
      code: serializer.fromJson<String>(json['code']),
      codeSafe: serializer.fromJson<String>(json['codeSafe']),
      name: serializer.fromJson<String?>(json['name']),
      spec: serializer.fromJson<String?>(json['spec']),
      qty: serializer.fromJson<double?>(json['qty']),
      unit: serializer.fromJson<String?>(json['unit']),
      requiredPhotos: serializer.fromJson<int>(json['requiredPhotos']),
      containerSummary: serializer.fromJson<String?>(json['containerSummary']),
      sourceLineCount: serializer.fromJson<int>(json['sourceLineCount']),
      state: serializer.fromJson<String>(json['state']),
      notFoundReason: serializer.fromJson<String?>(json['notFoundReason']),
      remark: serializer.fromJson<String?>(json['remark']),
      deletedAt: serializer.fromJson<int?>(json['deletedAt']),
    );
  }
  @override
  Map<String, dynamic> toJson({ValueSerializer? serializer}) {
    serializer ??= driftRuntimeOptions.defaultSerializer;
    return <String, dynamic>{
      'id': serializer.toJson<String>(id),
      'projectId': serializer.toJson<String>(projectId),
      'seq': serializer.toJson<int>(seq),
      'code': serializer.toJson<String>(code),
      'codeSafe': serializer.toJson<String>(codeSafe),
      'name': serializer.toJson<String?>(name),
      'spec': serializer.toJson<String?>(spec),
      'qty': serializer.toJson<double?>(qty),
      'unit': serializer.toJson<String?>(unit),
      'requiredPhotos': serializer.toJson<int>(requiredPhotos),
      'containerSummary': serializer.toJson<String?>(containerSummary),
      'sourceLineCount': serializer.toJson<int>(sourceLineCount),
      'state': serializer.toJson<String>(state),
      'notFoundReason': serializer.toJson<String?>(notFoundReason),
      'remark': serializer.toJson<String?>(remark),
      'deletedAt': serializer.toJson<int?>(deletedAt),
    };
  }

  Item copyWith(
          {String? id,
          String? projectId,
          int? seq,
          String? code,
          String? codeSafe,
          Value<String?> name = const Value.absent(),
          Value<String?> spec = const Value.absent(),
          Value<double?> qty = const Value.absent(),
          Value<String?> unit = const Value.absent(),
          int? requiredPhotos,
          Value<String?> containerSummary = const Value.absent(),
          int? sourceLineCount,
          String? state,
          Value<String?> notFoundReason = const Value.absent(),
          Value<String?> remark = const Value.absent(),
          Value<int?> deletedAt = const Value.absent()}) =>
      Item(
        id: id ?? this.id,
        projectId: projectId ?? this.projectId,
        seq: seq ?? this.seq,
        code: code ?? this.code,
        codeSafe: codeSafe ?? this.codeSafe,
        name: name.present ? name.value : this.name,
        spec: spec.present ? spec.value : this.spec,
        qty: qty.present ? qty.value : this.qty,
        unit: unit.present ? unit.value : this.unit,
        requiredPhotos: requiredPhotos ?? this.requiredPhotos,
        containerSummary: containerSummary.present
            ? containerSummary.value
            : this.containerSummary,
        sourceLineCount: sourceLineCount ?? this.sourceLineCount,
        state: state ?? this.state,
        notFoundReason:
            notFoundReason.present ? notFoundReason.value : this.notFoundReason,
        remark: remark.present ? remark.value : this.remark,
        deletedAt: deletedAt.present ? deletedAt.value : this.deletedAt,
      );
  Item copyWithCompanion(ItemsCompanion data) {
    return Item(
      id: data.id.present ? data.id.value : this.id,
      projectId: data.projectId.present ? data.projectId.value : this.projectId,
      seq: data.seq.present ? data.seq.value : this.seq,
      code: data.code.present ? data.code.value : this.code,
      codeSafe: data.codeSafe.present ? data.codeSafe.value : this.codeSafe,
      name: data.name.present ? data.name.value : this.name,
      spec: data.spec.present ? data.spec.value : this.spec,
      qty: data.qty.present ? data.qty.value : this.qty,
      unit: data.unit.present ? data.unit.value : this.unit,
      requiredPhotos: data.requiredPhotos.present
          ? data.requiredPhotos.value
          : this.requiredPhotos,
      containerSummary: data.containerSummary.present
          ? data.containerSummary.value
          : this.containerSummary,
      sourceLineCount: data.sourceLineCount.present
          ? data.sourceLineCount.value
          : this.sourceLineCount,
      state: data.state.present ? data.state.value : this.state,
      notFoundReason: data.notFoundReason.present
          ? data.notFoundReason.value
          : this.notFoundReason,
      remark: data.remark.present ? data.remark.value : this.remark,
      deletedAt: data.deletedAt.present ? data.deletedAt.value : this.deletedAt,
    );
  }

  @override
  String toString() {
    return (StringBuffer('Item(')
          ..write('id: $id, ')
          ..write('projectId: $projectId, ')
          ..write('seq: $seq, ')
          ..write('code: $code, ')
          ..write('codeSafe: $codeSafe, ')
          ..write('name: $name, ')
          ..write('spec: $spec, ')
          ..write('qty: $qty, ')
          ..write('unit: $unit, ')
          ..write('requiredPhotos: $requiredPhotos, ')
          ..write('containerSummary: $containerSummary, ')
          ..write('sourceLineCount: $sourceLineCount, ')
          ..write('state: $state, ')
          ..write('notFoundReason: $notFoundReason, ')
          ..write('remark: $remark, ')
          ..write('deletedAt: $deletedAt')
          ..write(')'))
        .toString();
  }

  @override
  int get hashCode => Object.hash(
      id,
      projectId,
      seq,
      code,
      codeSafe,
      name,
      spec,
      qty,
      unit,
      requiredPhotos,
      containerSummary,
      sourceLineCount,
      state,
      notFoundReason,
      remark,
      deletedAt);
  @override
  bool operator ==(Object other) =>
      identical(this, other) ||
      (other is Item &&
          other.id == this.id &&
          other.projectId == this.projectId &&
          other.seq == this.seq &&
          other.code == this.code &&
          other.codeSafe == this.codeSafe &&
          other.name == this.name &&
          other.spec == this.spec &&
          other.qty == this.qty &&
          other.unit == this.unit &&
          other.requiredPhotos == this.requiredPhotos &&
          other.containerSummary == this.containerSummary &&
          other.sourceLineCount == this.sourceLineCount &&
          other.state == this.state &&
          other.notFoundReason == this.notFoundReason &&
          other.remark == this.remark &&
          other.deletedAt == this.deletedAt);
}

class ItemsCompanion extends UpdateCompanion<Item> {
  final Value<String> id;
  final Value<String> projectId;
  final Value<int> seq;
  final Value<String> code;
  final Value<String> codeSafe;
  final Value<String?> name;
  final Value<String?> spec;
  final Value<double?> qty;
  final Value<String?> unit;
  final Value<int> requiredPhotos;
  final Value<String?> containerSummary;
  final Value<int> sourceLineCount;
  final Value<String> state;
  final Value<String?> notFoundReason;
  final Value<String?> remark;
  final Value<int?> deletedAt;
  final Value<int> rowid;
  const ItemsCompanion({
    this.id = const Value.absent(),
    this.projectId = const Value.absent(),
    this.seq = const Value.absent(),
    this.code = const Value.absent(),
    this.codeSafe = const Value.absent(),
    this.name = const Value.absent(),
    this.spec = const Value.absent(),
    this.qty = const Value.absent(),
    this.unit = const Value.absent(),
    this.requiredPhotos = const Value.absent(),
    this.containerSummary = const Value.absent(),
    this.sourceLineCount = const Value.absent(),
    this.state = const Value.absent(),
    this.notFoundReason = const Value.absent(),
    this.remark = const Value.absent(),
    this.deletedAt = const Value.absent(),
    this.rowid = const Value.absent(),
  });
  ItemsCompanion.insert({
    required String id,
    required String projectId,
    required int seq,
    required String code,
    required String codeSafe,
    this.name = const Value.absent(),
    this.spec = const Value.absent(),
    this.qty = const Value.absent(),
    this.unit = const Value.absent(),
    this.requiredPhotos = const Value.absent(),
    this.containerSummary = const Value.absent(),
    this.sourceLineCount = const Value.absent(),
    this.state = const Value.absent(),
    this.notFoundReason = const Value.absent(),
    this.remark = const Value.absent(),
    this.deletedAt = const Value.absent(),
    this.rowid = const Value.absent(),
  })  : id = Value(id),
        projectId = Value(projectId),
        seq = Value(seq),
        code = Value(code),
        codeSafe = Value(codeSafe);
  static Insertable<Item> custom({
    Expression<String>? id,
    Expression<String>? projectId,
    Expression<int>? seq,
    Expression<String>? code,
    Expression<String>? codeSafe,
    Expression<String>? name,
    Expression<String>? spec,
    Expression<double>? qty,
    Expression<String>? unit,
    Expression<int>? requiredPhotos,
    Expression<String>? containerSummary,
    Expression<int>? sourceLineCount,
    Expression<String>? state,
    Expression<String>? notFoundReason,
    Expression<String>? remark,
    Expression<int>? deletedAt,
    Expression<int>? rowid,
  }) {
    return RawValuesInsertable({
      if (id != null) 'id': id,
      if (projectId != null) 'project_id': projectId,
      if (seq != null) 'seq': seq,
      if (code != null) 'code': code,
      if (codeSafe != null) 'code_safe': codeSafe,
      if (name != null) 'name': name,
      if (spec != null) 'spec': spec,
      if (qty != null) 'qty': qty,
      if (unit != null) 'unit': unit,
      if (requiredPhotos != null) 'required_photos': requiredPhotos,
      if (containerSummary != null) 'container_summary': containerSummary,
      if (sourceLineCount != null) 'source_line_count': sourceLineCount,
      if (state != null) 'state': state,
      if (notFoundReason != null) 'not_found_reason': notFoundReason,
      if (remark != null) 'remark': remark,
      if (deletedAt != null) 'deleted_at': deletedAt,
      if (rowid != null) 'rowid': rowid,
    });
  }

  ItemsCompanion copyWith(
      {Value<String>? id,
      Value<String>? projectId,
      Value<int>? seq,
      Value<String>? code,
      Value<String>? codeSafe,
      Value<String?>? name,
      Value<String?>? spec,
      Value<double?>? qty,
      Value<String?>? unit,
      Value<int>? requiredPhotos,
      Value<String?>? containerSummary,
      Value<int>? sourceLineCount,
      Value<String>? state,
      Value<String?>? notFoundReason,
      Value<String?>? remark,
      Value<int?>? deletedAt,
      Value<int>? rowid}) {
    return ItemsCompanion(
      id: id ?? this.id,
      projectId: projectId ?? this.projectId,
      seq: seq ?? this.seq,
      code: code ?? this.code,
      codeSafe: codeSafe ?? this.codeSafe,
      name: name ?? this.name,
      spec: spec ?? this.spec,
      qty: qty ?? this.qty,
      unit: unit ?? this.unit,
      requiredPhotos: requiredPhotos ?? this.requiredPhotos,
      containerSummary: containerSummary ?? this.containerSummary,
      sourceLineCount: sourceLineCount ?? this.sourceLineCount,
      state: state ?? this.state,
      notFoundReason: notFoundReason ?? this.notFoundReason,
      remark: remark ?? this.remark,
      deletedAt: deletedAt ?? this.deletedAt,
      rowid: rowid ?? this.rowid,
    );
  }

  @override
  Map<String, Expression> toColumns(bool nullToAbsent) {
    final map = <String, Expression>{};
    if (id.present) {
      map['id'] = Variable<String>(id.value);
    }
    if (projectId.present) {
      map['project_id'] = Variable<String>(projectId.value);
    }
    if (seq.present) {
      map['seq'] = Variable<int>(seq.value);
    }
    if (code.present) {
      map['code'] = Variable<String>(code.value);
    }
    if (codeSafe.present) {
      map['code_safe'] = Variable<String>(codeSafe.value);
    }
    if (name.present) {
      map['name'] = Variable<String>(name.value);
    }
    if (spec.present) {
      map['spec'] = Variable<String>(spec.value);
    }
    if (qty.present) {
      map['qty'] = Variable<double>(qty.value);
    }
    if (unit.present) {
      map['unit'] = Variable<String>(unit.value);
    }
    if (requiredPhotos.present) {
      map['required_photos'] = Variable<int>(requiredPhotos.value);
    }
    if (containerSummary.present) {
      map['container_summary'] = Variable<String>(containerSummary.value);
    }
    if (sourceLineCount.present) {
      map['source_line_count'] = Variable<int>(sourceLineCount.value);
    }
    if (state.present) {
      map['state'] = Variable<String>(state.value);
    }
    if (notFoundReason.present) {
      map['not_found_reason'] = Variable<String>(notFoundReason.value);
    }
    if (remark.present) {
      map['remark'] = Variable<String>(remark.value);
    }
    if (deletedAt.present) {
      map['deleted_at'] = Variable<int>(deletedAt.value);
    }
    if (rowid.present) {
      map['rowid'] = Variable<int>(rowid.value);
    }
    return map;
  }

  @override
  String toString() {
    return (StringBuffer('ItemsCompanion(')
          ..write('id: $id, ')
          ..write('projectId: $projectId, ')
          ..write('seq: $seq, ')
          ..write('code: $code, ')
          ..write('codeSafe: $codeSafe, ')
          ..write('name: $name, ')
          ..write('spec: $spec, ')
          ..write('qty: $qty, ')
          ..write('unit: $unit, ')
          ..write('requiredPhotos: $requiredPhotos, ')
          ..write('containerSummary: $containerSummary, ')
          ..write('sourceLineCount: $sourceLineCount, ')
          ..write('state: $state, ')
          ..write('notFoundReason: $notFoundReason, ')
          ..write('remark: $remark, ')
          ..write('deletedAt: $deletedAt, ')
          ..write('rowid: $rowid')
          ..write(')'))
        .toString();
  }
}

class $CaptureSessionsTable extends CaptureSessions
    with TableInfo<$CaptureSessionsTable, CaptureSession> {
  @override
  final GeneratedDatabase attachedDatabase;
  final String? _alias;
  $CaptureSessionsTable(this.attachedDatabase, [this._alias]);
  static const VerificationMeta _idMeta = const VerificationMeta('id');
  @override
  late final GeneratedColumn<String> id = GeneratedColumn<String>(
      'id', aliasedName, false,
      type: DriftSqlType.string, requiredDuringInsert: true);
  static const VerificationMeta _projectIdMeta =
      const VerificationMeta('projectId');
  @override
  late final GeneratedColumn<String> projectId = GeneratedColumn<String>(
      'project_id', aliasedName, false,
      type: DriftSqlType.string,
      requiredDuringInsert: true,
      defaultConstraints:
          GeneratedColumn.constraintIsAlways('REFERENCES projects (id)'));
  static const VerificationMeta _sourceMeta = const VerificationMeta('source');
  @override
  late final GeneratedColumn<String> source = GeneratedColumn<String>(
      'source', aliasedName, false,
      type: DriftSqlType.string,
      requiredDuringInsert: false,
      defaultValue: const Constant('camera'));
  static const VerificationMeta _startedAtMeta =
      const VerificationMeta('startedAt');
  @override
  late final GeneratedColumn<int> startedAt = GeneratedColumn<int>(
      'started_at', aliasedName, false,
      type: DriftSqlType.int, requiredDuringInsert: true);
  static const VerificationMeta _endedAtMeta =
      const VerificationMeta('endedAt');
  @override
  late final GeneratedColumn<int> endedAt = GeneratedColumn<int>(
      'ended_at', aliasedName, true,
      type: DriftSqlType.int, requiredDuringInsert: false);
  static const VerificationMeta _photoCountMeta =
      const VerificationMeta('photoCount');
  @override
  late final GeneratedColumn<int> photoCount = GeneratedColumn<int>(
      'photo_count', aliasedName, false,
      type: DriftSqlType.int,
      requiredDuringInsert: false,
      defaultValue: const Constant(0));
  static const VerificationMeta _noteMeta = const VerificationMeta('note');
  @override
  late final GeneratedColumn<String> note = GeneratedColumn<String>(
      'note', aliasedName, true,
      type: DriftSqlType.string, requiredDuringInsert: false);
  @override
  List<GeneratedColumn> get $columns =>
      [id, projectId, source, startedAt, endedAt, photoCount, note];
  @override
  String get aliasedName => _alias ?? actualTableName;
  @override
  String get actualTableName => $name;
  static const String $name = 'capture_sessions';
  @override
  VerificationContext validateIntegrity(Insertable<CaptureSession> instance,
      {bool isInserting = false}) {
    final context = VerificationContext();
    final data = instance.toColumns(true);
    if (data.containsKey('id')) {
      context.handle(_idMeta, id.isAcceptableOrUnknown(data['id']!, _idMeta));
    } else if (isInserting) {
      context.missing(_idMeta);
    }
    if (data.containsKey('project_id')) {
      context.handle(_projectIdMeta,
          projectId.isAcceptableOrUnknown(data['project_id']!, _projectIdMeta));
    } else if (isInserting) {
      context.missing(_projectIdMeta);
    }
    if (data.containsKey('source')) {
      context.handle(_sourceMeta,
          source.isAcceptableOrUnknown(data['source']!, _sourceMeta));
    }
    if (data.containsKey('started_at')) {
      context.handle(_startedAtMeta,
          startedAt.isAcceptableOrUnknown(data['started_at']!, _startedAtMeta));
    } else if (isInserting) {
      context.missing(_startedAtMeta);
    }
    if (data.containsKey('ended_at')) {
      context.handle(_endedAtMeta,
          endedAt.isAcceptableOrUnknown(data['ended_at']!, _endedAtMeta));
    }
    if (data.containsKey('photo_count')) {
      context.handle(
          _photoCountMeta,
          photoCount.isAcceptableOrUnknown(
              data['photo_count']!, _photoCountMeta));
    }
    if (data.containsKey('note')) {
      context.handle(
          _noteMeta, note.isAcceptableOrUnknown(data['note']!, _noteMeta));
    }
    return context;
  }

  @override
  Set<GeneratedColumn> get $primaryKey => {id};
  @override
  CaptureSession map(Map<String, dynamic> data, {String? tablePrefix}) {
    final effectivePrefix = tablePrefix != null ? '$tablePrefix.' : '';
    return CaptureSession(
      id: attachedDatabase.typeMapping
          .read(DriftSqlType.string, data['${effectivePrefix}id'])!,
      projectId: attachedDatabase.typeMapping
          .read(DriftSqlType.string, data['${effectivePrefix}project_id'])!,
      source: attachedDatabase.typeMapping
          .read(DriftSqlType.string, data['${effectivePrefix}source'])!,
      startedAt: attachedDatabase.typeMapping
          .read(DriftSqlType.int, data['${effectivePrefix}started_at'])!,
      endedAt: attachedDatabase.typeMapping
          .read(DriftSqlType.int, data['${effectivePrefix}ended_at']),
      photoCount: attachedDatabase.typeMapping
          .read(DriftSqlType.int, data['${effectivePrefix}photo_count'])!,
      note: attachedDatabase.typeMapping
          .read(DriftSqlType.string, data['${effectivePrefix}note']),
    );
  }

  @override
  $CaptureSessionsTable createAlias(String alias) {
    return $CaptureSessionsTable(attachedDatabase, alias);
  }
}

class CaptureSession extends DataClass implements Insertable<CaptureSession> {
  final String id;
  final String projectId;

  /// CaptureSource.code: camera / album
  final String source;
  final int startedAt;
  final int? endedAt;
  final int photoCount;
  final String? note;
  const CaptureSession(
      {required this.id,
      required this.projectId,
      required this.source,
      required this.startedAt,
      this.endedAt,
      required this.photoCount,
      this.note});
  @override
  Map<String, Expression> toColumns(bool nullToAbsent) {
    final map = <String, Expression>{};
    map['id'] = Variable<String>(id);
    map['project_id'] = Variable<String>(projectId);
    map['source'] = Variable<String>(source);
    map['started_at'] = Variable<int>(startedAt);
    if (!nullToAbsent || endedAt != null) {
      map['ended_at'] = Variable<int>(endedAt);
    }
    map['photo_count'] = Variable<int>(photoCount);
    if (!nullToAbsent || note != null) {
      map['note'] = Variable<String>(note);
    }
    return map;
  }

  CaptureSessionsCompanion toCompanion(bool nullToAbsent) {
    return CaptureSessionsCompanion(
      id: Value(id),
      projectId: Value(projectId),
      source: Value(source),
      startedAt: Value(startedAt),
      endedAt: endedAt == null && nullToAbsent
          ? const Value.absent()
          : Value(endedAt),
      photoCount: Value(photoCount),
      note: note == null && nullToAbsent ? const Value.absent() : Value(note),
    );
  }

  factory CaptureSession.fromJson(Map<String, dynamic> json,
      {ValueSerializer? serializer}) {
    serializer ??= driftRuntimeOptions.defaultSerializer;
    return CaptureSession(
      id: serializer.fromJson<String>(json['id']),
      projectId: serializer.fromJson<String>(json['projectId']),
      source: serializer.fromJson<String>(json['source']),
      startedAt: serializer.fromJson<int>(json['startedAt']),
      endedAt: serializer.fromJson<int?>(json['endedAt']),
      photoCount: serializer.fromJson<int>(json['photoCount']),
      note: serializer.fromJson<String?>(json['note']),
    );
  }
  @override
  Map<String, dynamic> toJson({ValueSerializer? serializer}) {
    serializer ??= driftRuntimeOptions.defaultSerializer;
    return <String, dynamic>{
      'id': serializer.toJson<String>(id),
      'projectId': serializer.toJson<String>(projectId),
      'source': serializer.toJson<String>(source),
      'startedAt': serializer.toJson<int>(startedAt),
      'endedAt': serializer.toJson<int?>(endedAt),
      'photoCount': serializer.toJson<int>(photoCount),
      'note': serializer.toJson<String?>(note),
    };
  }

  CaptureSession copyWith(
          {String? id,
          String? projectId,
          String? source,
          int? startedAt,
          Value<int?> endedAt = const Value.absent(),
          int? photoCount,
          Value<String?> note = const Value.absent()}) =>
      CaptureSession(
        id: id ?? this.id,
        projectId: projectId ?? this.projectId,
        source: source ?? this.source,
        startedAt: startedAt ?? this.startedAt,
        endedAt: endedAt.present ? endedAt.value : this.endedAt,
        photoCount: photoCount ?? this.photoCount,
        note: note.present ? note.value : this.note,
      );
  CaptureSession copyWithCompanion(CaptureSessionsCompanion data) {
    return CaptureSession(
      id: data.id.present ? data.id.value : this.id,
      projectId: data.projectId.present ? data.projectId.value : this.projectId,
      source: data.source.present ? data.source.value : this.source,
      startedAt: data.startedAt.present ? data.startedAt.value : this.startedAt,
      endedAt: data.endedAt.present ? data.endedAt.value : this.endedAt,
      photoCount:
          data.photoCount.present ? data.photoCount.value : this.photoCount,
      note: data.note.present ? data.note.value : this.note,
    );
  }

  @override
  String toString() {
    return (StringBuffer('CaptureSession(')
          ..write('id: $id, ')
          ..write('projectId: $projectId, ')
          ..write('source: $source, ')
          ..write('startedAt: $startedAt, ')
          ..write('endedAt: $endedAt, ')
          ..write('photoCount: $photoCount, ')
          ..write('note: $note')
          ..write(')'))
        .toString();
  }

  @override
  int get hashCode =>
      Object.hash(id, projectId, source, startedAt, endedAt, photoCount, note);
  @override
  bool operator ==(Object other) =>
      identical(this, other) ||
      (other is CaptureSession &&
          other.id == this.id &&
          other.projectId == this.projectId &&
          other.source == this.source &&
          other.startedAt == this.startedAt &&
          other.endedAt == this.endedAt &&
          other.photoCount == this.photoCount &&
          other.note == this.note);
}

class CaptureSessionsCompanion extends UpdateCompanion<CaptureSession> {
  final Value<String> id;
  final Value<String> projectId;
  final Value<String> source;
  final Value<int> startedAt;
  final Value<int?> endedAt;
  final Value<int> photoCount;
  final Value<String?> note;
  final Value<int> rowid;
  const CaptureSessionsCompanion({
    this.id = const Value.absent(),
    this.projectId = const Value.absent(),
    this.source = const Value.absent(),
    this.startedAt = const Value.absent(),
    this.endedAt = const Value.absent(),
    this.photoCount = const Value.absent(),
    this.note = const Value.absent(),
    this.rowid = const Value.absent(),
  });
  CaptureSessionsCompanion.insert({
    required String id,
    required String projectId,
    this.source = const Value.absent(),
    required int startedAt,
    this.endedAt = const Value.absent(),
    this.photoCount = const Value.absent(),
    this.note = const Value.absent(),
    this.rowid = const Value.absent(),
  })  : id = Value(id),
        projectId = Value(projectId),
        startedAt = Value(startedAt);
  static Insertable<CaptureSession> custom({
    Expression<String>? id,
    Expression<String>? projectId,
    Expression<String>? source,
    Expression<int>? startedAt,
    Expression<int>? endedAt,
    Expression<int>? photoCount,
    Expression<String>? note,
    Expression<int>? rowid,
  }) {
    return RawValuesInsertable({
      if (id != null) 'id': id,
      if (projectId != null) 'project_id': projectId,
      if (source != null) 'source': source,
      if (startedAt != null) 'started_at': startedAt,
      if (endedAt != null) 'ended_at': endedAt,
      if (photoCount != null) 'photo_count': photoCount,
      if (note != null) 'note': note,
      if (rowid != null) 'rowid': rowid,
    });
  }

  CaptureSessionsCompanion copyWith(
      {Value<String>? id,
      Value<String>? projectId,
      Value<String>? source,
      Value<int>? startedAt,
      Value<int?>? endedAt,
      Value<int>? photoCount,
      Value<String?>? note,
      Value<int>? rowid}) {
    return CaptureSessionsCompanion(
      id: id ?? this.id,
      projectId: projectId ?? this.projectId,
      source: source ?? this.source,
      startedAt: startedAt ?? this.startedAt,
      endedAt: endedAt ?? this.endedAt,
      photoCount: photoCount ?? this.photoCount,
      note: note ?? this.note,
      rowid: rowid ?? this.rowid,
    );
  }

  @override
  Map<String, Expression> toColumns(bool nullToAbsent) {
    final map = <String, Expression>{};
    if (id.present) {
      map['id'] = Variable<String>(id.value);
    }
    if (projectId.present) {
      map['project_id'] = Variable<String>(projectId.value);
    }
    if (source.present) {
      map['source'] = Variable<String>(source.value);
    }
    if (startedAt.present) {
      map['started_at'] = Variable<int>(startedAt.value);
    }
    if (endedAt.present) {
      map['ended_at'] = Variable<int>(endedAt.value);
    }
    if (photoCount.present) {
      map['photo_count'] = Variable<int>(photoCount.value);
    }
    if (note.present) {
      map['note'] = Variable<String>(note.value);
    }
    if (rowid.present) {
      map['rowid'] = Variable<int>(rowid.value);
    }
    return map;
  }

  @override
  String toString() {
    return (StringBuffer('CaptureSessionsCompanion(')
          ..write('id: $id, ')
          ..write('projectId: $projectId, ')
          ..write('source: $source, ')
          ..write('startedAt: $startedAt, ')
          ..write('endedAt: $endedAt, ')
          ..write('photoCount: $photoCount, ')
          ..write('note: $note, ')
          ..write('rowid: $rowid')
          ..write(')'))
        .toString();
  }
}

class $PhotoGroupsTable extends PhotoGroups
    with TableInfo<$PhotoGroupsTable, PhotoGroup> {
  @override
  final GeneratedDatabase attachedDatabase;
  final String? _alias;
  $PhotoGroupsTable(this.attachedDatabase, [this._alias]);
  static const VerificationMeta _idMeta = const VerificationMeta('id');
  @override
  late final GeneratedColumn<String> id = GeneratedColumn<String>(
      'id', aliasedName, false,
      type: DriftSqlType.string, requiredDuringInsert: true);
  static const VerificationMeta _projectIdMeta =
      const VerificationMeta('projectId');
  @override
  late final GeneratedColumn<String> projectId = GeneratedColumn<String>(
      'project_id', aliasedName, false,
      type: DriftSqlType.string,
      requiredDuringInsert: true,
      defaultConstraints:
          GeneratedColumn.constraintIsAlways('REFERENCES projects (id)'));
  static const VerificationMeta _sessionIdMeta =
      const VerificationMeta('sessionId');
  @override
  late final GeneratedColumn<String> sessionId = GeneratedColumn<String>(
      'session_id', aliasedName, false,
      type: DriftSqlType.string,
      requiredDuringInsert: true,
      defaultConstraints: GeneratedColumn.constraintIsAlways(
          'REFERENCES capture_sessions (id)'));
  static const VerificationMeta _seqMeta = const VerificationMeta('seq');
  @override
  late final GeneratedColumn<int> seq = GeneratedColumn<int>(
      'seq', aliasedName, false,
      type: DriftSqlType.int, requiredDuringInsert: true);
  static const VerificationMeta _coverPhotoIdMeta =
      const VerificationMeta('coverPhotoId');
  @override
  late final GeneratedColumn<String> coverPhotoId = GeneratedColumn<String>(
      'cover_photo_id', aliasedName, true,
      type: DriftSqlType.string, requiredDuringInsert: false);
  static const VerificationMeta _photoCountMeta =
      const VerificationMeta('photoCount');
  @override
  late final GeneratedColumn<int> photoCount = GeneratedColumn<int>(
      'photo_count', aliasedName, false,
      type: DriftSqlType.int,
      requiredDuringInsert: false,
      defaultValue: const Constant(0));
  static const VerificationMeta _originMeta = const VerificationMeta('origin');
  @override
  late final GeneratedColumn<String> origin = GeneratedColumn<String>(
      'origin', aliasedName, false,
      type: DriftSqlType.string,
      requiredDuringInsert: false,
      defaultValue: const Constant('camera'));
  static const VerificationMeta _categoryMeta =
      const VerificationMeta('category');
  @override
  late final GeneratedColumn<String> category = GeneratedColumn<String>(
      'category', aliasedName, false,
      type: DriftSqlType.string,
      requiredDuringInsert: false,
      defaultValue: const Constant('precheck'));
  static const VerificationMeta _cartonMeta = const VerificationMeta('carton');
  @override
  late final GeneratedColumn<String> carton = GeneratedColumn<String>(
      'carton', aliasedName, true,
      type: DriftSqlType.string, requiredDuringInsert: false);
  static const VerificationMeta _suggestedItemIdMeta =
      const VerificationMeta('suggestedItemId');
  @override
  late final GeneratedColumn<String> suggestedItemId = GeneratedColumn<String>(
      'suggested_item_id', aliasedName, true,
      type: DriftSqlType.string, requiredDuringInsert: false);
  static const VerificationMeta _suggestionConfMeta =
      const VerificationMeta('suggestionConf');
  @override
  late final GeneratedColumn<double> suggestionConf = GeneratedColumn<double>(
      'suggestion_conf', aliasedName, true,
      type: DriftSqlType.double, requiredDuringInsert: false);
  static const VerificationMeta _suggestionJsonMeta =
      const VerificationMeta('suggestionJson');
  @override
  late final GeneratedColumn<String> suggestionJson = GeneratedColumn<String>(
      'suggestion_json', aliasedName, true,
      type: DriftSqlType.string, requiredDuringInsert: false);
  static const VerificationMeta _suggestStateMeta =
      const VerificationMeta('suggestState');
  @override
  late final GeneratedColumn<String> suggestState = GeneratedColumn<String>(
      'suggest_state', aliasedName, false,
      type: DriftSqlType.string,
      requiredDuringInsert: false,
      defaultValue: const Constant('pending'));
  static const VerificationMeta _itemIdMeta = const VerificationMeta('itemId');
  @override
  late final GeneratedColumn<String> itemId = GeneratedColumn<String>(
      'item_id', aliasedName, true,
      type: DriftSqlType.string, requiredDuringInsert: false);
  static const VerificationMeta _confirmedAtMeta =
      const VerificationMeta('confirmedAt');
  @override
  late final GeneratedColumn<int> confirmedAt = GeneratedColumn<int>(
      'confirmed_at', aliasedName, true,
      type: DriftSqlType.int, requiredDuringInsert: false);
  static const VerificationMeta _createdAtMeta =
      const VerificationMeta('createdAt');
  @override
  late final GeneratedColumn<int> createdAt = GeneratedColumn<int>(
      'created_at', aliasedName, false,
      type: DriftSqlType.int, requiredDuringInsert: true);
  @override
  List<GeneratedColumn> get $columns => [
        id,
        projectId,
        sessionId,
        seq,
        coverPhotoId,
        photoCount,
        origin,
        category,
        carton,
        suggestedItemId,
        suggestionConf,
        suggestionJson,
        suggestState,
        itemId,
        confirmedAt,
        createdAt
      ];
  @override
  String get aliasedName => _alias ?? actualTableName;
  @override
  String get actualTableName => $name;
  static const String $name = 'photo_groups';
  @override
  VerificationContext validateIntegrity(Insertable<PhotoGroup> instance,
      {bool isInserting = false}) {
    final context = VerificationContext();
    final data = instance.toColumns(true);
    if (data.containsKey('id')) {
      context.handle(_idMeta, id.isAcceptableOrUnknown(data['id']!, _idMeta));
    } else if (isInserting) {
      context.missing(_idMeta);
    }
    if (data.containsKey('project_id')) {
      context.handle(_projectIdMeta,
          projectId.isAcceptableOrUnknown(data['project_id']!, _projectIdMeta));
    } else if (isInserting) {
      context.missing(_projectIdMeta);
    }
    if (data.containsKey('session_id')) {
      context.handle(_sessionIdMeta,
          sessionId.isAcceptableOrUnknown(data['session_id']!, _sessionIdMeta));
    } else if (isInserting) {
      context.missing(_sessionIdMeta);
    }
    if (data.containsKey('seq')) {
      context.handle(
          _seqMeta, seq.isAcceptableOrUnknown(data['seq']!, _seqMeta));
    } else if (isInserting) {
      context.missing(_seqMeta);
    }
    if (data.containsKey('cover_photo_id')) {
      context.handle(
          _coverPhotoIdMeta,
          coverPhotoId.isAcceptableOrUnknown(
              data['cover_photo_id']!, _coverPhotoIdMeta));
    }
    if (data.containsKey('photo_count')) {
      context.handle(
          _photoCountMeta,
          photoCount.isAcceptableOrUnknown(
              data['photo_count']!, _photoCountMeta));
    }
    if (data.containsKey('origin')) {
      context.handle(_originMeta,
          origin.isAcceptableOrUnknown(data['origin']!, _originMeta));
    }
    if (data.containsKey('category')) {
      context.handle(_categoryMeta,
          category.isAcceptableOrUnknown(data['category']!, _categoryMeta));
    }
    if (data.containsKey('carton')) {
      context.handle(_cartonMeta,
          carton.isAcceptableOrUnknown(data['carton']!, _cartonMeta));
    }
    if (data.containsKey('suggested_item_id')) {
      context.handle(
          _suggestedItemIdMeta,
          suggestedItemId.isAcceptableOrUnknown(
              data['suggested_item_id']!, _suggestedItemIdMeta));
    }
    if (data.containsKey('suggestion_conf')) {
      context.handle(
          _suggestionConfMeta,
          suggestionConf.isAcceptableOrUnknown(
              data['suggestion_conf']!, _suggestionConfMeta));
    }
    if (data.containsKey('suggestion_json')) {
      context.handle(
          _suggestionJsonMeta,
          suggestionJson.isAcceptableOrUnknown(
              data['suggestion_json']!, _suggestionJsonMeta));
    }
    if (data.containsKey('suggest_state')) {
      context.handle(
          _suggestStateMeta,
          suggestState.isAcceptableOrUnknown(
              data['suggest_state']!, _suggestStateMeta));
    }
    if (data.containsKey('item_id')) {
      context.handle(_itemIdMeta,
          itemId.isAcceptableOrUnknown(data['item_id']!, _itemIdMeta));
    }
    if (data.containsKey('confirmed_at')) {
      context.handle(
          _confirmedAtMeta,
          confirmedAt.isAcceptableOrUnknown(
              data['confirmed_at']!, _confirmedAtMeta));
    }
    if (data.containsKey('created_at')) {
      context.handle(_createdAtMeta,
          createdAt.isAcceptableOrUnknown(data['created_at']!, _createdAtMeta));
    } else if (isInserting) {
      context.missing(_createdAtMeta);
    }
    return context;
  }

  @override
  Set<GeneratedColumn> get $primaryKey => {id};
  @override
  PhotoGroup map(Map<String, dynamic> data, {String? tablePrefix}) {
    final effectivePrefix = tablePrefix != null ? '$tablePrefix.' : '';
    return PhotoGroup(
      id: attachedDatabase.typeMapping
          .read(DriftSqlType.string, data['${effectivePrefix}id'])!,
      projectId: attachedDatabase.typeMapping
          .read(DriftSqlType.string, data['${effectivePrefix}project_id'])!,
      sessionId: attachedDatabase.typeMapping
          .read(DriftSqlType.string, data['${effectivePrefix}session_id'])!,
      seq: attachedDatabase.typeMapping
          .read(DriftSqlType.int, data['${effectivePrefix}seq'])!,
      coverPhotoId: attachedDatabase.typeMapping
          .read(DriftSqlType.string, data['${effectivePrefix}cover_photo_id']),
      photoCount: attachedDatabase.typeMapping
          .read(DriftSqlType.int, data['${effectivePrefix}photo_count'])!,
      origin: attachedDatabase.typeMapping
          .read(DriftSqlType.string, data['${effectivePrefix}origin'])!,
      category: attachedDatabase.typeMapping
          .read(DriftSqlType.string, data['${effectivePrefix}category'])!,
      carton: attachedDatabase.typeMapping
          .read(DriftSqlType.string, data['${effectivePrefix}carton']),
      suggestedItemId: attachedDatabase.typeMapping.read(
          DriftSqlType.string, data['${effectivePrefix}suggested_item_id']),
      suggestionConf: attachedDatabase.typeMapping
          .read(DriftSqlType.double, data['${effectivePrefix}suggestion_conf']),
      suggestionJson: attachedDatabase.typeMapping
          .read(DriftSqlType.string, data['${effectivePrefix}suggestion_json']),
      suggestState: attachedDatabase.typeMapping
          .read(DriftSqlType.string, data['${effectivePrefix}suggest_state'])!,
      itemId: attachedDatabase.typeMapping
          .read(DriftSqlType.string, data['${effectivePrefix}item_id']),
      confirmedAt: attachedDatabase.typeMapping
          .read(DriftSqlType.int, data['${effectivePrefix}confirmed_at']),
      createdAt: attachedDatabase.typeMapping
          .read(DriftSqlType.int, data['${effectivePrefix}created_at'])!,
    );
  }

  @override
  $PhotoGroupsTable createAlias(String alias) {
    return $PhotoGroupsTable(attachedDatabase, alias);
  }
}

class PhotoGroup extends DataClass implements Insertable<PhotoGroup> {
  final String id;
  final String projectId;
  final String sessionId;
  final int seq;
  final String? coverPhotoId;
  final int photoCount;

  /// GroupOrigin.code: camera / album / manual
  final String origin;

  /// PhotoCategory.code: precheck / supervision（老板 2026-09-27 拍板）。
  ///
  /// 部类由**人在整理阶段**指定（采集时不问）。默认 precheck ——
  /// 老数据与"还没归类的照片"都按预检处理，保证交付不丢照片。
  ///
  /// ⚠️ 不是归属：这里改类别不影响 `itemId`，因此不走 AssignService。
  final String category;

  /// 用户指定的箱号（老板 2026-09-27 拍板）。
  ///
  /// ★ 与 `Items.containerSummary` 的区别：
  ///   · 那个是**清单里写的**箱号信息（多数清单没有，且一货多箱时是汇总文本）；
  ///   · 这个是**整理时由人输入/选择**的箱号，是交付分文件夹的**唯一依据**。
  ///
  /// 「分组时由用户指定箱号，不依赖货品清单」—— 所以打包只看这一列。
  /// null / 空 = 还没指定箱号 → 交付时进 `_未分箱/`。
  final String? carton;
  final String? suggestedItemId;
  final double? suggestionConf;

  /// 候选列表 + 命中证据（JSON），供 UI 排序"改派"候选与复盘
  final String? suggestionJson;

  /// GroupSuggestState.code: pending / no_suggestion / conflict / none
  final String suggestState;

  /// ★ 只由 AssignService 写
  final String? itemId;
  final int? confirmedAt;
  final int createdAt;
  const PhotoGroup(
      {required this.id,
      required this.projectId,
      required this.sessionId,
      required this.seq,
      this.coverPhotoId,
      required this.photoCount,
      required this.origin,
      required this.category,
      this.carton,
      this.suggestedItemId,
      this.suggestionConf,
      this.suggestionJson,
      required this.suggestState,
      this.itemId,
      this.confirmedAt,
      required this.createdAt});
  @override
  Map<String, Expression> toColumns(bool nullToAbsent) {
    final map = <String, Expression>{};
    map['id'] = Variable<String>(id);
    map['project_id'] = Variable<String>(projectId);
    map['session_id'] = Variable<String>(sessionId);
    map['seq'] = Variable<int>(seq);
    if (!nullToAbsent || coverPhotoId != null) {
      map['cover_photo_id'] = Variable<String>(coverPhotoId);
    }
    map['photo_count'] = Variable<int>(photoCount);
    map['origin'] = Variable<String>(origin);
    map['category'] = Variable<String>(category);
    if (!nullToAbsent || carton != null) {
      map['carton'] = Variable<String>(carton);
    }
    if (!nullToAbsent || suggestedItemId != null) {
      map['suggested_item_id'] = Variable<String>(suggestedItemId);
    }
    if (!nullToAbsent || suggestionConf != null) {
      map['suggestion_conf'] = Variable<double>(suggestionConf);
    }
    if (!nullToAbsent || suggestionJson != null) {
      map['suggestion_json'] = Variable<String>(suggestionJson);
    }
    map['suggest_state'] = Variable<String>(suggestState);
    if (!nullToAbsent || itemId != null) {
      map['item_id'] = Variable<String>(itemId);
    }
    if (!nullToAbsent || confirmedAt != null) {
      map['confirmed_at'] = Variable<int>(confirmedAt);
    }
    map['created_at'] = Variable<int>(createdAt);
    return map;
  }

  PhotoGroupsCompanion toCompanion(bool nullToAbsent) {
    return PhotoGroupsCompanion(
      id: Value(id),
      projectId: Value(projectId),
      sessionId: Value(sessionId),
      seq: Value(seq),
      coverPhotoId: coverPhotoId == null && nullToAbsent
          ? const Value.absent()
          : Value(coverPhotoId),
      photoCount: Value(photoCount),
      origin: Value(origin),
      category: Value(category),
      carton:
          carton == null && nullToAbsent ? const Value.absent() : Value(carton),
      suggestedItemId: suggestedItemId == null && nullToAbsent
          ? const Value.absent()
          : Value(suggestedItemId),
      suggestionConf: suggestionConf == null && nullToAbsent
          ? const Value.absent()
          : Value(suggestionConf),
      suggestionJson: suggestionJson == null && nullToAbsent
          ? const Value.absent()
          : Value(suggestionJson),
      suggestState: Value(suggestState),
      itemId:
          itemId == null && nullToAbsent ? const Value.absent() : Value(itemId),
      confirmedAt: confirmedAt == null && nullToAbsent
          ? const Value.absent()
          : Value(confirmedAt),
      createdAt: Value(createdAt),
    );
  }

  factory PhotoGroup.fromJson(Map<String, dynamic> json,
      {ValueSerializer? serializer}) {
    serializer ??= driftRuntimeOptions.defaultSerializer;
    return PhotoGroup(
      id: serializer.fromJson<String>(json['id']),
      projectId: serializer.fromJson<String>(json['projectId']),
      sessionId: serializer.fromJson<String>(json['sessionId']),
      seq: serializer.fromJson<int>(json['seq']),
      coverPhotoId: serializer.fromJson<String?>(json['coverPhotoId']),
      photoCount: serializer.fromJson<int>(json['photoCount']),
      origin: serializer.fromJson<String>(json['origin']),
      category: serializer.fromJson<String>(json['category']),
      carton: serializer.fromJson<String?>(json['carton']),
      suggestedItemId: serializer.fromJson<String?>(json['suggestedItemId']),
      suggestionConf: serializer.fromJson<double?>(json['suggestionConf']),
      suggestionJson: serializer.fromJson<String?>(json['suggestionJson']),
      suggestState: serializer.fromJson<String>(json['suggestState']),
      itemId: serializer.fromJson<String?>(json['itemId']),
      confirmedAt: serializer.fromJson<int?>(json['confirmedAt']),
      createdAt: serializer.fromJson<int>(json['createdAt']),
    );
  }
  @override
  Map<String, dynamic> toJson({ValueSerializer? serializer}) {
    serializer ??= driftRuntimeOptions.defaultSerializer;
    return <String, dynamic>{
      'id': serializer.toJson<String>(id),
      'projectId': serializer.toJson<String>(projectId),
      'sessionId': serializer.toJson<String>(sessionId),
      'seq': serializer.toJson<int>(seq),
      'coverPhotoId': serializer.toJson<String?>(coverPhotoId),
      'photoCount': serializer.toJson<int>(photoCount),
      'origin': serializer.toJson<String>(origin),
      'category': serializer.toJson<String>(category),
      'carton': serializer.toJson<String?>(carton),
      'suggestedItemId': serializer.toJson<String?>(suggestedItemId),
      'suggestionConf': serializer.toJson<double?>(suggestionConf),
      'suggestionJson': serializer.toJson<String?>(suggestionJson),
      'suggestState': serializer.toJson<String>(suggestState),
      'itemId': serializer.toJson<String?>(itemId),
      'confirmedAt': serializer.toJson<int?>(confirmedAt),
      'createdAt': serializer.toJson<int>(createdAt),
    };
  }

  PhotoGroup copyWith(
          {String? id,
          String? projectId,
          String? sessionId,
          int? seq,
          Value<String?> coverPhotoId = const Value.absent(),
          int? photoCount,
          String? origin,
          String? category,
          Value<String?> carton = const Value.absent(),
          Value<String?> suggestedItemId = const Value.absent(),
          Value<double?> suggestionConf = const Value.absent(),
          Value<String?> suggestionJson = const Value.absent(),
          String? suggestState,
          Value<String?> itemId = const Value.absent(),
          Value<int?> confirmedAt = const Value.absent(),
          int? createdAt}) =>
      PhotoGroup(
        id: id ?? this.id,
        projectId: projectId ?? this.projectId,
        sessionId: sessionId ?? this.sessionId,
        seq: seq ?? this.seq,
        coverPhotoId:
            coverPhotoId.present ? coverPhotoId.value : this.coverPhotoId,
        photoCount: photoCount ?? this.photoCount,
        origin: origin ?? this.origin,
        category: category ?? this.category,
        carton: carton.present ? carton.value : this.carton,
        suggestedItemId: suggestedItemId.present
            ? suggestedItemId.value
            : this.suggestedItemId,
        suggestionConf:
            suggestionConf.present ? suggestionConf.value : this.suggestionConf,
        suggestionJson:
            suggestionJson.present ? suggestionJson.value : this.suggestionJson,
        suggestState: suggestState ?? this.suggestState,
        itemId: itemId.present ? itemId.value : this.itemId,
        confirmedAt: confirmedAt.present ? confirmedAt.value : this.confirmedAt,
        createdAt: createdAt ?? this.createdAt,
      );
  PhotoGroup copyWithCompanion(PhotoGroupsCompanion data) {
    return PhotoGroup(
      id: data.id.present ? data.id.value : this.id,
      projectId: data.projectId.present ? data.projectId.value : this.projectId,
      sessionId: data.sessionId.present ? data.sessionId.value : this.sessionId,
      seq: data.seq.present ? data.seq.value : this.seq,
      coverPhotoId: data.coverPhotoId.present
          ? data.coverPhotoId.value
          : this.coverPhotoId,
      photoCount:
          data.photoCount.present ? data.photoCount.value : this.photoCount,
      origin: data.origin.present ? data.origin.value : this.origin,
      category: data.category.present ? data.category.value : this.category,
      carton: data.carton.present ? data.carton.value : this.carton,
      suggestedItemId: data.suggestedItemId.present
          ? data.suggestedItemId.value
          : this.suggestedItemId,
      suggestionConf: data.suggestionConf.present
          ? data.suggestionConf.value
          : this.suggestionConf,
      suggestionJson: data.suggestionJson.present
          ? data.suggestionJson.value
          : this.suggestionJson,
      suggestState: data.suggestState.present
          ? data.suggestState.value
          : this.suggestState,
      itemId: data.itemId.present ? data.itemId.value : this.itemId,
      confirmedAt:
          data.confirmedAt.present ? data.confirmedAt.value : this.confirmedAt,
      createdAt: data.createdAt.present ? data.createdAt.value : this.createdAt,
    );
  }

  @override
  String toString() {
    return (StringBuffer('PhotoGroup(')
          ..write('id: $id, ')
          ..write('projectId: $projectId, ')
          ..write('sessionId: $sessionId, ')
          ..write('seq: $seq, ')
          ..write('coverPhotoId: $coverPhotoId, ')
          ..write('photoCount: $photoCount, ')
          ..write('origin: $origin, ')
          ..write('category: $category, ')
          ..write('carton: $carton, ')
          ..write('suggestedItemId: $suggestedItemId, ')
          ..write('suggestionConf: $suggestionConf, ')
          ..write('suggestionJson: $suggestionJson, ')
          ..write('suggestState: $suggestState, ')
          ..write('itemId: $itemId, ')
          ..write('confirmedAt: $confirmedAt, ')
          ..write('createdAt: $createdAt')
          ..write(')'))
        .toString();
  }

  @override
  int get hashCode => Object.hash(
      id,
      projectId,
      sessionId,
      seq,
      coverPhotoId,
      photoCount,
      origin,
      category,
      carton,
      suggestedItemId,
      suggestionConf,
      suggestionJson,
      suggestState,
      itemId,
      confirmedAt,
      createdAt);
  @override
  bool operator ==(Object other) =>
      identical(this, other) ||
      (other is PhotoGroup &&
          other.id == this.id &&
          other.projectId == this.projectId &&
          other.sessionId == this.sessionId &&
          other.seq == this.seq &&
          other.coverPhotoId == this.coverPhotoId &&
          other.photoCount == this.photoCount &&
          other.origin == this.origin &&
          other.category == this.category &&
          other.carton == this.carton &&
          other.suggestedItemId == this.suggestedItemId &&
          other.suggestionConf == this.suggestionConf &&
          other.suggestionJson == this.suggestionJson &&
          other.suggestState == this.suggestState &&
          other.itemId == this.itemId &&
          other.confirmedAt == this.confirmedAt &&
          other.createdAt == this.createdAt);
}

class PhotoGroupsCompanion extends UpdateCompanion<PhotoGroup> {
  final Value<String> id;
  final Value<String> projectId;
  final Value<String> sessionId;
  final Value<int> seq;
  final Value<String?> coverPhotoId;
  final Value<int> photoCount;
  final Value<String> origin;
  final Value<String> category;
  final Value<String?> carton;
  final Value<String?> suggestedItemId;
  final Value<double?> suggestionConf;
  final Value<String?> suggestionJson;
  final Value<String> suggestState;
  final Value<String?> itemId;
  final Value<int?> confirmedAt;
  final Value<int> createdAt;
  final Value<int> rowid;
  const PhotoGroupsCompanion({
    this.id = const Value.absent(),
    this.projectId = const Value.absent(),
    this.sessionId = const Value.absent(),
    this.seq = const Value.absent(),
    this.coverPhotoId = const Value.absent(),
    this.photoCount = const Value.absent(),
    this.origin = const Value.absent(),
    this.category = const Value.absent(),
    this.carton = const Value.absent(),
    this.suggestedItemId = const Value.absent(),
    this.suggestionConf = const Value.absent(),
    this.suggestionJson = const Value.absent(),
    this.suggestState = const Value.absent(),
    this.itemId = const Value.absent(),
    this.confirmedAt = const Value.absent(),
    this.createdAt = const Value.absent(),
    this.rowid = const Value.absent(),
  });
  PhotoGroupsCompanion.insert({
    required String id,
    required String projectId,
    required String sessionId,
    required int seq,
    this.coverPhotoId = const Value.absent(),
    this.photoCount = const Value.absent(),
    this.origin = const Value.absent(),
    this.category = const Value.absent(),
    this.carton = const Value.absent(),
    this.suggestedItemId = const Value.absent(),
    this.suggestionConf = const Value.absent(),
    this.suggestionJson = const Value.absent(),
    this.suggestState = const Value.absent(),
    this.itemId = const Value.absent(),
    this.confirmedAt = const Value.absent(),
    required int createdAt,
    this.rowid = const Value.absent(),
  })  : id = Value(id),
        projectId = Value(projectId),
        sessionId = Value(sessionId),
        seq = Value(seq),
        createdAt = Value(createdAt);
  static Insertable<PhotoGroup> custom({
    Expression<String>? id,
    Expression<String>? projectId,
    Expression<String>? sessionId,
    Expression<int>? seq,
    Expression<String>? coverPhotoId,
    Expression<int>? photoCount,
    Expression<String>? origin,
    Expression<String>? category,
    Expression<String>? carton,
    Expression<String>? suggestedItemId,
    Expression<double>? suggestionConf,
    Expression<String>? suggestionJson,
    Expression<String>? suggestState,
    Expression<String>? itemId,
    Expression<int>? confirmedAt,
    Expression<int>? createdAt,
    Expression<int>? rowid,
  }) {
    return RawValuesInsertable({
      if (id != null) 'id': id,
      if (projectId != null) 'project_id': projectId,
      if (sessionId != null) 'session_id': sessionId,
      if (seq != null) 'seq': seq,
      if (coverPhotoId != null) 'cover_photo_id': coverPhotoId,
      if (photoCount != null) 'photo_count': photoCount,
      if (origin != null) 'origin': origin,
      if (category != null) 'category': category,
      if (carton != null) 'carton': carton,
      if (suggestedItemId != null) 'suggested_item_id': suggestedItemId,
      if (suggestionConf != null) 'suggestion_conf': suggestionConf,
      if (suggestionJson != null) 'suggestion_json': suggestionJson,
      if (suggestState != null) 'suggest_state': suggestState,
      if (itemId != null) 'item_id': itemId,
      if (confirmedAt != null) 'confirmed_at': confirmedAt,
      if (createdAt != null) 'created_at': createdAt,
      if (rowid != null) 'rowid': rowid,
    });
  }

  PhotoGroupsCompanion copyWith(
      {Value<String>? id,
      Value<String>? projectId,
      Value<String>? sessionId,
      Value<int>? seq,
      Value<String?>? coverPhotoId,
      Value<int>? photoCount,
      Value<String>? origin,
      Value<String>? category,
      Value<String?>? carton,
      Value<String?>? suggestedItemId,
      Value<double?>? suggestionConf,
      Value<String?>? suggestionJson,
      Value<String>? suggestState,
      Value<String?>? itemId,
      Value<int?>? confirmedAt,
      Value<int>? createdAt,
      Value<int>? rowid}) {
    return PhotoGroupsCompanion(
      id: id ?? this.id,
      projectId: projectId ?? this.projectId,
      sessionId: sessionId ?? this.sessionId,
      seq: seq ?? this.seq,
      coverPhotoId: coverPhotoId ?? this.coverPhotoId,
      photoCount: photoCount ?? this.photoCount,
      origin: origin ?? this.origin,
      category: category ?? this.category,
      carton: carton ?? this.carton,
      suggestedItemId: suggestedItemId ?? this.suggestedItemId,
      suggestionConf: suggestionConf ?? this.suggestionConf,
      suggestionJson: suggestionJson ?? this.suggestionJson,
      suggestState: suggestState ?? this.suggestState,
      itemId: itemId ?? this.itemId,
      confirmedAt: confirmedAt ?? this.confirmedAt,
      createdAt: createdAt ?? this.createdAt,
      rowid: rowid ?? this.rowid,
    );
  }

  @override
  Map<String, Expression> toColumns(bool nullToAbsent) {
    final map = <String, Expression>{};
    if (id.present) {
      map['id'] = Variable<String>(id.value);
    }
    if (projectId.present) {
      map['project_id'] = Variable<String>(projectId.value);
    }
    if (sessionId.present) {
      map['session_id'] = Variable<String>(sessionId.value);
    }
    if (seq.present) {
      map['seq'] = Variable<int>(seq.value);
    }
    if (coverPhotoId.present) {
      map['cover_photo_id'] = Variable<String>(coverPhotoId.value);
    }
    if (photoCount.present) {
      map['photo_count'] = Variable<int>(photoCount.value);
    }
    if (origin.present) {
      map['origin'] = Variable<String>(origin.value);
    }
    if (category.present) {
      map['category'] = Variable<String>(category.value);
    }
    if (carton.present) {
      map['carton'] = Variable<String>(carton.value);
    }
    if (suggestedItemId.present) {
      map['suggested_item_id'] = Variable<String>(suggestedItemId.value);
    }
    if (suggestionConf.present) {
      map['suggestion_conf'] = Variable<double>(suggestionConf.value);
    }
    if (suggestionJson.present) {
      map['suggestion_json'] = Variable<String>(suggestionJson.value);
    }
    if (suggestState.present) {
      map['suggest_state'] = Variable<String>(suggestState.value);
    }
    if (itemId.present) {
      map['item_id'] = Variable<String>(itemId.value);
    }
    if (confirmedAt.present) {
      map['confirmed_at'] = Variable<int>(confirmedAt.value);
    }
    if (createdAt.present) {
      map['created_at'] = Variable<int>(createdAt.value);
    }
    if (rowid.present) {
      map['rowid'] = Variable<int>(rowid.value);
    }
    return map;
  }

  @override
  String toString() {
    return (StringBuffer('PhotoGroupsCompanion(')
          ..write('id: $id, ')
          ..write('projectId: $projectId, ')
          ..write('sessionId: $sessionId, ')
          ..write('seq: $seq, ')
          ..write('coverPhotoId: $coverPhotoId, ')
          ..write('photoCount: $photoCount, ')
          ..write('origin: $origin, ')
          ..write('category: $category, ')
          ..write('carton: $carton, ')
          ..write('suggestedItemId: $suggestedItemId, ')
          ..write('suggestionConf: $suggestionConf, ')
          ..write('suggestionJson: $suggestionJson, ')
          ..write('suggestState: $suggestState, ')
          ..write('itemId: $itemId, ')
          ..write('confirmedAt: $confirmedAt, ')
          ..write('createdAt: $createdAt, ')
          ..write('rowid: $rowid')
          ..write(')'))
        .toString();
  }
}

class $PhotosTable extends Photos with TableInfo<$PhotosTable, Photo> {
  @override
  final GeneratedDatabase attachedDatabase;
  final String? _alias;
  $PhotosTable(this.attachedDatabase, [this._alias]);
  static const VerificationMeta _idMeta = const VerificationMeta('id');
  @override
  late final GeneratedColumn<String> id = GeneratedColumn<String>(
      'id', aliasedName, false,
      type: DriftSqlType.string, requiredDuringInsert: true);
  static const VerificationMeta _projectIdMeta =
      const VerificationMeta('projectId');
  @override
  late final GeneratedColumn<String> projectId = GeneratedColumn<String>(
      'project_id', aliasedName, false,
      type: DriftSqlType.string,
      requiredDuringInsert: true,
      defaultConstraints:
          GeneratedColumn.constraintIsAlways('REFERENCES projects (id)'));
  static const VerificationMeta _sessionIdMeta =
      const VerificationMeta('sessionId');
  @override
  late final GeneratedColumn<String> sessionId = GeneratedColumn<String>(
      'session_id', aliasedName, false,
      type: DriftSqlType.string,
      requiredDuringInsert: true,
      defaultConstraints: GeneratedColumn.constraintIsAlways(
          'REFERENCES capture_sessions (id)'));
  static const VerificationMeta _groupIdMeta =
      const VerificationMeta('groupId');
  @override
  late final GeneratedColumn<String> groupId = GeneratedColumn<String>(
      'group_id', aliasedName, true,
      type: DriftSqlType.string, requiredDuringInsert: false);
  static const VerificationMeta _filePathMeta =
      const VerificationMeta('filePath');
  @override
  late final GeneratedColumn<String> filePath = GeneratedColumn<String>(
      'file_path', aliasedName, false,
      type: DriftSqlType.string, requiredDuringInsert: true);
  static const VerificationMeta _thumbPathMeta =
      const VerificationMeta('thumbPath');
  @override
  late final GeneratedColumn<String> thumbPath = GeneratedColumn<String>(
      'thumb_path', aliasedName, true,
      type: DriftSqlType.string, requiredDuringInsert: false);
  static const VerificationMeta _widthMeta = const VerificationMeta('width');
  @override
  late final GeneratedColumn<int> width = GeneratedColumn<int>(
      'width', aliasedName, true,
      type: DriftSqlType.int, requiredDuringInsert: false);
  static const VerificationMeta _heightMeta = const VerificationMeta('height');
  @override
  late final GeneratedColumn<int> height = GeneratedColumn<int>(
      'height', aliasedName, true,
      type: DriftSqlType.int, requiredDuringInsert: false);
  static const VerificationMeta _bytesMeta = const VerificationMeta('bytes');
  @override
  late final GeneratedColumn<int> bytes = GeneratedColumn<int>(
      'bytes', aliasedName, true,
      type: DriftSqlType.int, requiredDuringInsert: false);
  static const VerificationMeta _takenAtMeta =
      const VerificationMeta('takenAt');
  @override
  late final GeneratedColumn<int> takenAt = GeneratedColumn<int>(
      'taken_at', aliasedName, false,
      type: DriftSqlType.int, requiredDuringInsert: true);
  static const VerificationMeta _seqMeta = const VerificationMeta('seq');
  @override
  late final GeneratedColumn<int> seq = GeneratedColumn<int>(
      'seq', aliasedName, false,
      type: DriftSqlType.int, requiredDuringInsert: true);
  static const VerificationMeta _itemIdMeta = const VerificationMeta('itemId');
  @override
  late final GeneratedColumn<String> itemId = GeneratedColumn<String>(
      'item_id', aliasedName, true,
      type: DriftSqlType.string, requiredDuringInsert: false);
  static const VerificationMeta _stateMeta = const VerificationMeta('state');
  @override
  late final GeneratedColumn<String> state = GeneratedColumn<String>(
      'state', aliasedName, false,
      type: DriftSqlType.string,
      requiredDuringInsert: false,
      defaultValue: const Constant('unassigned'));
  static const VerificationMeta _categoryMeta =
      const VerificationMeta('category');
  @override
  late final GeneratedColumn<String> category = GeneratedColumn<String>(
      'category', aliasedName, false,
      type: DriftSqlType.string,
      requiredDuringInsert: false,
      defaultValue: const Constant('precheck'));
  static const VerificationMeta _ocrStateMeta =
      const VerificationMeta('ocrState');
  @override
  late final GeneratedColumn<String> ocrState = GeneratedColumn<String>(
      'ocr_state', aliasedName, false,
      type: DriftSqlType.string,
      requiredDuringInsert: false,
      defaultValue: const Constant('pending'));
  static const VerificationMeta _sharpnessFlagMeta =
      const VerificationMeta('sharpnessFlag');
  @override
  late final GeneratedColumn<String> sharpnessFlag = GeneratedColumn<String>(
      'sharpness_flag', aliasedName, true,
      type: DriftSqlType.string, requiredDuringInsert: false);
  static const VerificationMeta _contentHashMeta =
      const VerificationMeta('contentHash');
  @override
  late final GeneratedColumn<String> contentHash = GeneratedColumn<String>(
      'content_hash', aliasedName, true,
      type: DriftSqlType.string, requiredDuringInsert: false);
  static const VerificationMeta _createdAtMeta =
      const VerificationMeta('createdAt');
  @override
  late final GeneratedColumn<int> createdAt = GeneratedColumn<int>(
      'created_at', aliasedName, false,
      type: DriftSqlType.int, requiredDuringInsert: true);
  @override
  List<GeneratedColumn> get $columns => [
        id,
        projectId,
        sessionId,
        groupId,
        filePath,
        thumbPath,
        width,
        height,
        bytes,
        takenAt,
        seq,
        itemId,
        state,
        category,
        ocrState,
        sharpnessFlag,
        contentHash,
        createdAt
      ];
  @override
  String get aliasedName => _alias ?? actualTableName;
  @override
  String get actualTableName => $name;
  static const String $name = 'photos';
  @override
  VerificationContext validateIntegrity(Insertable<Photo> instance,
      {bool isInserting = false}) {
    final context = VerificationContext();
    final data = instance.toColumns(true);
    if (data.containsKey('id')) {
      context.handle(_idMeta, id.isAcceptableOrUnknown(data['id']!, _idMeta));
    } else if (isInserting) {
      context.missing(_idMeta);
    }
    if (data.containsKey('project_id')) {
      context.handle(_projectIdMeta,
          projectId.isAcceptableOrUnknown(data['project_id']!, _projectIdMeta));
    } else if (isInserting) {
      context.missing(_projectIdMeta);
    }
    if (data.containsKey('session_id')) {
      context.handle(_sessionIdMeta,
          sessionId.isAcceptableOrUnknown(data['session_id']!, _sessionIdMeta));
    } else if (isInserting) {
      context.missing(_sessionIdMeta);
    }
    if (data.containsKey('group_id')) {
      context.handle(_groupIdMeta,
          groupId.isAcceptableOrUnknown(data['group_id']!, _groupIdMeta));
    }
    if (data.containsKey('file_path')) {
      context.handle(_filePathMeta,
          filePath.isAcceptableOrUnknown(data['file_path']!, _filePathMeta));
    } else if (isInserting) {
      context.missing(_filePathMeta);
    }
    if (data.containsKey('thumb_path')) {
      context.handle(_thumbPathMeta,
          thumbPath.isAcceptableOrUnknown(data['thumb_path']!, _thumbPathMeta));
    }
    if (data.containsKey('width')) {
      context.handle(
          _widthMeta, width.isAcceptableOrUnknown(data['width']!, _widthMeta));
    }
    if (data.containsKey('height')) {
      context.handle(_heightMeta,
          height.isAcceptableOrUnknown(data['height']!, _heightMeta));
    }
    if (data.containsKey('bytes')) {
      context.handle(
          _bytesMeta, bytes.isAcceptableOrUnknown(data['bytes']!, _bytesMeta));
    }
    if (data.containsKey('taken_at')) {
      context.handle(_takenAtMeta,
          takenAt.isAcceptableOrUnknown(data['taken_at']!, _takenAtMeta));
    } else if (isInserting) {
      context.missing(_takenAtMeta);
    }
    if (data.containsKey('seq')) {
      context.handle(
          _seqMeta, seq.isAcceptableOrUnknown(data['seq']!, _seqMeta));
    } else if (isInserting) {
      context.missing(_seqMeta);
    }
    if (data.containsKey('item_id')) {
      context.handle(_itemIdMeta,
          itemId.isAcceptableOrUnknown(data['item_id']!, _itemIdMeta));
    }
    if (data.containsKey('state')) {
      context.handle(
          _stateMeta, state.isAcceptableOrUnknown(data['state']!, _stateMeta));
    }
    if (data.containsKey('category')) {
      context.handle(_categoryMeta,
          category.isAcceptableOrUnknown(data['category']!, _categoryMeta));
    }
    if (data.containsKey('ocr_state')) {
      context.handle(_ocrStateMeta,
          ocrState.isAcceptableOrUnknown(data['ocr_state']!, _ocrStateMeta));
    }
    if (data.containsKey('sharpness_flag')) {
      context.handle(
          _sharpnessFlagMeta,
          sharpnessFlag.isAcceptableOrUnknown(
              data['sharpness_flag']!, _sharpnessFlagMeta));
    }
    if (data.containsKey('content_hash')) {
      context.handle(
          _contentHashMeta,
          contentHash.isAcceptableOrUnknown(
              data['content_hash']!, _contentHashMeta));
    }
    if (data.containsKey('created_at')) {
      context.handle(_createdAtMeta,
          createdAt.isAcceptableOrUnknown(data['created_at']!, _createdAtMeta));
    } else if (isInserting) {
      context.missing(_createdAtMeta);
    }
    return context;
  }

  @override
  Set<GeneratedColumn> get $primaryKey => {id};
  @override
  Photo map(Map<String, dynamic> data, {String? tablePrefix}) {
    final effectivePrefix = tablePrefix != null ? '$tablePrefix.' : '';
    return Photo(
      id: attachedDatabase.typeMapping
          .read(DriftSqlType.string, data['${effectivePrefix}id'])!,
      projectId: attachedDatabase.typeMapping
          .read(DriftSqlType.string, data['${effectivePrefix}project_id'])!,
      sessionId: attachedDatabase.typeMapping
          .read(DriftSqlType.string, data['${effectivePrefix}session_id'])!,
      groupId: attachedDatabase.typeMapping
          .read(DriftSqlType.string, data['${effectivePrefix}group_id']),
      filePath: attachedDatabase.typeMapping
          .read(DriftSqlType.string, data['${effectivePrefix}file_path'])!,
      thumbPath: attachedDatabase.typeMapping
          .read(DriftSqlType.string, data['${effectivePrefix}thumb_path']),
      width: attachedDatabase.typeMapping
          .read(DriftSqlType.int, data['${effectivePrefix}width']),
      height: attachedDatabase.typeMapping
          .read(DriftSqlType.int, data['${effectivePrefix}height']),
      bytes: attachedDatabase.typeMapping
          .read(DriftSqlType.int, data['${effectivePrefix}bytes']),
      takenAt: attachedDatabase.typeMapping
          .read(DriftSqlType.int, data['${effectivePrefix}taken_at'])!,
      seq: attachedDatabase.typeMapping
          .read(DriftSqlType.int, data['${effectivePrefix}seq'])!,
      itemId: attachedDatabase.typeMapping
          .read(DriftSqlType.string, data['${effectivePrefix}item_id']),
      state: attachedDatabase.typeMapping
          .read(DriftSqlType.string, data['${effectivePrefix}state'])!,
      category: attachedDatabase.typeMapping
          .read(DriftSqlType.string, data['${effectivePrefix}category'])!,
      ocrState: attachedDatabase.typeMapping
          .read(DriftSqlType.string, data['${effectivePrefix}ocr_state'])!,
      sharpnessFlag: attachedDatabase.typeMapping
          .read(DriftSqlType.string, data['${effectivePrefix}sharpness_flag']),
      contentHash: attachedDatabase.typeMapping
          .read(DriftSqlType.string, data['${effectivePrefix}content_hash']),
      createdAt: attachedDatabase.typeMapping
          .read(DriftSqlType.int, data['${effectivePrefix}created_at'])!,
    );
  }

  @override
  $PhotosTable createAlias(String alias) {
    return $PhotosTable(attachedDatabase, alias);
  }
}

class Photo extends DataClass implements Insertable<Photo> {
  final String id;
  final String projectId;
  final String sessionId;
  final String? groupId;

  /// 原始文件路径 —— **永不改名**（§6.4）
  final String filePath;
  final String? thumbPath;
  final int? width;
  final int? height;
  final int? bytes;

  /// EXIF 优先，缺失时退化用写入时间
  final int takenAt;

  /// 项目内全局序号
  final int seq;

  /// ★ 只由 AssignService 写
  final String? itemId;

  /// PhotoState.code: unassigned / confirmed / unused
  final String state;

  /// PhotoCategory.code: precheck / supervision。
  ///
  /// 冗余一份在照片上的理由：打包与统计都按照片走（监装照片可能
  /// 根本不进组），每次 join 组再回退会话会让查询写得很绕，且游离
  /// 照片（groupId 为空）无处可 join。
  ///
  /// **一致性由写入口保证**：整理页切换组类别时，同一个事务里把
  /// 组内照片的 category 一起刷掉（见 OrganizeRepository）。
  final String category;

  /// OcrState.code: pending / running / done / failed / skipped
  final String ocrState;

  /// 画质标记：blur / exposure / reasonable（P2 才用）
  final String? sharpnessFlag;

  /// ★ 内容指纹（2026-10-04 老板「同一组内、不同组间的照片不能重复」）。
  ///
  /// 形态是「文件大小 + 前 64KB 的摘要」拼成的短串，**不是全文件哈希** ——
  /// 1200 张 × 2.4MB 全读一遍是 2.9GB IO，现场等不起；而同一张图无论
  /// 从相册选几次、经几次微信转发，**文件字节完全不变**，读头 64KB
  /// 就足以认出来。真正的重复一张不漏，可见的编辑/重压（同一场景两张
  /// 略不同的图）不会被误判 —— 宁可漏报也不错报。
  ///
  /// **NULL = 还没算过**（不是"没有重复"）。老照片在 v4 迁移后一律 NULL，
  /// 由 backfillHashes 分批补算；补算前照片页不显示重复提示。
  final String? contentHash;
  final int createdAt;
  const Photo(
      {required this.id,
      required this.projectId,
      required this.sessionId,
      this.groupId,
      required this.filePath,
      this.thumbPath,
      this.width,
      this.height,
      this.bytes,
      required this.takenAt,
      required this.seq,
      this.itemId,
      required this.state,
      required this.category,
      required this.ocrState,
      this.sharpnessFlag,
      this.contentHash,
      required this.createdAt});
  @override
  Map<String, Expression> toColumns(bool nullToAbsent) {
    final map = <String, Expression>{};
    map['id'] = Variable<String>(id);
    map['project_id'] = Variable<String>(projectId);
    map['session_id'] = Variable<String>(sessionId);
    if (!nullToAbsent || groupId != null) {
      map['group_id'] = Variable<String>(groupId);
    }
    map['file_path'] = Variable<String>(filePath);
    if (!nullToAbsent || thumbPath != null) {
      map['thumb_path'] = Variable<String>(thumbPath);
    }
    if (!nullToAbsent || width != null) {
      map['width'] = Variable<int>(width);
    }
    if (!nullToAbsent || height != null) {
      map['height'] = Variable<int>(height);
    }
    if (!nullToAbsent || bytes != null) {
      map['bytes'] = Variable<int>(bytes);
    }
    map['taken_at'] = Variable<int>(takenAt);
    map['seq'] = Variable<int>(seq);
    if (!nullToAbsent || itemId != null) {
      map['item_id'] = Variable<String>(itemId);
    }
    map['state'] = Variable<String>(state);
    map['category'] = Variable<String>(category);
    map['ocr_state'] = Variable<String>(ocrState);
    if (!nullToAbsent || sharpnessFlag != null) {
      map['sharpness_flag'] = Variable<String>(sharpnessFlag);
    }
    if (!nullToAbsent || contentHash != null) {
      map['content_hash'] = Variable<String>(contentHash);
    }
    map['created_at'] = Variable<int>(createdAt);
    return map;
  }

  PhotosCompanion toCompanion(bool nullToAbsent) {
    return PhotosCompanion(
      id: Value(id),
      projectId: Value(projectId),
      sessionId: Value(sessionId),
      groupId: groupId == null && nullToAbsent
          ? const Value.absent()
          : Value(groupId),
      filePath: Value(filePath),
      thumbPath: thumbPath == null && nullToAbsent
          ? const Value.absent()
          : Value(thumbPath),
      width:
          width == null && nullToAbsent ? const Value.absent() : Value(width),
      height:
          height == null && nullToAbsent ? const Value.absent() : Value(height),
      bytes:
          bytes == null && nullToAbsent ? const Value.absent() : Value(bytes),
      takenAt: Value(takenAt),
      seq: Value(seq),
      itemId:
          itemId == null && nullToAbsent ? const Value.absent() : Value(itemId),
      state: Value(state),
      category: Value(category),
      ocrState: Value(ocrState),
      sharpnessFlag: sharpnessFlag == null && nullToAbsent
          ? const Value.absent()
          : Value(sharpnessFlag),
      contentHash: contentHash == null && nullToAbsent
          ? const Value.absent()
          : Value(contentHash),
      createdAt: Value(createdAt),
    );
  }

  factory Photo.fromJson(Map<String, dynamic> json,
      {ValueSerializer? serializer}) {
    serializer ??= driftRuntimeOptions.defaultSerializer;
    return Photo(
      id: serializer.fromJson<String>(json['id']),
      projectId: serializer.fromJson<String>(json['projectId']),
      sessionId: serializer.fromJson<String>(json['sessionId']),
      groupId: serializer.fromJson<String?>(json['groupId']),
      filePath: serializer.fromJson<String>(json['filePath']),
      thumbPath: serializer.fromJson<String?>(json['thumbPath']),
      width: serializer.fromJson<int?>(json['width']),
      height: serializer.fromJson<int?>(json['height']),
      bytes: serializer.fromJson<int?>(json['bytes']),
      takenAt: serializer.fromJson<int>(json['takenAt']),
      seq: serializer.fromJson<int>(json['seq']),
      itemId: serializer.fromJson<String?>(json['itemId']),
      state: serializer.fromJson<String>(json['state']),
      category: serializer.fromJson<String>(json['category']),
      ocrState: serializer.fromJson<String>(json['ocrState']),
      sharpnessFlag: serializer.fromJson<String?>(json['sharpnessFlag']),
      contentHash: serializer.fromJson<String?>(json['contentHash']),
      createdAt: serializer.fromJson<int>(json['createdAt']),
    );
  }
  @override
  Map<String, dynamic> toJson({ValueSerializer? serializer}) {
    serializer ??= driftRuntimeOptions.defaultSerializer;
    return <String, dynamic>{
      'id': serializer.toJson<String>(id),
      'projectId': serializer.toJson<String>(projectId),
      'sessionId': serializer.toJson<String>(sessionId),
      'groupId': serializer.toJson<String?>(groupId),
      'filePath': serializer.toJson<String>(filePath),
      'thumbPath': serializer.toJson<String?>(thumbPath),
      'width': serializer.toJson<int?>(width),
      'height': serializer.toJson<int?>(height),
      'bytes': serializer.toJson<int?>(bytes),
      'takenAt': serializer.toJson<int>(takenAt),
      'seq': serializer.toJson<int>(seq),
      'itemId': serializer.toJson<String?>(itemId),
      'state': serializer.toJson<String>(state),
      'category': serializer.toJson<String>(category),
      'ocrState': serializer.toJson<String>(ocrState),
      'sharpnessFlag': serializer.toJson<String?>(sharpnessFlag),
      'contentHash': serializer.toJson<String?>(contentHash),
      'createdAt': serializer.toJson<int>(createdAt),
    };
  }

  Photo copyWith(
          {String? id,
          String? projectId,
          String? sessionId,
          Value<String?> groupId = const Value.absent(),
          String? filePath,
          Value<String?> thumbPath = const Value.absent(),
          Value<int?> width = const Value.absent(),
          Value<int?> height = const Value.absent(),
          Value<int?> bytes = const Value.absent(),
          int? takenAt,
          int? seq,
          Value<String?> itemId = const Value.absent(),
          String? state,
          String? category,
          String? ocrState,
          Value<String?> sharpnessFlag = const Value.absent(),
          Value<String?> contentHash = const Value.absent(),
          int? createdAt}) =>
      Photo(
        id: id ?? this.id,
        projectId: projectId ?? this.projectId,
        sessionId: sessionId ?? this.sessionId,
        groupId: groupId.present ? groupId.value : this.groupId,
        filePath: filePath ?? this.filePath,
        thumbPath: thumbPath.present ? thumbPath.value : this.thumbPath,
        width: width.present ? width.value : this.width,
        height: height.present ? height.value : this.height,
        bytes: bytes.present ? bytes.value : this.bytes,
        takenAt: takenAt ?? this.takenAt,
        seq: seq ?? this.seq,
        itemId: itemId.present ? itemId.value : this.itemId,
        state: state ?? this.state,
        category: category ?? this.category,
        ocrState: ocrState ?? this.ocrState,
        sharpnessFlag:
            sharpnessFlag.present ? sharpnessFlag.value : this.sharpnessFlag,
        contentHash: contentHash.present ? contentHash.value : this.contentHash,
        createdAt: createdAt ?? this.createdAt,
      );
  Photo copyWithCompanion(PhotosCompanion data) {
    return Photo(
      id: data.id.present ? data.id.value : this.id,
      projectId: data.projectId.present ? data.projectId.value : this.projectId,
      sessionId: data.sessionId.present ? data.sessionId.value : this.sessionId,
      groupId: data.groupId.present ? data.groupId.value : this.groupId,
      filePath: data.filePath.present ? data.filePath.value : this.filePath,
      thumbPath: data.thumbPath.present ? data.thumbPath.value : this.thumbPath,
      width: data.width.present ? data.width.value : this.width,
      height: data.height.present ? data.height.value : this.height,
      bytes: data.bytes.present ? data.bytes.value : this.bytes,
      takenAt: data.takenAt.present ? data.takenAt.value : this.takenAt,
      seq: data.seq.present ? data.seq.value : this.seq,
      itemId: data.itemId.present ? data.itemId.value : this.itemId,
      state: data.state.present ? data.state.value : this.state,
      category: data.category.present ? data.category.value : this.category,
      ocrState: data.ocrState.present ? data.ocrState.value : this.ocrState,
      sharpnessFlag: data.sharpnessFlag.present
          ? data.sharpnessFlag.value
          : this.sharpnessFlag,
      contentHash:
          data.contentHash.present ? data.contentHash.value : this.contentHash,
      createdAt: data.createdAt.present ? data.createdAt.value : this.createdAt,
    );
  }

  @override
  String toString() {
    return (StringBuffer('Photo(')
          ..write('id: $id, ')
          ..write('projectId: $projectId, ')
          ..write('sessionId: $sessionId, ')
          ..write('groupId: $groupId, ')
          ..write('filePath: $filePath, ')
          ..write('thumbPath: $thumbPath, ')
          ..write('width: $width, ')
          ..write('height: $height, ')
          ..write('bytes: $bytes, ')
          ..write('takenAt: $takenAt, ')
          ..write('seq: $seq, ')
          ..write('itemId: $itemId, ')
          ..write('state: $state, ')
          ..write('category: $category, ')
          ..write('ocrState: $ocrState, ')
          ..write('sharpnessFlag: $sharpnessFlag, ')
          ..write('contentHash: $contentHash, ')
          ..write('createdAt: $createdAt')
          ..write(')'))
        .toString();
  }

  @override
  int get hashCode => Object.hash(
      id,
      projectId,
      sessionId,
      groupId,
      filePath,
      thumbPath,
      width,
      height,
      bytes,
      takenAt,
      seq,
      itemId,
      state,
      category,
      ocrState,
      sharpnessFlag,
      contentHash,
      createdAt);
  @override
  bool operator ==(Object other) =>
      identical(this, other) ||
      (other is Photo &&
          other.id == this.id &&
          other.projectId == this.projectId &&
          other.sessionId == this.sessionId &&
          other.groupId == this.groupId &&
          other.filePath == this.filePath &&
          other.thumbPath == this.thumbPath &&
          other.width == this.width &&
          other.height == this.height &&
          other.bytes == this.bytes &&
          other.takenAt == this.takenAt &&
          other.seq == this.seq &&
          other.itemId == this.itemId &&
          other.state == this.state &&
          other.category == this.category &&
          other.ocrState == this.ocrState &&
          other.sharpnessFlag == this.sharpnessFlag &&
          other.contentHash == this.contentHash &&
          other.createdAt == this.createdAt);
}

class PhotosCompanion extends UpdateCompanion<Photo> {
  final Value<String> id;
  final Value<String> projectId;
  final Value<String> sessionId;
  final Value<String?> groupId;
  final Value<String> filePath;
  final Value<String?> thumbPath;
  final Value<int?> width;
  final Value<int?> height;
  final Value<int?> bytes;
  final Value<int> takenAt;
  final Value<int> seq;
  final Value<String?> itemId;
  final Value<String> state;
  final Value<String> category;
  final Value<String> ocrState;
  final Value<String?> sharpnessFlag;
  final Value<String?> contentHash;
  final Value<int> createdAt;
  final Value<int> rowid;
  const PhotosCompanion({
    this.id = const Value.absent(),
    this.projectId = const Value.absent(),
    this.sessionId = const Value.absent(),
    this.groupId = const Value.absent(),
    this.filePath = const Value.absent(),
    this.thumbPath = const Value.absent(),
    this.width = const Value.absent(),
    this.height = const Value.absent(),
    this.bytes = const Value.absent(),
    this.takenAt = const Value.absent(),
    this.seq = const Value.absent(),
    this.itemId = const Value.absent(),
    this.state = const Value.absent(),
    this.category = const Value.absent(),
    this.ocrState = const Value.absent(),
    this.sharpnessFlag = const Value.absent(),
    this.contentHash = const Value.absent(),
    this.createdAt = const Value.absent(),
    this.rowid = const Value.absent(),
  });
  PhotosCompanion.insert({
    required String id,
    required String projectId,
    required String sessionId,
    this.groupId = const Value.absent(),
    required String filePath,
    this.thumbPath = const Value.absent(),
    this.width = const Value.absent(),
    this.height = const Value.absent(),
    this.bytes = const Value.absent(),
    required int takenAt,
    required int seq,
    this.itemId = const Value.absent(),
    this.state = const Value.absent(),
    this.category = const Value.absent(),
    this.ocrState = const Value.absent(),
    this.sharpnessFlag = const Value.absent(),
    this.contentHash = const Value.absent(),
    required int createdAt,
    this.rowid = const Value.absent(),
  })  : id = Value(id),
        projectId = Value(projectId),
        sessionId = Value(sessionId),
        filePath = Value(filePath),
        takenAt = Value(takenAt),
        seq = Value(seq),
        createdAt = Value(createdAt);
  static Insertable<Photo> custom({
    Expression<String>? id,
    Expression<String>? projectId,
    Expression<String>? sessionId,
    Expression<String>? groupId,
    Expression<String>? filePath,
    Expression<String>? thumbPath,
    Expression<int>? width,
    Expression<int>? height,
    Expression<int>? bytes,
    Expression<int>? takenAt,
    Expression<int>? seq,
    Expression<String>? itemId,
    Expression<String>? state,
    Expression<String>? category,
    Expression<String>? ocrState,
    Expression<String>? sharpnessFlag,
    Expression<String>? contentHash,
    Expression<int>? createdAt,
    Expression<int>? rowid,
  }) {
    return RawValuesInsertable({
      if (id != null) 'id': id,
      if (projectId != null) 'project_id': projectId,
      if (sessionId != null) 'session_id': sessionId,
      if (groupId != null) 'group_id': groupId,
      if (filePath != null) 'file_path': filePath,
      if (thumbPath != null) 'thumb_path': thumbPath,
      if (width != null) 'width': width,
      if (height != null) 'height': height,
      if (bytes != null) 'bytes': bytes,
      if (takenAt != null) 'taken_at': takenAt,
      if (seq != null) 'seq': seq,
      if (itemId != null) 'item_id': itemId,
      if (state != null) 'state': state,
      if (category != null) 'category': category,
      if (ocrState != null) 'ocr_state': ocrState,
      if (sharpnessFlag != null) 'sharpness_flag': sharpnessFlag,
      if (contentHash != null) 'content_hash': contentHash,
      if (createdAt != null) 'created_at': createdAt,
      if (rowid != null) 'rowid': rowid,
    });
  }

  PhotosCompanion copyWith(
      {Value<String>? id,
      Value<String>? projectId,
      Value<String>? sessionId,
      Value<String?>? groupId,
      Value<String>? filePath,
      Value<String?>? thumbPath,
      Value<int?>? width,
      Value<int?>? height,
      Value<int?>? bytes,
      Value<int>? takenAt,
      Value<int>? seq,
      Value<String?>? itemId,
      Value<String>? state,
      Value<String>? category,
      Value<String>? ocrState,
      Value<String?>? sharpnessFlag,
      Value<String?>? contentHash,
      Value<int>? createdAt,
      Value<int>? rowid}) {
    return PhotosCompanion(
      id: id ?? this.id,
      projectId: projectId ?? this.projectId,
      sessionId: sessionId ?? this.sessionId,
      groupId: groupId ?? this.groupId,
      filePath: filePath ?? this.filePath,
      thumbPath: thumbPath ?? this.thumbPath,
      width: width ?? this.width,
      height: height ?? this.height,
      bytes: bytes ?? this.bytes,
      takenAt: takenAt ?? this.takenAt,
      seq: seq ?? this.seq,
      itemId: itemId ?? this.itemId,
      state: state ?? this.state,
      category: category ?? this.category,
      ocrState: ocrState ?? this.ocrState,
      sharpnessFlag: sharpnessFlag ?? this.sharpnessFlag,
      contentHash: contentHash ?? this.contentHash,
      createdAt: createdAt ?? this.createdAt,
      rowid: rowid ?? this.rowid,
    );
  }

  @override
  Map<String, Expression> toColumns(bool nullToAbsent) {
    final map = <String, Expression>{};
    if (id.present) {
      map['id'] = Variable<String>(id.value);
    }
    if (projectId.present) {
      map['project_id'] = Variable<String>(projectId.value);
    }
    if (sessionId.present) {
      map['session_id'] = Variable<String>(sessionId.value);
    }
    if (groupId.present) {
      map['group_id'] = Variable<String>(groupId.value);
    }
    if (filePath.present) {
      map['file_path'] = Variable<String>(filePath.value);
    }
    if (thumbPath.present) {
      map['thumb_path'] = Variable<String>(thumbPath.value);
    }
    if (width.present) {
      map['width'] = Variable<int>(width.value);
    }
    if (height.present) {
      map['height'] = Variable<int>(height.value);
    }
    if (bytes.present) {
      map['bytes'] = Variable<int>(bytes.value);
    }
    if (takenAt.present) {
      map['taken_at'] = Variable<int>(takenAt.value);
    }
    if (seq.present) {
      map['seq'] = Variable<int>(seq.value);
    }
    if (itemId.present) {
      map['item_id'] = Variable<String>(itemId.value);
    }
    if (state.present) {
      map['state'] = Variable<String>(state.value);
    }
    if (category.present) {
      map['category'] = Variable<String>(category.value);
    }
    if (ocrState.present) {
      map['ocr_state'] = Variable<String>(ocrState.value);
    }
    if (sharpnessFlag.present) {
      map['sharpness_flag'] = Variable<String>(sharpnessFlag.value);
    }
    if (contentHash.present) {
      map['content_hash'] = Variable<String>(contentHash.value);
    }
    if (createdAt.present) {
      map['created_at'] = Variable<int>(createdAt.value);
    }
    if (rowid.present) {
      map['rowid'] = Variable<int>(rowid.value);
    }
    return map;
  }

  @override
  String toString() {
    return (StringBuffer('PhotosCompanion(')
          ..write('id: $id, ')
          ..write('projectId: $projectId, ')
          ..write('sessionId: $sessionId, ')
          ..write('groupId: $groupId, ')
          ..write('filePath: $filePath, ')
          ..write('thumbPath: $thumbPath, ')
          ..write('width: $width, ')
          ..write('height: $height, ')
          ..write('bytes: $bytes, ')
          ..write('takenAt: $takenAt, ')
          ..write('seq: $seq, ')
          ..write('itemId: $itemId, ')
          ..write('state: $state, ')
          ..write('category: $category, ')
          ..write('ocrState: $ocrState, ')
          ..write('sharpnessFlag: $sharpnessFlag, ')
          ..write('contentHash: $contentHash, ')
          ..write('createdAt: $createdAt, ')
          ..write('rowid: $rowid')
          ..write(')'))
        .toString();
  }
}

class $OcrTokensTable extends OcrTokens
    with TableInfo<$OcrTokensTable, OcrToken> {
  @override
  final GeneratedDatabase attachedDatabase;
  final String? _alias;
  $OcrTokensTable(this.attachedDatabase, [this._alias]);
  static const VerificationMeta _idMeta = const VerificationMeta('id');
  @override
  late final GeneratedColumn<String> id = GeneratedColumn<String>(
      'id', aliasedName, false,
      type: DriftSqlType.string, requiredDuringInsert: true);
  static const VerificationMeta _photoIdMeta =
      const VerificationMeta('photoId');
  @override
  late final GeneratedColumn<String> photoId = GeneratedColumn<String>(
      'photo_id', aliasedName, false,
      type: DriftSqlType.string,
      requiredDuringInsert: true,
      defaultConstraints:
          GeneratedColumn.constraintIsAlways('REFERENCES photos (id)'));
  static const VerificationMeta _rawTextMeta =
      const VerificationMeta('rawText');
  @override
  late final GeneratedColumn<String> rawText = GeneratedColumn<String>(
      'text', aliasedName, false,
      type: DriftSqlType.string, requiredDuringInsert: true);
  static const VerificationMeta _confidenceMeta =
      const VerificationMeta('confidence');
  @override
  late final GeneratedColumn<double> confidence = GeneratedColumn<double>(
      'confidence', aliasedName, false,
      type: DriftSqlType.double, requiredDuringInsert: true);
  static const VerificationMeta _boxJsonMeta =
      const VerificationMeta('boxJson');
  @override
  late final GeneratedColumn<String> boxJson = GeneratedColumn<String>(
      'box_json', aliasedName, false,
      type: DriftSqlType.string, requiredDuringInsert: true);
  static const VerificationMeta _pageMeta = const VerificationMeta('page');
  @override
  late final GeneratedColumn<int> page = GeneratedColumn<int>(
      'page', aliasedName, false,
      type: DriftSqlType.int,
      requiredDuringInsert: false,
      defaultValue: const Constant(0));
  @override
  List<GeneratedColumn> get $columns =>
      [id, photoId, rawText, confidence, boxJson, page];
  @override
  String get aliasedName => _alias ?? actualTableName;
  @override
  String get actualTableName => $name;
  static const String $name = 'ocr_tokens';
  @override
  VerificationContext validateIntegrity(Insertable<OcrToken> instance,
      {bool isInserting = false}) {
    final context = VerificationContext();
    final data = instance.toColumns(true);
    if (data.containsKey('id')) {
      context.handle(_idMeta, id.isAcceptableOrUnknown(data['id']!, _idMeta));
    } else if (isInserting) {
      context.missing(_idMeta);
    }
    if (data.containsKey('photo_id')) {
      context.handle(_photoIdMeta,
          photoId.isAcceptableOrUnknown(data['photo_id']!, _photoIdMeta));
    } else if (isInserting) {
      context.missing(_photoIdMeta);
    }
    if (data.containsKey('text')) {
      context.handle(_rawTextMeta,
          rawText.isAcceptableOrUnknown(data['text']!, _rawTextMeta));
    } else if (isInserting) {
      context.missing(_rawTextMeta);
    }
    if (data.containsKey('confidence')) {
      context.handle(
          _confidenceMeta,
          confidence.isAcceptableOrUnknown(
              data['confidence']!, _confidenceMeta));
    } else if (isInserting) {
      context.missing(_confidenceMeta);
    }
    if (data.containsKey('box_json')) {
      context.handle(_boxJsonMeta,
          boxJson.isAcceptableOrUnknown(data['box_json']!, _boxJsonMeta));
    } else if (isInserting) {
      context.missing(_boxJsonMeta);
    }
    if (data.containsKey('page')) {
      context.handle(
          _pageMeta, page.isAcceptableOrUnknown(data['page']!, _pageMeta));
    }
    return context;
  }

  @override
  Set<GeneratedColumn> get $primaryKey => {id};
  @override
  OcrToken map(Map<String, dynamic> data, {String? tablePrefix}) {
    final effectivePrefix = tablePrefix != null ? '$tablePrefix.' : '';
    return OcrToken(
      id: attachedDatabase.typeMapping
          .read(DriftSqlType.string, data['${effectivePrefix}id'])!,
      photoId: attachedDatabase.typeMapping
          .read(DriftSqlType.string, data['${effectivePrefix}photo_id'])!,
      rawText: attachedDatabase.typeMapping
          .read(DriftSqlType.string, data['${effectivePrefix}text'])!,
      confidence: attachedDatabase.typeMapping
          .read(DriftSqlType.double, data['${effectivePrefix}confidence'])!,
      boxJson: attachedDatabase.typeMapping
          .read(DriftSqlType.string, data['${effectivePrefix}box_json'])!,
      page: attachedDatabase.typeMapping
          .read(DriftSqlType.int, data['${effectivePrefix}page'])!,
    );
  }

  @override
  $OcrTokensTable createAlias(String alias) {
    return $OcrTokensTable(attachedDatabase, alias);
  }
}

class OcrToken extends DataClass implements Insertable<OcrToken> {
  final String id;
  final String photoId;

  /// OCR 识别出的原始文本。
  ///
  /// ⚠️ Dart 侧字段名**不能**叫 `text` —— `Table` 基类有 `text()` 方法，
  /// 同名 getter 会把它遮蔽掉，导致本类其余 `text()` 调用全部报
  /// "invocation_of_non_function_expression"，且 drift 生成器直接失败。
  /// 所以用 `named('text')` 保留 SQL 列名不变，只改 Dart 侧标识符。
  final String rawText;
  final double confidence;

  /// 归一化坐标（JSON），用于位置权重
  final String boxJson;
  final int page;
  const OcrToken(
      {required this.id,
      required this.photoId,
      required this.rawText,
      required this.confidence,
      required this.boxJson,
      required this.page});
  @override
  Map<String, Expression> toColumns(bool nullToAbsent) {
    final map = <String, Expression>{};
    map['id'] = Variable<String>(id);
    map['photo_id'] = Variable<String>(photoId);
    map['text'] = Variable<String>(rawText);
    map['confidence'] = Variable<double>(confidence);
    map['box_json'] = Variable<String>(boxJson);
    map['page'] = Variable<int>(page);
    return map;
  }

  OcrTokensCompanion toCompanion(bool nullToAbsent) {
    return OcrTokensCompanion(
      id: Value(id),
      photoId: Value(photoId),
      rawText: Value(rawText),
      confidence: Value(confidence),
      boxJson: Value(boxJson),
      page: Value(page),
    );
  }

  factory OcrToken.fromJson(Map<String, dynamic> json,
      {ValueSerializer? serializer}) {
    serializer ??= driftRuntimeOptions.defaultSerializer;
    return OcrToken(
      id: serializer.fromJson<String>(json['id']),
      photoId: serializer.fromJson<String>(json['photoId']),
      rawText: serializer.fromJson<String>(json['rawText']),
      confidence: serializer.fromJson<double>(json['confidence']),
      boxJson: serializer.fromJson<String>(json['boxJson']),
      page: serializer.fromJson<int>(json['page']),
    );
  }
  @override
  Map<String, dynamic> toJson({ValueSerializer? serializer}) {
    serializer ??= driftRuntimeOptions.defaultSerializer;
    return <String, dynamic>{
      'id': serializer.toJson<String>(id),
      'photoId': serializer.toJson<String>(photoId),
      'rawText': serializer.toJson<String>(rawText),
      'confidence': serializer.toJson<double>(confidence),
      'boxJson': serializer.toJson<String>(boxJson),
      'page': serializer.toJson<int>(page),
    };
  }

  OcrToken copyWith(
          {String? id,
          String? photoId,
          String? rawText,
          double? confidence,
          String? boxJson,
          int? page}) =>
      OcrToken(
        id: id ?? this.id,
        photoId: photoId ?? this.photoId,
        rawText: rawText ?? this.rawText,
        confidence: confidence ?? this.confidence,
        boxJson: boxJson ?? this.boxJson,
        page: page ?? this.page,
      );
  OcrToken copyWithCompanion(OcrTokensCompanion data) {
    return OcrToken(
      id: data.id.present ? data.id.value : this.id,
      photoId: data.photoId.present ? data.photoId.value : this.photoId,
      rawText: data.rawText.present ? data.rawText.value : this.rawText,
      confidence:
          data.confidence.present ? data.confidence.value : this.confidence,
      boxJson: data.boxJson.present ? data.boxJson.value : this.boxJson,
      page: data.page.present ? data.page.value : this.page,
    );
  }

  @override
  String toString() {
    return (StringBuffer('OcrToken(')
          ..write('id: $id, ')
          ..write('photoId: $photoId, ')
          ..write('rawText: $rawText, ')
          ..write('confidence: $confidence, ')
          ..write('boxJson: $boxJson, ')
          ..write('page: $page')
          ..write(')'))
        .toString();
  }

  @override
  int get hashCode =>
      Object.hash(id, photoId, rawText, confidence, boxJson, page);
  @override
  bool operator ==(Object other) =>
      identical(this, other) ||
      (other is OcrToken &&
          other.id == this.id &&
          other.photoId == this.photoId &&
          other.rawText == this.rawText &&
          other.confidence == this.confidence &&
          other.boxJson == this.boxJson &&
          other.page == this.page);
}

class OcrTokensCompanion extends UpdateCompanion<OcrToken> {
  final Value<String> id;
  final Value<String> photoId;
  final Value<String> rawText;
  final Value<double> confidence;
  final Value<String> boxJson;
  final Value<int> page;
  final Value<int> rowid;
  const OcrTokensCompanion({
    this.id = const Value.absent(),
    this.photoId = const Value.absent(),
    this.rawText = const Value.absent(),
    this.confidence = const Value.absent(),
    this.boxJson = const Value.absent(),
    this.page = const Value.absent(),
    this.rowid = const Value.absent(),
  });
  OcrTokensCompanion.insert({
    required String id,
    required String photoId,
    required String rawText,
    required double confidence,
    required String boxJson,
    this.page = const Value.absent(),
    this.rowid = const Value.absent(),
  })  : id = Value(id),
        photoId = Value(photoId),
        rawText = Value(rawText),
        confidence = Value(confidence),
        boxJson = Value(boxJson);
  static Insertable<OcrToken> custom({
    Expression<String>? id,
    Expression<String>? photoId,
    Expression<String>? rawText,
    Expression<double>? confidence,
    Expression<String>? boxJson,
    Expression<int>? page,
    Expression<int>? rowid,
  }) {
    return RawValuesInsertable({
      if (id != null) 'id': id,
      if (photoId != null) 'photo_id': photoId,
      if (rawText != null) 'text': rawText,
      if (confidence != null) 'confidence': confidence,
      if (boxJson != null) 'box_json': boxJson,
      if (page != null) 'page': page,
      if (rowid != null) 'rowid': rowid,
    });
  }

  OcrTokensCompanion copyWith(
      {Value<String>? id,
      Value<String>? photoId,
      Value<String>? rawText,
      Value<double>? confidence,
      Value<String>? boxJson,
      Value<int>? page,
      Value<int>? rowid}) {
    return OcrTokensCompanion(
      id: id ?? this.id,
      photoId: photoId ?? this.photoId,
      rawText: rawText ?? this.rawText,
      confidence: confidence ?? this.confidence,
      boxJson: boxJson ?? this.boxJson,
      page: page ?? this.page,
      rowid: rowid ?? this.rowid,
    );
  }

  @override
  Map<String, Expression> toColumns(bool nullToAbsent) {
    final map = <String, Expression>{};
    if (id.present) {
      map['id'] = Variable<String>(id.value);
    }
    if (photoId.present) {
      map['photo_id'] = Variable<String>(photoId.value);
    }
    if (rawText.present) {
      map['text'] = Variable<String>(rawText.value);
    }
    if (confidence.present) {
      map['confidence'] = Variable<double>(confidence.value);
    }
    if (boxJson.present) {
      map['box_json'] = Variable<String>(boxJson.value);
    }
    if (page.present) {
      map['page'] = Variable<int>(page.value);
    }
    if (rowid.present) {
      map['rowid'] = Variable<int>(rowid.value);
    }
    return map;
  }

  @override
  String toString() {
    return (StringBuffer('OcrTokensCompanion(')
          ..write('id: $id, ')
          ..write('photoId: $photoId, ')
          ..write('rawText: $rawText, ')
          ..write('confidence: $confidence, ')
          ..write('boxJson: $boxJson, ')
          ..write('page: $page, ')
          ..write('rowid: $rowid')
          ..write(')'))
        .toString();
  }
}

class $AssignmentsTable extends Assignments
    with TableInfo<$AssignmentsTable, Assignment> {
  @override
  final GeneratedDatabase attachedDatabase;
  final String? _alias;
  $AssignmentsTable(this.attachedDatabase, [this._alias]);
  static const VerificationMeta _idMeta = const VerificationMeta('id');
  @override
  late final GeneratedColumn<String> id = GeneratedColumn<String>(
      'id', aliasedName, false,
      type: DriftSqlType.string, requiredDuringInsert: true);
  static const VerificationMeta _projectIdMeta =
      const VerificationMeta('projectId');
  @override
  late final GeneratedColumn<String> projectId = GeneratedColumn<String>(
      'project_id', aliasedName, false,
      type: DriftSqlType.string,
      requiredDuringInsert: true,
      defaultConstraints:
          GeneratedColumn.constraintIsAlways('REFERENCES projects (id)'));
  static const VerificationMeta _targetTypeMeta =
      const VerificationMeta('targetType');
  @override
  late final GeneratedColumn<String> targetType = GeneratedColumn<String>(
      'target_type', aliasedName, false,
      type: DriftSqlType.string, requiredDuringInsert: true);
  static const VerificationMeta _targetIdMeta =
      const VerificationMeta('targetId');
  @override
  late final GeneratedColumn<String> targetId = GeneratedColumn<String>(
      'target_id', aliasedName, false,
      type: DriftSqlType.string, requiredDuringInsert: true);
  static const VerificationMeta _itemIdMeta = const VerificationMeta('itemId');
  @override
  late final GeneratedColumn<String> itemId = GeneratedColumn<String>(
      'item_id', aliasedName, false,
      type: DriftSqlType.string, requiredDuringInsert: true);
  static const VerificationMeta _sourceMeta = const VerificationMeta('source');
  @override
  late final GeneratedColumn<String> source = GeneratedColumn<String>(
      'source', aliasedName, false,
      type: DriftSqlType.string, requiredDuringInsert: true);
  static const VerificationMeta _suggestedItemIdMeta =
      const VerificationMeta('suggestedItemId');
  @override
  late final GeneratedColumn<String> suggestedItemId = GeneratedColumn<String>(
      'suggested_item_id', aliasedName, true,
      type: DriftSqlType.string, requiredDuringInsert: false);
  static const VerificationMeta _suggestionConfMeta =
      const VerificationMeta('suggestionConf');
  @override
  late final GeneratedColumn<double> suggestionConf = GeneratedColumn<double>(
      'suggestion_conf', aliasedName, true,
      type: DriftSqlType.double, requiredDuringInsert: false);
  static const VerificationMeta _confirmedAtMeta =
      const VerificationMeta('confirmedAt');
  @override
  late final GeneratedColumn<int> confirmedAt = GeneratedColumn<int>(
      'confirmed_at', aliasedName, false,
      type: DriftSqlType.int, requiredDuringInsert: true);
  static const VerificationMeta _confirmedByMeta =
      const VerificationMeta('confirmedBy');
  @override
  late final GeneratedColumn<String> confirmedBy = GeneratedColumn<String>(
      'confirmed_by', aliasedName, false,
      type: DriftSqlType.string, requiredDuringInsert: true);
  static const VerificationMeta _revokedAtMeta =
      const VerificationMeta('revokedAt');
  @override
  late final GeneratedColumn<int> revokedAt = GeneratedColumn<int>(
      'revoked_at', aliasedName, true,
      type: DriftSqlType.int, requiredDuringInsert: false);
  static const VerificationMeta _noteMeta = const VerificationMeta('note');
  @override
  late final GeneratedColumn<String> note = GeneratedColumn<String>(
      'note', aliasedName, true,
      type: DriftSqlType.string, requiredDuringInsert: false);
  @override
  List<GeneratedColumn> get $columns => [
        id,
        projectId,
        targetType,
        targetId,
        itemId,
        source,
        suggestedItemId,
        suggestionConf,
        confirmedAt,
        confirmedBy,
        revokedAt,
        note
      ];
  @override
  String get aliasedName => _alias ?? actualTableName;
  @override
  String get actualTableName => $name;
  static const String $name = 'assignments';
  @override
  VerificationContext validateIntegrity(Insertable<Assignment> instance,
      {bool isInserting = false}) {
    final context = VerificationContext();
    final data = instance.toColumns(true);
    if (data.containsKey('id')) {
      context.handle(_idMeta, id.isAcceptableOrUnknown(data['id']!, _idMeta));
    } else if (isInserting) {
      context.missing(_idMeta);
    }
    if (data.containsKey('project_id')) {
      context.handle(_projectIdMeta,
          projectId.isAcceptableOrUnknown(data['project_id']!, _projectIdMeta));
    } else if (isInserting) {
      context.missing(_projectIdMeta);
    }
    if (data.containsKey('target_type')) {
      context.handle(
          _targetTypeMeta,
          targetType.isAcceptableOrUnknown(
              data['target_type']!, _targetTypeMeta));
    } else if (isInserting) {
      context.missing(_targetTypeMeta);
    }
    if (data.containsKey('target_id')) {
      context.handle(_targetIdMeta,
          targetId.isAcceptableOrUnknown(data['target_id']!, _targetIdMeta));
    } else if (isInserting) {
      context.missing(_targetIdMeta);
    }
    if (data.containsKey('item_id')) {
      context.handle(_itemIdMeta,
          itemId.isAcceptableOrUnknown(data['item_id']!, _itemIdMeta));
    } else if (isInserting) {
      context.missing(_itemIdMeta);
    }
    if (data.containsKey('source')) {
      context.handle(_sourceMeta,
          source.isAcceptableOrUnknown(data['source']!, _sourceMeta));
    } else if (isInserting) {
      context.missing(_sourceMeta);
    }
    if (data.containsKey('suggested_item_id')) {
      context.handle(
          _suggestedItemIdMeta,
          suggestedItemId.isAcceptableOrUnknown(
              data['suggested_item_id']!, _suggestedItemIdMeta));
    }
    if (data.containsKey('suggestion_conf')) {
      context.handle(
          _suggestionConfMeta,
          suggestionConf.isAcceptableOrUnknown(
              data['suggestion_conf']!, _suggestionConfMeta));
    }
    if (data.containsKey('confirmed_at')) {
      context.handle(
          _confirmedAtMeta,
          confirmedAt.isAcceptableOrUnknown(
              data['confirmed_at']!, _confirmedAtMeta));
    } else if (isInserting) {
      context.missing(_confirmedAtMeta);
    }
    if (data.containsKey('confirmed_by')) {
      context.handle(
          _confirmedByMeta,
          confirmedBy.isAcceptableOrUnknown(
              data['confirmed_by']!, _confirmedByMeta));
    } else if (isInserting) {
      context.missing(_confirmedByMeta);
    }
    if (data.containsKey('revoked_at')) {
      context.handle(_revokedAtMeta,
          revokedAt.isAcceptableOrUnknown(data['revoked_at']!, _revokedAtMeta));
    }
    if (data.containsKey('note')) {
      context.handle(
          _noteMeta, note.isAcceptableOrUnknown(data['note']!, _noteMeta));
    }
    return context;
  }

  @override
  Set<GeneratedColumn> get $primaryKey => {id};
  @override
  Assignment map(Map<String, dynamic> data, {String? tablePrefix}) {
    final effectivePrefix = tablePrefix != null ? '$tablePrefix.' : '';
    return Assignment(
      id: attachedDatabase.typeMapping
          .read(DriftSqlType.string, data['${effectivePrefix}id'])!,
      projectId: attachedDatabase.typeMapping
          .read(DriftSqlType.string, data['${effectivePrefix}project_id'])!,
      targetType: attachedDatabase.typeMapping
          .read(DriftSqlType.string, data['${effectivePrefix}target_type'])!,
      targetId: attachedDatabase.typeMapping
          .read(DriftSqlType.string, data['${effectivePrefix}target_id'])!,
      itemId: attachedDatabase.typeMapping
          .read(DriftSqlType.string, data['${effectivePrefix}item_id'])!,
      source: attachedDatabase.typeMapping
          .read(DriftSqlType.string, data['${effectivePrefix}source'])!,
      suggestedItemId: attachedDatabase.typeMapping.read(
          DriftSqlType.string, data['${effectivePrefix}suggested_item_id']),
      suggestionConf: attachedDatabase.typeMapping
          .read(DriftSqlType.double, data['${effectivePrefix}suggestion_conf']),
      confirmedAt: attachedDatabase.typeMapping
          .read(DriftSqlType.int, data['${effectivePrefix}confirmed_at'])!,
      confirmedBy: attachedDatabase.typeMapping
          .read(DriftSqlType.string, data['${effectivePrefix}confirmed_by'])!,
      revokedAt: attachedDatabase.typeMapping
          .read(DriftSqlType.int, data['${effectivePrefix}revoked_at']),
      note: attachedDatabase.typeMapping
          .read(DriftSqlType.string, data['${effectivePrefix}note']),
    );
  }

  @override
  $AssignmentsTable createAlias(String alias) {
    return $AssignmentsTable(attachedDatabase, alias);
  }
}

class Assignment extends DataClass implements Insertable<Assignment> {
  final String id;
  final String projectId;

  /// AssignTargetType.code: photo / group
  final String targetType;
  final String targetId;
  final String itemId;

  /// AssignSource.code
  final String source;

  /// 当时的机器建议是什么 —— 用于统计"建议采纳率"
  final String? suggestedItemId;
  final double? suggestionConf;

  /// ★ 非空。这是"人做决定"原则的落点。
  final int confirmedAt;

  /// 免登录下的最小身份标识（设备昵称）
  final String confirmedBy;

  /// 撤销时间。**撤销是打标记，不是删除** —— 留痕。
  final int? revokedAt;
  final String? note;
  const Assignment(
      {required this.id,
      required this.projectId,
      required this.targetType,
      required this.targetId,
      required this.itemId,
      required this.source,
      this.suggestedItemId,
      this.suggestionConf,
      required this.confirmedAt,
      required this.confirmedBy,
      this.revokedAt,
      this.note});
  @override
  Map<String, Expression> toColumns(bool nullToAbsent) {
    final map = <String, Expression>{};
    map['id'] = Variable<String>(id);
    map['project_id'] = Variable<String>(projectId);
    map['target_type'] = Variable<String>(targetType);
    map['target_id'] = Variable<String>(targetId);
    map['item_id'] = Variable<String>(itemId);
    map['source'] = Variable<String>(source);
    if (!nullToAbsent || suggestedItemId != null) {
      map['suggested_item_id'] = Variable<String>(suggestedItemId);
    }
    if (!nullToAbsent || suggestionConf != null) {
      map['suggestion_conf'] = Variable<double>(suggestionConf);
    }
    map['confirmed_at'] = Variable<int>(confirmedAt);
    map['confirmed_by'] = Variable<String>(confirmedBy);
    if (!nullToAbsent || revokedAt != null) {
      map['revoked_at'] = Variable<int>(revokedAt);
    }
    if (!nullToAbsent || note != null) {
      map['note'] = Variable<String>(note);
    }
    return map;
  }

  AssignmentsCompanion toCompanion(bool nullToAbsent) {
    return AssignmentsCompanion(
      id: Value(id),
      projectId: Value(projectId),
      targetType: Value(targetType),
      targetId: Value(targetId),
      itemId: Value(itemId),
      source: Value(source),
      suggestedItemId: suggestedItemId == null && nullToAbsent
          ? const Value.absent()
          : Value(suggestedItemId),
      suggestionConf: suggestionConf == null && nullToAbsent
          ? const Value.absent()
          : Value(suggestionConf),
      confirmedAt: Value(confirmedAt),
      confirmedBy: Value(confirmedBy),
      revokedAt: revokedAt == null && nullToAbsent
          ? const Value.absent()
          : Value(revokedAt),
      note: note == null && nullToAbsent ? const Value.absent() : Value(note),
    );
  }

  factory Assignment.fromJson(Map<String, dynamic> json,
      {ValueSerializer? serializer}) {
    serializer ??= driftRuntimeOptions.defaultSerializer;
    return Assignment(
      id: serializer.fromJson<String>(json['id']),
      projectId: serializer.fromJson<String>(json['projectId']),
      targetType: serializer.fromJson<String>(json['targetType']),
      targetId: serializer.fromJson<String>(json['targetId']),
      itemId: serializer.fromJson<String>(json['itemId']),
      source: serializer.fromJson<String>(json['source']),
      suggestedItemId: serializer.fromJson<String?>(json['suggestedItemId']),
      suggestionConf: serializer.fromJson<double?>(json['suggestionConf']),
      confirmedAt: serializer.fromJson<int>(json['confirmedAt']),
      confirmedBy: serializer.fromJson<String>(json['confirmedBy']),
      revokedAt: serializer.fromJson<int?>(json['revokedAt']),
      note: serializer.fromJson<String?>(json['note']),
    );
  }
  @override
  Map<String, dynamic> toJson({ValueSerializer? serializer}) {
    serializer ??= driftRuntimeOptions.defaultSerializer;
    return <String, dynamic>{
      'id': serializer.toJson<String>(id),
      'projectId': serializer.toJson<String>(projectId),
      'targetType': serializer.toJson<String>(targetType),
      'targetId': serializer.toJson<String>(targetId),
      'itemId': serializer.toJson<String>(itemId),
      'source': serializer.toJson<String>(source),
      'suggestedItemId': serializer.toJson<String?>(suggestedItemId),
      'suggestionConf': serializer.toJson<double?>(suggestionConf),
      'confirmedAt': serializer.toJson<int>(confirmedAt),
      'confirmedBy': serializer.toJson<String>(confirmedBy),
      'revokedAt': serializer.toJson<int?>(revokedAt),
      'note': serializer.toJson<String?>(note),
    };
  }

  Assignment copyWith(
          {String? id,
          String? projectId,
          String? targetType,
          String? targetId,
          String? itemId,
          String? source,
          Value<String?> suggestedItemId = const Value.absent(),
          Value<double?> suggestionConf = const Value.absent(),
          int? confirmedAt,
          String? confirmedBy,
          Value<int?> revokedAt = const Value.absent(),
          Value<String?> note = const Value.absent()}) =>
      Assignment(
        id: id ?? this.id,
        projectId: projectId ?? this.projectId,
        targetType: targetType ?? this.targetType,
        targetId: targetId ?? this.targetId,
        itemId: itemId ?? this.itemId,
        source: source ?? this.source,
        suggestedItemId: suggestedItemId.present
            ? suggestedItemId.value
            : this.suggestedItemId,
        suggestionConf:
            suggestionConf.present ? suggestionConf.value : this.suggestionConf,
        confirmedAt: confirmedAt ?? this.confirmedAt,
        confirmedBy: confirmedBy ?? this.confirmedBy,
        revokedAt: revokedAt.present ? revokedAt.value : this.revokedAt,
        note: note.present ? note.value : this.note,
      );
  Assignment copyWithCompanion(AssignmentsCompanion data) {
    return Assignment(
      id: data.id.present ? data.id.value : this.id,
      projectId: data.projectId.present ? data.projectId.value : this.projectId,
      targetType:
          data.targetType.present ? data.targetType.value : this.targetType,
      targetId: data.targetId.present ? data.targetId.value : this.targetId,
      itemId: data.itemId.present ? data.itemId.value : this.itemId,
      source: data.source.present ? data.source.value : this.source,
      suggestedItemId: data.suggestedItemId.present
          ? data.suggestedItemId.value
          : this.suggestedItemId,
      suggestionConf: data.suggestionConf.present
          ? data.suggestionConf.value
          : this.suggestionConf,
      confirmedAt:
          data.confirmedAt.present ? data.confirmedAt.value : this.confirmedAt,
      confirmedBy:
          data.confirmedBy.present ? data.confirmedBy.value : this.confirmedBy,
      revokedAt: data.revokedAt.present ? data.revokedAt.value : this.revokedAt,
      note: data.note.present ? data.note.value : this.note,
    );
  }

  @override
  String toString() {
    return (StringBuffer('Assignment(')
          ..write('id: $id, ')
          ..write('projectId: $projectId, ')
          ..write('targetType: $targetType, ')
          ..write('targetId: $targetId, ')
          ..write('itemId: $itemId, ')
          ..write('source: $source, ')
          ..write('suggestedItemId: $suggestedItemId, ')
          ..write('suggestionConf: $suggestionConf, ')
          ..write('confirmedAt: $confirmedAt, ')
          ..write('confirmedBy: $confirmedBy, ')
          ..write('revokedAt: $revokedAt, ')
          ..write('note: $note')
          ..write(')'))
        .toString();
  }

  @override
  int get hashCode => Object.hash(
      id,
      projectId,
      targetType,
      targetId,
      itemId,
      source,
      suggestedItemId,
      suggestionConf,
      confirmedAt,
      confirmedBy,
      revokedAt,
      note);
  @override
  bool operator ==(Object other) =>
      identical(this, other) ||
      (other is Assignment &&
          other.id == this.id &&
          other.projectId == this.projectId &&
          other.targetType == this.targetType &&
          other.targetId == this.targetId &&
          other.itemId == this.itemId &&
          other.source == this.source &&
          other.suggestedItemId == this.suggestedItemId &&
          other.suggestionConf == this.suggestionConf &&
          other.confirmedAt == this.confirmedAt &&
          other.confirmedBy == this.confirmedBy &&
          other.revokedAt == this.revokedAt &&
          other.note == this.note);
}

class AssignmentsCompanion extends UpdateCompanion<Assignment> {
  final Value<String> id;
  final Value<String> projectId;
  final Value<String> targetType;
  final Value<String> targetId;
  final Value<String> itemId;
  final Value<String> source;
  final Value<String?> suggestedItemId;
  final Value<double?> suggestionConf;
  final Value<int> confirmedAt;
  final Value<String> confirmedBy;
  final Value<int?> revokedAt;
  final Value<String?> note;
  final Value<int> rowid;
  const AssignmentsCompanion({
    this.id = const Value.absent(),
    this.projectId = const Value.absent(),
    this.targetType = const Value.absent(),
    this.targetId = const Value.absent(),
    this.itemId = const Value.absent(),
    this.source = const Value.absent(),
    this.suggestedItemId = const Value.absent(),
    this.suggestionConf = const Value.absent(),
    this.confirmedAt = const Value.absent(),
    this.confirmedBy = const Value.absent(),
    this.revokedAt = const Value.absent(),
    this.note = const Value.absent(),
    this.rowid = const Value.absent(),
  });
  AssignmentsCompanion.insert({
    required String id,
    required String projectId,
    required String targetType,
    required String targetId,
    required String itemId,
    required String source,
    this.suggestedItemId = const Value.absent(),
    this.suggestionConf = const Value.absent(),
    required int confirmedAt,
    required String confirmedBy,
    this.revokedAt = const Value.absent(),
    this.note = const Value.absent(),
    this.rowid = const Value.absent(),
  })  : id = Value(id),
        projectId = Value(projectId),
        targetType = Value(targetType),
        targetId = Value(targetId),
        itemId = Value(itemId),
        source = Value(source),
        confirmedAt = Value(confirmedAt),
        confirmedBy = Value(confirmedBy);
  static Insertable<Assignment> custom({
    Expression<String>? id,
    Expression<String>? projectId,
    Expression<String>? targetType,
    Expression<String>? targetId,
    Expression<String>? itemId,
    Expression<String>? source,
    Expression<String>? suggestedItemId,
    Expression<double>? suggestionConf,
    Expression<int>? confirmedAt,
    Expression<String>? confirmedBy,
    Expression<int>? revokedAt,
    Expression<String>? note,
    Expression<int>? rowid,
  }) {
    return RawValuesInsertable({
      if (id != null) 'id': id,
      if (projectId != null) 'project_id': projectId,
      if (targetType != null) 'target_type': targetType,
      if (targetId != null) 'target_id': targetId,
      if (itemId != null) 'item_id': itemId,
      if (source != null) 'source': source,
      if (suggestedItemId != null) 'suggested_item_id': suggestedItemId,
      if (suggestionConf != null) 'suggestion_conf': suggestionConf,
      if (confirmedAt != null) 'confirmed_at': confirmedAt,
      if (confirmedBy != null) 'confirmed_by': confirmedBy,
      if (revokedAt != null) 'revoked_at': revokedAt,
      if (note != null) 'note': note,
      if (rowid != null) 'rowid': rowid,
    });
  }

  AssignmentsCompanion copyWith(
      {Value<String>? id,
      Value<String>? projectId,
      Value<String>? targetType,
      Value<String>? targetId,
      Value<String>? itemId,
      Value<String>? source,
      Value<String?>? suggestedItemId,
      Value<double?>? suggestionConf,
      Value<int>? confirmedAt,
      Value<String>? confirmedBy,
      Value<int?>? revokedAt,
      Value<String?>? note,
      Value<int>? rowid}) {
    return AssignmentsCompanion(
      id: id ?? this.id,
      projectId: projectId ?? this.projectId,
      targetType: targetType ?? this.targetType,
      targetId: targetId ?? this.targetId,
      itemId: itemId ?? this.itemId,
      source: source ?? this.source,
      suggestedItemId: suggestedItemId ?? this.suggestedItemId,
      suggestionConf: suggestionConf ?? this.suggestionConf,
      confirmedAt: confirmedAt ?? this.confirmedAt,
      confirmedBy: confirmedBy ?? this.confirmedBy,
      revokedAt: revokedAt ?? this.revokedAt,
      note: note ?? this.note,
      rowid: rowid ?? this.rowid,
    );
  }

  @override
  Map<String, Expression> toColumns(bool nullToAbsent) {
    final map = <String, Expression>{};
    if (id.present) {
      map['id'] = Variable<String>(id.value);
    }
    if (projectId.present) {
      map['project_id'] = Variable<String>(projectId.value);
    }
    if (targetType.present) {
      map['target_type'] = Variable<String>(targetType.value);
    }
    if (targetId.present) {
      map['target_id'] = Variable<String>(targetId.value);
    }
    if (itemId.present) {
      map['item_id'] = Variable<String>(itemId.value);
    }
    if (source.present) {
      map['source'] = Variable<String>(source.value);
    }
    if (suggestedItemId.present) {
      map['suggested_item_id'] = Variable<String>(suggestedItemId.value);
    }
    if (suggestionConf.present) {
      map['suggestion_conf'] = Variable<double>(suggestionConf.value);
    }
    if (confirmedAt.present) {
      map['confirmed_at'] = Variable<int>(confirmedAt.value);
    }
    if (confirmedBy.present) {
      map['confirmed_by'] = Variable<String>(confirmedBy.value);
    }
    if (revokedAt.present) {
      map['revoked_at'] = Variable<int>(revokedAt.value);
    }
    if (note.present) {
      map['note'] = Variable<String>(note.value);
    }
    if (rowid.present) {
      map['rowid'] = Variable<int>(rowid.value);
    }
    return map;
  }

  @override
  String toString() {
    return (StringBuffer('AssignmentsCompanion(')
          ..write('id: $id, ')
          ..write('projectId: $projectId, ')
          ..write('targetType: $targetType, ')
          ..write('targetId: $targetId, ')
          ..write('itemId: $itemId, ')
          ..write('source: $source, ')
          ..write('suggestedItemId: $suggestedItemId, ')
          ..write('suggestionConf: $suggestionConf, ')
          ..write('confirmedAt: $confirmedAt, ')
          ..write('confirmedBy: $confirmedBy, ')
          ..write('revokedAt: $revokedAt, ')
          ..write('note: $note, ')
          ..write('rowid: $rowid')
          ..write(')'))
        .toString();
  }
}

class $DeliveriesTable extends Deliveries
    with TableInfo<$DeliveriesTable, Delivery> {
  @override
  final GeneratedDatabase attachedDatabase;
  final String? _alias;
  $DeliveriesTable(this.attachedDatabase, [this._alias]);
  static const VerificationMeta _idMeta = const VerificationMeta('id');
  @override
  late final GeneratedColumn<String> id = GeneratedColumn<String>(
      'id', aliasedName, false,
      type: DriftSqlType.string, requiredDuringInsert: true);
  static const VerificationMeta _projectIdMeta =
      const VerificationMeta('projectId');
  @override
  late final GeneratedColumn<String> projectId = GeneratedColumn<String>(
      'project_id', aliasedName, false,
      type: DriftSqlType.string,
      requiredDuringInsert: true,
      defaultConstraints:
          GeneratedColumn.constraintIsAlways('REFERENCES projects (id)'));
  static const VerificationMeta _createdAtMeta =
      const VerificationMeta('createdAt');
  @override
  late final GeneratedColumn<int> createdAt = GeneratedColumn<int>(
      'created_at', aliasedName, false,
      type: DriftSqlType.int, requiredDuringInsert: true);
  static const VerificationMeta _optionsJsonMeta =
      const VerificationMeta('optionsJson');
  @override
  late final GeneratedColumn<String> optionsJson = GeneratedColumn<String>(
      'options_json', aliasedName, false,
      type: DriftSqlType.string, requiredDuringInsert: true);
  static const VerificationMeta _zipPathMeta =
      const VerificationMeta('zipPath');
  @override
  late final GeneratedColumn<String> zipPath = GeneratedColumn<String>(
      'zip_path', aliasedName, true,
      type: DriftSqlType.string, requiredDuringInsert: false);
  static const VerificationMeta _pdfPathMeta =
      const VerificationMeta('pdfPath');
  @override
  late final GeneratedColumn<String> pdfPath = GeneratedColumn<String>(
      'pdf_path', aliasedName, true,
      type: DriftSqlType.string, requiredDuringInsert: false);
  static const VerificationMeta _bytesMeta = const VerificationMeta('bytes');
  @override
  late final GeneratedColumn<int> bytes = GeneratedColumn<int>(
      'bytes', aliasedName, true,
      type: DriftSqlType.int, requiredDuringInsert: false);
  static const VerificationMeta _itemCountMeta =
      const VerificationMeta('itemCount');
  @override
  late final GeneratedColumn<int> itemCount = GeneratedColumn<int>(
      'item_count', aliasedName, true,
      type: DriftSqlType.int, requiredDuringInsert: false);
  static const VerificationMeta _photoCountMeta =
      const VerificationMeta('photoCount');
  @override
  late final GeneratedColumn<int> photoCount = GeneratedColumn<int>(
      'photo_count', aliasedName, true,
      type: DriftSqlType.int, requiredDuringInsert: false);
  static const VerificationMeta _sha256Meta = const VerificationMeta('sha256');
  @override
  late final GeneratedColumn<String> sha256 = GeneratedColumn<String>(
      'sha256', aliasedName, true,
      type: DriftSqlType.string, requiredDuringInsert: false);
  static const VerificationMeta _sharedAtMeta =
      const VerificationMeta('sharedAt');
  @override
  late final GeneratedColumn<int> sharedAt = GeneratedColumn<int>(
      'shared_at', aliasedName, true,
      type: DriftSqlType.int, requiredDuringInsert: false);
  static const VerificationMeta _webdavPathMeta =
      const VerificationMeta('webdavPath');
  @override
  late final GeneratedColumn<String> webdavPath = GeneratedColumn<String>(
      'webdav_path', aliasedName, true,
      type: DriftSqlType.string, requiredDuringInsert: false);
  @override
  List<GeneratedColumn> get $columns => [
        id,
        projectId,
        createdAt,
        optionsJson,
        zipPath,
        pdfPath,
        bytes,
        itemCount,
        photoCount,
        sha256,
        sharedAt,
        webdavPath
      ];
  @override
  String get aliasedName => _alias ?? actualTableName;
  @override
  String get actualTableName => $name;
  static const String $name = 'deliveries';
  @override
  VerificationContext validateIntegrity(Insertable<Delivery> instance,
      {bool isInserting = false}) {
    final context = VerificationContext();
    final data = instance.toColumns(true);
    if (data.containsKey('id')) {
      context.handle(_idMeta, id.isAcceptableOrUnknown(data['id']!, _idMeta));
    } else if (isInserting) {
      context.missing(_idMeta);
    }
    if (data.containsKey('project_id')) {
      context.handle(_projectIdMeta,
          projectId.isAcceptableOrUnknown(data['project_id']!, _projectIdMeta));
    } else if (isInserting) {
      context.missing(_projectIdMeta);
    }
    if (data.containsKey('created_at')) {
      context.handle(_createdAtMeta,
          createdAt.isAcceptableOrUnknown(data['created_at']!, _createdAtMeta));
    } else if (isInserting) {
      context.missing(_createdAtMeta);
    }
    if (data.containsKey('options_json')) {
      context.handle(
          _optionsJsonMeta,
          optionsJson.isAcceptableOrUnknown(
              data['options_json']!, _optionsJsonMeta));
    } else if (isInserting) {
      context.missing(_optionsJsonMeta);
    }
    if (data.containsKey('zip_path')) {
      context.handle(_zipPathMeta,
          zipPath.isAcceptableOrUnknown(data['zip_path']!, _zipPathMeta));
    }
    if (data.containsKey('pdf_path')) {
      context.handle(_pdfPathMeta,
          pdfPath.isAcceptableOrUnknown(data['pdf_path']!, _pdfPathMeta));
    }
    if (data.containsKey('bytes')) {
      context.handle(
          _bytesMeta, bytes.isAcceptableOrUnknown(data['bytes']!, _bytesMeta));
    }
    if (data.containsKey('item_count')) {
      context.handle(_itemCountMeta,
          itemCount.isAcceptableOrUnknown(data['item_count']!, _itemCountMeta));
    }
    if (data.containsKey('photo_count')) {
      context.handle(
          _photoCountMeta,
          photoCount.isAcceptableOrUnknown(
              data['photo_count']!, _photoCountMeta));
    }
    if (data.containsKey('sha256')) {
      context.handle(_sha256Meta,
          sha256.isAcceptableOrUnknown(data['sha256']!, _sha256Meta));
    }
    if (data.containsKey('shared_at')) {
      context.handle(_sharedAtMeta,
          sharedAt.isAcceptableOrUnknown(data['shared_at']!, _sharedAtMeta));
    }
    if (data.containsKey('webdav_path')) {
      context.handle(
          _webdavPathMeta,
          webdavPath.isAcceptableOrUnknown(
              data['webdav_path']!, _webdavPathMeta));
    }
    return context;
  }

  @override
  Set<GeneratedColumn> get $primaryKey => {id};
  @override
  Delivery map(Map<String, dynamic> data, {String? tablePrefix}) {
    final effectivePrefix = tablePrefix != null ? '$tablePrefix.' : '';
    return Delivery(
      id: attachedDatabase.typeMapping
          .read(DriftSqlType.string, data['${effectivePrefix}id'])!,
      projectId: attachedDatabase.typeMapping
          .read(DriftSqlType.string, data['${effectivePrefix}project_id'])!,
      createdAt: attachedDatabase.typeMapping
          .read(DriftSqlType.int, data['${effectivePrefix}created_at'])!,
      optionsJson: attachedDatabase.typeMapping
          .read(DriftSqlType.string, data['${effectivePrefix}options_json'])!,
      zipPath: attachedDatabase.typeMapping
          .read(DriftSqlType.string, data['${effectivePrefix}zip_path']),
      pdfPath: attachedDatabase.typeMapping
          .read(DriftSqlType.string, data['${effectivePrefix}pdf_path']),
      bytes: attachedDatabase.typeMapping
          .read(DriftSqlType.int, data['${effectivePrefix}bytes']),
      itemCount: attachedDatabase.typeMapping
          .read(DriftSqlType.int, data['${effectivePrefix}item_count']),
      photoCount: attachedDatabase.typeMapping
          .read(DriftSqlType.int, data['${effectivePrefix}photo_count']),
      sha256: attachedDatabase.typeMapping
          .read(DriftSqlType.string, data['${effectivePrefix}sha256']),
      sharedAt: attachedDatabase.typeMapping
          .read(DriftSqlType.int, data['${effectivePrefix}shared_at']),
      webdavPath: attachedDatabase.typeMapping
          .read(DriftSqlType.string, data['${effectivePrefix}webdav_path']),
    );
  }

  @override
  $DeliveriesTable createAlias(String alias) {
    return $DeliveriesTable(attachedDatabase, alias);
  }
}

class Delivery extends DataClass implements Insertable<Delivery> {
  final String id;
  final String projectId;
  final int createdAt;

  /// includeRaw / includeManifest / includeUnused / groupByCarton
  final String optionsJson;
  final String? zipPath;
  final String? pdfPath;
  final int? bytes;
  final int? itemCount;
  final int? photoCount;
  final String? sha256;
  final int? sharedAt;
  final String? webdavPath;
  const Delivery(
      {required this.id,
      required this.projectId,
      required this.createdAt,
      required this.optionsJson,
      this.zipPath,
      this.pdfPath,
      this.bytes,
      this.itemCount,
      this.photoCount,
      this.sha256,
      this.sharedAt,
      this.webdavPath});
  @override
  Map<String, Expression> toColumns(bool nullToAbsent) {
    final map = <String, Expression>{};
    map['id'] = Variable<String>(id);
    map['project_id'] = Variable<String>(projectId);
    map['created_at'] = Variable<int>(createdAt);
    map['options_json'] = Variable<String>(optionsJson);
    if (!nullToAbsent || zipPath != null) {
      map['zip_path'] = Variable<String>(zipPath);
    }
    if (!nullToAbsent || pdfPath != null) {
      map['pdf_path'] = Variable<String>(pdfPath);
    }
    if (!nullToAbsent || bytes != null) {
      map['bytes'] = Variable<int>(bytes);
    }
    if (!nullToAbsent || itemCount != null) {
      map['item_count'] = Variable<int>(itemCount);
    }
    if (!nullToAbsent || photoCount != null) {
      map['photo_count'] = Variable<int>(photoCount);
    }
    if (!nullToAbsent || sha256 != null) {
      map['sha256'] = Variable<String>(sha256);
    }
    if (!nullToAbsent || sharedAt != null) {
      map['shared_at'] = Variable<int>(sharedAt);
    }
    if (!nullToAbsent || webdavPath != null) {
      map['webdav_path'] = Variable<String>(webdavPath);
    }
    return map;
  }

  DeliveriesCompanion toCompanion(bool nullToAbsent) {
    return DeliveriesCompanion(
      id: Value(id),
      projectId: Value(projectId),
      createdAt: Value(createdAt),
      optionsJson: Value(optionsJson),
      zipPath: zipPath == null && nullToAbsent
          ? const Value.absent()
          : Value(zipPath),
      pdfPath: pdfPath == null && nullToAbsent
          ? const Value.absent()
          : Value(pdfPath),
      bytes:
          bytes == null && nullToAbsent ? const Value.absent() : Value(bytes),
      itemCount: itemCount == null && nullToAbsent
          ? const Value.absent()
          : Value(itemCount),
      photoCount: photoCount == null && nullToAbsent
          ? const Value.absent()
          : Value(photoCount),
      sha256:
          sha256 == null && nullToAbsent ? const Value.absent() : Value(sha256),
      sharedAt: sharedAt == null && nullToAbsent
          ? const Value.absent()
          : Value(sharedAt),
      webdavPath: webdavPath == null && nullToAbsent
          ? const Value.absent()
          : Value(webdavPath),
    );
  }

  factory Delivery.fromJson(Map<String, dynamic> json,
      {ValueSerializer? serializer}) {
    serializer ??= driftRuntimeOptions.defaultSerializer;
    return Delivery(
      id: serializer.fromJson<String>(json['id']),
      projectId: serializer.fromJson<String>(json['projectId']),
      createdAt: serializer.fromJson<int>(json['createdAt']),
      optionsJson: serializer.fromJson<String>(json['optionsJson']),
      zipPath: serializer.fromJson<String?>(json['zipPath']),
      pdfPath: serializer.fromJson<String?>(json['pdfPath']),
      bytes: serializer.fromJson<int?>(json['bytes']),
      itemCount: serializer.fromJson<int?>(json['itemCount']),
      photoCount: serializer.fromJson<int?>(json['photoCount']),
      sha256: serializer.fromJson<String?>(json['sha256']),
      sharedAt: serializer.fromJson<int?>(json['sharedAt']),
      webdavPath: serializer.fromJson<String?>(json['webdavPath']),
    );
  }
  @override
  Map<String, dynamic> toJson({ValueSerializer? serializer}) {
    serializer ??= driftRuntimeOptions.defaultSerializer;
    return <String, dynamic>{
      'id': serializer.toJson<String>(id),
      'projectId': serializer.toJson<String>(projectId),
      'createdAt': serializer.toJson<int>(createdAt),
      'optionsJson': serializer.toJson<String>(optionsJson),
      'zipPath': serializer.toJson<String?>(zipPath),
      'pdfPath': serializer.toJson<String?>(pdfPath),
      'bytes': serializer.toJson<int?>(bytes),
      'itemCount': serializer.toJson<int?>(itemCount),
      'photoCount': serializer.toJson<int?>(photoCount),
      'sha256': serializer.toJson<String?>(sha256),
      'sharedAt': serializer.toJson<int?>(sharedAt),
      'webdavPath': serializer.toJson<String?>(webdavPath),
    };
  }

  Delivery copyWith(
          {String? id,
          String? projectId,
          int? createdAt,
          String? optionsJson,
          Value<String?> zipPath = const Value.absent(),
          Value<String?> pdfPath = const Value.absent(),
          Value<int?> bytes = const Value.absent(),
          Value<int?> itemCount = const Value.absent(),
          Value<int?> photoCount = const Value.absent(),
          Value<String?> sha256 = const Value.absent(),
          Value<int?> sharedAt = const Value.absent(),
          Value<String?> webdavPath = const Value.absent()}) =>
      Delivery(
        id: id ?? this.id,
        projectId: projectId ?? this.projectId,
        createdAt: createdAt ?? this.createdAt,
        optionsJson: optionsJson ?? this.optionsJson,
        zipPath: zipPath.present ? zipPath.value : this.zipPath,
        pdfPath: pdfPath.present ? pdfPath.value : this.pdfPath,
        bytes: bytes.present ? bytes.value : this.bytes,
        itemCount: itemCount.present ? itemCount.value : this.itemCount,
        photoCount: photoCount.present ? photoCount.value : this.photoCount,
        sha256: sha256.present ? sha256.value : this.sha256,
        sharedAt: sharedAt.present ? sharedAt.value : this.sharedAt,
        webdavPath: webdavPath.present ? webdavPath.value : this.webdavPath,
      );
  Delivery copyWithCompanion(DeliveriesCompanion data) {
    return Delivery(
      id: data.id.present ? data.id.value : this.id,
      projectId: data.projectId.present ? data.projectId.value : this.projectId,
      createdAt: data.createdAt.present ? data.createdAt.value : this.createdAt,
      optionsJson:
          data.optionsJson.present ? data.optionsJson.value : this.optionsJson,
      zipPath: data.zipPath.present ? data.zipPath.value : this.zipPath,
      pdfPath: data.pdfPath.present ? data.pdfPath.value : this.pdfPath,
      bytes: data.bytes.present ? data.bytes.value : this.bytes,
      itemCount: data.itemCount.present ? data.itemCount.value : this.itemCount,
      photoCount:
          data.photoCount.present ? data.photoCount.value : this.photoCount,
      sha256: data.sha256.present ? data.sha256.value : this.sha256,
      sharedAt: data.sharedAt.present ? data.sharedAt.value : this.sharedAt,
      webdavPath:
          data.webdavPath.present ? data.webdavPath.value : this.webdavPath,
    );
  }

  @override
  String toString() {
    return (StringBuffer('Delivery(')
          ..write('id: $id, ')
          ..write('projectId: $projectId, ')
          ..write('createdAt: $createdAt, ')
          ..write('optionsJson: $optionsJson, ')
          ..write('zipPath: $zipPath, ')
          ..write('pdfPath: $pdfPath, ')
          ..write('bytes: $bytes, ')
          ..write('itemCount: $itemCount, ')
          ..write('photoCount: $photoCount, ')
          ..write('sha256: $sha256, ')
          ..write('sharedAt: $sharedAt, ')
          ..write('webdavPath: $webdavPath')
          ..write(')'))
        .toString();
  }

  @override
  int get hashCode => Object.hash(
      id,
      projectId,
      createdAt,
      optionsJson,
      zipPath,
      pdfPath,
      bytes,
      itemCount,
      photoCount,
      sha256,
      sharedAt,
      webdavPath);
  @override
  bool operator ==(Object other) =>
      identical(this, other) ||
      (other is Delivery &&
          other.id == this.id &&
          other.projectId == this.projectId &&
          other.createdAt == this.createdAt &&
          other.optionsJson == this.optionsJson &&
          other.zipPath == this.zipPath &&
          other.pdfPath == this.pdfPath &&
          other.bytes == this.bytes &&
          other.itemCount == this.itemCount &&
          other.photoCount == this.photoCount &&
          other.sha256 == this.sha256 &&
          other.sharedAt == this.sharedAt &&
          other.webdavPath == this.webdavPath);
}

class DeliveriesCompanion extends UpdateCompanion<Delivery> {
  final Value<String> id;
  final Value<String> projectId;
  final Value<int> createdAt;
  final Value<String> optionsJson;
  final Value<String?> zipPath;
  final Value<String?> pdfPath;
  final Value<int?> bytes;
  final Value<int?> itemCount;
  final Value<int?> photoCount;
  final Value<String?> sha256;
  final Value<int?> sharedAt;
  final Value<String?> webdavPath;
  final Value<int> rowid;
  const DeliveriesCompanion({
    this.id = const Value.absent(),
    this.projectId = const Value.absent(),
    this.createdAt = const Value.absent(),
    this.optionsJson = const Value.absent(),
    this.zipPath = const Value.absent(),
    this.pdfPath = const Value.absent(),
    this.bytes = const Value.absent(),
    this.itemCount = const Value.absent(),
    this.photoCount = const Value.absent(),
    this.sha256 = const Value.absent(),
    this.sharedAt = const Value.absent(),
    this.webdavPath = const Value.absent(),
    this.rowid = const Value.absent(),
  });
  DeliveriesCompanion.insert({
    required String id,
    required String projectId,
    required int createdAt,
    required String optionsJson,
    this.zipPath = const Value.absent(),
    this.pdfPath = const Value.absent(),
    this.bytes = const Value.absent(),
    this.itemCount = const Value.absent(),
    this.photoCount = const Value.absent(),
    this.sha256 = const Value.absent(),
    this.sharedAt = const Value.absent(),
    this.webdavPath = const Value.absent(),
    this.rowid = const Value.absent(),
  })  : id = Value(id),
        projectId = Value(projectId),
        createdAt = Value(createdAt),
        optionsJson = Value(optionsJson);
  static Insertable<Delivery> custom({
    Expression<String>? id,
    Expression<String>? projectId,
    Expression<int>? createdAt,
    Expression<String>? optionsJson,
    Expression<String>? zipPath,
    Expression<String>? pdfPath,
    Expression<int>? bytes,
    Expression<int>? itemCount,
    Expression<int>? photoCount,
    Expression<String>? sha256,
    Expression<int>? sharedAt,
    Expression<String>? webdavPath,
    Expression<int>? rowid,
  }) {
    return RawValuesInsertable({
      if (id != null) 'id': id,
      if (projectId != null) 'project_id': projectId,
      if (createdAt != null) 'created_at': createdAt,
      if (optionsJson != null) 'options_json': optionsJson,
      if (zipPath != null) 'zip_path': zipPath,
      if (pdfPath != null) 'pdf_path': pdfPath,
      if (bytes != null) 'bytes': bytes,
      if (itemCount != null) 'item_count': itemCount,
      if (photoCount != null) 'photo_count': photoCount,
      if (sha256 != null) 'sha256': sha256,
      if (sharedAt != null) 'shared_at': sharedAt,
      if (webdavPath != null) 'webdav_path': webdavPath,
      if (rowid != null) 'rowid': rowid,
    });
  }

  DeliveriesCompanion copyWith(
      {Value<String>? id,
      Value<String>? projectId,
      Value<int>? createdAt,
      Value<String>? optionsJson,
      Value<String?>? zipPath,
      Value<String?>? pdfPath,
      Value<int?>? bytes,
      Value<int?>? itemCount,
      Value<int?>? photoCount,
      Value<String?>? sha256,
      Value<int?>? sharedAt,
      Value<String?>? webdavPath,
      Value<int>? rowid}) {
    return DeliveriesCompanion(
      id: id ?? this.id,
      projectId: projectId ?? this.projectId,
      createdAt: createdAt ?? this.createdAt,
      optionsJson: optionsJson ?? this.optionsJson,
      zipPath: zipPath ?? this.zipPath,
      pdfPath: pdfPath ?? this.pdfPath,
      bytes: bytes ?? this.bytes,
      itemCount: itemCount ?? this.itemCount,
      photoCount: photoCount ?? this.photoCount,
      sha256: sha256 ?? this.sha256,
      sharedAt: sharedAt ?? this.sharedAt,
      webdavPath: webdavPath ?? this.webdavPath,
      rowid: rowid ?? this.rowid,
    );
  }

  @override
  Map<String, Expression> toColumns(bool nullToAbsent) {
    final map = <String, Expression>{};
    if (id.present) {
      map['id'] = Variable<String>(id.value);
    }
    if (projectId.present) {
      map['project_id'] = Variable<String>(projectId.value);
    }
    if (createdAt.present) {
      map['created_at'] = Variable<int>(createdAt.value);
    }
    if (optionsJson.present) {
      map['options_json'] = Variable<String>(optionsJson.value);
    }
    if (zipPath.present) {
      map['zip_path'] = Variable<String>(zipPath.value);
    }
    if (pdfPath.present) {
      map['pdf_path'] = Variable<String>(pdfPath.value);
    }
    if (bytes.present) {
      map['bytes'] = Variable<int>(bytes.value);
    }
    if (itemCount.present) {
      map['item_count'] = Variable<int>(itemCount.value);
    }
    if (photoCount.present) {
      map['photo_count'] = Variable<int>(photoCount.value);
    }
    if (sha256.present) {
      map['sha256'] = Variable<String>(sha256.value);
    }
    if (sharedAt.present) {
      map['shared_at'] = Variable<int>(sharedAt.value);
    }
    if (webdavPath.present) {
      map['webdav_path'] = Variable<String>(webdavPath.value);
    }
    if (rowid.present) {
      map['rowid'] = Variable<int>(rowid.value);
    }
    return map;
  }

  @override
  String toString() {
    return (StringBuffer('DeliveriesCompanion(')
          ..write('id: $id, ')
          ..write('projectId: $projectId, ')
          ..write('createdAt: $createdAt, ')
          ..write('optionsJson: $optionsJson, ')
          ..write('zipPath: $zipPath, ')
          ..write('pdfPath: $pdfPath, ')
          ..write('bytes: $bytes, ')
          ..write('itemCount: $itemCount, ')
          ..write('photoCount: $photoCount, ')
          ..write('sha256: $sha256, ')
          ..write('sharedAt: $sharedAt, ')
          ..write('webdavPath: $webdavPath, ')
          ..write('rowid: $rowid')
          ..write(')'))
        .toString();
  }
}

class $UploadTasksTable extends UploadTasks
    with TableInfo<$UploadTasksTable, UploadTask> {
  @override
  final GeneratedDatabase attachedDatabase;
  final String? _alias;
  $UploadTasksTable(this.attachedDatabase, [this._alias]);
  static const VerificationMeta _idMeta = const VerificationMeta('id');
  @override
  late final GeneratedColumn<String> id = GeneratedColumn<String>(
      'id', aliasedName, false,
      type: DriftSqlType.string, requiredDuringInsert: true);
  static const VerificationMeta _deliveryIdMeta =
      const VerificationMeta('deliveryId');
  @override
  late final GeneratedColumn<String> deliveryId = GeneratedColumn<String>(
      'delivery_id', aliasedName, false,
      type: DriftSqlType.string,
      requiredDuringInsert: true,
      defaultConstraints:
          GeneratedColumn.constraintIsAlways('REFERENCES deliveries (id)'));
  static const VerificationMeta _localPathMeta =
      const VerificationMeta('localPath');
  @override
  late final GeneratedColumn<String> localPath = GeneratedColumn<String>(
      'local_path', aliasedName, false,
      type: DriftSqlType.string, requiredDuringInsert: true);
  static const VerificationMeta _remotePathMeta =
      const VerificationMeta('remotePath');
  @override
  late final GeneratedColumn<String> remotePath = GeneratedColumn<String>(
      'remote_path', aliasedName, false,
      type: DriftSqlType.string, requiredDuringInsert: true);
  static const VerificationMeta _bytesMeta = const VerificationMeta('bytes');
  @override
  late final GeneratedColumn<int> bytes = GeneratedColumn<int>(
      'bytes', aliasedName, false,
      type: DriftSqlType.int, requiredDuringInsert: true);
  static const VerificationMeta _uploadedBytesMeta =
      const VerificationMeta('uploadedBytes');
  @override
  late final GeneratedColumn<int> uploadedBytes = GeneratedColumn<int>(
      'uploaded_bytes', aliasedName, false,
      type: DriftSqlType.int,
      requiredDuringInsert: false,
      defaultValue: const Constant(0));
  static const VerificationMeta _stateMeta = const VerificationMeta('state');
  @override
  late final GeneratedColumn<String> state = GeneratedColumn<String>(
      'state', aliasedName, false,
      type: DriftSqlType.string,
      requiredDuringInsert: false,
      defaultValue: const Constant('queued'));
  static const VerificationMeta _attemptsMeta =
      const VerificationMeta('attempts');
  @override
  late final GeneratedColumn<int> attempts = GeneratedColumn<int>(
      'attempts', aliasedName, false,
      type: DriftSqlType.int,
      requiredDuringInsert: false,
      defaultValue: const Constant(0));
  static const VerificationMeta _nextRetryAtMeta =
      const VerificationMeta('nextRetryAt');
  @override
  late final GeneratedColumn<int> nextRetryAt = GeneratedColumn<int>(
      'next_retry_at', aliasedName, true,
      type: DriftSqlType.int, requiredDuringInsert: false);
  static const VerificationMeta _lastErrorMeta =
      const VerificationMeta('lastError');
  @override
  late final GeneratedColumn<String> lastError = GeneratedColumn<String>(
      'last_error', aliasedName, true,
      type: DriftSqlType.string, requiredDuringInsert: false);
  @override
  List<GeneratedColumn> get $columns => [
        id,
        deliveryId,
        localPath,
        remotePath,
        bytes,
        uploadedBytes,
        state,
        attempts,
        nextRetryAt,
        lastError
      ];
  @override
  String get aliasedName => _alias ?? actualTableName;
  @override
  String get actualTableName => $name;
  static const String $name = 'upload_tasks';
  @override
  VerificationContext validateIntegrity(Insertable<UploadTask> instance,
      {bool isInserting = false}) {
    final context = VerificationContext();
    final data = instance.toColumns(true);
    if (data.containsKey('id')) {
      context.handle(_idMeta, id.isAcceptableOrUnknown(data['id']!, _idMeta));
    } else if (isInserting) {
      context.missing(_idMeta);
    }
    if (data.containsKey('delivery_id')) {
      context.handle(
          _deliveryIdMeta,
          deliveryId.isAcceptableOrUnknown(
              data['delivery_id']!, _deliveryIdMeta));
    } else if (isInserting) {
      context.missing(_deliveryIdMeta);
    }
    if (data.containsKey('local_path')) {
      context.handle(_localPathMeta,
          localPath.isAcceptableOrUnknown(data['local_path']!, _localPathMeta));
    } else if (isInserting) {
      context.missing(_localPathMeta);
    }
    if (data.containsKey('remote_path')) {
      context.handle(
          _remotePathMeta,
          remotePath.isAcceptableOrUnknown(
              data['remote_path']!, _remotePathMeta));
    } else if (isInserting) {
      context.missing(_remotePathMeta);
    }
    if (data.containsKey('bytes')) {
      context.handle(
          _bytesMeta, bytes.isAcceptableOrUnknown(data['bytes']!, _bytesMeta));
    } else if (isInserting) {
      context.missing(_bytesMeta);
    }
    if (data.containsKey('uploaded_bytes')) {
      context.handle(
          _uploadedBytesMeta,
          uploadedBytes.isAcceptableOrUnknown(
              data['uploaded_bytes']!, _uploadedBytesMeta));
    }
    if (data.containsKey('state')) {
      context.handle(
          _stateMeta, state.isAcceptableOrUnknown(data['state']!, _stateMeta));
    }
    if (data.containsKey('attempts')) {
      context.handle(_attemptsMeta,
          attempts.isAcceptableOrUnknown(data['attempts']!, _attemptsMeta));
    }
    if (data.containsKey('next_retry_at')) {
      context.handle(
          _nextRetryAtMeta,
          nextRetryAt.isAcceptableOrUnknown(
              data['next_retry_at']!, _nextRetryAtMeta));
    }
    if (data.containsKey('last_error')) {
      context.handle(_lastErrorMeta,
          lastError.isAcceptableOrUnknown(data['last_error']!, _lastErrorMeta));
    }
    return context;
  }

  @override
  Set<GeneratedColumn> get $primaryKey => {id};
  @override
  UploadTask map(Map<String, dynamic> data, {String? tablePrefix}) {
    final effectivePrefix = tablePrefix != null ? '$tablePrefix.' : '';
    return UploadTask(
      id: attachedDatabase.typeMapping
          .read(DriftSqlType.string, data['${effectivePrefix}id'])!,
      deliveryId: attachedDatabase.typeMapping
          .read(DriftSqlType.string, data['${effectivePrefix}delivery_id'])!,
      localPath: attachedDatabase.typeMapping
          .read(DriftSqlType.string, data['${effectivePrefix}local_path'])!,
      remotePath: attachedDatabase.typeMapping
          .read(DriftSqlType.string, data['${effectivePrefix}remote_path'])!,
      bytes: attachedDatabase.typeMapping
          .read(DriftSqlType.int, data['${effectivePrefix}bytes'])!,
      uploadedBytes: attachedDatabase.typeMapping
          .read(DriftSqlType.int, data['${effectivePrefix}uploaded_bytes'])!,
      state: attachedDatabase.typeMapping
          .read(DriftSqlType.string, data['${effectivePrefix}state'])!,
      attempts: attachedDatabase.typeMapping
          .read(DriftSqlType.int, data['${effectivePrefix}attempts'])!,
      nextRetryAt: attachedDatabase.typeMapping
          .read(DriftSqlType.int, data['${effectivePrefix}next_retry_at']),
      lastError: attachedDatabase.typeMapping
          .read(DriftSqlType.string, data['${effectivePrefix}last_error']),
    );
  }

  @override
  $UploadTasksTable createAlias(String alias) {
    return $UploadTasksTable(attachedDatabase, alias);
  }
}

class UploadTask extends DataClass implements Insertable<UploadTask> {
  final String id;
  final String deliveryId;
  final String localPath;
  final String remotePath;
  final int bytes;
  final int uploadedBytes;

  /// UploadState.code
  final String state;
  final int attempts;
  final int? nextRetryAt;
  final String? lastError;
  const UploadTask(
      {required this.id,
      required this.deliveryId,
      required this.localPath,
      required this.remotePath,
      required this.bytes,
      required this.uploadedBytes,
      required this.state,
      required this.attempts,
      this.nextRetryAt,
      this.lastError});
  @override
  Map<String, Expression> toColumns(bool nullToAbsent) {
    final map = <String, Expression>{};
    map['id'] = Variable<String>(id);
    map['delivery_id'] = Variable<String>(deliveryId);
    map['local_path'] = Variable<String>(localPath);
    map['remote_path'] = Variable<String>(remotePath);
    map['bytes'] = Variable<int>(bytes);
    map['uploaded_bytes'] = Variable<int>(uploadedBytes);
    map['state'] = Variable<String>(state);
    map['attempts'] = Variable<int>(attempts);
    if (!nullToAbsent || nextRetryAt != null) {
      map['next_retry_at'] = Variable<int>(nextRetryAt);
    }
    if (!nullToAbsent || lastError != null) {
      map['last_error'] = Variable<String>(lastError);
    }
    return map;
  }

  UploadTasksCompanion toCompanion(bool nullToAbsent) {
    return UploadTasksCompanion(
      id: Value(id),
      deliveryId: Value(deliveryId),
      localPath: Value(localPath),
      remotePath: Value(remotePath),
      bytes: Value(bytes),
      uploadedBytes: Value(uploadedBytes),
      state: Value(state),
      attempts: Value(attempts),
      nextRetryAt: nextRetryAt == null && nullToAbsent
          ? const Value.absent()
          : Value(nextRetryAt),
      lastError: lastError == null && nullToAbsent
          ? const Value.absent()
          : Value(lastError),
    );
  }

  factory UploadTask.fromJson(Map<String, dynamic> json,
      {ValueSerializer? serializer}) {
    serializer ??= driftRuntimeOptions.defaultSerializer;
    return UploadTask(
      id: serializer.fromJson<String>(json['id']),
      deliveryId: serializer.fromJson<String>(json['deliveryId']),
      localPath: serializer.fromJson<String>(json['localPath']),
      remotePath: serializer.fromJson<String>(json['remotePath']),
      bytes: serializer.fromJson<int>(json['bytes']),
      uploadedBytes: serializer.fromJson<int>(json['uploadedBytes']),
      state: serializer.fromJson<String>(json['state']),
      attempts: serializer.fromJson<int>(json['attempts']),
      nextRetryAt: serializer.fromJson<int?>(json['nextRetryAt']),
      lastError: serializer.fromJson<String?>(json['lastError']),
    );
  }
  @override
  Map<String, dynamic> toJson({ValueSerializer? serializer}) {
    serializer ??= driftRuntimeOptions.defaultSerializer;
    return <String, dynamic>{
      'id': serializer.toJson<String>(id),
      'deliveryId': serializer.toJson<String>(deliveryId),
      'localPath': serializer.toJson<String>(localPath),
      'remotePath': serializer.toJson<String>(remotePath),
      'bytes': serializer.toJson<int>(bytes),
      'uploadedBytes': serializer.toJson<int>(uploadedBytes),
      'state': serializer.toJson<String>(state),
      'attempts': serializer.toJson<int>(attempts),
      'nextRetryAt': serializer.toJson<int?>(nextRetryAt),
      'lastError': serializer.toJson<String?>(lastError),
    };
  }

  UploadTask copyWith(
          {String? id,
          String? deliveryId,
          String? localPath,
          String? remotePath,
          int? bytes,
          int? uploadedBytes,
          String? state,
          int? attempts,
          Value<int?> nextRetryAt = const Value.absent(),
          Value<String?> lastError = const Value.absent()}) =>
      UploadTask(
        id: id ?? this.id,
        deliveryId: deliveryId ?? this.deliveryId,
        localPath: localPath ?? this.localPath,
        remotePath: remotePath ?? this.remotePath,
        bytes: bytes ?? this.bytes,
        uploadedBytes: uploadedBytes ?? this.uploadedBytes,
        state: state ?? this.state,
        attempts: attempts ?? this.attempts,
        nextRetryAt: nextRetryAt.present ? nextRetryAt.value : this.nextRetryAt,
        lastError: lastError.present ? lastError.value : this.lastError,
      );
  UploadTask copyWithCompanion(UploadTasksCompanion data) {
    return UploadTask(
      id: data.id.present ? data.id.value : this.id,
      deliveryId:
          data.deliveryId.present ? data.deliveryId.value : this.deliveryId,
      localPath: data.localPath.present ? data.localPath.value : this.localPath,
      remotePath:
          data.remotePath.present ? data.remotePath.value : this.remotePath,
      bytes: data.bytes.present ? data.bytes.value : this.bytes,
      uploadedBytes: data.uploadedBytes.present
          ? data.uploadedBytes.value
          : this.uploadedBytes,
      state: data.state.present ? data.state.value : this.state,
      attempts: data.attempts.present ? data.attempts.value : this.attempts,
      nextRetryAt:
          data.nextRetryAt.present ? data.nextRetryAt.value : this.nextRetryAt,
      lastError: data.lastError.present ? data.lastError.value : this.lastError,
    );
  }

  @override
  String toString() {
    return (StringBuffer('UploadTask(')
          ..write('id: $id, ')
          ..write('deliveryId: $deliveryId, ')
          ..write('localPath: $localPath, ')
          ..write('remotePath: $remotePath, ')
          ..write('bytes: $bytes, ')
          ..write('uploadedBytes: $uploadedBytes, ')
          ..write('state: $state, ')
          ..write('attempts: $attempts, ')
          ..write('nextRetryAt: $nextRetryAt, ')
          ..write('lastError: $lastError')
          ..write(')'))
        .toString();
  }

  @override
  int get hashCode => Object.hash(id, deliveryId, localPath, remotePath, bytes,
      uploadedBytes, state, attempts, nextRetryAt, lastError);
  @override
  bool operator ==(Object other) =>
      identical(this, other) ||
      (other is UploadTask &&
          other.id == this.id &&
          other.deliveryId == this.deliveryId &&
          other.localPath == this.localPath &&
          other.remotePath == this.remotePath &&
          other.bytes == this.bytes &&
          other.uploadedBytes == this.uploadedBytes &&
          other.state == this.state &&
          other.attempts == this.attempts &&
          other.nextRetryAt == this.nextRetryAt &&
          other.lastError == this.lastError);
}

class UploadTasksCompanion extends UpdateCompanion<UploadTask> {
  final Value<String> id;
  final Value<String> deliveryId;
  final Value<String> localPath;
  final Value<String> remotePath;
  final Value<int> bytes;
  final Value<int> uploadedBytes;
  final Value<String> state;
  final Value<int> attempts;
  final Value<int?> nextRetryAt;
  final Value<String?> lastError;
  final Value<int> rowid;
  const UploadTasksCompanion({
    this.id = const Value.absent(),
    this.deliveryId = const Value.absent(),
    this.localPath = const Value.absent(),
    this.remotePath = const Value.absent(),
    this.bytes = const Value.absent(),
    this.uploadedBytes = const Value.absent(),
    this.state = const Value.absent(),
    this.attempts = const Value.absent(),
    this.nextRetryAt = const Value.absent(),
    this.lastError = const Value.absent(),
    this.rowid = const Value.absent(),
  });
  UploadTasksCompanion.insert({
    required String id,
    required String deliveryId,
    required String localPath,
    required String remotePath,
    required int bytes,
    this.uploadedBytes = const Value.absent(),
    this.state = const Value.absent(),
    this.attempts = const Value.absent(),
    this.nextRetryAt = const Value.absent(),
    this.lastError = const Value.absent(),
    this.rowid = const Value.absent(),
  })  : id = Value(id),
        deliveryId = Value(deliveryId),
        localPath = Value(localPath),
        remotePath = Value(remotePath),
        bytes = Value(bytes);
  static Insertable<UploadTask> custom({
    Expression<String>? id,
    Expression<String>? deliveryId,
    Expression<String>? localPath,
    Expression<String>? remotePath,
    Expression<int>? bytes,
    Expression<int>? uploadedBytes,
    Expression<String>? state,
    Expression<int>? attempts,
    Expression<int>? nextRetryAt,
    Expression<String>? lastError,
    Expression<int>? rowid,
  }) {
    return RawValuesInsertable({
      if (id != null) 'id': id,
      if (deliveryId != null) 'delivery_id': deliveryId,
      if (localPath != null) 'local_path': localPath,
      if (remotePath != null) 'remote_path': remotePath,
      if (bytes != null) 'bytes': bytes,
      if (uploadedBytes != null) 'uploaded_bytes': uploadedBytes,
      if (state != null) 'state': state,
      if (attempts != null) 'attempts': attempts,
      if (nextRetryAt != null) 'next_retry_at': nextRetryAt,
      if (lastError != null) 'last_error': lastError,
      if (rowid != null) 'rowid': rowid,
    });
  }

  UploadTasksCompanion copyWith(
      {Value<String>? id,
      Value<String>? deliveryId,
      Value<String>? localPath,
      Value<String>? remotePath,
      Value<int>? bytes,
      Value<int>? uploadedBytes,
      Value<String>? state,
      Value<int>? attempts,
      Value<int?>? nextRetryAt,
      Value<String?>? lastError,
      Value<int>? rowid}) {
    return UploadTasksCompanion(
      id: id ?? this.id,
      deliveryId: deliveryId ?? this.deliveryId,
      localPath: localPath ?? this.localPath,
      remotePath: remotePath ?? this.remotePath,
      bytes: bytes ?? this.bytes,
      uploadedBytes: uploadedBytes ?? this.uploadedBytes,
      state: state ?? this.state,
      attempts: attempts ?? this.attempts,
      nextRetryAt: nextRetryAt ?? this.nextRetryAt,
      lastError: lastError ?? this.lastError,
      rowid: rowid ?? this.rowid,
    );
  }

  @override
  Map<String, Expression> toColumns(bool nullToAbsent) {
    final map = <String, Expression>{};
    if (id.present) {
      map['id'] = Variable<String>(id.value);
    }
    if (deliveryId.present) {
      map['delivery_id'] = Variable<String>(deliveryId.value);
    }
    if (localPath.present) {
      map['local_path'] = Variable<String>(localPath.value);
    }
    if (remotePath.present) {
      map['remote_path'] = Variable<String>(remotePath.value);
    }
    if (bytes.present) {
      map['bytes'] = Variable<int>(bytes.value);
    }
    if (uploadedBytes.present) {
      map['uploaded_bytes'] = Variable<int>(uploadedBytes.value);
    }
    if (state.present) {
      map['state'] = Variable<String>(state.value);
    }
    if (attempts.present) {
      map['attempts'] = Variable<int>(attempts.value);
    }
    if (nextRetryAt.present) {
      map['next_retry_at'] = Variable<int>(nextRetryAt.value);
    }
    if (lastError.present) {
      map['last_error'] = Variable<String>(lastError.value);
    }
    if (rowid.present) {
      map['rowid'] = Variable<int>(rowid.value);
    }
    return map;
  }

  @override
  String toString() {
    return (StringBuffer('UploadTasksCompanion(')
          ..write('id: $id, ')
          ..write('deliveryId: $deliveryId, ')
          ..write('localPath: $localPath, ')
          ..write('remotePath: $remotePath, ')
          ..write('bytes: $bytes, ')
          ..write('uploadedBytes: $uploadedBytes, ')
          ..write('state: $state, ')
          ..write('attempts: $attempts, ')
          ..write('nextRetryAt: $nextRetryAt, ')
          ..write('lastError: $lastError, ')
          ..write('rowid: $rowid')
          ..write(')'))
        .toString();
  }
}

class $ItemPhotoExtrasTable extends ItemPhotoExtras
    with TableInfo<$ItemPhotoExtrasTable, ItemPhotoExtra> {
  @override
  final GeneratedDatabase attachedDatabase;
  final String? _alias;
  $ItemPhotoExtrasTable(this.attachedDatabase, [this._alias]);
  static const VerificationMeta _idMeta = const VerificationMeta('id');
  @override
  late final GeneratedColumn<String> id = GeneratedColumn<String>(
      'id', aliasedName, false,
      type: DriftSqlType.string, requiredDuringInsert: true);
  static const VerificationMeta _photoIdMeta =
      const VerificationMeta('photoId');
  @override
  late final GeneratedColumn<String> photoId = GeneratedColumn<String>(
      'photo_id', aliasedName, false,
      type: DriftSqlType.string,
      requiredDuringInsert: true,
      defaultConstraints:
          GeneratedColumn.constraintIsAlways('REFERENCES photos (id)'));
  static const VerificationMeta _itemIdMeta = const VerificationMeta('itemId');
  @override
  late final GeneratedColumn<String> itemId = GeneratedColumn<String>(
      'item_id', aliasedName, false,
      type: DriftSqlType.string,
      requiredDuringInsert: true,
      defaultConstraints:
          GeneratedColumn.constraintIsAlways('REFERENCES items (id)'));
  static const VerificationMeta _roleMeta = const VerificationMeta('role');
  @override
  late final GeneratedColumn<String> role = GeneratedColumn<String>(
      'role', aliasedName, false,
      type: DriftSqlType.string,
      requiredDuringInsert: false,
      defaultValue: const Constant('co_visible'));
  static const VerificationMeta _createdAtMeta =
      const VerificationMeta('createdAt');
  @override
  late final GeneratedColumn<int> createdAt = GeneratedColumn<int>(
      'created_at', aliasedName, false,
      type: DriftSqlType.int, requiredDuringInsert: true);
  @override
  List<GeneratedColumn> get $columns => [id, photoId, itemId, role, createdAt];
  @override
  String get aliasedName => _alias ?? actualTableName;
  @override
  String get actualTableName => $name;
  static const String $name = 'item_photo_extras';
  @override
  VerificationContext validateIntegrity(Insertable<ItemPhotoExtra> instance,
      {bool isInserting = false}) {
    final context = VerificationContext();
    final data = instance.toColumns(true);
    if (data.containsKey('id')) {
      context.handle(_idMeta, id.isAcceptableOrUnknown(data['id']!, _idMeta));
    } else if (isInserting) {
      context.missing(_idMeta);
    }
    if (data.containsKey('photo_id')) {
      context.handle(_photoIdMeta,
          photoId.isAcceptableOrUnknown(data['photo_id']!, _photoIdMeta));
    } else if (isInserting) {
      context.missing(_photoIdMeta);
    }
    if (data.containsKey('item_id')) {
      context.handle(_itemIdMeta,
          itemId.isAcceptableOrUnknown(data['item_id']!, _itemIdMeta));
    } else if (isInserting) {
      context.missing(_itemIdMeta);
    }
    if (data.containsKey('role')) {
      context.handle(
          _roleMeta, role.isAcceptableOrUnknown(data['role']!, _roleMeta));
    }
    if (data.containsKey('created_at')) {
      context.handle(_createdAtMeta,
          createdAt.isAcceptableOrUnknown(data['created_at']!, _createdAtMeta));
    } else if (isInserting) {
      context.missing(_createdAtMeta);
    }
    return context;
  }

  @override
  Set<GeneratedColumn> get $primaryKey => {id};
  @override
  List<Set<GeneratedColumn>> get uniqueKeys => [
        {photoId, itemId},
      ];
  @override
  ItemPhotoExtra map(Map<String, dynamic> data, {String? tablePrefix}) {
    final effectivePrefix = tablePrefix != null ? '$tablePrefix.' : '';
    return ItemPhotoExtra(
      id: attachedDatabase.typeMapping
          .read(DriftSqlType.string, data['${effectivePrefix}id'])!,
      photoId: attachedDatabase.typeMapping
          .read(DriftSqlType.string, data['${effectivePrefix}photo_id'])!,
      itemId: attachedDatabase.typeMapping
          .read(DriftSqlType.string, data['${effectivePrefix}item_id'])!,
      role: attachedDatabase.typeMapping
          .read(DriftSqlType.string, data['${effectivePrefix}role'])!,
      createdAt: attachedDatabase.typeMapping
          .read(DriftSqlType.int, data['${effectivePrefix}created_at'])!,
    );
  }

  @override
  $ItemPhotoExtrasTable createAlias(String alias) {
    return $ItemPhotoExtrasTable(attachedDatabase, alias);
  }
}

class ItemPhotoExtra extends DataClass implements Insertable<ItemPhotoExtra> {
  final String id;
  final String photoId;
  final String itemId;

  /// 关联角色：co_visible（同框可见） / damaged（破损处） …
  final String role;
  final int createdAt;
  const ItemPhotoExtra(
      {required this.id,
      required this.photoId,
      required this.itemId,
      required this.role,
      required this.createdAt});
  @override
  Map<String, Expression> toColumns(bool nullToAbsent) {
    final map = <String, Expression>{};
    map['id'] = Variable<String>(id);
    map['photo_id'] = Variable<String>(photoId);
    map['item_id'] = Variable<String>(itemId);
    map['role'] = Variable<String>(role);
    map['created_at'] = Variable<int>(createdAt);
    return map;
  }

  ItemPhotoExtrasCompanion toCompanion(bool nullToAbsent) {
    return ItemPhotoExtrasCompanion(
      id: Value(id),
      photoId: Value(photoId),
      itemId: Value(itemId),
      role: Value(role),
      createdAt: Value(createdAt),
    );
  }

  factory ItemPhotoExtra.fromJson(Map<String, dynamic> json,
      {ValueSerializer? serializer}) {
    serializer ??= driftRuntimeOptions.defaultSerializer;
    return ItemPhotoExtra(
      id: serializer.fromJson<String>(json['id']),
      photoId: serializer.fromJson<String>(json['photoId']),
      itemId: serializer.fromJson<String>(json['itemId']),
      role: serializer.fromJson<String>(json['role']),
      createdAt: serializer.fromJson<int>(json['createdAt']),
    );
  }
  @override
  Map<String, dynamic> toJson({ValueSerializer? serializer}) {
    serializer ??= driftRuntimeOptions.defaultSerializer;
    return <String, dynamic>{
      'id': serializer.toJson<String>(id),
      'photoId': serializer.toJson<String>(photoId),
      'itemId': serializer.toJson<String>(itemId),
      'role': serializer.toJson<String>(role),
      'createdAt': serializer.toJson<int>(createdAt),
    };
  }

  ItemPhotoExtra copyWith(
          {String? id,
          String? photoId,
          String? itemId,
          String? role,
          int? createdAt}) =>
      ItemPhotoExtra(
        id: id ?? this.id,
        photoId: photoId ?? this.photoId,
        itemId: itemId ?? this.itemId,
        role: role ?? this.role,
        createdAt: createdAt ?? this.createdAt,
      );
  ItemPhotoExtra copyWithCompanion(ItemPhotoExtrasCompanion data) {
    return ItemPhotoExtra(
      id: data.id.present ? data.id.value : this.id,
      photoId: data.photoId.present ? data.photoId.value : this.photoId,
      itemId: data.itemId.present ? data.itemId.value : this.itemId,
      role: data.role.present ? data.role.value : this.role,
      createdAt: data.createdAt.present ? data.createdAt.value : this.createdAt,
    );
  }

  @override
  String toString() {
    return (StringBuffer('ItemPhotoExtra(')
          ..write('id: $id, ')
          ..write('photoId: $photoId, ')
          ..write('itemId: $itemId, ')
          ..write('role: $role, ')
          ..write('createdAt: $createdAt')
          ..write(')'))
        .toString();
  }

  @override
  int get hashCode => Object.hash(id, photoId, itemId, role, createdAt);
  @override
  bool operator ==(Object other) =>
      identical(this, other) ||
      (other is ItemPhotoExtra &&
          other.id == this.id &&
          other.photoId == this.photoId &&
          other.itemId == this.itemId &&
          other.role == this.role &&
          other.createdAt == this.createdAt);
}

class ItemPhotoExtrasCompanion extends UpdateCompanion<ItemPhotoExtra> {
  final Value<String> id;
  final Value<String> photoId;
  final Value<String> itemId;
  final Value<String> role;
  final Value<int> createdAt;
  final Value<int> rowid;
  const ItemPhotoExtrasCompanion({
    this.id = const Value.absent(),
    this.photoId = const Value.absent(),
    this.itemId = const Value.absent(),
    this.role = const Value.absent(),
    this.createdAt = const Value.absent(),
    this.rowid = const Value.absent(),
  });
  ItemPhotoExtrasCompanion.insert({
    required String id,
    required String photoId,
    required String itemId,
    this.role = const Value.absent(),
    required int createdAt,
    this.rowid = const Value.absent(),
  })  : id = Value(id),
        photoId = Value(photoId),
        itemId = Value(itemId),
        createdAt = Value(createdAt);
  static Insertable<ItemPhotoExtra> custom({
    Expression<String>? id,
    Expression<String>? photoId,
    Expression<String>? itemId,
    Expression<String>? role,
    Expression<int>? createdAt,
    Expression<int>? rowid,
  }) {
    return RawValuesInsertable({
      if (id != null) 'id': id,
      if (photoId != null) 'photo_id': photoId,
      if (itemId != null) 'item_id': itemId,
      if (role != null) 'role': role,
      if (createdAt != null) 'created_at': createdAt,
      if (rowid != null) 'rowid': rowid,
    });
  }

  ItemPhotoExtrasCompanion copyWith(
      {Value<String>? id,
      Value<String>? photoId,
      Value<String>? itemId,
      Value<String>? role,
      Value<int>? createdAt,
      Value<int>? rowid}) {
    return ItemPhotoExtrasCompanion(
      id: id ?? this.id,
      photoId: photoId ?? this.photoId,
      itemId: itemId ?? this.itemId,
      role: role ?? this.role,
      createdAt: createdAt ?? this.createdAt,
      rowid: rowid ?? this.rowid,
    );
  }

  @override
  Map<String, Expression> toColumns(bool nullToAbsent) {
    final map = <String, Expression>{};
    if (id.present) {
      map['id'] = Variable<String>(id.value);
    }
    if (photoId.present) {
      map['photo_id'] = Variable<String>(photoId.value);
    }
    if (itemId.present) {
      map['item_id'] = Variable<String>(itemId.value);
    }
    if (role.present) {
      map['role'] = Variable<String>(role.value);
    }
    if (createdAt.present) {
      map['created_at'] = Variable<int>(createdAt.value);
    }
    if (rowid.present) {
      map['rowid'] = Variable<int>(rowid.value);
    }
    return map;
  }

  @override
  String toString() {
    return (StringBuffer('ItemPhotoExtrasCompanion(')
          ..write('id: $id, ')
          ..write('photoId: $photoId, ')
          ..write('itemId: $itemId, ')
          ..write('role: $role, ')
          ..write('createdAt: $createdAt, ')
          ..write('rowid: $rowid')
          ..write(')'))
        .toString();
  }
}

class $AppSettingsTable extends AppSettings
    with TableInfo<$AppSettingsTable, AppSetting> {
  @override
  final GeneratedDatabase attachedDatabase;
  final String? _alias;
  $AppSettingsTable(this.attachedDatabase, [this._alias]);
  static const VerificationMeta _keyMeta = const VerificationMeta('key');
  @override
  late final GeneratedColumn<String> key = GeneratedColumn<String>(
      'key', aliasedName, false,
      type: DriftSqlType.string, requiredDuringInsert: true);
  static const VerificationMeta _valueMeta = const VerificationMeta('value');
  @override
  late final GeneratedColumn<String> value = GeneratedColumn<String>(
      'value', aliasedName, false,
      type: DriftSqlType.string, requiredDuringInsert: true);
  static const VerificationMeta _updatedAtMeta =
      const VerificationMeta('updatedAt');
  @override
  late final GeneratedColumn<int> updatedAt = GeneratedColumn<int>(
      'updated_at', aliasedName, false,
      type: DriftSqlType.int, requiredDuringInsert: true);
  @override
  List<GeneratedColumn> get $columns => [key, value, updatedAt];
  @override
  String get aliasedName => _alias ?? actualTableName;
  @override
  String get actualTableName => $name;
  static const String $name = 'app_settings';
  @override
  VerificationContext validateIntegrity(Insertable<AppSetting> instance,
      {bool isInserting = false}) {
    final context = VerificationContext();
    final data = instance.toColumns(true);
    if (data.containsKey('key')) {
      context.handle(
          _keyMeta, key.isAcceptableOrUnknown(data['key']!, _keyMeta));
    } else if (isInserting) {
      context.missing(_keyMeta);
    }
    if (data.containsKey('value')) {
      context.handle(
          _valueMeta, value.isAcceptableOrUnknown(data['value']!, _valueMeta));
    } else if (isInserting) {
      context.missing(_valueMeta);
    }
    if (data.containsKey('updated_at')) {
      context.handle(_updatedAtMeta,
          updatedAt.isAcceptableOrUnknown(data['updated_at']!, _updatedAtMeta));
    } else if (isInserting) {
      context.missing(_updatedAtMeta);
    }
    return context;
  }

  @override
  Set<GeneratedColumn> get $primaryKey => {key};
  @override
  AppSetting map(Map<String, dynamic> data, {String? tablePrefix}) {
    final effectivePrefix = tablePrefix != null ? '$tablePrefix.' : '';
    return AppSetting(
      key: attachedDatabase.typeMapping
          .read(DriftSqlType.string, data['${effectivePrefix}key'])!,
      value: attachedDatabase.typeMapping
          .read(DriftSqlType.string, data['${effectivePrefix}value'])!,
      updatedAt: attachedDatabase.typeMapping
          .read(DriftSqlType.int, data['${effectivePrefix}updated_at'])!,
    );
  }

  @override
  $AppSettingsTable createAlias(String alias) {
    return $AppSettingsTable(attachedDatabase, alias);
  }
}

class AppSetting extends DataClass implements Insertable<AppSetting> {
  final String key;
  final String value;
  final int updatedAt;
  const AppSetting(
      {required this.key, required this.value, required this.updatedAt});
  @override
  Map<String, Expression> toColumns(bool nullToAbsent) {
    final map = <String, Expression>{};
    map['key'] = Variable<String>(key);
    map['value'] = Variable<String>(value);
    map['updated_at'] = Variable<int>(updatedAt);
    return map;
  }

  AppSettingsCompanion toCompanion(bool nullToAbsent) {
    return AppSettingsCompanion(
      key: Value(key),
      value: Value(value),
      updatedAt: Value(updatedAt),
    );
  }

  factory AppSetting.fromJson(Map<String, dynamic> json,
      {ValueSerializer? serializer}) {
    serializer ??= driftRuntimeOptions.defaultSerializer;
    return AppSetting(
      key: serializer.fromJson<String>(json['key']),
      value: serializer.fromJson<String>(json['value']),
      updatedAt: serializer.fromJson<int>(json['updatedAt']),
    );
  }
  @override
  Map<String, dynamic> toJson({ValueSerializer? serializer}) {
    serializer ??= driftRuntimeOptions.defaultSerializer;
    return <String, dynamic>{
      'key': serializer.toJson<String>(key),
      'value': serializer.toJson<String>(value),
      'updatedAt': serializer.toJson<int>(updatedAt),
    };
  }

  AppSetting copyWith({String? key, String? value, int? updatedAt}) =>
      AppSetting(
        key: key ?? this.key,
        value: value ?? this.value,
        updatedAt: updatedAt ?? this.updatedAt,
      );
  AppSetting copyWithCompanion(AppSettingsCompanion data) {
    return AppSetting(
      key: data.key.present ? data.key.value : this.key,
      value: data.value.present ? data.value.value : this.value,
      updatedAt: data.updatedAt.present ? data.updatedAt.value : this.updatedAt,
    );
  }

  @override
  String toString() {
    return (StringBuffer('AppSetting(')
          ..write('key: $key, ')
          ..write('value: $value, ')
          ..write('updatedAt: $updatedAt')
          ..write(')'))
        .toString();
  }

  @override
  int get hashCode => Object.hash(key, value, updatedAt);
  @override
  bool operator ==(Object other) =>
      identical(this, other) ||
      (other is AppSetting &&
          other.key == this.key &&
          other.value == this.value &&
          other.updatedAt == this.updatedAt);
}

class AppSettingsCompanion extends UpdateCompanion<AppSetting> {
  final Value<String> key;
  final Value<String> value;
  final Value<int> updatedAt;
  final Value<int> rowid;
  const AppSettingsCompanion({
    this.key = const Value.absent(),
    this.value = const Value.absent(),
    this.updatedAt = const Value.absent(),
    this.rowid = const Value.absent(),
  });
  AppSettingsCompanion.insert({
    required String key,
    required String value,
    required int updatedAt,
    this.rowid = const Value.absent(),
  })  : key = Value(key),
        value = Value(value),
        updatedAt = Value(updatedAt);
  static Insertable<AppSetting> custom({
    Expression<String>? key,
    Expression<String>? value,
    Expression<int>? updatedAt,
    Expression<int>? rowid,
  }) {
    return RawValuesInsertable({
      if (key != null) 'key': key,
      if (value != null) 'value': value,
      if (updatedAt != null) 'updated_at': updatedAt,
      if (rowid != null) 'rowid': rowid,
    });
  }

  AppSettingsCompanion copyWith(
      {Value<String>? key,
      Value<String>? value,
      Value<int>? updatedAt,
      Value<int>? rowid}) {
    return AppSettingsCompanion(
      key: key ?? this.key,
      value: value ?? this.value,
      updatedAt: updatedAt ?? this.updatedAt,
      rowid: rowid ?? this.rowid,
    );
  }

  @override
  Map<String, Expression> toColumns(bool nullToAbsent) {
    final map = <String, Expression>{};
    if (key.present) {
      map['key'] = Variable<String>(key.value);
    }
    if (value.present) {
      map['value'] = Variable<String>(value.value);
    }
    if (updatedAt.present) {
      map['updated_at'] = Variable<int>(updatedAt.value);
    }
    if (rowid.present) {
      map['rowid'] = Variable<int>(rowid.value);
    }
    return map;
  }

  @override
  String toString() {
    return (StringBuffer('AppSettingsCompanion(')
          ..write('key: $key, ')
          ..write('value: $value, ')
          ..write('updatedAt: $updatedAt, ')
          ..write('rowid: $rowid')
          ..write(')'))
        .toString();
  }
}

abstract class _$AppDatabase extends GeneratedDatabase {
  _$AppDatabase(QueryExecutor e) : super(e);
  $AppDatabaseManager get managers => $AppDatabaseManager(this);
  late final $ProjectsTable projects = $ProjectsTable(this);
  late final $ItemsTable items = $ItemsTable(this);
  late final $CaptureSessionsTable captureSessions =
      $CaptureSessionsTable(this);
  late final $PhotoGroupsTable photoGroups = $PhotoGroupsTable(this);
  late final $PhotosTable photos = $PhotosTable(this);
  late final $OcrTokensTable ocrTokens = $OcrTokensTable(this);
  late final $AssignmentsTable assignments = $AssignmentsTable(this);
  late final $DeliveriesTable deliveries = $DeliveriesTable(this);
  late final $UploadTasksTable uploadTasks = $UploadTasksTable(this);
  late final $ItemPhotoExtrasTable itemPhotoExtras =
      $ItemPhotoExtrasTable(this);
  late final $AppSettingsTable appSettings = $AppSettingsTable(this);
  late final Index photosContentHash = Index('photos_content_hash',
      'CREATE INDEX photos_content_hash ON photos (content_hash)');
  @override
  Iterable<TableInfo<Table, Object?>> get allTables =>
      allSchemaEntities.whereType<TableInfo<Table, Object?>>();
  @override
  List<DatabaseSchemaEntity> get allSchemaEntities => [
        projects,
        items,
        captureSessions,
        photoGroups,
        photos,
        ocrTokens,
        assignments,
        deliveries,
        uploadTasks,
        itemPhotoExtras,
        appSettings,
        photosContentHash
      ];
}

typedef $$ProjectsTableCreateCompanionBuilder = ProjectsCompanion Function({
  required String id,
  required String name,
  Value<String?> client,
  required int createdAt,
  Value<String> status,
  Value<String?> checklistFile,
  Value<String?> settingsJson,
  Value<int?> deletedAt,
  Value<int> rowid,
});
typedef $$ProjectsTableUpdateCompanionBuilder = ProjectsCompanion Function({
  Value<String> id,
  Value<String> name,
  Value<String?> client,
  Value<int> createdAt,
  Value<String> status,
  Value<String?> checklistFile,
  Value<String?> settingsJson,
  Value<int?> deletedAt,
  Value<int> rowid,
});

final class $$ProjectsTableReferences
    extends BaseReferences<_$AppDatabase, $ProjectsTable, Project> {
  $$ProjectsTableReferences(super.$_db, super.$_table, super.$_typedResult);

  static MultiTypedResultKey<$ItemsTable, List<Item>> _itemsRefsTable(
          _$AppDatabase db) =>
      MultiTypedResultKey.fromTable(db.items,
          aliasName: $_aliasNameGenerator(db.projects.id, db.items.projectId));

  $$ItemsTableProcessedTableManager get itemsRefs {
    final manager = $$ItemsTableTableManager($_db, $_db.items)
        .filter((f) => f.projectId.id.sqlEquals($_itemColumn<String>('id')!));

    final cache = $_typedResult.readTableOrNull(_itemsRefsTable($_db));
    return ProcessedTableManager(
        manager.$state.copyWith(prefetchedData: cache));
  }

  static MultiTypedResultKey<$CaptureSessionsTable, List<CaptureSession>>
      _captureSessionsRefsTable(_$AppDatabase db) =>
          MultiTypedResultKey.fromTable(db.captureSessions,
              aliasName: $_aliasNameGenerator(
                  db.projects.id, db.captureSessions.projectId));

  $$CaptureSessionsTableProcessedTableManager get captureSessionsRefs {
    final manager = $$CaptureSessionsTableTableManager(
            $_db, $_db.captureSessions)
        .filter((f) => f.projectId.id.sqlEquals($_itemColumn<String>('id')!));

    final cache =
        $_typedResult.readTableOrNull(_captureSessionsRefsTable($_db));
    return ProcessedTableManager(
        manager.$state.copyWith(prefetchedData: cache));
  }

  static MultiTypedResultKey<$PhotoGroupsTable, List<PhotoGroup>>
      _photoGroupsRefsTable(_$AppDatabase db) => MultiTypedResultKey.fromTable(
          db.photoGroups,
          aliasName:
              $_aliasNameGenerator(db.projects.id, db.photoGroups.projectId));

  $$PhotoGroupsTableProcessedTableManager get photoGroupsRefs {
    final manager = $$PhotoGroupsTableTableManager($_db, $_db.photoGroups)
        .filter((f) => f.projectId.id.sqlEquals($_itemColumn<String>('id')!));

    final cache = $_typedResult.readTableOrNull(_photoGroupsRefsTable($_db));
    return ProcessedTableManager(
        manager.$state.copyWith(prefetchedData: cache));
  }

  static MultiTypedResultKey<$PhotosTable, List<Photo>> _photosRefsTable(
          _$AppDatabase db) =>
      MultiTypedResultKey.fromTable(db.photos,
          aliasName: $_aliasNameGenerator(db.projects.id, db.photos.projectId));

  $$PhotosTableProcessedTableManager get photosRefs {
    final manager = $$PhotosTableTableManager($_db, $_db.photos)
        .filter((f) => f.projectId.id.sqlEquals($_itemColumn<String>('id')!));

    final cache = $_typedResult.readTableOrNull(_photosRefsTable($_db));
    return ProcessedTableManager(
        manager.$state.copyWith(prefetchedData: cache));
  }

  static MultiTypedResultKey<$AssignmentsTable, List<Assignment>>
      _assignmentsRefsTable(_$AppDatabase db) => MultiTypedResultKey.fromTable(
          db.assignments,
          aliasName:
              $_aliasNameGenerator(db.projects.id, db.assignments.projectId));

  $$AssignmentsTableProcessedTableManager get assignmentsRefs {
    final manager = $$AssignmentsTableTableManager($_db, $_db.assignments)
        .filter((f) => f.projectId.id.sqlEquals($_itemColumn<String>('id')!));

    final cache = $_typedResult.readTableOrNull(_assignmentsRefsTable($_db));
    return ProcessedTableManager(
        manager.$state.copyWith(prefetchedData: cache));
  }

  static MultiTypedResultKey<$DeliveriesTable, List<Delivery>>
      _deliveriesRefsTable(_$AppDatabase db) => MultiTypedResultKey.fromTable(
          db.deliveries,
          aliasName:
              $_aliasNameGenerator(db.projects.id, db.deliveries.projectId));

  $$DeliveriesTableProcessedTableManager get deliveriesRefs {
    final manager = $$DeliveriesTableTableManager($_db, $_db.deliveries)
        .filter((f) => f.projectId.id.sqlEquals($_itemColumn<String>('id')!));

    final cache = $_typedResult.readTableOrNull(_deliveriesRefsTable($_db));
    return ProcessedTableManager(
        manager.$state.copyWith(prefetchedData: cache));
  }
}

class $$ProjectsTableFilterComposer
    extends Composer<_$AppDatabase, $ProjectsTable> {
  $$ProjectsTableFilterComposer({
    required super.$db,
    required super.$table,
    super.joinBuilder,
    super.$addJoinBuilderToRootComposer,
    super.$removeJoinBuilderFromRootComposer,
  });
  ColumnFilters<String> get id => $composableBuilder(
      column: $table.id, builder: (column) => ColumnFilters(column));

  ColumnFilters<String> get name => $composableBuilder(
      column: $table.name, builder: (column) => ColumnFilters(column));

  ColumnFilters<String> get client => $composableBuilder(
      column: $table.client, builder: (column) => ColumnFilters(column));

  ColumnFilters<int> get createdAt => $composableBuilder(
      column: $table.createdAt, builder: (column) => ColumnFilters(column));

  ColumnFilters<String> get status => $composableBuilder(
      column: $table.status, builder: (column) => ColumnFilters(column));

  ColumnFilters<String> get checklistFile => $composableBuilder(
      column: $table.checklistFile, builder: (column) => ColumnFilters(column));

  ColumnFilters<String> get settingsJson => $composableBuilder(
      column: $table.settingsJson, builder: (column) => ColumnFilters(column));

  ColumnFilters<int> get deletedAt => $composableBuilder(
      column: $table.deletedAt, builder: (column) => ColumnFilters(column));

  Expression<bool> itemsRefs(
      Expression<bool> Function($$ItemsTableFilterComposer f) f) {
    final $$ItemsTableFilterComposer composer = $composerBuilder(
        composer: this,
        getCurrentColumn: (t) => t.id,
        referencedTable: $db.items,
        getReferencedColumn: (t) => t.projectId,
        builder: (joinBuilder,
                {$addJoinBuilderToRootComposer,
                $removeJoinBuilderFromRootComposer}) =>
            $$ItemsTableFilterComposer(
              $db: $db,
              $table: $db.items,
              $addJoinBuilderToRootComposer: $addJoinBuilderToRootComposer,
              joinBuilder: joinBuilder,
              $removeJoinBuilderFromRootComposer:
                  $removeJoinBuilderFromRootComposer,
            ));
    return f(composer);
  }

  Expression<bool> captureSessionsRefs(
      Expression<bool> Function($$CaptureSessionsTableFilterComposer f) f) {
    final $$CaptureSessionsTableFilterComposer composer = $composerBuilder(
        composer: this,
        getCurrentColumn: (t) => t.id,
        referencedTable: $db.captureSessions,
        getReferencedColumn: (t) => t.projectId,
        builder: (joinBuilder,
                {$addJoinBuilderToRootComposer,
                $removeJoinBuilderFromRootComposer}) =>
            $$CaptureSessionsTableFilterComposer(
              $db: $db,
              $table: $db.captureSessions,
              $addJoinBuilderToRootComposer: $addJoinBuilderToRootComposer,
              joinBuilder: joinBuilder,
              $removeJoinBuilderFromRootComposer:
                  $removeJoinBuilderFromRootComposer,
            ));
    return f(composer);
  }

  Expression<bool> photoGroupsRefs(
      Expression<bool> Function($$PhotoGroupsTableFilterComposer f) f) {
    final $$PhotoGroupsTableFilterComposer composer = $composerBuilder(
        composer: this,
        getCurrentColumn: (t) => t.id,
        referencedTable: $db.photoGroups,
        getReferencedColumn: (t) => t.projectId,
        builder: (joinBuilder,
                {$addJoinBuilderToRootComposer,
                $removeJoinBuilderFromRootComposer}) =>
            $$PhotoGroupsTableFilterComposer(
              $db: $db,
              $table: $db.photoGroups,
              $addJoinBuilderToRootComposer: $addJoinBuilderToRootComposer,
              joinBuilder: joinBuilder,
              $removeJoinBuilderFromRootComposer:
                  $removeJoinBuilderFromRootComposer,
            ));
    return f(composer);
  }

  Expression<bool> photosRefs(
      Expression<bool> Function($$PhotosTableFilterComposer f) f) {
    final $$PhotosTableFilterComposer composer = $composerBuilder(
        composer: this,
        getCurrentColumn: (t) => t.id,
        referencedTable: $db.photos,
        getReferencedColumn: (t) => t.projectId,
        builder: (joinBuilder,
                {$addJoinBuilderToRootComposer,
                $removeJoinBuilderFromRootComposer}) =>
            $$PhotosTableFilterComposer(
              $db: $db,
              $table: $db.photos,
              $addJoinBuilderToRootComposer: $addJoinBuilderToRootComposer,
              joinBuilder: joinBuilder,
              $removeJoinBuilderFromRootComposer:
                  $removeJoinBuilderFromRootComposer,
            ));
    return f(composer);
  }

  Expression<bool> assignmentsRefs(
      Expression<bool> Function($$AssignmentsTableFilterComposer f) f) {
    final $$AssignmentsTableFilterComposer composer = $composerBuilder(
        composer: this,
        getCurrentColumn: (t) => t.id,
        referencedTable: $db.assignments,
        getReferencedColumn: (t) => t.projectId,
        builder: (joinBuilder,
                {$addJoinBuilderToRootComposer,
                $removeJoinBuilderFromRootComposer}) =>
            $$AssignmentsTableFilterComposer(
              $db: $db,
              $table: $db.assignments,
              $addJoinBuilderToRootComposer: $addJoinBuilderToRootComposer,
              joinBuilder: joinBuilder,
              $removeJoinBuilderFromRootComposer:
                  $removeJoinBuilderFromRootComposer,
            ));
    return f(composer);
  }

  Expression<bool> deliveriesRefs(
      Expression<bool> Function($$DeliveriesTableFilterComposer f) f) {
    final $$DeliveriesTableFilterComposer composer = $composerBuilder(
        composer: this,
        getCurrentColumn: (t) => t.id,
        referencedTable: $db.deliveries,
        getReferencedColumn: (t) => t.projectId,
        builder: (joinBuilder,
                {$addJoinBuilderToRootComposer,
                $removeJoinBuilderFromRootComposer}) =>
            $$DeliveriesTableFilterComposer(
              $db: $db,
              $table: $db.deliveries,
              $addJoinBuilderToRootComposer: $addJoinBuilderToRootComposer,
              joinBuilder: joinBuilder,
              $removeJoinBuilderFromRootComposer:
                  $removeJoinBuilderFromRootComposer,
            ));
    return f(composer);
  }
}

class $$ProjectsTableOrderingComposer
    extends Composer<_$AppDatabase, $ProjectsTable> {
  $$ProjectsTableOrderingComposer({
    required super.$db,
    required super.$table,
    super.joinBuilder,
    super.$addJoinBuilderToRootComposer,
    super.$removeJoinBuilderFromRootComposer,
  });
  ColumnOrderings<String> get id => $composableBuilder(
      column: $table.id, builder: (column) => ColumnOrderings(column));

  ColumnOrderings<String> get name => $composableBuilder(
      column: $table.name, builder: (column) => ColumnOrderings(column));

  ColumnOrderings<String> get client => $composableBuilder(
      column: $table.client, builder: (column) => ColumnOrderings(column));

  ColumnOrderings<int> get createdAt => $composableBuilder(
      column: $table.createdAt, builder: (column) => ColumnOrderings(column));

  ColumnOrderings<String> get status => $composableBuilder(
      column: $table.status, builder: (column) => ColumnOrderings(column));

  ColumnOrderings<String> get checklistFile => $composableBuilder(
      column: $table.checklistFile,
      builder: (column) => ColumnOrderings(column));

  ColumnOrderings<String> get settingsJson => $composableBuilder(
      column: $table.settingsJson,
      builder: (column) => ColumnOrderings(column));

  ColumnOrderings<int> get deletedAt => $composableBuilder(
      column: $table.deletedAt, builder: (column) => ColumnOrderings(column));
}

class $$ProjectsTableAnnotationComposer
    extends Composer<_$AppDatabase, $ProjectsTable> {
  $$ProjectsTableAnnotationComposer({
    required super.$db,
    required super.$table,
    super.joinBuilder,
    super.$addJoinBuilderToRootComposer,
    super.$removeJoinBuilderFromRootComposer,
  });
  GeneratedColumn<String> get id =>
      $composableBuilder(column: $table.id, builder: (column) => column);

  GeneratedColumn<String> get name =>
      $composableBuilder(column: $table.name, builder: (column) => column);

  GeneratedColumn<String> get client =>
      $composableBuilder(column: $table.client, builder: (column) => column);

  GeneratedColumn<int> get createdAt =>
      $composableBuilder(column: $table.createdAt, builder: (column) => column);

  GeneratedColumn<String> get status =>
      $composableBuilder(column: $table.status, builder: (column) => column);

  GeneratedColumn<String> get checklistFile => $composableBuilder(
      column: $table.checklistFile, builder: (column) => column);

  GeneratedColumn<String> get settingsJson => $composableBuilder(
      column: $table.settingsJson, builder: (column) => column);

  GeneratedColumn<int> get deletedAt =>
      $composableBuilder(column: $table.deletedAt, builder: (column) => column);

  Expression<T> itemsRefs<T extends Object>(
      Expression<T> Function($$ItemsTableAnnotationComposer a) f) {
    final $$ItemsTableAnnotationComposer composer = $composerBuilder(
        composer: this,
        getCurrentColumn: (t) => t.id,
        referencedTable: $db.items,
        getReferencedColumn: (t) => t.projectId,
        builder: (joinBuilder,
                {$addJoinBuilderToRootComposer,
                $removeJoinBuilderFromRootComposer}) =>
            $$ItemsTableAnnotationComposer(
              $db: $db,
              $table: $db.items,
              $addJoinBuilderToRootComposer: $addJoinBuilderToRootComposer,
              joinBuilder: joinBuilder,
              $removeJoinBuilderFromRootComposer:
                  $removeJoinBuilderFromRootComposer,
            ));
    return f(composer);
  }

  Expression<T> captureSessionsRefs<T extends Object>(
      Expression<T> Function($$CaptureSessionsTableAnnotationComposer a) f) {
    final $$CaptureSessionsTableAnnotationComposer composer = $composerBuilder(
        composer: this,
        getCurrentColumn: (t) => t.id,
        referencedTable: $db.captureSessions,
        getReferencedColumn: (t) => t.projectId,
        builder: (joinBuilder,
                {$addJoinBuilderToRootComposer,
                $removeJoinBuilderFromRootComposer}) =>
            $$CaptureSessionsTableAnnotationComposer(
              $db: $db,
              $table: $db.captureSessions,
              $addJoinBuilderToRootComposer: $addJoinBuilderToRootComposer,
              joinBuilder: joinBuilder,
              $removeJoinBuilderFromRootComposer:
                  $removeJoinBuilderFromRootComposer,
            ));
    return f(composer);
  }

  Expression<T> photoGroupsRefs<T extends Object>(
      Expression<T> Function($$PhotoGroupsTableAnnotationComposer a) f) {
    final $$PhotoGroupsTableAnnotationComposer composer = $composerBuilder(
        composer: this,
        getCurrentColumn: (t) => t.id,
        referencedTable: $db.photoGroups,
        getReferencedColumn: (t) => t.projectId,
        builder: (joinBuilder,
                {$addJoinBuilderToRootComposer,
                $removeJoinBuilderFromRootComposer}) =>
            $$PhotoGroupsTableAnnotationComposer(
              $db: $db,
              $table: $db.photoGroups,
              $addJoinBuilderToRootComposer: $addJoinBuilderToRootComposer,
              joinBuilder: joinBuilder,
              $removeJoinBuilderFromRootComposer:
                  $removeJoinBuilderFromRootComposer,
            ));
    return f(composer);
  }

  Expression<T> photosRefs<T extends Object>(
      Expression<T> Function($$PhotosTableAnnotationComposer a) f) {
    final $$PhotosTableAnnotationComposer composer = $composerBuilder(
        composer: this,
        getCurrentColumn: (t) => t.id,
        referencedTable: $db.photos,
        getReferencedColumn: (t) => t.projectId,
        builder: (joinBuilder,
                {$addJoinBuilderToRootComposer,
                $removeJoinBuilderFromRootComposer}) =>
            $$PhotosTableAnnotationComposer(
              $db: $db,
              $table: $db.photos,
              $addJoinBuilderToRootComposer: $addJoinBuilderToRootComposer,
              joinBuilder: joinBuilder,
              $removeJoinBuilderFromRootComposer:
                  $removeJoinBuilderFromRootComposer,
            ));
    return f(composer);
  }

  Expression<T> assignmentsRefs<T extends Object>(
      Expression<T> Function($$AssignmentsTableAnnotationComposer a) f) {
    final $$AssignmentsTableAnnotationComposer composer = $composerBuilder(
        composer: this,
        getCurrentColumn: (t) => t.id,
        referencedTable: $db.assignments,
        getReferencedColumn: (t) => t.projectId,
        builder: (joinBuilder,
                {$addJoinBuilderToRootComposer,
                $removeJoinBuilderFromRootComposer}) =>
            $$AssignmentsTableAnnotationComposer(
              $db: $db,
              $table: $db.assignments,
              $addJoinBuilderToRootComposer: $addJoinBuilderToRootComposer,
              joinBuilder: joinBuilder,
              $removeJoinBuilderFromRootComposer:
                  $removeJoinBuilderFromRootComposer,
            ));
    return f(composer);
  }

  Expression<T> deliveriesRefs<T extends Object>(
      Expression<T> Function($$DeliveriesTableAnnotationComposer a) f) {
    final $$DeliveriesTableAnnotationComposer composer = $composerBuilder(
        composer: this,
        getCurrentColumn: (t) => t.id,
        referencedTable: $db.deliveries,
        getReferencedColumn: (t) => t.projectId,
        builder: (joinBuilder,
                {$addJoinBuilderToRootComposer,
                $removeJoinBuilderFromRootComposer}) =>
            $$DeliveriesTableAnnotationComposer(
              $db: $db,
              $table: $db.deliveries,
              $addJoinBuilderToRootComposer: $addJoinBuilderToRootComposer,
              joinBuilder: joinBuilder,
              $removeJoinBuilderFromRootComposer:
                  $removeJoinBuilderFromRootComposer,
            ));
    return f(composer);
  }
}

class $$ProjectsTableTableManager extends RootTableManager<
    _$AppDatabase,
    $ProjectsTable,
    Project,
    $$ProjectsTableFilterComposer,
    $$ProjectsTableOrderingComposer,
    $$ProjectsTableAnnotationComposer,
    $$ProjectsTableCreateCompanionBuilder,
    $$ProjectsTableUpdateCompanionBuilder,
    (Project, $$ProjectsTableReferences),
    Project,
    PrefetchHooks Function(
        {bool itemsRefs,
        bool captureSessionsRefs,
        bool photoGroupsRefs,
        bool photosRefs,
        bool assignmentsRefs,
        bool deliveriesRefs})> {
  $$ProjectsTableTableManager(_$AppDatabase db, $ProjectsTable table)
      : super(TableManagerState(
          db: db,
          table: table,
          createFilteringComposer: () =>
              $$ProjectsTableFilterComposer($db: db, $table: table),
          createOrderingComposer: () =>
              $$ProjectsTableOrderingComposer($db: db, $table: table),
          createComputedFieldComposer: () =>
              $$ProjectsTableAnnotationComposer($db: db, $table: table),
          updateCompanionCallback: ({
            Value<String> id = const Value.absent(),
            Value<String> name = const Value.absent(),
            Value<String?> client = const Value.absent(),
            Value<int> createdAt = const Value.absent(),
            Value<String> status = const Value.absent(),
            Value<String?> checklistFile = const Value.absent(),
            Value<String?> settingsJson = const Value.absent(),
            Value<int?> deletedAt = const Value.absent(),
            Value<int> rowid = const Value.absent(),
          }) =>
              ProjectsCompanion(
            id: id,
            name: name,
            client: client,
            createdAt: createdAt,
            status: status,
            checklistFile: checklistFile,
            settingsJson: settingsJson,
            deletedAt: deletedAt,
            rowid: rowid,
          ),
          createCompanionCallback: ({
            required String id,
            required String name,
            Value<String?> client = const Value.absent(),
            required int createdAt,
            Value<String> status = const Value.absent(),
            Value<String?> checklistFile = const Value.absent(),
            Value<String?> settingsJson = const Value.absent(),
            Value<int?> deletedAt = const Value.absent(),
            Value<int> rowid = const Value.absent(),
          }) =>
              ProjectsCompanion.insert(
            id: id,
            name: name,
            client: client,
            createdAt: createdAt,
            status: status,
            checklistFile: checklistFile,
            settingsJson: settingsJson,
            deletedAt: deletedAt,
            rowid: rowid,
          ),
          withReferenceMapper: (p0) => p0
              .map((e) =>
                  (e.readTable(table), $$ProjectsTableReferences(db, table, e)))
              .toList(),
          prefetchHooksCallback: (
              {itemsRefs = false,
              captureSessionsRefs = false,
              photoGroupsRefs = false,
              photosRefs = false,
              assignmentsRefs = false,
              deliveriesRefs = false}) {
            return PrefetchHooks(
              db: db,
              explicitlyWatchedTables: [
                if (itemsRefs) db.items,
                if (captureSessionsRefs) db.captureSessions,
                if (photoGroupsRefs) db.photoGroups,
                if (photosRefs) db.photos,
                if (assignmentsRefs) db.assignments,
                if (deliveriesRefs) db.deliveries
              ],
              addJoins: null,
              getPrefetchedDataCallback: (items) async {
                return [
                  if (itemsRefs)
                    await $_getPrefetchedData<Project, $ProjectsTable, Item>(
                        currentTable: table,
                        referencedTable:
                            $$ProjectsTableReferences._itemsRefsTable(db),
                        managerFromTypedResult: (p0) =>
                            $$ProjectsTableReferences(db, table, p0).itemsRefs,
                        referencedItemsForCurrentItem:
                            (item, referencedItems) => referencedItems
                                .where((e) => e.projectId == item.id),
                        typedResults: items),
                  if (captureSessionsRefs)
                    await $_getPrefetchedData<Project, $ProjectsTable,
                            CaptureSession>(
                        currentTable: table,
                        referencedTable: $$ProjectsTableReferences
                            ._captureSessionsRefsTable(db),
                        managerFromTypedResult: (p0) =>
                            $$ProjectsTableReferences(db, table, p0)
                                .captureSessionsRefs,
                        referencedItemsForCurrentItem:
                            (item, referencedItems) => referencedItems
                                .where((e) => e.projectId == item.id),
                        typedResults: items),
                  if (photoGroupsRefs)
                    await $_getPrefetchedData<Project, $ProjectsTable,
                            PhotoGroup>(
                        currentTable: table,
                        referencedTable:
                            $$ProjectsTableReferences._photoGroupsRefsTable(db),
                        managerFromTypedResult: (p0) =>
                            $$ProjectsTableReferences(db, table, p0)
                                .photoGroupsRefs,
                        referencedItemsForCurrentItem:
                            (item, referencedItems) => referencedItems
                                .where((e) => e.projectId == item.id),
                        typedResults: items),
                  if (photosRefs)
                    await $_getPrefetchedData<Project, $ProjectsTable, Photo>(
                        currentTable: table,
                        referencedTable:
                            $$ProjectsTableReferences._photosRefsTable(db),
                        managerFromTypedResult: (p0) =>
                            $$ProjectsTableReferences(db, table, p0).photosRefs,
                        referencedItemsForCurrentItem:
                            (item, referencedItems) => referencedItems
                                .where((e) => e.projectId == item.id),
                        typedResults: items),
                  if (assignmentsRefs)
                    await $_getPrefetchedData<Project, $ProjectsTable,
                            Assignment>(
                        currentTable: table,
                        referencedTable:
                            $$ProjectsTableReferences._assignmentsRefsTable(db),
                        managerFromTypedResult: (p0) =>
                            $$ProjectsTableReferences(db, table, p0)
                                .assignmentsRefs,
                        referencedItemsForCurrentItem:
                            (item, referencedItems) => referencedItems
                                .where((e) => e.projectId == item.id),
                        typedResults: items),
                  if (deliveriesRefs)
                    await $_getPrefetchedData<Project, $ProjectsTable,
                            Delivery>(
                        currentTable: table,
                        referencedTable:
                            $$ProjectsTableReferences._deliveriesRefsTable(db),
                        managerFromTypedResult: (p0) =>
                            $$ProjectsTableReferences(db, table, p0)
                                .deliveriesRefs,
                        referencedItemsForCurrentItem:
                            (item, referencedItems) => referencedItems
                                .where((e) => e.projectId == item.id),
                        typedResults: items)
                ];
              },
            );
          },
        ));
}

typedef $$ProjectsTableProcessedTableManager = ProcessedTableManager<
    _$AppDatabase,
    $ProjectsTable,
    Project,
    $$ProjectsTableFilterComposer,
    $$ProjectsTableOrderingComposer,
    $$ProjectsTableAnnotationComposer,
    $$ProjectsTableCreateCompanionBuilder,
    $$ProjectsTableUpdateCompanionBuilder,
    (Project, $$ProjectsTableReferences),
    Project,
    PrefetchHooks Function(
        {bool itemsRefs,
        bool captureSessionsRefs,
        bool photoGroupsRefs,
        bool photosRefs,
        bool assignmentsRefs,
        bool deliveriesRefs})>;
typedef $$ItemsTableCreateCompanionBuilder = ItemsCompanion Function({
  required String id,
  required String projectId,
  required int seq,
  required String code,
  required String codeSafe,
  Value<String?> name,
  Value<String?> spec,
  Value<double?> qty,
  Value<String?> unit,
  Value<int> requiredPhotos,
  Value<String?> containerSummary,
  Value<int> sourceLineCount,
  Value<String> state,
  Value<String?> notFoundReason,
  Value<String?> remark,
  Value<int?> deletedAt,
  Value<int> rowid,
});
typedef $$ItemsTableUpdateCompanionBuilder = ItemsCompanion Function({
  Value<String> id,
  Value<String> projectId,
  Value<int> seq,
  Value<String> code,
  Value<String> codeSafe,
  Value<String?> name,
  Value<String?> spec,
  Value<double?> qty,
  Value<String?> unit,
  Value<int> requiredPhotos,
  Value<String?> containerSummary,
  Value<int> sourceLineCount,
  Value<String> state,
  Value<String?> notFoundReason,
  Value<String?> remark,
  Value<int?> deletedAt,
  Value<int> rowid,
});

final class $$ItemsTableReferences
    extends BaseReferences<_$AppDatabase, $ItemsTable, Item> {
  $$ItemsTableReferences(super.$_db, super.$_table, super.$_typedResult);

  static $ProjectsTable _projectIdTable(_$AppDatabase db) => db.projects
      .createAlias($_aliasNameGenerator(db.items.projectId, db.projects.id));

  $$ProjectsTableProcessedTableManager get projectId {
    final $_column = $_itemColumn<String>('project_id')!;

    final manager = $$ProjectsTableTableManager($_db, $_db.projects)
        .filter((f) => f.id.sqlEquals($_column));
    final item = $_typedResult.readTableOrNull(_projectIdTable($_db));
    if (item == null) return manager;
    return ProcessedTableManager(
        manager.$state.copyWith(prefetchedData: [item]));
  }

  static MultiTypedResultKey<$ItemPhotoExtrasTable, List<ItemPhotoExtra>>
      _itemPhotoExtrasRefsTable(_$AppDatabase db) =>
          MultiTypedResultKey.fromTable(db.itemPhotoExtras,
              aliasName:
                  $_aliasNameGenerator(db.items.id, db.itemPhotoExtras.itemId));

  $$ItemPhotoExtrasTableProcessedTableManager get itemPhotoExtrasRefs {
    final manager =
        $$ItemPhotoExtrasTableTableManager($_db, $_db.itemPhotoExtras)
            .filter((f) => f.itemId.id.sqlEquals($_itemColumn<String>('id')!));

    final cache =
        $_typedResult.readTableOrNull(_itemPhotoExtrasRefsTable($_db));
    return ProcessedTableManager(
        manager.$state.copyWith(prefetchedData: cache));
  }
}

class $$ItemsTableFilterComposer extends Composer<_$AppDatabase, $ItemsTable> {
  $$ItemsTableFilterComposer({
    required super.$db,
    required super.$table,
    super.joinBuilder,
    super.$addJoinBuilderToRootComposer,
    super.$removeJoinBuilderFromRootComposer,
  });
  ColumnFilters<String> get id => $composableBuilder(
      column: $table.id, builder: (column) => ColumnFilters(column));

  ColumnFilters<int> get seq => $composableBuilder(
      column: $table.seq, builder: (column) => ColumnFilters(column));

  ColumnFilters<String> get code => $composableBuilder(
      column: $table.code, builder: (column) => ColumnFilters(column));

  ColumnFilters<String> get codeSafe => $composableBuilder(
      column: $table.codeSafe, builder: (column) => ColumnFilters(column));

  ColumnFilters<String> get name => $composableBuilder(
      column: $table.name, builder: (column) => ColumnFilters(column));

  ColumnFilters<String> get spec => $composableBuilder(
      column: $table.spec, builder: (column) => ColumnFilters(column));

  ColumnFilters<double> get qty => $composableBuilder(
      column: $table.qty, builder: (column) => ColumnFilters(column));

  ColumnFilters<String> get unit => $composableBuilder(
      column: $table.unit, builder: (column) => ColumnFilters(column));

  ColumnFilters<int> get requiredPhotos => $composableBuilder(
      column: $table.requiredPhotos,
      builder: (column) => ColumnFilters(column));

  ColumnFilters<String> get containerSummary => $composableBuilder(
      column: $table.containerSummary,
      builder: (column) => ColumnFilters(column));

  ColumnFilters<int> get sourceLineCount => $composableBuilder(
      column: $table.sourceLineCount,
      builder: (column) => ColumnFilters(column));

  ColumnFilters<String> get state => $composableBuilder(
      column: $table.state, builder: (column) => ColumnFilters(column));

  ColumnFilters<String> get notFoundReason => $composableBuilder(
      column: $table.notFoundReason,
      builder: (column) => ColumnFilters(column));

  ColumnFilters<String> get remark => $composableBuilder(
      column: $table.remark, builder: (column) => ColumnFilters(column));

  ColumnFilters<int> get deletedAt => $composableBuilder(
      column: $table.deletedAt, builder: (column) => ColumnFilters(column));

  $$ProjectsTableFilterComposer get projectId {
    final $$ProjectsTableFilterComposer composer = $composerBuilder(
        composer: this,
        getCurrentColumn: (t) => t.projectId,
        referencedTable: $db.projects,
        getReferencedColumn: (t) => t.id,
        builder: (joinBuilder,
                {$addJoinBuilderToRootComposer,
                $removeJoinBuilderFromRootComposer}) =>
            $$ProjectsTableFilterComposer(
              $db: $db,
              $table: $db.projects,
              $addJoinBuilderToRootComposer: $addJoinBuilderToRootComposer,
              joinBuilder: joinBuilder,
              $removeJoinBuilderFromRootComposer:
                  $removeJoinBuilderFromRootComposer,
            ));
    return composer;
  }

  Expression<bool> itemPhotoExtrasRefs(
      Expression<bool> Function($$ItemPhotoExtrasTableFilterComposer f) f) {
    final $$ItemPhotoExtrasTableFilterComposer composer = $composerBuilder(
        composer: this,
        getCurrentColumn: (t) => t.id,
        referencedTable: $db.itemPhotoExtras,
        getReferencedColumn: (t) => t.itemId,
        builder: (joinBuilder,
                {$addJoinBuilderToRootComposer,
                $removeJoinBuilderFromRootComposer}) =>
            $$ItemPhotoExtrasTableFilterComposer(
              $db: $db,
              $table: $db.itemPhotoExtras,
              $addJoinBuilderToRootComposer: $addJoinBuilderToRootComposer,
              joinBuilder: joinBuilder,
              $removeJoinBuilderFromRootComposer:
                  $removeJoinBuilderFromRootComposer,
            ));
    return f(composer);
  }
}

class $$ItemsTableOrderingComposer
    extends Composer<_$AppDatabase, $ItemsTable> {
  $$ItemsTableOrderingComposer({
    required super.$db,
    required super.$table,
    super.joinBuilder,
    super.$addJoinBuilderToRootComposer,
    super.$removeJoinBuilderFromRootComposer,
  });
  ColumnOrderings<String> get id => $composableBuilder(
      column: $table.id, builder: (column) => ColumnOrderings(column));

  ColumnOrderings<int> get seq => $composableBuilder(
      column: $table.seq, builder: (column) => ColumnOrderings(column));

  ColumnOrderings<String> get code => $composableBuilder(
      column: $table.code, builder: (column) => ColumnOrderings(column));

  ColumnOrderings<String> get codeSafe => $composableBuilder(
      column: $table.codeSafe, builder: (column) => ColumnOrderings(column));

  ColumnOrderings<String> get name => $composableBuilder(
      column: $table.name, builder: (column) => ColumnOrderings(column));

  ColumnOrderings<String> get spec => $composableBuilder(
      column: $table.spec, builder: (column) => ColumnOrderings(column));

  ColumnOrderings<double> get qty => $composableBuilder(
      column: $table.qty, builder: (column) => ColumnOrderings(column));

  ColumnOrderings<String> get unit => $composableBuilder(
      column: $table.unit, builder: (column) => ColumnOrderings(column));

  ColumnOrderings<int> get requiredPhotos => $composableBuilder(
      column: $table.requiredPhotos,
      builder: (column) => ColumnOrderings(column));

  ColumnOrderings<String> get containerSummary => $composableBuilder(
      column: $table.containerSummary,
      builder: (column) => ColumnOrderings(column));

  ColumnOrderings<int> get sourceLineCount => $composableBuilder(
      column: $table.sourceLineCount,
      builder: (column) => ColumnOrderings(column));

  ColumnOrderings<String> get state => $composableBuilder(
      column: $table.state, builder: (column) => ColumnOrderings(column));

  ColumnOrderings<String> get notFoundReason => $composableBuilder(
      column: $table.notFoundReason,
      builder: (column) => ColumnOrderings(column));

  ColumnOrderings<String> get remark => $composableBuilder(
      column: $table.remark, builder: (column) => ColumnOrderings(column));

  ColumnOrderings<int> get deletedAt => $composableBuilder(
      column: $table.deletedAt, builder: (column) => ColumnOrderings(column));

  $$ProjectsTableOrderingComposer get projectId {
    final $$ProjectsTableOrderingComposer composer = $composerBuilder(
        composer: this,
        getCurrentColumn: (t) => t.projectId,
        referencedTable: $db.projects,
        getReferencedColumn: (t) => t.id,
        builder: (joinBuilder,
                {$addJoinBuilderToRootComposer,
                $removeJoinBuilderFromRootComposer}) =>
            $$ProjectsTableOrderingComposer(
              $db: $db,
              $table: $db.projects,
              $addJoinBuilderToRootComposer: $addJoinBuilderToRootComposer,
              joinBuilder: joinBuilder,
              $removeJoinBuilderFromRootComposer:
                  $removeJoinBuilderFromRootComposer,
            ));
    return composer;
  }
}

class $$ItemsTableAnnotationComposer
    extends Composer<_$AppDatabase, $ItemsTable> {
  $$ItemsTableAnnotationComposer({
    required super.$db,
    required super.$table,
    super.joinBuilder,
    super.$addJoinBuilderToRootComposer,
    super.$removeJoinBuilderFromRootComposer,
  });
  GeneratedColumn<String> get id =>
      $composableBuilder(column: $table.id, builder: (column) => column);

  GeneratedColumn<int> get seq =>
      $composableBuilder(column: $table.seq, builder: (column) => column);

  GeneratedColumn<String> get code =>
      $composableBuilder(column: $table.code, builder: (column) => column);

  GeneratedColumn<String> get codeSafe =>
      $composableBuilder(column: $table.codeSafe, builder: (column) => column);

  GeneratedColumn<String> get name =>
      $composableBuilder(column: $table.name, builder: (column) => column);

  GeneratedColumn<String> get spec =>
      $composableBuilder(column: $table.spec, builder: (column) => column);

  GeneratedColumn<double> get qty =>
      $composableBuilder(column: $table.qty, builder: (column) => column);

  GeneratedColumn<String> get unit =>
      $composableBuilder(column: $table.unit, builder: (column) => column);

  GeneratedColumn<int> get requiredPhotos => $composableBuilder(
      column: $table.requiredPhotos, builder: (column) => column);

  GeneratedColumn<String> get containerSummary => $composableBuilder(
      column: $table.containerSummary, builder: (column) => column);

  GeneratedColumn<int> get sourceLineCount => $composableBuilder(
      column: $table.sourceLineCount, builder: (column) => column);

  GeneratedColumn<String> get state =>
      $composableBuilder(column: $table.state, builder: (column) => column);

  GeneratedColumn<String> get notFoundReason => $composableBuilder(
      column: $table.notFoundReason, builder: (column) => column);

  GeneratedColumn<String> get remark =>
      $composableBuilder(column: $table.remark, builder: (column) => column);

  GeneratedColumn<int> get deletedAt =>
      $composableBuilder(column: $table.deletedAt, builder: (column) => column);

  $$ProjectsTableAnnotationComposer get projectId {
    final $$ProjectsTableAnnotationComposer composer = $composerBuilder(
        composer: this,
        getCurrentColumn: (t) => t.projectId,
        referencedTable: $db.projects,
        getReferencedColumn: (t) => t.id,
        builder: (joinBuilder,
                {$addJoinBuilderToRootComposer,
                $removeJoinBuilderFromRootComposer}) =>
            $$ProjectsTableAnnotationComposer(
              $db: $db,
              $table: $db.projects,
              $addJoinBuilderToRootComposer: $addJoinBuilderToRootComposer,
              joinBuilder: joinBuilder,
              $removeJoinBuilderFromRootComposer:
                  $removeJoinBuilderFromRootComposer,
            ));
    return composer;
  }

  Expression<T> itemPhotoExtrasRefs<T extends Object>(
      Expression<T> Function($$ItemPhotoExtrasTableAnnotationComposer a) f) {
    final $$ItemPhotoExtrasTableAnnotationComposer composer = $composerBuilder(
        composer: this,
        getCurrentColumn: (t) => t.id,
        referencedTable: $db.itemPhotoExtras,
        getReferencedColumn: (t) => t.itemId,
        builder: (joinBuilder,
                {$addJoinBuilderToRootComposer,
                $removeJoinBuilderFromRootComposer}) =>
            $$ItemPhotoExtrasTableAnnotationComposer(
              $db: $db,
              $table: $db.itemPhotoExtras,
              $addJoinBuilderToRootComposer: $addJoinBuilderToRootComposer,
              joinBuilder: joinBuilder,
              $removeJoinBuilderFromRootComposer:
                  $removeJoinBuilderFromRootComposer,
            ));
    return f(composer);
  }
}

class $$ItemsTableTableManager extends RootTableManager<
    _$AppDatabase,
    $ItemsTable,
    Item,
    $$ItemsTableFilterComposer,
    $$ItemsTableOrderingComposer,
    $$ItemsTableAnnotationComposer,
    $$ItemsTableCreateCompanionBuilder,
    $$ItemsTableUpdateCompanionBuilder,
    (Item, $$ItemsTableReferences),
    Item,
    PrefetchHooks Function({bool projectId, bool itemPhotoExtrasRefs})> {
  $$ItemsTableTableManager(_$AppDatabase db, $ItemsTable table)
      : super(TableManagerState(
          db: db,
          table: table,
          createFilteringComposer: () =>
              $$ItemsTableFilterComposer($db: db, $table: table),
          createOrderingComposer: () =>
              $$ItemsTableOrderingComposer($db: db, $table: table),
          createComputedFieldComposer: () =>
              $$ItemsTableAnnotationComposer($db: db, $table: table),
          updateCompanionCallback: ({
            Value<String> id = const Value.absent(),
            Value<String> projectId = const Value.absent(),
            Value<int> seq = const Value.absent(),
            Value<String> code = const Value.absent(),
            Value<String> codeSafe = const Value.absent(),
            Value<String?> name = const Value.absent(),
            Value<String?> spec = const Value.absent(),
            Value<double?> qty = const Value.absent(),
            Value<String?> unit = const Value.absent(),
            Value<int> requiredPhotos = const Value.absent(),
            Value<String?> containerSummary = const Value.absent(),
            Value<int> sourceLineCount = const Value.absent(),
            Value<String> state = const Value.absent(),
            Value<String?> notFoundReason = const Value.absent(),
            Value<String?> remark = const Value.absent(),
            Value<int?> deletedAt = const Value.absent(),
            Value<int> rowid = const Value.absent(),
          }) =>
              ItemsCompanion(
            id: id,
            projectId: projectId,
            seq: seq,
            code: code,
            codeSafe: codeSafe,
            name: name,
            spec: spec,
            qty: qty,
            unit: unit,
            requiredPhotos: requiredPhotos,
            containerSummary: containerSummary,
            sourceLineCount: sourceLineCount,
            state: state,
            notFoundReason: notFoundReason,
            remark: remark,
            deletedAt: deletedAt,
            rowid: rowid,
          ),
          createCompanionCallback: ({
            required String id,
            required String projectId,
            required int seq,
            required String code,
            required String codeSafe,
            Value<String?> name = const Value.absent(),
            Value<String?> spec = const Value.absent(),
            Value<double?> qty = const Value.absent(),
            Value<String?> unit = const Value.absent(),
            Value<int> requiredPhotos = const Value.absent(),
            Value<String?> containerSummary = const Value.absent(),
            Value<int> sourceLineCount = const Value.absent(),
            Value<String> state = const Value.absent(),
            Value<String?> notFoundReason = const Value.absent(),
            Value<String?> remark = const Value.absent(),
            Value<int?> deletedAt = const Value.absent(),
            Value<int> rowid = const Value.absent(),
          }) =>
              ItemsCompanion.insert(
            id: id,
            projectId: projectId,
            seq: seq,
            code: code,
            codeSafe: codeSafe,
            name: name,
            spec: spec,
            qty: qty,
            unit: unit,
            requiredPhotos: requiredPhotos,
            containerSummary: containerSummary,
            sourceLineCount: sourceLineCount,
            state: state,
            notFoundReason: notFoundReason,
            remark: remark,
            deletedAt: deletedAt,
            rowid: rowid,
          ),
          withReferenceMapper: (p0) => p0
              .map((e) =>
                  (e.readTable(table), $$ItemsTableReferences(db, table, e)))
              .toList(),
          prefetchHooksCallback: (
              {projectId = false, itemPhotoExtrasRefs = false}) {
            return PrefetchHooks(
              db: db,
              explicitlyWatchedTables: [
                if (itemPhotoExtrasRefs) db.itemPhotoExtras
              ],
              addJoins: <
                  T extends TableManagerState<
                      dynamic,
                      dynamic,
                      dynamic,
                      dynamic,
                      dynamic,
                      dynamic,
                      dynamic,
                      dynamic,
                      dynamic,
                      dynamic,
                      dynamic>>(state) {
                if (projectId) {
                  state = state.withJoin(
                    currentTable: table,
                    currentColumn: table.projectId,
                    referencedTable: $$ItemsTableReferences._projectIdTable(db),
                    referencedColumn:
                        $$ItemsTableReferences._projectIdTable(db).id,
                  ) as T;
                }

                return state;
              },
              getPrefetchedDataCallback: (items) async {
                return [
                  if (itemPhotoExtrasRefs)
                    await $_getPrefetchedData<Item, $ItemsTable,
                            ItemPhotoExtra>(
                        currentTable: table,
                        referencedTable: $$ItemsTableReferences
                            ._itemPhotoExtrasRefsTable(db),
                        managerFromTypedResult: (p0) =>
                            $$ItemsTableReferences(db, table, p0)
                                .itemPhotoExtrasRefs,
                        referencedItemsForCurrentItem: (item,
                                referencedItems) =>
                            referencedItems.where((e) => e.itemId == item.id),
                        typedResults: items)
                ];
              },
            );
          },
        ));
}

typedef $$ItemsTableProcessedTableManager = ProcessedTableManager<
    _$AppDatabase,
    $ItemsTable,
    Item,
    $$ItemsTableFilterComposer,
    $$ItemsTableOrderingComposer,
    $$ItemsTableAnnotationComposer,
    $$ItemsTableCreateCompanionBuilder,
    $$ItemsTableUpdateCompanionBuilder,
    (Item, $$ItemsTableReferences),
    Item,
    PrefetchHooks Function({bool projectId, bool itemPhotoExtrasRefs})>;
typedef $$CaptureSessionsTableCreateCompanionBuilder = CaptureSessionsCompanion
    Function({
  required String id,
  required String projectId,
  Value<String> source,
  required int startedAt,
  Value<int?> endedAt,
  Value<int> photoCount,
  Value<String?> note,
  Value<int> rowid,
});
typedef $$CaptureSessionsTableUpdateCompanionBuilder = CaptureSessionsCompanion
    Function({
  Value<String> id,
  Value<String> projectId,
  Value<String> source,
  Value<int> startedAt,
  Value<int?> endedAt,
  Value<int> photoCount,
  Value<String?> note,
  Value<int> rowid,
});

final class $$CaptureSessionsTableReferences extends BaseReferences<
    _$AppDatabase, $CaptureSessionsTable, CaptureSession> {
  $$CaptureSessionsTableReferences(
      super.$_db, super.$_table, super.$_typedResult);

  static $ProjectsTable _projectIdTable(_$AppDatabase db) =>
      db.projects.createAlias(
          $_aliasNameGenerator(db.captureSessions.projectId, db.projects.id));

  $$ProjectsTableProcessedTableManager get projectId {
    final $_column = $_itemColumn<String>('project_id')!;

    final manager = $$ProjectsTableTableManager($_db, $_db.projects)
        .filter((f) => f.id.sqlEquals($_column));
    final item = $_typedResult.readTableOrNull(_projectIdTable($_db));
    if (item == null) return manager;
    return ProcessedTableManager(
        manager.$state.copyWith(prefetchedData: [item]));
  }

  static MultiTypedResultKey<$PhotoGroupsTable, List<PhotoGroup>>
      _photoGroupsRefsTable(_$AppDatabase db) =>
          MultiTypedResultKey.fromTable(db.photoGroups,
              aliasName: $_aliasNameGenerator(
                  db.captureSessions.id, db.photoGroups.sessionId));

  $$PhotoGroupsTableProcessedTableManager get photoGroupsRefs {
    final manager = $$PhotoGroupsTableTableManager($_db, $_db.photoGroups)
        .filter((f) => f.sessionId.id.sqlEquals($_itemColumn<String>('id')!));

    final cache = $_typedResult.readTableOrNull(_photoGroupsRefsTable($_db));
    return ProcessedTableManager(
        manager.$state.copyWith(prefetchedData: cache));
  }

  static MultiTypedResultKey<$PhotosTable, List<Photo>> _photosRefsTable(
          _$AppDatabase db) =>
      MultiTypedResultKey.fromTable(db.photos,
          aliasName:
              $_aliasNameGenerator(db.captureSessions.id, db.photos.sessionId));

  $$PhotosTableProcessedTableManager get photosRefs {
    final manager = $$PhotosTableTableManager($_db, $_db.photos)
        .filter((f) => f.sessionId.id.sqlEquals($_itemColumn<String>('id')!));

    final cache = $_typedResult.readTableOrNull(_photosRefsTable($_db));
    return ProcessedTableManager(
        manager.$state.copyWith(prefetchedData: cache));
  }
}

class $$CaptureSessionsTableFilterComposer
    extends Composer<_$AppDatabase, $CaptureSessionsTable> {
  $$CaptureSessionsTableFilterComposer({
    required super.$db,
    required super.$table,
    super.joinBuilder,
    super.$addJoinBuilderToRootComposer,
    super.$removeJoinBuilderFromRootComposer,
  });
  ColumnFilters<String> get id => $composableBuilder(
      column: $table.id, builder: (column) => ColumnFilters(column));

  ColumnFilters<String> get source => $composableBuilder(
      column: $table.source, builder: (column) => ColumnFilters(column));

  ColumnFilters<int> get startedAt => $composableBuilder(
      column: $table.startedAt, builder: (column) => ColumnFilters(column));

  ColumnFilters<int> get endedAt => $composableBuilder(
      column: $table.endedAt, builder: (column) => ColumnFilters(column));

  ColumnFilters<int> get photoCount => $composableBuilder(
      column: $table.photoCount, builder: (column) => ColumnFilters(column));

  ColumnFilters<String> get note => $composableBuilder(
      column: $table.note, builder: (column) => ColumnFilters(column));

  $$ProjectsTableFilterComposer get projectId {
    final $$ProjectsTableFilterComposer composer = $composerBuilder(
        composer: this,
        getCurrentColumn: (t) => t.projectId,
        referencedTable: $db.projects,
        getReferencedColumn: (t) => t.id,
        builder: (joinBuilder,
                {$addJoinBuilderToRootComposer,
                $removeJoinBuilderFromRootComposer}) =>
            $$ProjectsTableFilterComposer(
              $db: $db,
              $table: $db.projects,
              $addJoinBuilderToRootComposer: $addJoinBuilderToRootComposer,
              joinBuilder: joinBuilder,
              $removeJoinBuilderFromRootComposer:
                  $removeJoinBuilderFromRootComposer,
            ));
    return composer;
  }

  Expression<bool> photoGroupsRefs(
      Expression<bool> Function($$PhotoGroupsTableFilterComposer f) f) {
    final $$PhotoGroupsTableFilterComposer composer = $composerBuilder(
        composer: this,
        getCurrentColumn: (t) => t.id,
        referencedTable: $db.photoGroups,
        getReferencedColumn: (t) => t.sessionId,
        builder: (joinBuilder,
                {$addJoinBuilderToRootComposer,
                $removeJoinBuilderFromRootComposer}) =>
            $$PhotoGroupsTableFilterComposer(
              $db: $db,
              $table: $db.photoGroups,
              $addJoinBuilderToRootComposer: $addJoinBuilderToRootComposer,
              joinBuilder: joinBuilder,
              $removeJoinBuilderFromRootComposer:
                  $removeJoinBuilderFromRootComposer,
            ));
    return f(composer);
  }

  Expression<bool> photosRefs(
      Expression<bool> Function($$PhotosTableFilterComposer f) f) {
    final $$PhotosTableFilterComposer composer = $composerBuilder(
        composer: this,
        getCurrentColumn: (t) => t.id,
        referencedTable: $db.photos,
        getReferencedColumn: (t) => t.sessionId,
        builder: (joinBuilder,
                {$addJoinBuilderToRootComposer,
                $removeJoinBuilderFromRootComposer}) =>
            $$PhotosTableFilterComposer(
              $db: $db,
              $table: $db.photos,
              $addJoinBuilderToRootComposer: $addJoinBuilderToRootComposer,
              joinBuilder: joinBuilder,
              $removeJoinBuilderFromRootComposer:
                  $removeJoinBuilderFromRootComposer,
            ));
    return f(composer);
  }
}

class $$CaptureSessionsTableOrderingComposer
    extends Composer<_$AppDatabase, $CaptureSessionsTable> {
  $$CaptureSessionsTableOrderingComposer({
    required super.$db,
    required super.$table,
    super.joinBuilder,
    super.$addJoinBuilderToRootComposer,
    super.$removeJoinBuilderFromRootComposer,
  });
  ColumnOrderings<String> get id => $composableBuilder(
      column: $table.id, builder: (column) => ColumnOrderings(column));

  ColumnOrderings<String> get source => $composableBuilder(
      column: $table.source, builder: (column) => ColumnOrderings(column));

  ColumnOrderings<int> get startedAt => $composableBuilder(
      column: $table.startedAt, builder: (column) => ColumnOrderings(column));

  ColumnOrderings<int> get endedAt => $composableBuilder(
      column: $table.endedAt, builder: (column) => ColumnOrderings(column));

  ColumnOrderings<int> get photoCount => $composableBuilder(
      column: $table.photoCount, builder: (column) => ColumnOrderings(column));

  ColumnOrderings<String> get note => $composableBuilder(
      column: $table.note, builder: (column) => ColumnOrderings(column));

  $$ProjectsTableOrderingComposer get projectId {
    final $$ProjectsTableOrderingComposer composer = $composerBuilder(
        composer: this,
        getCurrentColumn: (t) => t.projectId,
        referencedTable: $db.projects,
        getReferencedColumn: (t) => t.id,
        builder: (joinBuilder,
                {$addJoinBuilderToRootComposer,
                $removeJoinBuilderFromRootComposer}) =>
            $$ProjectsTableOrderingComposer(
              $db: $db,
              $table: $db.projects,
              $addJoinBuilderToRootComposer: $addJoinBuilderToRootComposer,
              joinBuilder: joinBuilder,
              $removeJoinBuilderFromRootComposer:
                  $removeJoinBuilderFromRootComposer,
            ));
    return composer;
  }
}

class $$CaptureSessionsTableAnnotationComposer
    extends Composer<_$AppDatabase, $CaptureSessionsTable> {
  $$CaptureSessionsTableAnnotationComposer({
    required super.$db,
    required super.$table,
    super.joinBuilder,
    super.$addJoinBuilderToRootComposer,
    super.$removeJoinBuilderFromRootComposer,
  });
  GeneratedColumn<String> get id =>
      $composableBuilder(column: $table.id, builder: (column) => column);

  GeneratedColumn<String> get source =>
      $composableBuilder(column: $table.source, builder: (column) => column);

  GeneratedColumn<int> get startedAt =>
      $composableBuilder(column: $table.startedAt, builder: (column) => column);

  GeneratedColumn<int> get endedAt =>
      $composableBuilder(column: $table.endedAt, builder: (column) => column);

  GeneratedColumn<int> get photoCount => $composableBuilder(
      column: $table.photoCount, builder: (column) => column);

  GeneratedColumn<String> get note =>
      $composableBuilder(column: $table.note, builder: (column) => column);

  $$ProjectsTableAnnotationComposer get projectId {
    final $$ProjectsTableAnnotationComposer composer = $composerBuilder(
        composer: this,
        getCurrentColumn: (t) => t.projectId,
        referencedTable: $db.projects,
        getReferencedColumn: (t) => t.id,
        builder: (joinBuilder,
                {$addJoinBuilderToRootComposer,
                $removeJoinBuilderFromRootComposer}) =>
            $$ProjectsTableAnnotationComposer(
              $db: $db,
              $table: $db.projects,
              $addJoinBuilderToRootComposer: $addJoinBuilderToRootComposer,
              joinBuilder: joinBuilder,
              $removeJoinBuilderFromRootComposer:
                  $removeJoinBuilderFromRootComposer,
            ));
    return composer;
  }

  Expression<T> photoGroupsRefs<T extends Object>(
      Expression<T> Function($$PhotoGroupsTableAnnotationComposer a) f) {
    final $$PhotoGroupsTableAnnotationComposer composer = $composerBuilder(
        composer: this,
        getCurrentColumn: (t) => t.id,
        referencedTable: $db.photoGroups,
        getReferencedColumn: (t) => t.sessionId,
        builder: (joinBuilder,
                {$addJoinBuilderToRootComposer,
                $removeJoinBuilderFromRootComposer}) =>
            $$PhotoGroupsTableAnnotationComposer(
              $db: $db,
              $table: $db.photoGroups,
              $addJoinBuilderToRootComposer: $addJoinBuilderToRootComposer,
              joinBuilder: joinBuilder,
              $removeJoinBuilderFromRootComposer:
                  $removeJoinBuilderFromRootComposer,
            ));
    return f(composer);
  }

  Expression<T> photosRefs<T extends Object>(
      Expression<T> Function($$PhotosTableAnnotationComposer a) f) {
    final $$PhotosTableAnnotationComposer composer = $composerBuilder(
        composer: this,
        getCurrentColumn: (t) => t.id,
        referencedTable: $db.photos,
        getReferencedColumn: (t) => t.sessionId,
        builder: (joinBuilder,
                {$addJoinBuilderToRootComposer,
                $removeJoinBuilderFromRootComposer}) =>
            $$PhotosTableAnnotationComposer(
              $db: $db,
              $table: $db.photos,
              $addJoinBuilderToRootComposer: $addJoinBuilderToRootComposer,
              joinBuilder: joinBuilder,
              $removeJoinBuilderFromRootComposer:
                  $removeJoinBuilderFromRootComposer,
            ));
    return f(composer);
  }
}

class $$CaptureSessionsTableTableManager extends RootTableManager<
    _$AppDatabase,
    $CaptureSessionsTable,
    CaptureSession,
    $$CaptureSessionsTableFilterComposer,
    $$CaptureSessionsTableOrderingComposer,
    $$CaptureSessionsTableAnnotationComposer,
    $$CaptureSessionsTableCreateCompanionBuilder,
    $$CaptureSessionsTableUpdateCompanionBuilder,
    (CaptureSession, $$CaptureSessionsTableReferences),
    CaptureSession,
    PrefetchHooks Function(
        {bool projectId, bool photoGroupsRefs, bool photosRefs})> {
  $$CaptureSessionsTableTableManager(
      _$AppDatabase db, $CaptureSessionsTable table)
      : super(TableManagerState(
          db: db,
          table: table,
          createFilteringComposer: () =>
              $$CaptureSessionsTableFilterComposer($db: db, $table: table),
          createOrderingComposer: () =>
              $$CaptureSessionsTableOrderingComposer($db: db, $table: table),
          createComputedFieldComposer: () =>
              $$CaptureSessionsTableAnnotationComposer($db: db, $table: table),
          updateCompanionCallback: ({
            Value<String> id = const Value.absent(),
            Value<String> projectId = const Value.absent(),
            Value<String> source = const Value.absent(),
            Value<int> startedAt = const Value.absent(),
            Value<int?> endedAt = const Value.absent(),
            Value<int> photoCount = const Value.absent(),
            Value<String?> note = const Value.absent(),
            Value<int> rowid = const Value.absent(),
          }) =>
              CaptureSessionsCompanion(
            id: id,
            projectId: projectId,
            source: source,
            startedAt: startedAt,
            endedAt: endedAt,
            photoCount: photoCount,
            note: note,
            rowid: rowid,
          ),
          createCompanionCallback: ({
            required String id,
            required String projectId,
            Value<String> source = const Value.absent(),
            required int startedAt,
            Value<int?> endedAt = const Value.absent(),
            Value<int> photoCount = const Value.absent(),
            Value<String?> note = const Value.absent(),
            Value<int> rowid = const Value.absent(),
          }) =>
              CaptureSessionsCompanion.insert(
            id: id,
            projectId: projectId,
            source: source,
            startedAt: startedAt,
            endedAt: endedAt,
            photoCount: photoCount,
            note: note,
            rowid: rowid,
          ),
          withReferenceMapper: (p0) => p0
              .map((e) => (
                    e.readTable(table),
                    $$CaptureSessionsTableReferences(db, table, e)
                  ))
              .toList(),
          prefetchHooksCallback: (
              {projectId = false,
              photoGroupsRefs = false,
              photosRefs = false}) {
            return PrefetchHooks(
              db: db,
              explicitlyWatchedTables: [
                if (photoGroupsRefs) db.photoGroups,
                if (photosRefs) db.photos
              ],
              addJoins: <
                  T extends TableManagerState<
                      dynamic,
                      dynamic,
                      dynamic,
                      dynamic,
                      dynamic,
                      dynamic,
                      dynamic,
                      dynamic,
                      dynamic,
                      dynamic,
                      dynamic>>(state) {
                if (projectId) {
                  state = state.withJoin(
                    currentTable: table,
                    currentColumn: table.projectId,
                    referencedTable:
                        $$CaptureSessionsTableReferences._projectIdTable(db),
                    referencedColumn:
                        $$CaptureSessionsTableReferences._projectIdTable(db).id,
                  ) as T;
                }

                return state;
              },
              getPrefetchedDataCallback: (items) async {
                return [
                  if (photoGroupsRefs)
                    await $_getPrefetchedData<CaptureSession, $CaptureSessionsTable,
                            PhotoGroup>(
                        currentTable: table,
                        referencedTable: $$CaptureSessionsTableReferences
                            ._photoGroupsRefsTable(db),
                        managerFromTypedResult: (p0) =>
                            $$CaptureSessionsTableReferences(db, table, p0)
                                .photoGroupsRefs,
                        referencedItemsForCurrentItem:
                            (item, referencedItems) => referencedItems
                                .where((e) => e.sessionId == item.id),
                        typedResults: items),
                  if (photosRefs)
                    await $_getPrefetchedData<CaptureSession,
                            $CaptureSessionsTable, Photo>(
                        currentTable: table,
                        referencedTable: $$CaptureSessionsTableReferences
                            ._photosRefsTable(db),
                        managerFromTypedResult: (p0) =>
                            $$CaptureSessionsTableReferences(db, table, p0)
                                .photosRefs,
                        referencedItemsForCurrentItem:
                            (item, referencedItems) => referencedItems
                                .where((e) => e.sessionId == item.id),
                        typedResults: items)
                ];
              },
            );
          },
        ));
}

typedef $$CaptureSessionsTableProcessedTableManager = ProcessedTableManager<
    _$AppDatabase,
    $CaptureSessionsTable,
    CaptureSession,
    $$CaptureSessionsTableFilterComposer,
    $$CaptureSessionsTableOrderingComposer,
    $$CaptureSessionsTableAnnotationComposer,
    $$CaptureSessionsTableCreateCompanionBuilder,
    $$CaptureSessionsTableUpdateCompanionBuilder,
    (CaptureSession, $$CaptureSessionsTableReferences),
    CaptureSession,
    PrefetchHooks Function(
        {bool projectId, bool photoGroupsRefs, bool photosRefs})>;
typedef $$PhotoGroupsTableCreateCompanionBuilder = PhotoGroupsCompanion
    Function({
  required String id,
  required String projectId,
  required String sessionId,
  required int seq,
  Value<String?> coverPhotoId,
  Value<int> photoCount,
  Value<String> origin,
  Value<String> category,
  Value<String?> carton,
  Value<String?> suggestedItemId,
  Value<double?> suggestionConf,
  Value<String?> suggestionJson,
  Value<String> suggestState,
  Value<String?> itemId,
  Value<int?> confirmedAt,
  required int createdAt,
  Value<int> rowid,
});
typedef $$PhotoGroupsTableUpdateCompanionBuilder = PhotoGroupsCompanion
    Function({
  Value<String> id,
  Value<String> projectId,
  Value<String> sessionId,
  Value<int> seq,
  Value<String?> coverPhotoId,
  Value<int> photoCount,
  Value<String> origin,
  Value<String> category,
  Value<String?> carton,
  Value<String?> suggestedItemId,
  Value<double?> suggestionConf,
  Value<String?> suggestionJson,
  Value<String> suggestState,
  Value<String?> itemId,
  Value<int?> confirmedAt,
  Value<int> createdAt,
  Value<int> rowid,
});

final class $$PhotoGroupsTableReferences
    extends BaseReferences<_$AppDatabase, $PhotoGroupsTable, PhotoGroup> {
  $$PhotoGroupsTableReferences(super.$_db, super.$_table, super.$_typedResult);

  static $ProjectsTable _projectIdTable(_$AppDatabase db) =>
      db.projects.createAlias(
          $_aliasNameGenerator(db.photoGroups.projectId, db.projects.id));

  $$ProjectsTableProcessedTableManager get projectId {
    final $_column = $_itemColumn<String>('project_id')!;

    final manager = $$ProjectsTableTableManager($_db, $_db.projects)
        .filter((f) => f.id.sqlEquals($_column));
    final item = $_typedResult.readTableOrNull(_projectIdTable($_db));
    if (item == null) return manager;
    return ProcessedTableManager(
        manager.$state.copyWith(prefetchedData: [item]));
  }

  static $CaptureSessionsTable _sessionIdTable(_$AppDatabase db) =>
      db.captureSessions.createAlias($_aliasNameGenerator(
          db.photoGroups.sessionId, db.captureSessions.id));

  $$CaptureSessionsTableProcessedTableManager get sessionId {
    final $_column = $_itemColumn<String>('session_id')!;

    final manager =
        $$CaptureSessionsTableTableManager($_db, $_db.captureSessions)
            .filter((f) => f.id.sqlEquals($_column));
    final item = $_typedResult.readTableOrNull(_sessionIdTable($_db));
    if (item == null) return manager;
    return ProcessedTableManager(
        manager.$state.copyWith(prefetchedData: [item]));
  }
}

class $$PhotoGroupsTableFilterComposer
    extends Composer<_$AppDatabase, $PhotoGroupsTable> {
  $$PhotoGroupsTableFilterComposer({
    required super.$db,
    required super.$table,
    super.joinBuilder,
    super.$addJoinBuilderToRootComposer,
    super.$removeJoinBuilderFromRootComposer,
  });
  ColumnFilters<String> get id => $composableBuilder(
      column: $table.id, builder: (column) => ColumnFilters(column));

  ColumnFilters<int> get seq => $composableBuilder(
      column: $table.seq, builder: (column) => ColumnFilters(column));

  ColumnFilters<String> get coverPhotoId => $composableBuilder(
      column: $table.coverPhotoId, builder: (column) => ColumnFilters(column));

  ColumnFilters<int> get photoCount => $composableBuilder(
      column: $table.photoCount, builder: (column) => ColumnFilters(column));

  ColumnFilters<String> get origin => $composableBuilder(
      column: $table.origin, builder: (column) => ColumnFilters(column));

  ColumnFilters<String> get category => $composableBuilder(
      column: $table.category, builder: (column) => ColumnFilters(column));

  ColumnFilters<String> get carton => $composableBuilder(
      column: $table.carton, builder: (column) => ColumnFilters(column));

  ColumnFilters<String> get suggestedItemId => $composableBuilder(
      column: $table.suggestedItemId,
      builder: (column) => ColumnFilters(column));

  ColumnFilters<double> get suggestionConf => $composableBuilder(
      column: $table.suggestionConf,
      builder: (column) => ColumnFilters(column));

  ColumnFilters<String> get suggestionJson => $composableBuilder(
      column: $table.suggestionJson,
      builder: (column) => ColumnFilters(column));

  ColumnFilters<String> get suggestState => $composableBuilder(
      column: $table.suggestState, builder: (column) => ColumnFilters(column));

  ColumnFilters<String> get itemId => $composableBuilder(
      column: $table.itemId, builder: (column) => ColumnFilters(column));

  ColumnFilters<int> get confirmedAt => $composableBuilder(
      column: $table.confirmedAt, builder: (column) => ColumnFilters(column));

  ColumnFilters<int> get createdAt => $composableBuilder(
      column: $table.createdAt, builder: (column) => ColumnFilters(column));

  $$ProjectsTableFilterComposer get projectId {
    final $$ProjectsTableFilterComposer composer = $composerBuilder(
        composer: this,
        getCurrentColumn: (t) => t.projectId,
        referencedTable: $db.projects,
        getReferencedColumn: (t) => t.id,
        builder: (joinBuilder,
                {$addJoinBuilderToRootComposer,
                $removeJoinBuilderFromRootComposer}) =>
            $$ProjectsTableFilterComposer(
              $db: $db,
              $table: $db.projects,
              $addJoinBuilderToRootComposer: $addJoinBuilderToRootComposer,
              joinBuilder: joinBuilder,
              $removeJoinBuilderFromRootComposer:
                  $removeJoinBuilderFromRootComposer,
            ));
    return composer;
  }

  $$CaptureSessionsTableFilterComposer get sessionId {
    final $$CaptureSessionsTableFilterComposer composer = $composerBuilder(
        composer: this,
        getCurrentColumn: (t) => t.sessionId,
        referencedTable: $db.captureSessions,
        getReferencedColumn: (t) => t.id,
        builder: (joinBuilder,
                {$addJoinBuilderToRootComposer,
                $removeJoinBuilderFromRootComposer}) =>
            $$CaptureSessionsTableFilterComposer(
              $db: $db,
              $table: $db.captureSessions,
              $addJoinBuilderToRootComposer: $addJoinBuilderToRootComposer,
              joinBuilder: joinBuilder,
              $removeJoinBuilderFromRootComposer:
                  $removeJoinBuilderFromRootComposer,
            ));
    return composer;
  }
}

class $$PhotoGroupsTableOrderingComposer
    extends Composer<_$AppDatabase, $PhotoGroupsTable> {
  $$PhotoGroupsTableOrderingComposer({
    required super.$db,
    required super.$table,
    super.joinBuilder,
    super.$addJoinBuilderToRootComposer,
    super.$removeJoinBuilderFromRootComposer,
  });
  ColumnOrderings<String> get id => $composableBuilder(
      column: $table.id, builder: (column) => ColumnOrderings(column));

  ColumnOrderings<int> get seq => $composableBuilder(
      column: $table.seq, builder: (column) => ColumnOrderings(column));

  ColumnOrderings<String> get coverPhotoId => $composableBuilder(
      column: $table.coverPhotoId,
      builder: (column) => ColumnOrderings(column));

  ColumnOrderings<int> get photoCount => $composableBuilder(
      column: $table.photoCount, builder: (column) => ColumnOrderings(column));

  ColumnOrderings<String> get origin => $composableBuilder(
      column: $table.origin, builder: (column) => ColumnOrderings(column));

  ColumnOrderings<String> get category => $composableBuilder(
      column: $table.category, builder: (column) => ColumnOrderings(column));

  ColumnOrderings<String> get carton => $composableBuilder(
      column: $table.carton, builder: (column) => ColumnOrderings(column));

  ColumnOrderings<String> get suggestedItemId => $composableBuilder(
      column: $table.suggestedItemId,
      builder: (column) => ColumnOrderings(column));

  ColumnOrderings<double> get suggestionConf => $composableBuilder(
      column: $table.suggestionConf,
      builder: (column) => ColumnOrderings(column));

  ColumnOrderings<String> get suggestionJson => $composableBuilder(
      column: $table.suggestionJson,
      builder: (column) => ColumnOrderings(column));

  ColumnOrderings<String> get suggestState => $composableBuilder(
      column: $table.suggestState,
      builder: (column) => ColumnOrderings(column));

  ColumnOrderings<String> get itemId => $composableBuilder(
      column: $table.itemId, builder: (column) => ColumnOrderings(column));

  ColumnOrderings<int> get confirmedAt => $composableBuilder(
      column: $table.confirmedAt, builder: (column) => ColumnOrderings(column));

  ColumnOrderings<int> get createdAt => $composableBuilder(
      column: $table.createdAt, builder: (column) => ColumnOrderings(column));

  $$ProjectsTableOrderingComposer get projectId {
    final $$ProjectsTableOrderingComposer composer = $composerBuilder(
        composer: this,
        getCurrentColumn: (t) => t.projectId,
        referencedTable: $db.projects,
        getReferencedColumn: (t) => t.id,
        builder: (joinBuilder,
                {$addJoinBuilderToRootComposer,
                $removeJoinBuilderFromRootComposer}) =>
            $$ProjectsTableOrderingComposer(
              $db: $db,
              $table: $db.projects,
              $addJoinBuilderToRootComposer: $addJoinBuilderToRootComposer,
              joinBuilder: joinBuilder,
              $removeJoinBuilderFromRootComposer:
                  $removeJoinBuilderFromRootComposer,
            ));
    return composer;
  }

  $$CaptureSessionsTableOrderingComposer get sessionId {
    final $$CaptureSessionsTableOrderingComposer composer = $composerBuilder(
        composer: this,
        getCurrentColumn: (t) => t.sessionId,
        referencedTable: $db.captureSessions,
        getReferencedColumn: (t) => t.id,
        builder: (joinBuilder,
                {$addJoinBuilderToRootComposer,
                $removeJoinBuilderFromRootComposer}) =>
            $$CaptureSessionsTableOrderingComposer(
              $db: $db,
              $table: $db.captureSessions,
              $addJoinBuilderToRootComposer: $addJoinBuilderToRootComposer,
              joinBuilder: joinBuilder,
              $removeJoinBuilderFromRootComposer:
                  $removeJoinBuilderFromRootComposer,
            ));
    return composer;
  }
}

class $$PhotoGroupsTableAnnotationComposer
    extends Composer<_$AppDatabase, $PhotoGroupsTable> {
  $$PhotoGroupsTableAnnotationComposer({
    required super.$db,
    required super.$table,
    super.joinBuilder,
    super.$addJoinBuilderToRootComposer,
    super.$removeJoinBuilderFromRootComposer,
  });
  GeneratedColumn<String> get id =>
      $composableBuilder(column: $table.id, builder: (column) => column);

  GeneratedColumn<int> get seq =>
      $composableBuilder(column: $table.seq, builder: (column) => column);

  GeneratedColumn<String> get coverPhotoId => $composableBuilder(
      column: $table.coverPhotoId, builder: (column) => column);

  GeneratedColumn<int> get photoCount => $composableBuilder(
      column: $table.photoCount, builder: (column) => column);

  GeneratedColumn<String> get origin =>
      $composableBuilder(column: $table.origin, builder: (column) => column);

  GeneratedColumn<String> get category =>
      $composableBuilder(column: $table.category, builder: (column) => column);

  GeneratedColumn<String> get carton =>
      $composableBuilder(column: $table.carton, builder: (column) => column);

  GeneratedColumn<String> get suggestedItemId => $composableBuilder(
      column: $table.suggestedItemId, builder: (column) => column);

  GeneratedColumn<double> get suggestionConf => $composableBuilder(
      column: $table.suggestionConf, builder: (column) => column);

  GeneratedColumn<String> get suggestionJson => $composableBuilder(
      column: $table.suggestionJson, builder: (column) => column);

  GeneratedColumn<String> get suggestState => $composableBuilder(
      column: $table.suggestState, builder: (column) => column);

  GeneratedColumn<String> get itemId =>
      $composableBuilder(column: $table.itemId, builder: (column) => column);

  GeneratedColumn<int> get confirmedAt => $composableBuilder(
      column: $table.confirmedAt, builder: (column) => column);

  GeneratedColumn<int> get createdAt =>
      $composableBuilder(column: $table.createdAt, builder: (column) => column);

  $$ProjectsTableAnnotationComposer get projectId {
    final $$ProjectsTableAnnotationComposer composer = $composerBuilder(
        composer: this,
        getCurrentColumn: (t) => t.projectId,
        referencedTable: $db.projects,
        getReferencedColumn: (t) => t.id,
        builder: (joinBuilder,
                {$addJoinBuilderToRootComposer,
                $removeJoinBuilderFromRootComposer}) =>
            $$ProjectsTableAnnotationComposer(
              $db: $db,
              $table: $db.projects,
              $addJoinBuilderToRootComposer: $addJoinBuilderToRootComposer,
              joinBuilder: joinBuilder,
              $removeJoinBuilderFromRootComposer:
                  $removeJoinBuilderFromRootComposer,
            ));
    return composer;
  }

  $$CaptureSessionsTableAnnotationComposer get sessionId {
    final $$CaptureSessionsTableAnnotationComposer composer = $composerBuilder(
        composer: this,
        getCurrentColumn: (t) => t.sessionId,
        referencedTable: $db.captureSessions,
        getReferencedColumn: (t) => t.id,
        builder: (joinBuilder,
                {$addJoinBuilderToRootComposer,
                $removeJoinBuilderFromRootComposer}) =>
            $$CaptureSessionsTableAnnotationComposer(
              $db: $db,
              $table: $db.captureSessions,
              $addJoinBuilderToRootComposer: $addJoinBuilderToRootComposer,
              joinBuilder: joinBuilder,
              $removeJoinBuilderFromRootComposer:
                  $removeJoinBuilderFromRootComposer,
            ));
    return composer;
  }
}

class $$PhotoGroupsTableTableManager extends RootTableManager<
    _$AppDatabase,
    $PhotoGroupsTable,
    PhotoGroup,
    $$PhotoGroupsTableFilterComposer,
    $$PhotoGroupsTableOrderingComposer,
    $$PhotoGroupsTableAnnotationComposer,
    $$PhotoGroupsTableCreateCompanionBuilder,
    $$PhotoGroupsTableUpdateCompanionBuilder,
    (PhotoGroup, $$PhotoGroupsTableReferences),
    PhotoGroup,
    PrefetchHooks Function({bool projectId, bool sessionId})> {
  $$PhotoGroupsTableTableManager(_$AppDatabase db, $PhotoGroupsTable table)
      : super(TableManagerState(
          db: db,
          table: table,
          createFilteringComposer: () =>
              $$PhotoGroupsTableFilterComposer($db: db, $table: table),
          createOrderingComposer: () =>
              $$PhotoGroupsTableOrderingComposer($db: db, $table: table),
          createComputedFieldComposer: () =>
              $$PhotoGroupsTableAnnotationComposer($db: db, $table: table),
          updateCompanionCallback: ({
            Value<String> id = const Value.absent(),
            Value<String> projectId = const Value.absent(),
            Value<String> sessionId = const Value.absent(),
            Value<int> seq = const Value.absent(),
            Value<String?> coverPhotoId = const Value.absent(),
            Value<int> photoCount = const Value.absent(),
            Value<String> origin = const Value.absent(),
            Value<String> category = const Value.absent(),
            Value<String?> carton = const Value.absent(),
            Value<String?> suggestedItemId = const Value.absent(),
            Value<double?> suggestionConf = const Value.absent(),
            Value<String?> suggestionJson = const Value.absent(),
            Value<String> suggestState = const Value.absent(),
            Value<String?> itemId = const Value.absent(),
            Value<int?> confirmedAt = const Value.absent(),
            Value<int> createdAt = const Value.absent(),
            Value<int> rowid = const Value.absent(),
          }) =>
              PhotoGroupsCompanion(
            id: id,
            projectId: projectId,
            sessionId: sessionId,
            seq: seq,
            coverPhotoId: coverPhotoId,
            photoCount: photoCount,
            origin: origin,
            category: category,
            carton: carton,
            suggestedItemId: suggestedItemId,
            suggestionConf: suggestionConf,
            suggestionJson: suggestionJson,
            suggestState: suggestState,
            itemId: itemId,
            confirmedAt: confirmedAt,
            createdAt: createdAt,
            rowid: rowid,
          ),
          createCompanionCallback: ({
            required String id,
            required String projectId,
            required String sessionId,
            required int seq,
            Value<String?> coverPhotoId = const Value.absent(),
            Value<int> photoCount = const Value.absent(),
            Value<String> origin = const Value.absent(),
            Value<String> category = const Value.absent(),
            Value<String?> carton = const Value.absent(),
            Value<String?> suggestedItemId = const Value.absent(),
            Value<double?> suggestionConf = const Value.absent(),
            Value<String?> suggestionJson = const Value.absent(),
            Value<String> suggestState = const Value.absent(),
            Value<String?> itemId = const Value.absent(),
            Value<int?> confirmedAt = const Value.absent(),
            required int createdAt,
            Value<int> rowid = const Value.absent(),
          }) =>
              PhotoGroupsCompanion.insert(
            id: id,
            projectId: projectId,
            sessionId: sessionId,
            seq: seq,
            coverPhotoId: coverPhotoId,
            photoCount: photoCount,
            origin: origin,
            category: category,
            carton: carton,
            suggestedItemId: suggestedItemId,
            suggestionConf: suggestionConf,
            suggestionJson: suggestionJson,
            suggestState: suggestState,
            itemId: itemId,
            confirmedAt: confirmedAt,
            createdAt: createdAt,
            rowid: rowid,
          ),
          withReferenceMapper: (p0) => p0
              .map((e) => (
                    e.readTable(table),
                    $$PhotoGroupsTableReferences(db, table, e)
                  ))
              .toList(),
          prefetchHooksCallback: ({projectId = false, sessionId = false}) {
            return PrefetchHooks(
              db: db,
              explicitlyWatchedTables: [],
              addJoins: <
                  T extends TableManagerState<
                      dynamic,
                      dynamic,
                      dynamic,
                      dynamic,
                      dynamic,
                      dynamic,
                      dynamic,
                      dynamic,
                      dynamic,
                      dynamic,
                      dynamic>>(state) {
                if (projectId) {
                  state = state.withJoin(
                    currentTable: table,
                    currentColumn: table.projectId,
                    referencedTable:
                        $$PhotoGroupsTableReferences._projectIdTable(db),
                    referencedColumn:
                        $$PhotoGroupsTableReferences._projectIdTable(db).id,
                  ) as T;
                }
                if (sessionId) {
                  state = state.withJoin(
                    currentTable: table,
                    currentColumn: table.sessionId,
                    referencedTable:
                        $$PhotoGroupsTableReferences._sessionIdTable(db),
                    referencedColumn:
                        $$PhotoGroupsTableReferences._sessionIdTable(db).id,
                  ) as T;
                }

                return state;
              },
              getPrefetchedDataCallback: (items) async {
                return [];
              },
            );
          },
        ));
}

typedef $$PhotoGroupsTableProcessedTableManager = ProcessedTableManager<
    _$AppDatabase,
    $PhotoGroupsTable,
    PhotoGroup,
    $$PhotoGroupsTableFilterComposer,
    $$PhotoGroupsTableOrderingComposer,
    $$PhotoGroupsTableAnnotationComposer,
    $$PhotoGroupsTableCreateCompanionBuilder,
    $$PhotoGroupsTableUpdateCompanionBuilder,
    (PhotoGroup, $$PhotoGroupsTableReferences),
    PhotoGroup,
    PrefetchHooks Function({bool projectId, bool sessionId})>;
typedef $$PhotosTableCreateCompanionBuilder = PhotosCompanion Function({
  required String id,
  required String projectId,
  required String sessionId,
  Value<String?> groupId,
  required String filePath,
  Value<String?> thumbPath,
  Value<int?> width,
  Value<int?> height,
  Value<int?> bytes,
  required int takenAt,
  required int seq,
  Value<String?> itemId,
  Value<String> state,
  Value<String> category,
  Value<String> ocrState,
  Value<String?> sharpnessFlag,
  Value<String?> contentHash,
  required int createdAt,
  Value<int> rowid,
});
typedef $$PhotosTableUpdateCompanionBuilder = PhotosCompanion Function({
  Value<String> id,
  Value<String> projectId,
  Value<String> sessionId,
  Value<String?> groupId,
  Value<String> filePath,
  Value<String?> thumbPath,
  Value<int?> width,
  Value<int?> height,
  Value<int?> bytes,
  Value<int> takenAt,
  Value<int> seq,
  Value<String?> itemId,
  Value<String> state,
  Value<String> category,
  Value<String> ocrState,
  Value<String?> sharpnessFlag,
  Value<String?> contentHash,
  Value<int> createdAt,
  Value<int> rowid,
});

final class $$PhotosTableReferences
    extends BaseReferences<_$AppDatabase, $PhotosTable, Photo> {
  $$PhotosTableReferences(super.$_db, super.$_table, super.$_typedResult);

  static $ProjectsTable _projectIdTable(_$AppDatabase db) => db.projects
      .createAlias($_aliasNameGenerator(db.photos.projectId, db.projects.id));

  $$ProjectsTableProcessedTableManager get projectId {
    final $_column = $_itemColumn<String>('project_id')!;

    final manager = $$ProjectsTableTableManager($_db, $_db.projects)
        .filter((f) => f.id.sqlEquals($_column));
    final item = $_typedResult.readTableOrNull(_projectIdTable($_db));
    if (item == null) return manager;
    return ProcessedTableManager(
        manager.$state.copyWith(prefetchedData: [item]));
  }

  static $CaptureSessionsTable _sessionIdTable(_$AppDatabase db) =>
      db.captureSessions.createAlias(
          $_aliasNameGenerator(db.photos.sessionId, db.captureSessions.id));

  $$CaptureSessionsTableProcessedTableManager get sessionId {
    final $_column = $_itemColumn<String>('session_id')!;

    final manager =
        $$CaptureSessionsTableTableManager($_db, $_db.captureSessions)
            .filter((f) => f.id.sqlEquals($_column));
    final item = $_typedResult.readTableOrNull(_sessionIdTable($_db));
    if (item == null) return manager;
    return ProcessedTableManager(
        manager.$state.copyWith(prefetchedData: [item]));
  }

  static MultiTypedResultKey<$OcrTokensTable, List<OcrToken>>
      _ocrTokensRefsTable(_$AppDatabase db) => MultiTypedResultKey.fromTable(
          db.ocrTokens,
          aliasName: $_aliasNameGenerator(db.photos.id, db.ocrTokens.photoId));

  $$OcrTokensTableProcessedTableManager get ocrTokensRefs {
    final manager = $$OcrTokensTableTableManager($_db, $_db.ocrTokens)
        .filter((f) => f.photoId.id.sqlEquals($_itemColumn<String>('id')!));

    final cache = $_typedResult.readTableOrNull(_ocrTokensRefsTable($_db));
    return ProcessedTableManager(
        manager.$state.copyWith(prefetchedData: cache));
  }

  static MultiTypedResultKey<$ItemPhotoExtrasTable, List<ItemPhotoExtra>>
      _itemPhotoExtrasRefsTable(_$AppDatabase db) =>
          MultiTypedResultKey.fromTable(db.itemPhotoExtras,
              aliasName: $_aliasNameGenerator(
                  db.photos.id, db.itemPhotoExtras.photoId));

  $$ItemPhotoExtrasTableProcessedTableManager get itemPhotoExtrasRefs {
    final manager =
        $$ItemPhotoExtrasTableTableManager($_db, $_db.itemPhotoExtras)
            .filter((f) => f.photoId.id.sqlEquals($_itemColumn<String>('id')!));

    final cache =
        $_typedResult.readTableOrNull(_itemPhotoExtrasRefsTable($_db));
    return ProcessedTableManager(
        manager.$state.copyWith(prefetchedData: cache));
  }
}

class $$PhotosTableFilterComposer
    extends Composer<_$AppDatabase, $PhotosTable> {
  $$PhotosTableFilterComposer({
    required super.$db,
    required super.$table,
    super.joinBuilder,
    super.$addJoinBuilderToRootComposer,
    super.$removeJoinBuilderFromRootComposer,
  });
  ColumnFilters<String> get id => $composableBuilder(
      column: $table.id, builder: (column) => ColumnFilters(column));

  ColumnFilters<String> get groupId => $composableBuilder(
      column: $table.groupId, builder: (column) => ColumnFilters(column));

  ColumnFilters<String> get filePath => $composableBuilder(
      column: $table.filePath, builder: (column) => ColumnFilters(column));

  ColumnFilters<String> get thumbPath => $composableBuilder(
      column: $table.thumbPath, builder: (column) => ColumnFilters(column));

  ColumnFilters<int> get width => $composableBuilder(
      column: $table.width, builder: (column) => ColumnFilters(column));

  ColumnFilters<int> get height => $composableBuilder(
      column: $table.height, builder: (column) => ColumnFilters(column));

  ColumnFilters<int> get bytes => $composableBuilder(
      column: $table.bytes, builder: (column) => ColumnFilters(column));

  ColumnFilters<int> get takenAt => $composableBuilder(
      column: $table.takenAt, builder: (column) => ColumnFilters(column));

  ColumnFilters<int> get seq => $composableBuilder(
      column: $table.seq, builder: (column) => ColumnFilters(column));

  ColumnFilters<String> get itemId => $composableBuilder(
      column: $table.itemId, builder: (column) => ColumnFilters(column));

  ColumnFilters<String> get state => $composableBuilder(
      column: $table.state, builder: (column) => ColumnFilters(column));

  ColumnFilters<String> get category => $composableBuilder(
      column: $table.category, builder: (column) => ColumnFilters(column));

  ColumnFilters<String> get ocrState => $composableBuilder(
      column: $table.ocrState, builder: (column) => ColumnFilters(column));

  ColumnFilters<String> get sharpnessFlag => $composableBuilder(
      column: $table.sharpnessFlag, builder: (column) => ColumnFilters(column));

  ColumnFilters<String> get contentHash => $composableBuilder(
      column: $table.contentHash, builder: (column) => ColumnFilters(column));

  ColumnFilters<int> get createdAt => $composableBuilder(
      column: $table.createdAt, builder: (column) => ColumnFilters(column));

  $$ProjectsTableFilterComposer get projectId {
    final $$ProjectsTableFilterComposer composer = $composerBuilder(
        composer: this,
        getCurrentColumn: (t) => t.projectId,
        referencedTable: $db.projects,
        getReferencedColumn: (t) => t.id,
        builder: (joinBuilder,
                {$addJoinBuilderToRootComposer,
                $removeJoinBuilderFromRootComposer}) =>
            $$ProjectsTableFilterComposer(
              $db: $db,
              $table: $db.projects,
              $addJoinBuilderToRootComposer: $addJoinBuilderToRootComposer,
              joinBuilder: joinBuilder,
              $removeJoinBuilderFromRootComposer:
                  $removeJoinBuilderFromRootComposer,
            ));
    return composer;
  }

  $$CaptureSessionsTableFilterComposer get sessionId {
    final $$CaptureSessionsTableFilterComposer composer = $composerBuilder(
        composer: this,
        getCurrentColumn: (t) => t.sessionId,
        referencedTable: $db.captureSessions,
        getReferencedColumn: (t) => t.id,
        builder: (joinBuilder,
                {$addJoinBuilderToRootComposer,
                $removeJoinBuilderFromRootComposer}) =>
            $$CaptureSessionsTableFilterComposer(
              $db: $db,
              $table: $db.captureSessions,
              $addJoinBuilderToRootComposer: $addJoinBuilderToRootComposer,
              joinBuilder: joinBuilder,
              $removeJoinBuilderFromRootComposer:
                  $removeJoinBuilderFromRootComposer,
            ));
    return composer;
  }

  Expression<bool> ocrTokensRefs(
      Expression<bool> Function($$OcrTokensTableFilterComposer f) f) {
    final $$OcrTokensTableFilterComposer composer = $composerBuilder(
        composer: this,
        getCurrentColumn: (t) => t.id,
        referencedTable: $db.ocrTokens,
        getReferencedColumn: (t) => t.photoId,
        builder: (joinBuilder,
                {$addJoinBuilderToRootComposer,
                $removeJoinBuilderFromRootComposer}) =>
            $$OcrTokensTableFilterComposer(
              $db: $db,
              $table: $db.ocrTokens,
              $addJoinBuilderToRootComposer: $addJoinBuilderToRootComposer,
              joinBuilder: joinBuilder,
              $removeJoinBuilderFromRootComposer:
                  $removeJoinBuilderFromRootComposer,
            ));
    return f(composer);
  }

  Expression<bool> itemPhotoExtrasRefs(
      Expression<bool> Function($$ItemPhotoExtrasTableFilterComposer f) f) {
    final $$ItemPhotoExtrasTableFilterComposer composer = $composerBuilder(
        composer: this,
        getCurrentColumn: (t) => t.id,
        referencedTable: $db.itemPhotoExtras,
        getReferencedColumn: (t) => t.photoId,
        builder: (joinBuilder,
                {$addJoinBuilderToRootComposer,
                $removeJoinBuilderFromRootComposer}) =>
            $$ItemPhotoExtrasTableFilterComposer(
              $db: $db,
              $table: $db.itemPhotoExtras,
              $addJoinBuilderToRootComposer: $addJoinBuilderToRootComposer,
              joinBuilder: joinBuilder,
              $removeJoinBuilderFromRootComposer:
                  $removeJoinBuilderFromRootComposer,
            ));
    return f(composer);
  }
}

class $$PhotosTableOrderingComposer
    extends Composer<_$AppDatabase, $PhotosTable> {
  $$PhotosTableOrderingComposer({
    required super.$db,
    required super.$table,
    super.joinBuilder,
    super.$addJoinBuilderToRootComposer,
    super.$removeJoinBuilderFromRootComposer,
  });
  ColumnOrderings<String> get id => $composableBuilder(
      column: $table.id, builder: (column) => ColumnOrderings(column));

  ColumnOrderings<String> get groupId => $composableBuilder(
      column: $table.groupId, builder: (column) => ColumnOrderings(column));

  ColumnOrderings<String> get filePath => $composableBuilder(
      column: $table.filePath, builder: (column) => ColumnOrderings(column));

  ColumnOrderings<String> get thumbPath => $composableBuilder(
      column: $table.thumbPath, builder: (column) => ColumnOrderings(column));

  ColumnOrderings<int> get width => $composableBuilder(
      column: $table.width, builder: (column) => ColumnOrderings(column));

  ColumnOrderings<int> get height => $composableBuilder(
      column: $table.height, builder: (column) => ColumnOrderings(column));

  ColumnOrderings<int> get bytes => $composableBuilder(
      column: $table.bytes, builder: (column) => ColumnOrderings(column));

  ColumnOrderings<int> get takenAt => $composableBuilder(
      column: $table.takenAt, builder: (column) => ColumnOrderings(column));

  ColumnOrderings<int> get seq => $composableBuilder(
      column: $table.seq, builder: (column) => ColumnOrderings(column));

  ColumnOrderings<String> get itemId => $composableBuilder(
      column: $table.itemId, builder: (column) => ColumnOrderings(column));

  ColumnOrderings<String> get state => $composableBuilder(
      column: $table.state, builder: (column) => ColumnOrderings(column));

  ColumnOrderings<String> get category => $composableBuilder(
      column: $table.category, builder: (column) => ColumnOrderings(column));

  ColumnOrderings<String> get ocrState => $composableBuilder(
      column: $table.ocrState, builder: (column) => ColumnOrderings(column));

  ColumnOrderings<String> get sharpnessFlag => $composableBuilder(
      column: $table.sharpnessFlag,
      builder: (column) => ColumnOrderings(column));

  ColumnOrderings<String> get contentHash => $composableBuilder(
      column: $table.contentHash, builder: (column) => ColumnOrderings(column));

  ColumnOrderings<int> get createdAt => $composableBuilder(
      column: $table.createdAt, builder: (column) => ColumnOrderings(column));

  $$ProjectsTableOrderingComposer get projectId {
    final $$ProjectsTableOrderingComposer composer = $composerBuilder(
        composer: this,
        getCurrentColumn: (t) => t.projectId,
        referencedTable: $db.projects,
        getReferencedColumn: (t) => t.id,
        builder: (joinBuilder,
                {$addJoinBuilderToRootComposer,
                $removeJoinBuilderFromRootComposer}) =>
            $$ProjectsTableOrderingComposer(
              $db: $db,
              $table: $db.projects,
              $addJoinBuilderToRootComposer: $addJoinBuilderToRootComposer,
              joinBuilder: joinBuilder,
              $removeJoinBuilderFromRootComposer:
                  $removeJoinBuilderFromRootComposer,
            ));
    return composer;
  }

  $$CaptureSessionsTableOrderingComposer get sessionId {
    final $$CaptureSessionsTableOrderingComposer composer = $composerBuilder(
        composer: this,
        getCurrentColumn: (t) => t.sessionId,
        referencedTable: $db.captureSessions,
        getReferencedColumn: (t) => t.id,
        builder: (joinBuilder,
                {$addJoinBuilderToRootComposer,
                $removeJoinBuilderFromRootComposer}) =>
            $$CaptureSessionsTableOrderingComposer(
              $db: $db,
              $table: $db.captureSessions,
              $addJoinBuilderToRootComposer: $addJoinBuilderToRootComposer,
              joinBuilder: joinBuilder,
              $removeJoinBuilderFromRootComposer:
                  $removeJoinBuilderFromRootComposer,
            ));
    return composer;
  }
}

class $$PhotosTableAnnotationComposer
    extends Composer<_$AppDatabase, $PhotosTable> {
  $$PhotosTableAnnotationComposer({
    required super.$db,
    required super.$table,
    super.joinBuilder,
    super.$addJoinBuilderToRootComposer,
    super.$removeJoinBuilderFromRootComposer,
  });
  GeneratedColumn<String> get id =>
      $composableBuilder(column: $table.id, builder: (column) => column);

  GeneratedColumn<String> get groupId =>
      $composableBuilder(column: $table.groupId, builder: (column) => column);

  GeneratedColumn<String> get filePath =>
      $composableBuilder(column: $table.filePath, builder: (column) => column);

  GeneratedColumn<String> get thumbPath =>
      $composableBuilder(column: $table.thumbPath, builder: (column) => column);

  GeneratedColumn<int> get width =>
      $composableBuilder(column: $table.width, builder: (column) => column);

  GeneratedColumn<int> get height =>
      $composableBuilder(column: $table.height, builder: (column) => column);

  GeneratedColumn<int> get bytes =>
      $composableBuilder(column: $table.bytes, builder: (column) => column);

  GeneratedColumn<int> get takenAt =>
      $composableBuilder(column: $table.takenAt, builder: (column) => column);

  GeneratedColumn<int> get seq =>
      $composableBuilder(column: $table.seq, builder: (column) => column);

  GeneratedColumn<String> get itemId =>
      $composableBuilder(column: $table.itemId, builder: (column) => column);

  GeneratedColumn<String> get state =>
      $composableBuilder(column: $table.state, builder: (column) => column);

  GeneratedColumn<String> get category =>
      $composableBuilder(column: $table.category, builder: (column) => column);

  GeneratedColumn<String> get ocrState =>
      $composableBuilder(column: $table.ocrState, builder: (column) => column);

  GeneratedColumn<String> get sharpnessFlag => $composableBuilder(
      column: $table.sharpnessFlag, builder: (column) => column);

  GeneratedColumn<String> get contentHash => $composableBuilder(
      column: $table.contentHash, builder: (column) => column);

  GeneratedColumn<int> get createdAt =>
      $composableBuilder(column: $table.createdAt, builder: (column) => column);

  $$ProjectsTableAnnotationComposer get projectId {
    final $$ProjectsTableAnnotationComposer composer = $composerBuilder(
        composer: this,
        getCurrentColumn: (t) => t.projectId,
        referencedTable: $db.projects,
        getReferencedColumn: (t) => t.id,
        builder: (joinBuilder,
                {$addJoinBuilderToRootComposer,
                $removeJoinBuilderFromRootComposer}) =>
            $$ProjectsTableAnnotationComposer(
              $db: $db,
              $table: $db.projects,
              $addJoinBuilderToRootComposer: $addJoinBuilderToRootComposer,
              joinBuilder: joinBuilder,
              $removeJoinBuilderFromRootComposer:
                  $removeJoinBuilderFromRootComposer,
            ));
    return composer;
  }

  $$CaptureSessionsTableAnnotationComposer get sessionId {
    final $$CaptureSessionsTableAnnotationComposer composer = $composerBuilder(
        composer: this,
        getCurrentColumn: (t) => t.sessionId,
        referencedTable: $db.captureSessions,
        getReferencedColumn: (t) => t.id,
        builder: (joinBuilder,
                {$addJoinBuilderToRootComposer,
                $removeJoinBuilderFromRootComposer}) =>
            $$CaptureSessionsTableAnnotationComposer(
              $db: $db,
              $table: $db.captureSessions,
              $addJoinBuilderToRootComposer: $addJoinBuilderToRootComposer,
              joinBuilder: joinBuilder,
              $removeJoinBuilderFromRootComposer:
                  $removeJoinBuilderFromRootComposer,
            ));
    return composer;
  }

  Expression<T> ocrTokensRefs<T extends Object>(
      Expression<T> Function($$OcrTokensTableAnnotationComposer a) f) {
    final $$OcrTokensTableAnnotationComposer composer = $composerBuilder(
        composer: this,
        getCurrentColumn: (t) => t.id,
        referencedTable: $db.ocrTokens,
        getReferencedColumn: (t) => t.photoId,
        builder: (joinBuilder,
                {$addJoinBuilderToRootComposer,
                $removeJoinBuilderFromRootComposer}) =>
            $$OcrTokensTableAnnotationComposer(
              $db: $db,
              $table: $db.ocrTokens,
              $addJoinBuilderToRootComposer: $addJoinBuilderToRootComposer,
              joinBuilder: joinBuilder,
              $removeJoinBuilderFromRootComposer:
                  $removeJoinBuilderFromRootComposer,
            ));
    return f(composer);
  }

  Expression<T> itemPhotoExtrasRefs<T extends Object>(
      Expression<T> Function($$ItemPhotoExtrasTableAnnotationComposer a) f) {
    final $$ItemPhotoExtrasTableAnnotationComposer composer = $composerBuilder(
        composer: this,
        getCurrentColumn: (t) => t.id,
        referencedTable: $db.itemPhotoExtras,
        getReferencedColumn: (t) => t.photoId,
        builder: (joinBuilder,
                {$addJoinBuilderToRootComposer,
                $removeJoinBuilderFromRootComposer}) =>
            $$ItemPhotoExtrasTableAnnotationComposer(
              $db: $db,
              $table: $db.itemPhotoExtras,
              $addJoinBuilderToRootComposer: $addJoinBuilderToRootComposer,
              joinBuilder: joinBuilder,
              $removeJoinBuilderFromRootComposer:
                  $removeJoinBuilderFromRootComposer,
            ));
    return f(composer);
  }
}

class $$PhotosTableTableManager extends RootTableManager<
    _$AppDatabase,
    $PhotosTable,
    Photo,
    $$PhotosTableFilterComposer,
    $$PhotosTableOrderingComposer,
    $$PhotosTableAnnotationComposer,
    $$PhotosTableCreateCompanionBuilder,
    $$PhotosTableUpdateCompanionBuilder,
    (Photo, $$PhotosTableReferences),
    Photo,
    PrefetchHooks Function(
        {bool projectId,
        bool sessionId,
        bool ocrTokensRefs,
        bool itemPhotoExtrasRefs})> {
  $$PhotosTableTableManager(_$AppDatabase db, $PhotosTable table)
      : super(TableManagerState(
          db: db,
          table: table,
          createFilteringComposer: () =>
              $$PhotosTableFilterComposer($db: db, $table: table),
          createOrderingComposer: () =>
              $$PhotosTableOrderingComposer($db: db, $table: table),
          createComputedFieldComposer: () =>
              $$PhotosTableAnnotationComposer($db: db, $table: table),
          updateCompanionCallback: ({
            Value<String> id = const Value.absent(),
            Value<String> projectId = const Value.absent(),
            Value<String> sessionId = const Value.absent(),
            Value<String?> groupId = const Value.absent(),
            Value<String> filePath = const Value.absent(),
            Value<String?> thumbPath = const Value.absent(),
            Value<int?> width = const Value.absent(),
            Value<int?> height = const Value.absent(),
            Value<int?> bytes = const Value.absent(),
            Value<int> takenAt = const Value.absent(),
            Value<int> seq = const Value.absent(),
            Value<String?> itemId = const Value.absent(),
            Value<String> state = const Value.absent(),
            Value<String> category = const Value.absent(),
            Value<String> ocrState = const Value.absent(),
            Value<String?> sharpnessFlag = const Value.absent(),
            Value<String?> contentHash = const Value.absent(),
            Value<int> createdAt = const Value.absent(),
            Value<int> rowid = const Value.absent(),
          }) =>
              PhotosCompanion(
            id: id,
            projectId: projectId,
            sessionId: sessionId,
            groupId: groupId,
            filePath: filePath,
            thumbPath: thumbPath,
            width: width,
            height: height,
            bytes: bytes,
            takenAt: takenAt,
            seq: seq,
            itemId: itemId,
            state: state,
            category: category,
            ocrState: ocrState,
            sharpnessFlag: sharpnessFlag,
            contentHash: contentHash,
            createdAt: createdAt,
            rowid: rowid,
          ),
          createCompanionCallback: ({
            required String id,
            required String projectId,
            required String sessionId,
            Value<String?> groupId = const Value.absent(),
            required String filePath,
            Value<String?> thumbPath = const Value.absent(),
            Value<int?> width = const Value.absent(),
            Value<int?> height = const Value.absent(),
            Value<int?> bytes = const Value.absent(),
            required int takenAt,
            required int seq,
            Value<String?> itemId = const Value.absent(),
            Value<String> state = const Value.absent(),
            Value<String> category = const Value.absent(),
            Value<String> ocrState = const Value.absent(),
            Value<String?> sharpnessFlag = const Value.absent(),
            Value<String?> contentHash = const Value.absent(),
            required int createdAt,
            Value<int> rowid = const Value.absent(),
          }) =>
              PhotosCompanion.insert(
            id: id,
            projectId: projectId,
            sessionId: sessionId,
            groupId: groupId,
            filePath: filePath,
            thumbPath: thumbPath,
            width: width,
            height: height,
            bytes: bytes,
            takenAt: takenAt,
            seq: seq,
            itemId: itemId,
            state: state,
            category: category,
            ocrState: ocrState,
            sharpnessFlag: sharpnessFlag,
            contentHash: contentHash,
            createdAt: createdAt,
            rowid: rowid,
          ),
          withReferenceMapper: (p0) => p0
              .map((e) =>
                  (e.readTable(table), $$PhotosTableReferences(db, table, e)))
              .toList(),
          prefetchHooksCallback: (
              {projectId = false,
              sessionId = false,
              ocrTokensRefs = false,
              itemPhotoExtrasRefs = false}) {
            return PrefetchHooks(
              db: db,
              explicitlyWatchedTables: [
                if (ocrTokensRefs) db.ocrTokens,
                if (itemPhotoExtrasRefs) db.itemPhotoExtras
              ],
              addJoins: <
                  T extends TableManagerState<
                      dynamic,
                      dynamic,
                      dynamic,
                      dynamic,
                      dynamic,
                      dynamic,
                      dynamic,
                      dynamic,
                      dynamic,
                      dynamic,
                      dynamic>>(state) {
                if (projectId) {
                  state = state.withJoin(
                    currentTable: table,
                    currentColumn: table.projectId,
                    referencedTable:
                        $$PhotosTableReferences._projectIdTable(db),
                    referencedColumn:
                        $$PhotosTableReferences._projectIdTable(db).id,
                  ) as T;
                }
                if (sessionId) {
                  state = state.withJoin(
                    currentTable: table,
                    currentColumn: table.sessionId,
                    referencedTable:
                        $$PhotosTableReferences._sessionIdTable(db),
                    referencedColumn:
                        $$PhotosTableReferences._sessionIdTable(db).id,
                  ) as T;
                }

                return state;
              },
              getPrefetchedDataCallback: (items) async {
                return [
                  if (ocrTokensRefs)
                    await $_getPrefetchedData<Photo, $PhotosTable, OcrToken>(
                        currentTable: table,
                        referencedTable:
                            $$PhotosTableReferences._ocrTokensRefsTable(db),
                        managerFromTypedResult: (p0) =>
                            $$PhotosTableReferences(db, table, p0)
                                .ocrTokensRefs,
                        referencedItemsForCurrentItem: (item,
                                referencedItems) =>
                            referencedItems.where((e) => e.photoId == item.id),
                        typedResults: items),
                  if (itemPhotoExtrasRefs)
                    await $_getPrefetchedData<Photo, $PhotosTable,
                            ItemPhotoExtra>(
                        currentTable: table,
                        referencedTable: $$PhotosTableReferences
                            ._itemPhotoExtrasRefsTable(db),
                        managerFromTypedResult: (p0) =>
                            $$PhotosTableReferences(db, table, p0)
                                .itemPhotoExtrasRefs,
                        referencedItemsForCurrentItem: (item,
                                referencedItems) =>
                            referencedItems.where((e) => e.photoId == item.id),
                        typedResults: items)
                ];
              },
            );
          },
        ));
}

typedef $$PhotosTableProcessedTableManager = ProcessedTableManager<
    _$AppDatabase,
    $PhotosTable,
    Photo,
    $$PhotosTableFilterComposer,
    $$PhotosTableOrderingComposer,
    $$PhotosTableAnnotationComposer,
    $$PhotosTableCreateCompanionBuilder,
    $$PhotosTableUpdateCompanionBuilder,
    (Photo, $$PhotosTableReferences),
    Photo,
    PrefetchHooks Function(
        {bool projectId,
        bool sessionId,
        bool ocrTokensRefs,
        bool itemPhotoExtrasRefs})>;
typedef $$OcrTokensTableCreateCompanionBuilder = OcrTokensCompanion Function({
  required String id,
  required String photoId,
  required String rawText,
  required double confidence,
  required String boxJson,
  Value<int> page,
  Value<int> rowid,
});
typedef $$OcrTokensTableUpdateCompanionBuilder = OcrTokensCompanion Function({
  Value<String> id,
  Value<String> photoId,
  Value<String> rawText,
  Value<double> confidence,
  Value<String> boxJson,
  Value<int> page,
  Value<int> rowid,
});

final class $$OcrTokensTableReferences
    extends BaseReferences<_$AppDatabase, $OcrTokensTable, OcrToken> {
  $$OcrTokensTableReferences(super.$_db, super.$_table, super.$_typedResult);

  static $PhotosTable _photoIdTable(_$AppDatabase db) => db.photos
      .createAlias($_aliasNameGenerator(db.ocrTokens.photoId, db.photos.id));

  $$PhotosTableProcessedTableManager get photoId {
    final $_column = $_itemColumn<String>('photo_id')!;

    final manager = $$PhotosTableTableManager($_db, $_db.photos)
        .filter((f) => f.id.sqlEquals($_column));
    final item = $_typedResult.readTableOrNull(_photoIdTable($_db));
    if (item == null) return manager;
    return ProcessedTableManager(
        manager.$state.copyWith(prefetchedData: [item]));
  }
}

class $$OcrTokensTableFilterComposer
    extends Composer<_$AppDatabase, $OcrTokensTable> {
  $$OcrTokensTableFilterComposer({
    required super.$db,
    required super.$table,
    super.joinBuilder,
    super.$addJoinBuilderToRootComposer,
    super.$removeJoinBuilderFromRootComposer,
  });
  ColumnFilters<String> get id => $composableBuilder(
      column: $table.id, builder: (column) => ColumnFilters(column));

  ColumnFilters<String> get rawText => $composableBuilder(
      column: $table.rawText, builder: (column) => ColumnFilters(column));

  ColumnFilters<double> get confidence => $composableBuilder(
      column: $table.confidence, builder: (column) => ColumnFilters(column));

  ColumnFilters<String> get boxJson => $composableBuilder(
      column: $table.boxJson, builder: (column) => ColumnFilters(column));

  ColumnFilters<int> get page => $composableBuilder(
      column: $table.page, builder: (column) => ColumnFilters(column));

  $$PhotosTableFilterComposer get photoId {
    final $$PhotosTableFilterComposer composer = $composerBuilder(
        composer: this,
        getCurrentColumn: (t) => t.photoId,
        referencedTable: $db.photos,
        getReferencedColumn: (t) => t.id,
        builder: (joinBuilder,
                {$addJoinBuilderToRootComposer,
                $removeJoinBuilderFromRootComposer}) =>
            $$PhotosTableFilterComposer(
              $db: $db,
              $table: $db.photos,
              $addJoinBuilderToRootComposer: $addJoinBuilderToRootComposer,
              joinBuilder: joinBuilder,
              $removeJoinBuilderFromRootComposer:
                  $removeJoinBuilderFromRootComposer,
            ));
    return composer;
  }
}

class $$OcrTokensTableOrderingComposer
    extends Composer<_$AppDatabase, $OcrTokensTable> {
  $$OcrTokensTableOrderingComposer({
    required super.$db,
    required super.$table,
    super.joinBuilder,
    super.$addJoinBuilderToRootComposer,
    super.$removeJoinBuilderFromRootComposer,
  });
  ColumnOrderings<String> get id => $composableBuilder(
      column: $table.id, builder: (column) => ColumnOrderings(column));

  ColumnOrderings<String> get rawText => $composableBuilder(
      column: $table.rawText, builder: (column) => ColumnOrderings(column));

  ColumnOrderings<double> get confidence => $composableBuilder(
      column: $table.confidence, builder: (column) => ColumnOrderings(column));

  ColumnOrderings<String> get boxJson => $composableBuilder(
      column: $table.boxJson, builder: (column) => ColumnOrderings(column));

  ColumnOrderings<int> get page => $composableBuilder(
      column: $table.page, builder: (column) => ColumnOrderings(column));

  $$PhotosTableOrderingComposer get photoId {
    final $$PhotosTableOrderingComposer composer = $composerBuilder(
        composer: this,
        getCurrentColumn: (t) => t.photoId,
        referencedTable: $db.photos,
        getReferencedColumn: (t) => t.id,
        builder: (joinBuilder,
                {$addJoinBuilderToRootComposer,
                $removeJoinBuilderFromRootComposer}) =>
            $$PhotosTableOrderingComposer(
              $db: $db,
              $table: $db.photos,
              $addJoinBuilderToRootComposer: $addJoinBuilderToRootComposer,
              joinBuilder: joinBuilder,
              $removeJoinBuilderFromRootComposer:
                  $removeJoinBuilderFromRootComposer,
            ));
    return composer;
  }
}

class $$OcrTokensTableAnnotationComposer
    extends Composer<_$AppDatabase, $OcrTokensTable> {
  $$OcrTokensTableAnnotationComposer({
    required super.$db,
    required super.$table,
    super.joinBuilder,
    super.$addJoinBuilderToRootComposer,
    super.$removeJoinBuilderFromRootComposer,
  });
  GeneratedColumn<String> get id =>
      $composableBuilder(column: $table.id, builder: (column) => column);

  GeneratedColumn<String> get rawText =>
      $composableBuilder(column: $table.rawText, builder: (column) => column);

  GeneratedColumn<double> get confidence => $composableBuilder(
      column: $table.confidence, builder: (column) => column);

  GeneratedColumn<String> get boxJson =>
      $composableBuilder(column: $table.boxJson, builder: (column) => column);

  GeneratedColumn<int> get page =>
      $composableBuilder(column: $table.page, builder: (column) => column);

  $$PhotosTableAnnotationComposer get photoId {
    final $$PhotosTableAnnotationComposer composer = $composerBuilder(
        composer: this,
        getCurrentColumn: (t) => t.photoId,
        referencedTable: $db.photos,
        getReferencedColumn: (t) => t.id,
        builder: (joinBuilder,
                {$addJoinBuilderToRootComposer,
                $removeJoinBuilderFromRootComposer}) =>
            $$PhotosTableAnnotationComposer(
              $db: $db,
              $table: $db.photos,
              $addJoinBuilderToRootComposer: $addJoinBuilderToRootComposer,
              joinBuilder: joinBuilder,
              $removeJoinBuilderFromRootComposer:
                  $removeJoinBuilderFromRootComposer,
            ));
    return composer;
  }
}

class $$OcrTokensTableTableManager extends RootTableManager<
    _$AppDatabase,
    $OcrTokensTable,
    OcrToken,
    $$OcrTokensTableFilterComposer,
    $$OcrTokensTableOrderingComposer,
    $$OcrTokensTableAnnotationComposer,
    $$OcrTokensTableCreateCompanionBuilder,
    $$OcrTokensTableUpdateCompanionBuilder,
    (OcrToken, $$OcrTokensTableReferences),
    OcrToken,
    PrefetchHooks Function({bool photoId})> {
  $$OcrTokensTableTableManager(_$AppDatabase db, $OcrTokensTable table)
      : super(TableManagerState(
          db: db,
          table: table,
          createFilteringComposer: () =>
              $$OcrTokensTableFilterComposer($db: db, $table: table),
          createOrderingComposer: () =>
              $$OcrTokensTableOrderingComposer($db: db, $table: table),
          createComputedFieldComposer: () =>
              $$OcrTokensTableAnnotationComposer($db: db, $table: table),
          updateCompanionCallback: ({
            Value<String> id = const Value.absent(),
            Value<String> photoId = const Value.absent(),
            Value<String> rawText = const Value.absent(),
            Value<double> confidence = const Value.absent(),
            Value<String> boxJson = const Value.absent(),
            Value<int> page = const Value.absent(),
            Value<int> rowid = const Value.absent(),
          }) =>
              OcrTokensCompanion(
            id: id,
            photoId: photoId,
            rawText: rawText,
            confidence: confidence,
            boxJson: boxJson,
            page: page,
            rowid: rowid,
          ),
          createCompanionCallback: ({
            required String id,
            required String photoId,
            required String rawText,
            required double confidence,
            required String boxJson,
            Value<int> page = const Value.absent(),
            Value<int> rowid = const Value.absent(),
          }) =>
              OcrTokensCompanion.insert(
            id: id,
            photoId: photoId,
            rawText: rawText,
            confidence: confidence,
            boxJson: boxJson,
            page: page,
            rowid: rowid,
          ),
          withReferenceMapper: (p0) => p0
              .map((e) => (
                    e.readTable(table),
                    $$OcrTokensTableReferences(db, table, e)
                  ))
              .toList(),
          prefetchHooksCallback: ({photoId = false}) {
            return PrefetchHooks(
              db: db,
              explicitlyWatchedTables: [],
              addJoins: <
                  T extends TableManagerState<
                      dynamic,
                      dynamic,
                      dynamic,
                      dynamic,
                      dynamic,
                      dynamic,
                      dynamic,
                      dynamic,
                      dynamic,
                      dynamic,
                      dynamic>>(state) {
                if (photoId) {
                  state = state.withJoin(
                    currentTable: table,
                    currentColumn: table.photoId,
                    referencedTable:
                        $$OcrTokensTableReferences._photoIdTable(db),
                    referencedColumn:
                        $$OcrTokensTableReferences._photoIdTable(db).id,
                  ) as T;
                }

                return state;
              },
              getPrefetchedDataCallback: (items) async {
                return [];
              },
            );
          },
        ));
}

typedef $$OcrTokensTableProcessedTableManager = ProcessedTableManager<
    _$AppDatabase,
    $OcrTokensTable,
    OcrToken,
    $$OcrTokensTableFilterComposer,
    $$OcrTokensTableOrderingComposer,
    $$OcrTokensTableAnnotationComposer,
    $$OcrTokensTableCreateCompanionBuilder,
    $$OcrTokensTableUpdateCompanionBuilder,
    (OcrToken, $$OcrTokensTableReferences),
    OcrToken,
    PrefetchHooks Function({bool photoId})>;
typedef $$AssignmentsTableCreateCompanionBuilder = AssignmentsCompanion
    Function({
  required String id,
  required String projectId,
  required String targetType,
  required String targetId,
  required String itemId,
  required String source,
  Value<String?> suggestedItemId,
  Value<double?> suggestionConf,
  required int confirmedAt,
  required String confirmedBy,
  Value<int?> revokedAt,
  Value<String?> note,
  Value<int> rowid,
});
typedef $$AssignmentsTableUpdateCompanionBuilder = AssignmentsCompanion
    Function({
  Value<String> id,
  Value<String> projectId,
  Value<String> targetType,
  Value<String> targetId,
  Value<String> itemId,
  Value<String> source,
  Value<String?> suggestedItemId,
  Value<double?> suggestionConf,
  Value<int> confirmedAt,
  Value<String> confirmedBy,
  Value<int?> revokedAt,
  Value<String?> note,
  Value<int> rowid,
});

final class $$AssignmentsTableReferences
    extends BaseReferences<_$AppDatabase, $AssignmentsTable, Assignment> {
  $$AssignmentsTableReferences(super.$_db, super.$_table, super.$_typedResult);

  static $ProjectsTable _projectIdTable(_$AppDatabase db) =>
      db.projects.createAlias(
          $_aliasNameGenerator(db.assignments.projectId, db.projects.id));

  $$ProjectsTableProcessedTableManager get projectId {
    final $_column = $_itemColumn<String>('project_id')!;

    final manager = $$ProjectsTableTableManager($_db, $_db.projects)
        .filter((f) => f.id.sqlEquals($_column));
    final item = $_typedResult.readTableOrNull(_projectIdTable($_db));
    if (item == null) return manager;
    return ProcessedTableManager(
        manager.$state.copyWith(prefetchedData: [item]));
  }
}

class $$AssignmentsTableFilterComposer
    extends Composer<_$AppDatabase, $AssignmentsTable> {
  $$AssignmentsTableFilterComposer({
    required super.$db,
    required super.$table,
    super.joinBuilder,
    super.$addJoinBuilderToRootComposer,
    super.$removeJoinBuilderFromRootComposer,
  });
  ColumnFilters<String> get id => $composableBuilder(
      column: $table.id, builder: (column) => ColumnFilters(column));

  ColumnFilters<String> get targetType => $composableBuilder(
      column: $table.targetType, builder: (column) => ColumnFilters(column));

  ColumnFilters<String> get targetId => $composableBuilder(
      column: $table.targetId, builder: (column) => ColumnFilters(column));

  ColumnFilters<String> get itemId => $composableBuilder(
      column: $table.itemId, builder: (column) => ColumnFilters(column));

  ColumnFilters<String> get source => $composableBuilder(
      column: $table.source, builder: (column) => ColumnFilters(column));

  ColumnFilters<String> get suggestedItemId => $composableBuilder(
      column: $table.suggestedItemId,
      builder: (column) => ColumnFilters(column));

  ColumnFilters<double> get suggestionConf => $composableBuilder(
      column: $table.suggestionConf,
      builder: (column) => ColumnFilters(column));

  ColumnFilters<int> get confirmedAt => $composableBuilder(
      column: $table.confirmedAt, builder: (column) => ColumnFilters(column));

  ColumnFilters<String> get confirmedBy => $composableBuilder(
      column: $table.confirmedBy, builder: (column) => ColumnFilters(column));

  ColumnFilters<int> get revokedAt => $composableBuilder(
      column: $table.revokedAt, builder: (column) => ColumnFilters(column));

  ColumnFilters<String> get note => $composableBuilder(
      column: $table.note, builder: (column) => ColumnFilters(column));

  $$ProjectsTableFilterComposer get projectId {
    final $$ProjectsTableFilterComposer composer = $composerBuilder(
        composer: this,
        getCurrentColumn: (t) => t.projectId,
        referencedTable: $db.projects,
        getReferencedColumn: (t) => t.id,
        builder: (joinBuilder,
                {$addJoinBuilderToRootComposer,
                $removeJoinBuilderFromRootComposer}) =>
            $$ProjectsTableFilterComposer(
              $db: $db,
              $table: $db.projects,
              $addJoinBuilderToRootComposer: $addJoinBuilderToRootComposer,
              joinBuilder: joinBuilder,
              $removeJoinBuilderFromRootComposer:
                  $removeJoinBuilderFromRootComposer,
            ));
    return composer;
  }
}

class $$AssignmentsTableOrderingComposer
    extends Composer<_$AppDatabase, $AssignmentsTable> {
  $$AssignmentsTableOrderingComposer({
    required super.$db,
    required super.$table,
    super.joinBuilder,
    super.$addJoinBuilderToRootComposer,
    super.$removeJoinBuilderFromRootComposer,
  });
  ColumnOrderings<String> get id => $composableBuilder(
      column: $table.id, builder: (column) => ColumnOrderings(column));

  ColumnOrderings<String> get targetType => $composableBuilder(
      column: $table.targetType, builder: (column) => ColumnOrderings(column));

  ColumnOrderings<String> get targetId => $composableBuilder(
      column: $table.targetId, builder: (column) => ColumnOrderings(column));

  ColumnOrderings<String> get itemId => $composableBuilder(
      column: $table.itemId, builder: (column) => ColumnOrderings(column));

  ColumnOrderings<String> get source => $composableBuilder(
      column: $table.source, builder: (column) => ColumnOrderings(column));

  ColumnOrderings<String> get suggestedItemId => $composableBuilder(
      column: $table.suggestedItemId,
      builder: (column) => ColumnOrderings(column));

  ColumnOrderings<double> get suggestionConf => $composableBuilder(
      column: $table.suggestionConf,
      builder: (column) => ColumnOrderings(column));

  ColumnOrderings<int> get confirmedAt => $composableBuilder(
      column: $table.confirmedAt, builder: (column) => ColumnOrderings(column));

  ColumnOrderings<String> get confirmedBy => $composableBuilder(
      column: $table.confirmedBy, builder: (column) => ColumnOrderings(column));

  ColumnOrderings<int> get revokedAt => $composableBuilder(
      column: $table.revokedAt, builder: (column) => ColumnOrderings(column));

  ColumnOrderings<String> get note => $composableBuilder(
      column: $table.note, builder: (column) => ColumnOrderings(column));

  $$ProjectsTableOrderingComposer get projectId {
    final $$ProjectsTableOrderingComposer composer = $composerBuilder(
        composer: this,
        getCurrentColumn: (t) => t.projectId,
        referencedTable: $db.projects,
        getReferencedColumn: (t) => t.id,
        builder: (joinBuilder,
                {$addJoinBuilderToRootComposer,
                $removeJoinBuilderFromRootComposer}) =>
            $$ProjectsTableOrderingComposer(
              $db: $db,
              $table: $db.projects,
              $addJoinBuilderToRootComposer: $addJoinBuilderToRootComposer,
              joinBuilder: joinBuilder,
              $removeJoinBuilderFromRootComposer:
                  $removeJoinBuilderFromRootComposer,
            ));
    return composer;
  }
}

class $$AssignmentsTableAnnotationComposer
    extends Composer<_$AppDatabase, $AssignmentsTable> {
  $$AssignmentsTableAnnotationComposer({
    required super.$db,
    required super.$table,
    super.joinBuilder,
    super.$addJoinBuilderToRootComposer,
    super.$removeJoinBuilderFromRootComposer,
  });
  GeneratedColumn<String> get id =>
      $composableBuilder(column: $table.id, builder: (column) => column);

  GeneratedColumn<String> get targetType => $composableBuilder(
      column: $table.targetType, builder: (column) => column);

  GeneratedColumn<String> get targetId =>
      $composableBuilder(column: $table.targetId, builder: (column) => column);

  GeneratedColumn<String> get itemId =>
      $composableBuilder(column: $table.itemId, builder: (column) => column);

  GeneratedColumn<String> get source =>
      $composableBuilder(column: $table.source, builder: (column) => column);

  GeneratedColumn<String> get suggestedItemId => $composableBuilder(
      column: $table.suggestedItemId, builder: (column) => column);

  GeneratedColumn<double> get suggestionConf => $composableBuilder(
      column: $table.suggestionConf, builder: (column) => column);

  GeneratedColumn<int> get confirmedAt => $composableBuilder(
      column: $table.confirmedAt, builder: (column) => column);

  GeneratedColumn<String> get confirmedBy => $composableBuilder(
      column: $table.confirmedBy, builder: (column) => column);

  GeneratedColumn<int> get revokedAt =>
      $composableBuilder(column: $table.revokedAt, builder: (column) => column);

  GeneratedColumn<String> get note =>
      $composableBuilder(column: $table.note, builder: (column) => column);

  $$ProjectsTableAnnotationComposer get projectId {
    final $$ProjectsTableAnnotationComposer composer = $composerBuilder(
        composer: this,
        getCurrentColumn: (t) => t.projectId,
        referencedTable: $db.projects,
        getReferencedColumn: (t) => t.id,
        builder: (joinBuilder,
                {$addJoinBuilderToRootComposer,
                $removeJoinBuilderFromRootComposer}) =>
            $$ProjectsTableAnnotationComposer(
              $db: $db,
              $table: $db.projects,
              $addJoinBuilderToRootComposer: $addJoinBuilderToRootComposer,
              joinBuilder: joinBuilder,
              $removeJoinBuilderFromRootComposer:
                  $removeJoinBuilderFromRootComposer,
            ));
    return composer;
  }
}

class $$AssignmentsTableTableManager extends RootTableManager<
    _$AppDatabase,
    $AssignmentsTable,
    Assignment,
    $$AssignmentsTableFilterComposer,
    $$AssignmentsTableOrderingComposer,
    $$AssignmentsTableAnnotationComposer,
    $$AssignmentsTableCreateCompanionBuilder,
    $$AssignmentsTableUpdateCompanionBuilder,
    (Assignment, $$AssignmentsTableReferences),
    Assignment,
    PrefetchHooks Function({bool projectId})> {
  $$AssignmentsTableTableManager(_$AppDatabase db, $AssignmentsTable table)
      : super(TableManagerState(
          db: db,
          table: table,
          createFilteringComposer: () =>
              $$AssignmentsTableFilterComposer($db: db, $table: table),
          createOrderingComposer: () =>
              $$AssignmentsTableOrderingComposer($db: db, $table: table),
          createComputedFieldComposer: () =>
              $$AssignmentsTableAnnotationComposer($db: db, $table: table),
          updateCompanionCallback: ({
            Value<String> id = const Value.absent(),
            Value<String> projectId = const Value.absent(),
            Value<String> targetType = const Value.absent(),
            Value<String> targetId = const Value.absent(),
            Value<String> itemId = const Value.absent(),
            Value<String> source = const Value.absent(),
            Value<String?> suggestedItemId = const Value.absent(),
            Value<double?> suggestionConf = const Value.absent(),
            Value<int> confirmedAt = const Value.absent(),
            Value<String> confirmedBy = const Value.absent(),
            Value<int?> revokedAt = const Value.absent(),
            Value<String?> note = const Value.absent(),
            Value<int> rowid = const Value.absent(),
          }) =>
              AssignmentsCompanion(
            id: id,
            projectId: projectId,
            targetType: targetType,
            targetId: targetId,
            itemId: itemId,
            source: source,
            suggestedItemId: suggestedItemId,
            suggestionConf: suggestionConf,
            confirmedAt: confirmedAt,
            confirmedBy: confirmedBy,
            revokedAt: revokedAt,
            note: note,
            rowid: rowid,
          ),
          createCompanionCallback: ({
            required String id,
            required String projectId,
            required String targetType,
            required String targetId,
            required String itemId,
            required String source,
            Value<String?> suggestedItemId = const Value.absent(),
            Value<double?> suggestionConf = const Value.absent(),
            required int confirmedAt,
            required String confirmedBy,
            Value<int?> revokedAt = const Value.absent(),
            Value<String?> note = const Value.absent(),
            Value<int> rowid = const Value.absent(),
          }) =>
              AssignmentsCompanion.insert(
            id: id,
            projectId: projectId,
            targetType: targetType,
            targetId: targetId,
            itemId: itemId,
            source: source,
            suggestedItemId: suggestedItemId,
            suggestionConf: suggestionConf,
            confirmedAt: confirmedAt,
            confirmedBy: confirmedBy,
            revokedAt: revokedAt,
            note: note,
            rowid: rowid,
          ),
          withReferenceMapper: (p0) => p0
              .map((e) => (
                    e.readTable(table),
                    $$AssignmentsTableReferences(db, table, e)
                  ))
              .toList(),
          prefetchHooksCallback: ({projectId = false}) {
            return PrefetchHooks(
              db: db,
              explicitlyWatchedTables: [],
              addJoins: <
                  T extends TableManagerState<
                      dynamic,
                      dynamic,
                      dynamic,
                      dynamic,
                      dynamic,
                      dynamic,
                      dynamic,
                      dynamic,
                      dynamic,
                      dynamic,
                      dynamic>>(state) {
                if (projectId) {
                  state = state.withJoin(
                    currentTable: table,
                    currentColumn: table.projectId,
                    referencedTable:
                        $$AssignmentsTableReferences._projectIdTable(db),
                    referencedColumn:
                        $$AssignmentsTableReferences._projectIdTable(db).id,
                  ) as T;
                }

                return state;
              },
              getPrefetchedDataCallback: (items) async {
                return [];
              },
            );
          },
        ));
}

typedef $$AssignmentsTableProcessedTableManager = ProcessedTableManager<
    _$AppDatabase,
    $AssignmentsTable,
    Assignment,
    $$AssignmentsTableFilterComposer,
    $$AssignmentsTableOrderingComposer,
    $$AssignmentsTableAnnotationComposer,
    $$AssignmentsTableCreateCompanionBuilder,
    $$AssignmentsTableUpdateCompanionBuilder,
    (Assignment, $$AssignmentsTableReferences),
    Assignment,
    PrefetchHooks Function({bool projectId})>;
typedef $$DeliveriesTableCreateCompanionBuilder = DeliveriesCompanion Function({
  required String id,
  required String projectId,
  required int createdAt,
  required String optionsJson,
  Value<String?> zipPath,
  Value<String?> pdfPath,
  Value<int?> bytes,
  Value<int?> itemCount,
  Value<int?> photoCount,
  Value<String?> sha256,
  Value<int?> sharedAt,
  Value<String?> webdavPath,
  Value<int> rowid,
});
typedef $$DeliveriesTableUpdateCompanionBuilder = DeliveriesCompanion Function({
  Value<String> id,
  Value<String> projectId,
  Value<int> createdAt,
  Value<String> optionsJson,
  Value<String?> zipPath,
  Value<String?> pdfPath,
  Value<int?> bytes,
  Value<int?> itemCount,
  Value<int?> photoCount,
  Value<String?> sha256,
  Value<int?> sharedAt,
  Value<String?> webdavPath,
  Value<int> rowid,
});

final class $$DeliveriesTableReferences
    extends BaseReferences<_$AppDatabase, $DeliveriesTable, Delivery> {
  $$DeliveriesTableReferences(super.$_db, super.$_table, super.$_typedResult);

  static $ProjectsTable _projectIdTable(_$AppDatabase db) =>
      db.projects.createAlias(
          $_aliasNameGenerator(db.deliveries.projectId, db.projects.id));

  $$ProjectsTableProcessedTableManager get projectId {
    final $_column = $_itemColumn<String>('project_id')!;

    final manager = $$ProjectsTableTableManager($_db, $_db.projects)
        .filter((f) => f.id.sqlEquals($_column));
    final item = $_typedResult.readTableOrNull(_projectIdTable($_db));
    if (item == null) return manager;
    return ProcessedTableManager(
        manager.$state.copyWith(prefetchedData: [item]));
  }

  static MultiTypedResultKey<$UploadTasksTable, List<UploadTask>>
      _uploadTasksRefsTable(_$AppDatabase db) =>
          MultiTypedResultKey.fromTable(db.uploadTasks,
              aliasName: $_aliasNameGenerator(
                  db.deliveries.id, db.uploadTasks.deliveryId));

  $$UploadTasksTableProcessedTableManager get uploadTasksRefs {
    final manager = $$UploadTasksTableTableManager($_db, $_db.uploadTasks)
        .filter((f) => f.deliveryId.id.sqlEquals($_itemColumn<String>('id')!));

    final cache = $_typedResult.readTableOrNull(_uploadTasksRefsTable($_db));
    return ProcessedTableManager(
        manager.$state.copyWith(prefetchedData: cache));
  }
}

class $$DeliveriesTableFilterComposer
    extends Composer<_$AppDatabase, $DeliveriesTable> {
  $$DeliveriesTableFilterComposer({
    required super.$db,
    required super.$table,
    super.joinBuilder,
    super.$addJoinBuilderToRootComposer,
    super.$removeJoinBuilderFromRootComposer,
  });
  ColumnFilters<String> get id => $composableBuilder(
      column: $table.id, builder: (column) => ColumnFilters(column));

  ColumnFilters<int> get createdAt => $composableBuilder(
      column: $table.createdAt, builder: (column) => ColumnFilters(column));

  ColumnFilters<String> get optionsJson => $composableBuilder(
      column: $table.optionsJson, builder: (column) => ColumnFilters(column));

  ColumnFilters<String> get zipPath => $composableBuilder(
      column: $table.zipPath, builder: (column) => ColumnFilters(column));

  ColumnFilters<String> get pdfPath => $composableBuilder(
      column: $table.pdfPath, builder: (column) => ColumnFilters(column));

  ColumnFilters<int> get bytes => $composableBuilder(
      column: $table.bytes, builder: (column) => ColumnFilters(column));

  ColumnFilters<int> get itemCount => $composableBuilder(
      column: $table.itemCount, builder: (column) => ColumnFilters(column));

  ColumnFilters<int> get photoCount => $composableBuilder(
      column: $table.photoCount, builder: (column) => ColumnFilters(column));

  ColumnFilters<String> get sha256 => $composableBuilder(
      column: $table.sha256, builder: (column) => ColumnFilters(column));

  ColumnFilters<int> get sharedAt => $composableBuilder(
      column: $table.sharedAt, builder: (column) => ColumnFilters(column));

  ColumnFilters<String> get webdavPath => $composableBuilder(
      column: $table.webdavPath, builder: (column) => ColumnFilters(column));

  $$ProjectsTableFilterComposer get projectId {
    final $$ProjectsTableFilterComposer composer = $composerBuilder(
        composer: this,
        getCurrentColumn: (t) => t.projectId,
        referencedTable: $db.projects,
        getReferencedColumn: (t) => t.id,
        builder: (joinBuilder,
                {$addJoinBuilderToRootComposer,
                $removeJoinBuilderFromRootComposer}) =>
            $$ProjectsTableFilterComposer(
              $db: $db,
              $table: $db.projects,
              $addJoinBuilderToRootComposer: $addJoinBuilderToRootComposer,
              joinBuilder: joinBuilder,
              $removeJoinBuilderFromRootComposer:
                  $removeJoinBuilderFromRootComposer,
            ));
    return composer;
  }

  Expression<bool> uploadTasksRefs(
      Expression<bool> Function($$UploadTasksTableFilterComposer f) f) {
    final $$UploadTasksTableFilterComposer composer = $composerBuilder(
        composer: this,
        getCurrentColumn: (t) => t.id,
        referencedTable: $db.uploadTasks,
        getReferencedColumn: (t) => t.deliveryId,
        builder: (joinBuilder,
                {$addJoinBuilderToRootComposer,
                $removeJoinBuilderFromRootComposer}) =>
            $$UploadTasksTableFilterComposer(
              $db: $db,
              $table: $db.uploadTasks,
              $addJoinBuilderToRootComposer: $addJoinBuilderToRootComposer,
              joinBuilder: joinBuilder,
              $removeJoinBuilderFromRootComposer:
                  $removeJoinBuilderFromRootComposer,
            ));
    return f(composer);
  }
}

class $$DeliveriesTableOrderingComposer
    extends Composer<_$AppDatabase, $DeliveriesTable> {
  $$DeliveriesTableOrderingComposer({
    required super.$db,
    required super.$table,
    super.joinBuilder,
    super.$addJoinBuilderToRootComposer,
    super.$removeJoinBuilderFromRootComposer,
  });
  ColumnOrderings<String> get id => $composableBuilder(
      column: $table.id, builder: (column) => ColumnOrderings(column));

  ColumnOrderings<int> get createdAt => $composableBuilder(
      column: $table.createdAt, builder: (column) => ColumnOrderings(column));

  ColumnOrderings<String> get optionsJson => $composableBuilder(
      column: $table.optionsJson, builder: (column) => ColumnOrderings(column));

  ColumnOrderings<String> get zipPath => $composableBuilder(
      column: $table.zipPath, builder: (column) => ColumnOrderings(column));

  ColumnOrderings<String> get pdfPath => $composableBuilder(
      column: $table.pdfPath, builder: (column) => ColumnOrderings(column));

  ColumnOrderings<int> get bytes => $composableBuilder(
      column: $table.bytes, builder: (column) => ColumnOrderings(column));

  ColumnOrderings<int> get itemCount => $composableBuilder(
      column: $table.itemCount, builder: (column) => ColumnOrderings(column));

  ColumnOrderings<int> get photoCount => $composableBuilder(
      column: $table.photoCount, builder: (column) => ColumnOrderings(column));

  ColumnOrderings<String> get sha256 => $composableBuilder(
      column: $table.sha256, builder: (column) => ColumnOrderings(column));

  ColumnOrderings<int> get sharedAt => $composableBuilder(
      column: $table.sharedAt, builder: (column) => ColumnOrderings(column));

  ColumnOrderings<String> get webdavPath => $composableBuilder(
      column: $table.webdavPath, builder: (column) => ColumnOrderings(column));

  $$ProjectsTableOrderingComposer get projectId {
    final $$ProjectsTableOrderingComposer composer = $composerBuilder(
        composer: this,
        getCurrentColumn: (t) => t.projectId,
        referencedTable: $db.projects,
        getReferencedColumn: (t) => t.id,
        builder: (joinBuilder,
                {$addJoinBuilderToRootComposer,
                $removeJoinBuilderFromRootComposer}) =>
            $$ProjectsTableOrderingComposer(
              $db: $db,
              $table: $db.projects,
              $addJoinBuilderToRootComposer: $addJoinBuilderToRootComposer,
              joinBuilder: joinBuilder,
              $removeJoinBuilderFromRootComposer:
                  $removeJoinBuilderFromRootComposer,
            ));
    return composer;
  }
}

class $$DeliveriesTableAnnotationComposer
    extends Composer<_$AppDatabase, $DeliveriesTable> {
  $$DeliveriesTableAnnotationComposer({
    required super.$db,
    required super.$table,
    super.joinBuilder,
    super.$addJoinBuilderToRootComposer,
    super.$removeJoinBuilderFromRootComposer,
  });
  GeneratedColumn<String> get id =>
      $composableBuilder(column: $table.id, builder: (column) => column);

  GeneratedColumn<int> get createdAt =>
      $composableBuilder(column: $table.createdAt, builder: (column) => column);

  GeneratedColumn<String> get optionsJson => $composableBuilder(
      column: $table.optionsJson, builder: (column) => column);

  GeneratedColumn<String> get zipPath =>
      $composableBuilder(column: $table.zipPath, builder: (column) => column);

  GeneratedColumn<String> get pdfPath =>
      $composableBuilder(column: $table.pdfPath, builder: (column) => column);

  GeneratedColumn<int> get bytes =>
      $composableBuilder(column: $table.bytes, builder: (column) => column);

  GeneratedColumn<int> get itemCount =>
      $composableBuilder(column: $table.itemCount, builder: (column) => column);

  GeneratedColumn<int> get photoCount => $composableBuilder(
      column: $table.photoCount, builder: (column) => column);

  GeneratedColumn<String> get sha256 =>
      $composableBuilder(column: $table.sha256, builder: (column) => column);

  GeneratedColumn<int> get sharedAt =>
      $composableBuilder(column: $table.sharedAt, builder: (column) => column);

  GeneratedColumn<String> get webdavPath => $composableBuilder(
      column: $table.webdavPath, builder: (column) => column);

  $$ProjectsTableAnnotationComposer get projectId {
    final $$ProjectsTableAnnotationComposer composer = $composerBuilder(
        composer: this,
        getCurrentColumn: (t) => t.projectId,
        referencedTable: $db.projects,
        getReferencedColumn: (t) => t.id,
        builder: (joinBuilder,
                {$addJoinBuilderToRootComposer,
                $removeJoinBuilderFromRootComposer}) =>
            $$ProjectsTableAnnotationComposer(
              $db: $db,
              $table: $db.projects,
              $addJoinBuilderToRootComposer: $addJoinBuilderToRootComposer,
              joinBuilder: joinBuilder,
              $removeJoinBuilderFromRootComposer:
                  $removeJoinBuilderFromRootComposer,
            ));
    return composer;
  }

  Expression<T> uploadTasksRefs<T extends Object>(
      Expression<T> Function($$UploadTasksTableAnnotationComposer a) f) {
    final $$UploadTasksTableAnnotationComposer composer = $composerBuilder(
        composer: this,
        getCurrentColumn: (t) => t.id,
        referencedTable: $db.uploadTasks,
        getReferencedColumn: (t) => t.deliveryId,
        builder: (joinBuilder,
                {$addJoinBuilderToRootComposer,
                $removeJoinBuilderFromRootComposer}) =>
            $$UploadTasksTableAnnotationComposer(
              $db: $db,
              $table: $db.uploadTasks,
              $addJoinBuilderToRootComposer: $addJoinBuilderToRootComposer,
              joinBuilder: joinBuilder,
              $removeJoinBuilderFromRootComposer:
                  $removeJoinBuilderFromRootComposer,
            ));
    return f(composer);
  }
}

class $$DeliveriesTableTableManager extends RootTableManager<
    _$AppDatabase,
    $DeliveriesTable,
    Delivery,
    $$DeliveriesTableFilterComposer,
    $$DeliveriesTableOrderingComposer,
    $$DeliveriesTableAnnotationComposer,
    $$DeliveriesTableCreateCompanionBuilder,
    $$DeliveriesTableUpdateCompanionBuilder,
    (Delivery, $$DeliveriesTableReferences),
    Delivery,
    PrefetchHooks Function({bool projectId, bool uploadTasksRefs})> {
  $$DeliveriesTableTableManager(_$AppDatabase db, $DeliveriesTable table)
      : super(TableManagerState(
          db: db,
          table: table,
          createFilteringComposer: () =>
              $$DeliveriesTableFilterComposer($db: db, $table: table),
          createOrderingComposer: () =>
              $$DeliveriesTableOrderingComposer($db: db, $table: table),
          createComputedFieldComposer: () =>
              $$DeliveriesTableAnnotationComposer($db: db, $table: table),
          updateCompanionCallback: ({
            Value<String> id = const Value.absent(),
            Value<String> projectId = const Value.absent(),
            Value<int> createdAt = const Value.absent(),
            Value<String> optionsJson = const Value.absent(),
            Value<String?> zipPath = const Value.absent(),
            Value<String?> pdfPath = const Value.absent(),
            Value<int?> bytes = const Value.absent(),
            Value<int?> itemCount = const Value.absent(),
            Value<int?> photoCount = const Value.absent(),
            Value<String?> sha256 = const Value.absent(),
            Value<int?> sharedAt = const Value.absent(),
            Value<String?> webdavPath = const Value.absent(),
            Value<int> rowid = const Value.absent(),
          }) =>
              DeliveriesCompanion(
            id: id,
            projectId: projectId,
            createdAt: createdAt,
            optionsJson: optionsJson,
            zipPath: zipPath,
            pdfPath: pdfPath,
            bytes: bytes,
            itemCount: itemCount,
            photoCount: photoCount,
            sha256: sha256,
            sharedAt: sharedAt,
            webdavPath: webdavPath,
            rowid: rowid,
          ),
          createCompanionCallback: ({
            required String id,
            required String projectId,
            required int createdAt,
            required String optionsJson,
            Value<String?> zipPath = const Value.absent(),
            Value<String?> pdfPath = const Value.absent(),
            Value<int?> bytes = const Value.absent(),
            Value<int?> itemCount = const Value.absent(),
            Value<int?> photoCount = const Value.absent(),
            Value<String?> sha256 = const Value.absent(),
            Value<int?> sharedAt = const Value.absent(),
            Value<String?> webdavPath = const Value.absent(),
            Value<int> rowid = const Value.absent(),
          }) =>
              DeliveriesCompanion.insert(
            id: id,
            projectId: projectId,
            createdAt: createdAt,
            optionsJson: optionsJson,
            zipPath: zipPath,
            pdfPath: pdfPath,
            bytes: bytes,
            itemCount: itemCount,
            photoCount: photoCount,
            sha256: sha256,
            sharedAt: sharedAt,
            webdavPath: webdavPath,
            rowid: rowid,
          ),
          withReferenceMapper: (p0) => p0
              .map((e) => (
                    e.readTable(table),
                    $$DeliveriesTableReferences(db, table, e)
                  ))
              .toList(),
          prefetchHooksCallback: (
              {projectId = false, uploadTasksRefs = false}) {
            return PrefetchHooks(
              db: db,
              explicitlyWatchedTables: [if (uploadTasksRefs) db.uploadTasks],
              addJoins: <
                  T extends TableManagerState<
                      dynamic,
                      dynamic,
                      dynamic,
                      dynamic,
                      dynamic,
                      dynamic,
                      dynamic,
                      dynamic,
                      dynamic,
                      dynamic,
                      dynamic>>(state) {
                if (projectId) {
                  state = state.withJoin(
                    currentTable: table,
                    currentColumn: table.projectId,
                    referencedTable:
                        $$DeliveriesTableReferences._projectIdTable(db),
                    referencedColumn:
                        $$DeliveriesTableReferences._projectIdTable(db).id,
                  ) as T;
                }

                return state;
              },
              getPrefetchedDataCallback: (items) async {
                return [
                  if (uploadTasksRefs)
                    await $_getPrefetchedData<Delivery, $DeliveriesTable,
                            UploadTask>(
                        currentTable: table,
                        referencedTable: $$DeliveriesTableReferences
                            ._uploadTasksRefsTable(db),
                        managerFromTypedResult: (p0) =>
                            $$DeliveriesTableReferences(db, table, p0)
                                .uploadTasksRefs,
                        referencedItemsForCurrentItem:
                            (item, referencedItems) => referencedItems
                                .where((e) => e.deliveryId == item.id),
                        typedResults: items)
                ];
              },
            );
          },
        ));
}

typedef $$DeliveriesTableProcessedTableManager = ProcessedTableManager<
    _$AppDatabase,
    $DeliveriesTable,
    Delivery,
    $$DeliveriesTableFilterComposer,
    $$DeliveriesTableOrderingComposer,
    $$DeliveriesTableAnnotationComposer,
    $$DeliveriesTableCreateCompanionBuilder,
    $$DeliveriesTableUpdateCompanionBuilder,
    (Delivery, $$DeliveriesTableReferences),
    Delivery,
    PrefetchHooks Function({bool projectId, bool uploadTasksRefs})>;
typedef $$UploadTasksTableCreateCompanionBuilder = UploadTasksCompanion
    Function({
  required String id,
  required String deliveryId,
  required String localPath,
  required String remotePath,
  required int bytes,
  Value<int> uploadedBytes,
  Value<String> state,
  Value<int> attempts,
  Value<int?> nextRetryAt,
  Value<String?> lastError,
  Value<int> rowid,
});
typedef $$UploadTasksTableUpdateCompanionBuilder = UploadTasksCompanion
    Function({
  Value<String> id,
  Value<String> deliveryId,
  Value<String> localPath,
  Value<String> remotePath,
  Value<int> bytes,
  Value<int> uploadedBytes,
  Value<String> state,
  Value<int> attempts,
  Value<int?> nextRetryAt,
  Value<String?> lastError,
  Value<int> rowid,
});

final class $$UploadTasksTableReferences
    extends BaseReferences<_$AppDatabase, $UploadTasksTable, UploadTask> {
  $$UploadTasksTableReferences(super.$_db, super.$_table, super.$_typedResult);

  static $DeliveriesTable _deliveryIdTable(_$AppDatabase db) =>
      db.deliveries.createAlias(
          $_aliasNameGenerator(db.uploadTasks.deliveryId, db.deliveries.id));

  $$DeliveriesTableProcessedTableManager get deliveryId {
    final $_column = $_itemColumn<String>('delivery_id')!;

    final manager = $$DeliveriesTableTableManager($_db, $_db.deliveries)
        .filter((f) => f.id.sqlEquals($_column));
    final item = $_typedResult.readTableOrNull(_deliveryIdTable($_db));
    if (item == null) return manager;
    return ProcessedTableManager(
        manager.$state.copyWith(prefetchedData: [item]));
  }
}

class $$UploadTasksTableFilterComposer
    extends Composer<_$AppDatabase, $UploadTasksTable> {
  $$UploadTasksTableFilterComposer({
    required super.$db,
    required super.$table,
    super.joinBuilder,
    super.$addJoinBuilderToRootComposer,
    super.$removeJoinBuilderFromRootComposer,
  });
  ColumnFilters<String> get id => $composableBuilder(
      column: $table.id, builder: (column) => ColumnFilters(column));

  ColumnFilters<String> get localPath => $composableBuilder(
      column: $table.localPath, builder: (column) => ColumnFilters(column));

  ColumnFilters<String> get remotePath => $composableBuilder(
      column: $table.remotePath, builder: (column) => ColumnFilters(column));

  ColumnFilters<int> get bytes => $composableBuilder(
      column: $table.bytes, builder: (column) => ColumnFilters(column));

  ColumnFilters<int> get uploadedBytes => $composableBuilder(
      column: $table.uploadedBytes, builder: (column) => ColumnFilters(column));

  ColumnFilters<String> get state => $composableBuilder(
      column: $table.state, builder: (column) => ColumnFilters(column));

  ColumnFilters<int> get attempts => $composableBuilder(
      column: $table.attempts, builder: (column) => ColumnFilters(column));

  ColumnFilters<int> get nextRetryAt => $composableBuilder(
      column: $table.nextRetryAt, builder: (column) => ColumnFilters(column));

  ColumnFilters<String> get lastError => $composableBuilder(
      column: $table.lastError, builder: (column) => ColumnFilters(column));

  $$DeliveriesTableFilterComposer get deliveryId {
    final $$DeliveriesTableFilterComposer composer = $composerBuilder(
        composer: this,
        getCurrentColumn: (t) => t.deliveryId,
        referencedTable: $db.deliveries,
        getReferencedColumn: (t) => t.id,
        builder: (joinBuilder,
                {$addJoinBuilderToRootComposer,
                $removeJoinBuilderFromRootComposer}) =>
            $$DeliveriesTableFilterComposer(
              $db: $db,
              $table: $db.deliveries,
              $addJoinBuilderToRootComposer: $addJoinBuilderToRootComposer,
              joinBuilder: joinBuilder,
              $removeJoinBuilderFromRootComposer:
                  $removeJoinBuilderFromRootComposer,
            ));
    return composer;
  }
}

class $$UploadTasksTableOrderingComposer
    extends Composer<_$AppDatabase, $UploadTasksTable> {
  $$UploadTasksTableOrderingComposer({
    required super.$db,
    required super.$table,
    super.joinBuilder,
    super.$addJoinBuilderToRootComposer,
    super.$removeJoinBuilderFromRootComposer,
  });
  ColumnOrderings<String> get id => $composableBuilder(
      column: $table.id, builder: (column) => ColumnOrderings(column));

  ColumnOrderings<String> get localPath => $composableBuilder(
      column: $table.localPath, builder: (column) => ColumnOrderings(column));

  ColumnOrderings<String> get remotePath => $composableBuilder(
      column: $table.remotePath, builder: (column) => ColumnOrderings(column));

  ColumnOrderings<int> get bytes => $composableBuilder(
      column: $table.bytes, builder: (column) => ColumnOrderings(column));

  ColumnOrderings<int> get uploadedBytes => $composableBuilder(
      column: $table.uploadedBytes,
      builder: (column) => ColumnOrderings(column));

  ColumnOrderings<String> get state => $composableBuilder(
      column: $table.state, builder: (column) => ColumnOrderings(column));

  ColumnOrderings<int> get attempts => $composableBuilder(
      column: $table.attempts, builder: (column) => ColumnOrderings(column));

  ColumnOrderings<int> get nextRetryAt => $composableBuilder(
      column: $table.nextRetryAt, builder: (column) => ColumnOrderings(column));

  ColumnOrderings<String> get lastError => $composableBuilder(
      column: $table.lastError, builder: (column) => ColumnOrderings(column));

  $$DeliveriesTableOrderingComposer get deliveryId {
    final $$DeliveriesTableOrderingComposer composer = $composerBuilder(
        composer: this,
        getCurrentColumn: (t) => t.deliveryId,
        referencedTable: $db.deliveries,
        getReferencedColumn: (t) => t.id,
        builder: (joinBuilder,
                {$addJoinBuilderToRootComposer,
                $removeJoinBuilderFromRootComposer}) =>
            $$DeliveriesTableOrderingComposer(
              $db: $db,
              $table: $db.deliveries,
              $addJoinBuilderToRootComposer: $addJoinBuilderToRootComposer,
              joinBuilder: joinBuilder,
              $removeJoinBuilderFromRootComposer:
                  $removeJoinBuilderFromRootComposer,
            ));
    return composer;
  }
}

class $$UploadTasksTableAnnotationComposer
    extends Composer<_$AppDatabase, $UploadTasksTable> {
  $$UploadTasksTableAnnotationComposer({
    required super.$db,
    required super.$table,
    super.joinBuilder,
    super.$addJoinBuilderToRootComposer,
    super.$removeJoinBuilderFromRootComposer,
  });
  GeneratedColumn<String> get id =>
      $composableBuilder(column: $table.id, builder: (column) => column);

  GeneratedColumn<String> get localPath =>
      $composableBuilder(column: $table.localPath, builder: (column) => column);

  GeneratedColumn<String> get remotePath => $composableBuilder(
      column: $table.remotePath, builder: (column) => column);

  GeneratedColumn<int> get bytes =>
      $composableBuilder(column: $table.bytes, builder: (column) => column);

  GeneratedColumn<int> get uploadedBytes => $composableBuilder(
      column: $table.uploadedBytes, builder: (column) => column);

  GeneratedColumn<String> get state =>
      $composableBuilder(column: $table.state, builder: (column) => column);

  GeneratedColumn<int> get attempts =>
      $composableBuilder(column: $table.attempts, builder: (column) => column);

  GeneratedColumn<int> get nextRetryAt => $composableBuilder(
      column: $table.nextRetryAt, builder: (column) => column);

  GeneratedColumn<String> get lastError =>
      $composableBuilder(column: $table.lastError, builder: (column) => column);

  $$DeliveriesTableAnnotationComposer get deliveryId {
    final $$DeliveriesTableAnnotationComposer composer = $composerBuilder(
        composer: this,
        getCurrentColumn: (t) => t.deliveryId,
        referencedTable: $db.deliveries,
        getReferencedColumn: (t) => t.id,
        builder: (joinBuilder,
                {$addJoinBuilderToRootComposer,
                $removeJoinBuilderFromRootComposer}) =>
            $$DeliveriesTableAnnotationComposer(
              $db: $db,
              $table: $db.deliveries,
              $addJoinBuilderToRootComposer: $addJoinBuilderToRootComposer,
              joinBuilder: joinBuilder,
              $removeJoinBuilderFromRootComposer:
                  $removeJoinBuilderFromRootComposer,
            ));
    return composer;
  }
}

class $$UploadTasksTableTableManager extends RootTableManager<
    _$AppDatabase,
    $UploadTasksTable,
    UploadTask,
    $$UploadTasksTableFilterComposer,
    $$UploadTasksTableOrderingComposer,
    $$UploadTasksTableAnnotationComposer,
    $$UploadTasksTableCreateCompanionBuilder,
    $$UploadTasksTableUpdateCompanionBuilder,
    (UploadTask, $$UploadTasksTableReferences),
    UploadTask,
    PrefetchHooks Function({bool deliveryId})> {
  $$UploadTasksTableTableManager(_$AppDatabase db, $UploadTasksTable table)
      : super(TableManagerState(
          db: db,
          table: table,
          createFilteringComposer: () =>
              $$UploadTasksTableFilterComposer($db: db, $table: table),
          createOrderingComposer: () =>
              $$UploadTasksTableOrderingComposer($db: db, $table: table),
          createComputedFieldComposer: () =>
              $$UploadTasksTableAnnotationComposer($db: db, $table: table),
          updateCompanionCallback: ({
            Value<String> id = const Value.absent(),
            Value<String> deliveryId = const Value.absent(),
            Value<String> localPath = const Value.absent(),
            Value<String> remotePath = const Value.absent(),
            Value<int> bytes = const Value.absent(),
            Value<int> uploadedBytes = const Value.absent(),
            Value<String> state = const Value.absent(),
            Value<int> attempts = const Value.absent(),
            Value<int?> nextRetryAt = const Value.absent(),
            Value<String?> lastError = const Value.absent(),
            Value<int> rowid = const Value.absent(),
          }) =>
              UploadTasksCompanion(
            id: id,
            deliveryId: deliveryId,
            localPath: localPath,
            remotePath: remotePath,
            bytes: bytes,
            uploadedBytes: uploadedBytes,
            state: state,
            attempts: attempts,
            nextRetryAt: nextRetryAt,
            lastError: lastError,
            rowid: rowid,
          ),
          createCompanionCallback: ({
            required String id,
            required String deliveryId,
            required String localPath,
            required String remotePath,
            required int bytes,
            Value<int> uploadedBytes = const Value.absent(),
            Value<String> state = const Value.absent(),
            Value<int> attempts = const Value.absent(),
            Value<int?> nextRetryAt = const Value.absent(),
            Value<String?> lastError = const Value.absent(),
            Value<int> rowid = const Value.absent(),
          }) =>
              UploadTasksCompanion.insert(
            id: id,
            deliveryId: deliveryId,
            localPath: localPath,
            remotePath: remotePath,
            bytes: bytes,
            uploadedBytes: uploadedBytes,
            state: state,
            attempts: attempts,
            nextRetryAt: nextRetryAt,
            lastError: lastError,
            rowid: rowid,
          ),
          withReferenceMapper: (p0) => p0
              .map((e) => (
                    e.readTable(table),
                    $$UploadTasksTableReferences(db, table, e)
                  ))
              .toList(),
          prefetchHooksCallback: ({deliveryId = false}) {
            return PrefetchHooks(
              db: db,
              explicitlyWatchedTables: [],
              addJoins: <
                  T extends TableManagerState<
                      dynamic,
                      dynamic,
                      dynamic,
                      dynamic,
                      dynamic,
                      dynamic,
                      dynamic,
                      dynamic,
                      dynamic,
                      dynamic,
                      dynamic>>(state) {
                if (deliveryId) {
                  state = state.withJoin(
                    currentTable: table,
                    currentColumn: table.deliveryId,
                    referencedTable:
                        $$UploadTasksTableReferences._deliveryIdTable(db),
                    referencedColumn:
                        $$UploadTasksTableReferences._deliveryIdTable(db).id,
                  ) as T;
                }

                return state;
              },
              getPrefetchedDataCallback: (items) async {
                return [];
              },
            );
          },
        ));
}

typedef $$UploadTasksTableProcessedTableManager = ProcessedTableManager<
    _$AppDatabase,
    $UploadTasksTable,
    UploadTask,
    $$UploadTasksTableFilterComposer,
    $$UploadTasksTableOrderingComposer,
    $$UploadTasksTableAnnotationComposer,
    $$UploadTasksTableCreateCompanionBuilder,
    $$UploadTasksTableUpdateCompanionBuilder,
    (UploadTask, $$UploadTasksTableReferences),
    UploadTask,
    PrefetchHooks Function({bool deliveryId})>;
typedef $$ItemPhotoExtrasTableCreateCompanionBuilder = ItemPhotoExtrasCompanion
    Function({
  required String id,
  required String photoId,
  required String itemId,
  Value<String> role,
  required int createdAt,
  Value<int> rowid,
});
typedef $$ItemPhotoExtrasTableUpdateCompanionBuilder = ItemPhotoExtrasCompanion
    Function({
  Value<String> id,
  Value<String> photoId,
  Value<String> itemId,
  Value<String> role,
  Value<int> createdAt,
  Value<int> rowid,
});

final class $$ItemPhotoExtrasTableReferences extends BaseReferences<
    _$AppDatabase, $ItemPhotoExtrasTable, ItemPhotoExtra> {
  $$ItemPhotoExtrasTableReferences(
      super.$_db, super.$_table, super.$_typedResult);

  static $PhotosTable _photoIdTable(_$AppDatabase db) => db.photos.createAlias(
      $_aliasNameGenerator(db.itemPhotoExtras.photoId, db.photos.id));

  $$PhotosTableProcessedTableManager get photoId {
    final $_column = $_itemColumn<String>('photo_id')!;

    final manager = $$PhotosTableTableManager($_db, $_db.photos)
        .filter((f) => f.id.sqlEquals($_column));
    final item = $_typedResult.readTableOrNull(_photoIdTable($_db));
    if (item == null) return manager;
    return ProcessedTableManager(
        manager.$state.copyWith(prefetchedData: [item]));
  }

  static $ItemsTable _itemIdTable(_$AppDatabase db) => db.items.createAlias(
      $_aliasNameGenerator(db.itemPhotoExtras.itemId, db.items.id));

  $$ItemsTableProcessedTableManager get itemId {
    final $_column = $_itemColumn<String>('item_id')!;

    final manager = $$ItemsTableTableManager($_db, $_db.items)
        .filter((f) => f.id.sqlEquals($_column));
    final item = $_typedResult.readTableOrNull(_itemIdTable($_db));
    if (item == null) return manager;
    return ProcessedTableManager(
        manager.$state.copyWith(prefetchedData: [item]));
  }
}

class $$ItemPhotoExtrasTableFilterComposer
    extends Composer<_$AppDatabase, $ItemPhotoExtrasTable> {
  $$ItemPhotoExtrasTableFilterComposer({
    required super.$db,
    required super.$table,
    super.joinBuilder,
    super.$addJoinBuilderToRootComposer,
    super.$removeJoinBuilderFromRootComposer,
  });
  ColumnFilters<String> get id => $composableBuilder(
      column: $table.id, builder: (column) => ColumnFilters(column));

  ColumnFilters<String> get role => $composableBuilder(
      column: $table.role, builder: (column) => ColumnFilters(column));

  ColumnFilters<int> get createdAt => $composableBuilder(
      column: $table.createdAt, builder: (column) => ColumnFilters(column));

  $$PhotosTableFilterComposer get photoId {
    final $$PhotosTableFilterComposer composer = $composerBuilder(
        composer: this,
        getCurrentColumn: (t) => t.photoId,
        referencedTable: $db.photos,
        getReferencedColumn: (t) => t.id,
        builder: (joinBuilder,
                {$addJoinBuilderToRootComposer,
                $removeJoinBuilderFromRootComposer}) =>
            $$PhotosTableFilterComposer(
              $db: $db,
              $table: $db.photos,
              $addJoinBuilderToRootComposer: $addJoinBuilderToRootComposer,
              joinBuilder: joinBuilder,
              $removeJoinBuilderFromRootComposer:
                  $removeJoinBuilderFromRootComposer,
            ));
    return composer;
  }

  $$ItemsTableFilterComposer get itemId {
    final $$ItemsTableFilterComposer composer = $composerBuilder(
        composer: this,
        getCurrentColumn: (t) => t.itemId,
        referencedTable: $db.items,
        getReferencedColumn: (t) => t.id,
        builder: (joinBuilder,
                {$addJoinBuilderToRootComposer,
                $removeJoinBuilderFromRootComposer}) =>
            $$ItemsTableFilterComposer(
              $db: $db,
              $table: $db.items,
              $addJoinBuilderToRootComposer: $addJoinBuilderToRootComposer,
              joinBuilder: joinBuilder,
              $removeJoinBuilderFromRootComposer:
                  $removeJoinBuilderFromRootComposer,
            ));
    return composer;
  }
}

class $$ItemPhotoExtrasTableOrderingComposer
    extends Composer<_$AppDatabase, $ItemPhotoExtrasTable> {
  $$ItemPhotoExtrasTableOrderingComposer({
    required super.$db,
    required super.$table,
    super.joinBuilder,
    super.$addJoinBuilderToRootComposer,
    super.$removeJoinBuilderFromRootComposer,
  });
  ColumnOrderings<String> get id => $composableBuilder(
      column: $table.id, builder: (column) => ColumnOrderings(column));

  ColumnOrderings<String> get role => $composableBuilder(
      column: $table.role, builder: (column) => ColumnOrderings(column));

  ColumnOrderings<int> get createdAt => $composableBuilder(
      column: $table.createdAt, builder: (column) => ColumnOrderings(column));

  $$PhotosTableOrderingComposer get photoId {
    final $$PhotosTableOrderingComposer composer = $composerBuilder(
        composer: this,
        getCurrentColumn: (t) => t.photoId,
        referencedTable: $db.photos,
        getReferencedColumn: (t) => t.id,
        builder: (joinBuilder,
                {$addJoinBuilderToRootComposer,
                $removeJoinBuilderFromRootComposer}) =>
            $$PhotosTableOrderingComposer(
              $db: $db,
              $table: $db.photos,
              $addJoinBuilderToRootComposer: $addJoinBuilderToRootComposer,
              joinBuilder: joinBuilder,
              $removeJoinBuilderFromRootComposer:
                  $removeJoinBuilderFromRootComposer,
            ));
    return composer;
  }

  $$ItemsTableOrderingComposer get itemId {
    final $$ItemsTableOrderingComposer composer = $composerBuilder(
        composer: this,
        getCurrentColumn: (t) => t.itemId,
        referencedTable: $db.items,
        getReferencedColumn: (t) => t.id,
        builder: (joinBuilder,
                {$addJoinBuilderToRootComposer,
                $removeJoinBuilderFromRootComposer}) =>
            $$ItemsTableOrderingComposer(
              $db: $db,
              $table: $db.items,
              $addJoinBuilderToRootComposer: $addJoinBuilderToRootComposer,
              joinBuilder: joinBuilder,
              $removeJoinBuilderFromRootComposer:
                  $removeJoinBuilderFromRootComposer,
            ));
    return composer;
  }
}

class $$ItemPhotoExtrasTableAnnotationComposer
    extends Composer<_$AppDatabase, $ItemPhotoExtrasTable> {
  $$ItemPhotoExtrasTableAnnotationComposer({
    required super.$db,
    required super.$table,
    super.joinBuilder,
    super.$addJoinBuilderToRootComposer,
    super.$removeJoinBuilderFromRootComposer,
  });
  GeneratedColumn<String> get id =>
      $composableBuilder(column: $table.id, builder: (column) => column);

  GeneratedColumn<String> get role =>
      $composableBuilder(column: $table.role, builder: (column) => column);

  GeneratedColumn<int> get createdAt =>
      $composableBuilder(column: $table.createdAt, builder: (column) => column);

  $$PhotosTableAnnotationComposer get photoId {
    final $$PhotosTableAnnotationComposer composer = $composerBuilder(
        composer: this,
        getCurrentColumn: (t) => t.photoId,
        referencedTable: $db.photos,
        getReferencedColumn: (t) => t.id,
        builder: (joinBuilder,
                {$addJoinBuilderToRootComposer,
                $removeJoinBuilderFromRootComposer}) =>
            $$PhotosTableAnnotationComposer(
              $db: $db,
              $table: $db.photos,
              $addJoinBuilderToRootComposer: $addJoinBuilderToRootComposer,
              joinBuilder: joinBuilder,
              $removeJoinBuilderFromRootComposer:
                  $removeJoinBuilderFromRootComposer,
            ));
    return composer;
  }

  $$ItemsTableAnnotationComposer get itemId {
    final $$ItemsTableAnnotationComposer composer = $composerBuilder(
        composer: this,
        getCurrentColumn: (t) => t.itemId,
        referencedTable: $db.items,
        getReferencedColumn: (t) => t.id,
        builder: (joinBuilder,
                {$addJoinBuilderToRootComposer,
                $removeJoinBuilderFromRootComposer}) =>
            $$ItemsTableAnnotationComposer(
              $db: $db,
              $table: $db.items,
              $addJoinBuilderToRootComposer: $addJoinBuilderToRootComposer,
              joinBuilder: joinBuilder,
              $removeJoinBuilderFromRootComposer:
                  $removeJoinBuilderFromRootComposer,
            ));
    return composer;
  }
}

class $$ItemPhotoExtrasTableTableManager extends RootTableManager<
    _$AppDatabase,
    $ItemPhotoExtrasTable,
    ItemPhotoExtra,
    $$ItemPhotoExtrasTableFilterComposer,
    $$ItemPhotoExtrasTableOrderingComposer,
    $$ItemPhotoExtrasTableAnnotationComposer,
    $$ItemPhotoExtrasTableCreateCompanionBuilder,
    $$ItemPhotoExtrasTableUpdateCompanionBuilder,
    (ItemPhotoExtra, $$ItemPhotoExtrasTableReferences),
    ItemPhotoExtra,
    PrefetchHooks Function({bool photoId, bool itemId})> {
  $$ItemPhotoExtrasTableTableManager(
      _$AppDatabase db, $ItemPhotoExtrasTable table)
      : super(TableManagerState(
          db: db,
          table: table,
          createFilteringComposer: () =>
              $$ItemPhotoExtrasTableFilterComposer($db: db, $table: table),
          createOrderingComposer: () =>
              $$ItemPhotoExtrasTableOrderingComposer($db: db, $table: table),
          createComputedFieldComposer: () =>
              $$ItemPhotoExtrasTableAnnotationComposer($db: db, $table: table),
          updateCompanionCallback: ({
            Value<String> id = const Value.absent(),
            Value<String> photoId = const Value.absent(),
            Value<String> itemId = const Value.absent(),
            Value<String> role = const Value.absent(),
            Value<int> createdAt = const Value.absent(),
            Value<int> rowid = const Value.absent(),
          }) =>
              ItemPhotoExtrasCompanion(
            id: id,
            photoId: photoId,
            itemId: itemId,
            role: role,
            createdAt: createdAt,
            rowid: rowid,
          ),
          createCompanionCallback: ({
            required String id,
            required String photoId,
            required String itemId,
            Value<String> role = const Value.absent(),
            required int createdAt,
            Value<int> rowid = const Value.absent(),
          }) =>
              ItemPhotoExtrasCompanion.insert(
            id: id,
            photoId: photoId,
            itemId: itemId,
            role: role,
            createdAt: createdAt,
            rowid: rowid,
          ),
          withReferenceMapper: (p0) => p0
              .map((e) => (
                    e.readTable(table),
                    $$ItemPhotoExtrasTableReferences(db, table, e)
                  ))
              .toList(),
          prefetchHooksCallback: ({photoId = false, itemId = false}) {
            return PrefetchHooks(
              db: db,
              explicitlyWatchedTables: [],
              addJoins: <
                  T extends TableManagerState<
                      dynamic,
                      dynamic,
                      dynamic,
                      dynamic,
                      dynamic,
                      dynamic,
                      dynamic,
                      dynamic,
                      dynamic,
                      dynamic,
                      dynamic>>(state) {
                if (photoId) {
                  state = state.withJoin(
                    currentTable: table,
                    currentColumn: table.photoId,
                    referencedTable:
                        $$ItemPhotoExtrasTableReferences._photoIdTable(db),
                    referencedColumn:
                        $$ItemPhotoExtrasTableReferences._photoIdTable(db).id,
                  ) as T;
                }
                if (itemId) {
                  state = state.withJoin(
                    currentTable: table,
                    currentColumn: table.itemId,
                    referencedTable:
                        $$ItemPhotoExtrasTableReferences._itemIdTable(db),
                    referencedColumn:
                        $$ItemPhotoExtrasTableReferences._itemIdTable(db).id,
                  ) as T;
                }

                return state;
              },
              getPrefetchedDataCallback: (items) async {
                return [];
              },
            );
          },
        ));
}

typedef $$ItemPhotoExtrasTableProcessedTableManager = ProcessedTableManager<
    _$AppDatabase,
    $ItemPhotoExtrasTable,
    ItemPhotoExtra,
    $$ItemPhotoExtrasTableFilterComposer,
    $$ItemPhotoExtrasTableOrderingComposer,
    $$ItemPhotoExtrasTableAnnotationComposer,
    $$ItemPhotoExtrasTableCreateCompanionBuilder,
    $$ItemPhotoExtrasTableUpdateCompanionBuilder,
    (ItemPhotoExtra, $$ItemPhotoExtrasTableReferences),
    ItemPhotoExtra,
    PrefetchHooks Function({bool photoId, bool itemId})>;
typedef $$AppSettingsTableCreateCompanionBuilder = AppSettingsCompanion
    Function({
  required String key,
  required String value,
  required int updatedAt,
  Value<int> rowid,
});
typedef $$AppSettingsTableUpdateCompanionBuilder = AppSettingsCompanion
    Function({
  Value<String> key,
  Value<String> value,
  Value<int> updatedAt,
  Value<int> rowid,
});

class $$AppSettingsTableFilterComposer
    extends Composer<_$AppDatabase, $AppSettingsTable> {
  $$AppSettingsTableFilterComposer({
    required super.$db,
    required super.$table,
    super.joinBuilder,
    super.$addJoinBuilderToRootComposer,
    super.$removeJoinBuilderFromRootComposer,
  });
  ColumnFilters<String> get key => $composableBuilder(
      column: $table.key, builder: (column) => ColumnFilters(column));

  ColumnFilters<String> get value => $composableBuilder(
      column: $table.value, builder: (column) => ColumnFilters(column));

  ColumnFilters<int> get updatedAt => $composableBuilder(
      column: $table.updatedAt, builder: (column) => ColumnFilters(column));
}

class $$AppSettingsTableOrderingComposer
    extends Composer<_$AppDatabase, $AppSettingsTable> {
  $$AppSettingsTableOrderingComposer({
    required super.$db,
    required super.$table,
    super.joinBuilder,
    super.$addJoinBuilderToRootComposer,
    super.$removeJoinBuilderFromRootComposer,
  });
  ColumnOrderings<String> get key => $composableBuilder(
      column: $table.key, builder: (column) => ColumnOrderings(column));

  ColumnOrderings<String> get value => $composableBuilder(
      column: $table.value, builder: (column) => ColumnOrderings(column));

  ColumnOrderings<int> get updatedAt => $composableBuilder(
      column: $table.updatedAt, builder: (column) => ColumnOrderings(column));
}

class $$AppSettingsTableAnnotationComposer
    extends Composer<_$AppDatabase, $AppSettingsTable> {
  $$AppSettingsTableAnnotationComposer({
    required super.$db,
    required super.$table,
    super.joinBuilder,
    super.$addJoinBuilderToRootComposer,
    super.$removeJoinBuilderFromRootComposer,
  });
  GeneratedColumn<String> get key =>
      $composableBuilder(column: $table.key, builder: (column) => column);

  GeneratedColumn<String> get value =>
      $composableBuilder(column: $table.value, builder: (column) => column);

  GeneratedColumn<int> get updatedAt =>
      $composableBuilder(column: $table.updatedAt, builder: (column) => column);
}

class $$AppSettingsTableTableManager extends RootTableManager<
    _$AppDatabase,
    $AppSettingsTable,
    AppSetting,
    $$AppSettingsTableFilterComposer,
    $$AppSettingsTableOrderingComposer,
    $$AppSettingsTableAnnotationComposer,
    $$AppSettingsTableCreateCompanionBuilder,
    $$AppSettingsTableUpdateCompanionBuilder,
    (AppSetting, BaseReferences<_$AppDatabase, $AppSettingsTable, AppSetting>),
    AppSetting,
    PrefetchHooks Function()> {
  $$AppSettingsTableTableManager(_$AppDatabase db, $AppSettingsTable table)
      : super(TableManagerState(
          db: db,
          table: table,
          createFilteringComposer: () =>
              $$AppSettingsTableFilterComposer($db: db, $table: table),
          createOrderingComposer: () =>
              $$AppSettingsTableOrderingComposer($db: db, $table: table),
          createComputedFieldComposer: () =>
              $$AppSettingsTableAnnotationComposer($db: db, $table: table),
          updateCompanionCallback: ({
            Value<String> key = const Value.absent(),
            Value<String> value = const Value.absent(),
            Value<int> updatedAt = const Value.absent(),
            Value<int> rowid = const Value.absent(),
          }) =>
              AppSettingsCompanion(
            key: key,
            value: value,
            updatedAt: updatedAt,
            rowid: rowid,
          ),
          createCompanionCallback: ({
            required String key,
            required String value,
            required int updatedAt,
            Value<int> rowid = const Value.absent(),
          }) =>
              AppSettingsCompanion.insert(
            key: key,
            value: value,
            updatedAt: updatedAt,
            rowid: rowid,
          ),
          withReferenceMapper: (p0) => p0
              .map((e) => (e.readTable(table), BaseReferences(db, table, e)))
              .toList(),
          prefetchHooksCallback: null,
        ));
}

typedef $$AppSettingsTableProcessedTableManager = ProcessedTableManager<
    _$AppDatabase,
    $AppSettingsTable,
    AppSetting,
    $$AppSettingsTableFilterComposer,
    $$AppSettingsTableOrderingComposer,
    $$AppSettingsTableAnnotationComposer,
    $$AppSettingsTableCreateCompanionBuilder,
    $$AppSettingsTableUpdateCompanionBuilder,
    (AppSetting, BaseReferences<_$AppDatabase, $AppSettingsTable, AppSetting>),
    AppSetting,
    PrefetchHooks Function()>;

class $AppDatabaseManager {
  final _$AppDatabase _db;
  $AppDatabaseManager(this._db);
  $$ProjectsTableTableManager get projects =>
      $$ProjectsTableTableManager(_db, _db.projects);
  $$ItemsTableTableManager get items =>
      $$ItemsTableTableManager(_db, _db.items);
  $$CaptureSessionsTableTableManager get captureSessions =>
      $$CaptureSessionsTableTableManager(_db, _db.captureSessions);
  $$PhotoGroupsTableTableManager get photoGroups =>
      $$PhotoGroupsTableTableManager(_db, _db.photoGroups);
  $$PhotosTableTableManager get photos =>
      $$PhotosTableTableManager(_db, _db.photos);
  $$OcrTokensTableTableManager get ocrTokens =>
      $$OcrTokensTableTableManager(_db, _db.ocrTokens);
  $$AssignmentsTableTableManager get assignments =>
      $$AssignmentsTableTableManager(_db, _db.assignments);
  $$DeliveriesTableTableManager get deliveries =>
      $$DeliveriesTableTableManager(_db, _db.deliveries);
  $$UploadTasksTableTableManager get uploadTasks =>
      $$UploadTasksTableTableManager(_db, _db.uploadTasks);
  $$ItemPhotoExtrasTableTableManager get itemPhotoExtras =>
      $$ItemPhotoExtrasTableTableManager(_db, _db.itemPhotoExtras);
  $$AppSettingsTableTableManager get appSettings =>
      $$AppSettingsTableTableManager(_db, _db.appSettings);
}
