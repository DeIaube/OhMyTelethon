from pathlib import Path


RUNTIME_PATH_FIELDS = (
    ('session_path', lambda config: config.session_path),
    ('state_path', lambda config: config.state_path),
    ('audit_log_path', lambda config: config.audit_log_path),
    ('daemon.queue_path', lambda config: config.daemon.get('queue_path')),
    ('daemon.lock_path', lambda config: config.daemon.get('lock_path')),
    ('daemon.status_path', lambda config: config.daemon.get('status_path')),
    ('quota.state_path', lambda config: config.quota.get('state_path')),
    ('memory.path', lambda config: config.memory.get('path')),
    ('bad_cases.path', lambda config: config.bad_cases.get('path')),
)


def _path_text(value):
    if value in (None, ''):
        return ''
    return str(Path(value).expanduser().resolve())


def inspect_config(config):
    runtime_paths = {}
    for field_name, getter in RUNTIME_PATH_FIELDS:
        path = _path_text(getter(config))
        if path:
            runtime_paths[field_name] = path
    return {
        'account_name': getattr(config, 'account_name', '') or '',
        'config_path': str(getattr(config, 'config_path', '') or ''),
        'allowed_chats': list(getattr(config, 'allowed_chats', ()) or ()),
        'runtime_paths': runtime_paths,
    }


def _finding(severity, code, message, configs=None, path=None):
    payload = {
        'severity': severity,
        'code': code,
        'message': message,
    }
    if configs is not None:
        payload['configs'] = list(configs)
    if path is not None:
        payload['path'] = path
    return payload


def doctor_configs(primary_config, other_configs):
    inspections = [
        inspect_config(primary_config),
    ] + [inspect_config(config) for config in other_configs]
    findings = []

    names = {}
    for item in inspections:
        name = item.get('account_name') or ''
        label = item.get('config_path') or name or '<in-memory>'
        if not name:
            findings.append(_finding(
                'warning', 'missing_account_name',
                'Config {} has no account_name.'.format(label),
                configs=[label]))
            continue
        names.setdefault(name, []).append(label)
    for name, labels in sorted(names.items()):
        if len(labels) > 1:
            findings.append(_finding(
                'error', 'duplicate_account_name',
                'Duplicate account_name "{}" appears in {} configs.'.format(
                    name, len(labels)),
                configs=labels))

    paths = {}
    for index, item in enumerate(inspections):
        label = (
            item.get('config_path') or item.get('account_name') or '<in-memory>')
        for field_name, path in sorted(item.get('runtime_paths', {}).items()):
            paths.setdefault(path, []).append((index, label, field_name))

    for path, owners in sorted(paths.items()):
        owner_indexes = {index for index, _label, _field in owners}
        if len(owner_indexes) < 2:
            continue
        labels = sorted({label for _index, label, _field in owners})
        fields = sorted({field for _index, _label, field in owners})
        findings.append(_finding(
            'error', 'shared_runtime_path',
            'Runtime path is shared by multiple configs: {} -> {}.'.format(
                path, ', '.join(fields)),
            configs=labels,
            path=path))

    return {
        'ok': not any(finding['severity'] == 'error' for finding in findings),
        'configs': inspections,
        'findings': findings,
    }
