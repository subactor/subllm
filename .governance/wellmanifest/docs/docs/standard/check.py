#!/usr/bin/env python3
"""Read-only placement and structure checks; not semantic or authority approval."""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import importlib.util
import json
import re
import subprocess
from pathlib import Path
from posixpath import relpath
from urllib.parse import unquote, urlsplit

PACK = Path(__file__).resolve().parent
CONTRACT_SPEC = importlib.util.spec_from_file_location('docs_change_contract', PACK / 'change_contract.py')
CONTRACT = importlib.util.module_from_spec(CONTRACT_SPEC)
CONTRACT_SPEC.loader.exec_module(CONTRACT)
POLICY_BYTES = (PACK / 'policy.json').read_bytes()
POLICY = json.loads(POLICY_BYTES)
POLICY_SHA256 = hashlib.sha256(POLICY_BYTES).hexdigest()
SHA = re.compile(r'^[0-9a-f]{40}$')
REPO = re.compile(r'^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$')
MARKER = re.compile(r'<!-- docs:section ([a-z_]+) -->')
PLACEHOLDER = re.compile(r'\{\{\s*[A-Za-z_][A-Za-z0-9_]*\s*\}\}')


def origin(root):
    if not Path(root).is_dir():
        return None
    result = subprocess.run(['git', 'remote', 'get-url', 'origin'], cwd=root,
                            capture_output=True, text=True, check=False)
    match = re.fullmatch(r'(?:https://github\.com/|git@github\.com:|ssh://git@github\.com/)([\w.-]+/[\w.-]+?)(?:\.git)?', result.stdout.strip(), re.I)
    return match.group(1) if result.returncode == 0 and match else None


def tracked(root):
    if not Path(root).is_dir():
        raise ValueError('DOCS_GIT_REQUIRED')
    result = subprocess.run(['git', 'ls-files', '-z'], cwd=root, capture_output=True, check=False)
    if result.returncode:
        raise ValueError('DOCS_GIT_REQUIRED')
    return set(result.stdout.decode().split('\0')) - {''}


def layout(repository, kind, slug, compact=False):
    profile = POLICY['profile']
    override = profile['repository_overrides'].get(repository, {})
    root = override.get('docs_root', profile['docs_root'])
    directory = (POLICY['compact']['directories'][kind] if compact
                 else POLICY['kinds'][kind]['directory'])
    if compact:
        slug = slug.replace('-', '_').upper()
    return Path(root) / override.get('prefix', '') / directory / (slug + '.md'), override.get('index', profile['index'])


def metadata(text):
    match = re.match(r'\A---\r?\n(.*?)\r?\n---(?:\r?\n|$)', text, re.S)
    if not match:
        raise ValueError('DOCS_METADATA_REQUIRED')
    value = json.loads(match.group(1))
    if not isinstance(value, dict):
        raise ValueError('DOCS_METADATA_OBJECT_REQUIRED')
    return value, text[match.end():]


def valid_value(kind, value):
    if kind == 'positive_integer':
        return type(value) is int and value > 0
    if kind in {'repositories', 'references'}:
        if not isinstance(value, list) or not value or len(value) > 128:
            return False
        if not all(isinstance(v, str) and v.strip() == v and v for v in value):
            return False
        if len(set(value)) != len(value):
            return False
        if kind == 'repositories':
            return all(REPO.fullmatch(v) for v in value)
        return all(v.startswith(('repo://', 'github://', 'https://', 'receipt:', 'artifact://', 'knowledge://'))
                   and not re.search(r'://[^/]*@|[?&](token|key|password)=', v, re.I) for v in value)
    if not isinstance(value, str) or value.strip() != value or not value:
        return False
    if kind == 'slug':
        return bool(re.fullmatch(r'[a-z0-9]+(?:-[a-z0-9]+)*', value))
    if kind == 'sha40':
        return bool(SHA.fullmatch(value))
    if kind == 'kind':
        return value in POLICY['kinds']
    if kind == 'compact_kind':
        return value in POLICY['compact']['directories']
    if kind == 'priority':
        return value in POLICY['compact']['priorities']
    if kind == 'scope':
        return value in POLICY['delivery_scopes']
    if kind == 'status':
        return value in POLICY['statuses']
    if kind == 'date':
        try:
            return dt.date.fromisoformat(value).isoformat() == value
        except ValueError:
            return False
    return kind == 'string'


def safe_path(root, path):
    path = Path(path)
    candidate = path if path.is_absolute() else root / path
    try:
        relative = candidate.relative_to(root)
        if '..' in relative.parts:
            return None
        current = root
        for part in relative.parts:
            current /= part
            if current.is_symlink():
                return None
        candidate.resolve().relative_to(root)
    except ValueError:
        return None
    return relative


def report_home(repository, scope):
    """Resolve ownership only; this never creates a repository or grants writes."""
    if not isinstance(repository, str) or not REPO.fullmatch(repository):
        raise ValueError('DOCS_REPOSITORY_REQUIRED')
    if scope not in POLICY['delivery_scopes']:
        raise ValueError('DOCS_SCOPE_REQUIRED')
    if scope == 'organization':
        return repository.split('/')[0] + '/' + POLICY['profile']['organization_report_repository']
    return repository


def prepare_delivery(root, revision, kind, slug, scope, destination, compact=False, policy_dsl_root=None, managed_copies=None):
    """Fail closed before generation; consumers must require ok before writing."""
    root = Path(root).resolve()
    repository = origin(root)
    if not SHA.fullmatch(revision):
        raise ValueError('Trusted standard revision must be a full immutable SHA')
    findings = []
    def fail(code, message):
        findings.append({'code': code, 'message': message})
    try:
        owner = report_home(repository, scope)
    except ValueError as error:
        return {'ok': False, 'findings': [{'code': str(error)}]}
    if repository != owner:
        fail('DOCS_OWNER', 'Open the owning repository first: ' + owner)
    kinds = POLICY['compact']['directories'] if compact else POLICY['kinds']
    if kind not in kinds or not valid_value('slug', slug) or (compact and not slug[0].isalpha()):
        fail('DOCS_METADATA', 'A known kind and stable slug are required')
        return {'ok': False, 'repository': repository, 'owner': owner, 'findings': findings}
    expected_path, index = layout(owner, kind, slug, compact)
    relative = safe_path(root, destination)
    if relative != expected_path or safe_path(root, expected_path) is None:
        fail('DOCS_LOCATION', 'Expected repository-relative destination: ' + expected_path.as_posix())
    # Reuse adoption, tracked index and existing document validation. Do not
    # declare the not-yet-generated document, which is intentionally absent.
    existing = check(root, revision, policy_dsl_root=policy_dsl_root, managed_copies=managed_copies)
    findings.extend(existing['findings'])
    plan = {'schema': 'wellmanifest.docs/delivery-plan/v1', 'repository': repository,
            'owner': owner, 'scope': scope, 'kind': kind, 'id': slug,
            'path': expected_path.as_posix(), 'index': index,
            'standard_revision': revision, 'policy_sha256': POLICY_SHA256,
            'authority': 'read-only-placement-evidence'}
    if managed_copies:
        plan["managed_copies"] = managed_copies
    if compact:
        plan['document_schema'] = POLICY['compact']['document_schema']
    return {'ok': not findings, 'plan': plan, 'findings': findings,
            'plan_sha256': hashlib.sha256(json.dumps(plan, sort_keys=True).encode()).hexdigest()}


def document_schemas():
    return (POLICY['document_schema'], POLICY['compact']['document_schema'], POLICY['redirect_schema'])


def check_redirect(root, repository, name, meta, body, files, base, fail):
    """A legacy path is a bounded link map, never a second canonical document."""
    fields = {'schema', 'owner', 'version', 'updated', 'targets'}
    if (set(meta) != fields or meta.get('owner') != repository
            or not valid_value('positive_integer', meta.get('version'))
            or not valid_value('date', meta.get('updated'))
            or not isinstance(meta.get('targets'), list) or not meta['targets']
            or len(meta['targets']) > 16
            or any(not isinstance(t, str) for t in meta['targets'])
            or len(set(meta['targets'])) != len(meta['targets'])):
        fail('DOCS_REDIRECT', name, 'Expected owner, version, updated and unique target paths')
        return
    if base:
        old = subprocess.run(['git', 'cat-file', '-e', base + ':' + name],
                             cwd=root, capture_output=True, check=False)
        if old.returncode:
            fail('DOCS_REDIRECT_BASE', name, 'Only a path present in the trusted base may become a link map')
    if len(body.splitlines()) > 120 or len(body.encode('utf-8')) > 12288:
        fail('DOCS_SIZE', name, 'Legacy maps must stay below 120 body lines and 12 KiB')
    targets = set()
    for target in meta['targets']:
        relative = safe_path(root, target)
        if (relative is None or Path(target).is_absolute() or target not in files
                or not (root / relative).is_file()):
            fail('DOCS_REDIRECT_TARGET', name, 'Missing, untracked or unsafe target: ' + target)
            continue
        try:
            target_meta, _ = metadata((root / relative).read_text())
            compact = target_meta.get('schema') == POLICY['compact']['document_schema']
            kinds = POLICY['compact']['directories'] if compact else POLICY['kinds']
            if (target_meta.get('schema') not in document_schemas()[:2]
                    or not valid_value('slug', target_meta.get('id'))
                    or not isinstance(target_meta.get('kind'), str)
                    or target_meta['kind'] not in kinds):
                raise ValueError('not canonical')
            expected, _ = layout(repository, target_meta['kind'], target_meta['id'], compact)
            if expected != relative:
                raise ValueError('wrong path')
        except (OSError, ValueError):
            fail('DOCS_REDIRECT_TARGET', name, 'Target must be canonical v1/v2, never another redirect: ' + target)
            continue
        targets.add(relative)
    linked = set()
    for line in body.splitlines():
        if not line.strip() or re.fullmatch(r'#{1,6} .+', line):
            continue
        match = re.fullmatch(r'(?:- )?\[[^\]\n]+\]\(([^)]+)\)', line)
        if not match:
            fail('DOCS_REDIRECT_BODY', name, 'Only headings and whole-file links are allowed')
            continue
        try:
            destination = urlsplit(match.group(1))
        except ValueError:
            fail('DOCS_REDIRECT_BODY', name, 'Malformed destination')
            continue
        if destination.scheme or destination.netloc or destination.query or destination.fragment:
            fail('DOCS_REDIRECT_BODY', name, 'Link directly to a listed canonical file')
            continue
        links = {relpath(t.as_posix(), Path(name).parent.as_posix()): t for t in targets}
        relative = links.get(unquote(destination.path))
        if relative is None:
            fail('DOCS_REDIRECT_BODY', name, 'Link is not a listed canonical target')
        else:
            linked.add(relative)
    if linked != targets:
        fail('DOCS_REDIRECT_BODY', name, 'Every target must be linked in the map')


def check_changelog(root, files, fail):
    """Check local Markdown destinations; never fetch external links."""
    name = POLICY['compact']['changelog']
    if name not in files:
        return
    if safe_path(root, name) is None or not (root / name).is_file():
        fail('DOCS_CHANGELOG_LINK', name, 'Changelog must be a regular tracked file')
        return
    text = (root / name).read_text()
    # Ignore fenced examples; support inline links and reference definitions.
    text = re.sub(r'(?ms)^ *(`{3,}|~{3,})[^\n]*\n.*?^ *\1 *$', '', text)
    destinations = re.findall(r'\]\(<?([^\s)>]+)>?(?:\s+"[^"]*")?\)', text)
    destinations += re.findall(r'^\s*\[[^]]+\]:\s*<?([^\s>]+)>?', text, re.M)
    for destination in destinations:
        try:
            link = urlsplit(destination)
        except ValueError:
            fail('DOCS_CHANGELOG_LINK', name, 'Malformed destination: ' + destination)
            continue
        if link.scheme or link.netloc or not link.path:
            continue
        path = unquote(link.path)
        if not path.lower().endswith('.md'):
            continue
        relative = safe_path(root, path)
        if (relative is None or relative.as_posix() not in files
                or not (root / relative).is_file()):
            fail('DOCS_CHANGELOG_LINK', name, 'Missing, untracked or unsafe target: ' + destination)
            continue
        # Heading rendering is host-specific. Verify the file only; authors
        # should link whole documents to avoid fragile heading fragments.


def check(root, revision, deliverables=(), today=None, base=None, policy_dsl_root=None, managed_copies=None):
    root = Path(root).resolve()
    findings, warnings = [], []
    def fail(code, path, message):
        findings.append({'code': code, 'path': str(path), 'message': message})
    if not SHA.fullmatch(revision):
        raise ValueError('Trusted standard revision must be a full immutable SHA')
    repository = origin(root)
    try:
        files = tracked(root)
    except ValueError as error:
        return {'ok': False, 'repository': repository, 'findings': [{'code': str(error)}], 'warnings': []}
    config_path = '.governance/docs.json'
    if safe_path(root, config_path) is None:
        fail('DOCS_ADOPTION', config_path, 'Adoption path must not use symlinks')
        config = {}
    else:
        try:
            config = json.loads((root / config_path).read_text())
        except (OSError, ValueError):
            config = {}
    expected = {'schema': POLICY['adoption_schema'], 'repository': repository,
                'standard': POLICY['id'], 'source_revision': revision, 'policy_sha256': POLICY_SHA256}
    if not repository or config != expected or config_path not in files:
        fail('DOCS_ADOPTION', config_path, 'Missing or divergent tracked adoption; pin the trusted revision and policy digest')
    index = layout(repository, "information", "placeholder")[1]
    if safe_path(root, index) is None or index not in files or not (root / index).is_file():
        fail("DOCS_INDEX", index, "Tracked documentation index required for every adopter")
    if base and not SHA.fullmatch(base):
        raise ValueError("Base must be a full commit SHA")
    if base:
        resolved = subprocess.run(['git', 'cat-file', '-t', base], cwd=root, capture_output=True, text=True, check=False)
        if resolved.returncode or resolved.stdout.strip() != 'commit':
            fail('DOCS_BASE', base, 'Trusted base commit must be available locally')
    selected = set()
    for declared in deliverables:
        relative = safe_path(root, declared)
        if relative is None:
            fail('DOCS_LOCATION', declared, 'Deliverable must remain inside its owning repository without symlinks')
        else:
            selected.add(relative.as_posix())
    if base and not any(item['code'] == 'DOCS_BASE' for item in findings):
        changes = subprocess.run(
            ['git', 'diff', '--no-renames', '--name-only', '-z', base, '--'],
            cwd=root, capture_output=True, check=False)
        if changes.returncode:
            fail('DOCS_BASE', base, 'Cannot enumerate changes against the trusted base')
        else:
            discovery = POLICY['discovery']
            for name in set(changes.stdout.decode().split('\0')) & files:
                if not name.lower().endswith('.md'):
                    continue
                old = subprocess.run(['git', 'show', base + ':' + name], cwd=root,
                                     capture_output=True, text=True, check=False)
                try:
                    previous, _ = metadata(old.stdout)
                    was_managed = previous.get('schema') in document_schemas()
                except ValueError:
                    was_managed = False
                organizational = (
                    Path(name).name in discovery['organizational_names']
                    or name in discovery['organizational_paths']
                    or any(name.startswith(prefix) for prefix in discovery['organizational_prefixes'])
                    or re.fullmatch(discovery['ticket_pattern'], name) is not None)
                if was_managed or not organizational:
                    selected.add(name)
    for name in files:
        if not name.lower().endswith('.md') or safe_path(root, name) is None:
            continue
        path = root / name
        if path.is_file() and path.read_text(errors='replace').startswith('---') and any(
                schema in path.read_text(errors='replace')[:8192] for schema in document_schemas()):
            selected.add(name)
    verified_copies = []
    if managed_copies is not None and not isinstance(managed_copies, dict):
        fail('DOCS_MANAGED_COPY', '', 'Trusted managed-copy inventory must be a path-to-SHA256 object')
    else:
        for name, digest in (managed_copies or {}).items():
            relative = safe_path(root, name) if isinstance(name, str) else None
            if (relative is None or not name.startswith('.governance/docs/')
                    or not name.endswith('.md') or name in deliverables
                    or name not in files or not isinstance(digest, str)
                    or re.fullmatch('[0-9a-f]{64}', digest) is None):
                fail('DOCS_MANAGED_COPY', name, 'Only tracked external standard documentation may be excluded; never a deliverable')
                continue
            try:
                actual = hashlib.sha256((root / relative).read_bytes()).hexdigest()
            except OSError:
                actual = None
            if actual != digest:
                fail('DOCS_MANAGED_COPY', name, 'Actual bytes differ from independently trusted standard-copy digest')
                continue
            selected.discard(name)
            verified_copies.append({'path': name, 'sha256': digest})
    ids = set()
    for name in sorted(selected):
        if safe_path(root, name) is None:
            fail('DOCS_LOCATION', name, 'Symlink or escaped path')
            continue
        if name not in files:
            fail('DOCS_UNTRACKED', name, 'Stage the documentation in Git before completing delivery')
        try:
            text = (root / name).read_text()
            meta, body = metadata(text)
        except (OSError, ValueError) as error:
            fail('DOCS_METADATA', name, type(error).__name__)
            continue
        if PLACEHOLDER.search(text):
            fail('DOCS_PLACEHOLDER', name, 'Replace template placeholders with actual findings or a reasoned not-applicable statement')
        if base:
            old = subprocess.run(['git', 'show', base + ':' + name], cwd=root,
                                 capture_output=True, text=True, check=False)
            if old.returncode == 0 and old.stdout != text:
                try:
                    previous, _ = metadata(old.stdout)
                    if previous.get('schema') in document_schemas() and type(meta.get('version')) is int and type(previous.get('version')) is int and meta['version'] <= previous['version']:
                        fail('DOCS_VERSION', name, 'Changed document must increase its declared version')
                except ValueError:
                    pass
        compact = meta.get('schema') == POLICY['compact']['document_schema']
        fields = POLICY['compact']['metadata'] if compact else POLICY['metadata']
        if meta.get('schema') == POLICY['redirect_schema']:
            check_redirect(root, repository, name, meta, body, files, base, fail)
            continue
        optional = {} if compact else POLICY.get('optional_metadata', {})
        if (not set(fields) <= set(meta) or not set(meta) <= set(fields) | set(optional)
                or any(not valid_value(t, meta.get(k)) for k, t in fields.items())
                or any(not valid_value(optional[k], meta[k]) for k in set(meta) & set(optional))
                or meta.get('schema') not in document_schemas()):
            fail('DOCS_METADATA', name, 'Metadata fields, types or values violate the declared document schema')
            continue
        if meta['id'] in ids:
            fail('DOCS_DUPLICATE_ID', name, 'One canonical owner and one document for this id')
        if compact:
            try:
                CONTRACT.check(body, meta, root, files, safe_path, policy_dsl_root)
            except CONTRACT.ContractError as error:
                fail(error.code, name, str(error))
        ids.add(meta['id'])
        expected_path, index = layout(repository, meta['kind'], meta['id'], compact)
        if compact:
            limits = POLICY['compact']['limits']
            if not re.fullmatch(POLICY['compact']['filename_pattern'], Path(name).stem):
                fail('DOCS_FILENAME', name, 'Use UPPER_SNAKE_CASE.md with a descriptive stable name')
            if (len(text.splitlines()) > limits['max_lines']
                    or len(text.split()) > limits['max_words']
                    or len(text.encode('utf-8')) > limits['max_bytes']):
                fail('DOCS_SIZE', name, 'Split by topic; limits include metadata, code and tables: ' + str(limits))
        if Path(name) != expected_path:
            fail('DOCS_LOCATION', name, 'Expected ' + expected_path.as_posix())
        scope = meta.get('scope')
        if scope is not None:
            if not repository or meta['owner'] != repository or report_home(repository, scope) != repository:
                fail('DOCS_OWNER', name, 'Explicit delivery owner must match its repository; organization scope requires org/report')
        elif meta['affected_repositories'] != [repository] and repository != POLICY['profile']['cross_repository_home']:
            fail('DOCS_OWNER', name, 'Cross-repository deliverables belong to subactor/docs; reference dependencies in scope instead')
        # Preserve historical metadata during audits. New or changed results
        # must state scope explicitly; deleting scope cannot restore an exemption.
        if scope is None and base:
            previous_text = subprocess.run(['git', 'show', base + ':' + name], cwd=root,
                                           capture_output=True, text=True, check=False)
            if previous_text.returncode or previous_text.stdout != text:
                fail('DOCS_SCOPE', name, 'New or changed deliverables require explicit repository or organization scope')
        if not compact and not meta['created'] <= meta['updated'] <= meta['review_after']:
            fail('DOCS_DATES', name, 'Expected created <= updated <= review_after')
        if not compact and dt.date.fromisoformat(meta['review_after']) < (today or dt.date.today()):
            warnings.append({'code': 'DOCS_REVIEW_DUE', 'path': name})
        matches = list(MARKER.finditer(body))
        sections = [m.group(1) for m in matches]
        required = POLICY['compact']['sections'] if compact else POLICY['kinds'][meta['kind']]['sections']
        if (len(sections) != len(set(sections)) or any(s not in sections for s in required)
                or (compact and set(sections) != set(required))):
            fail('DOCS_SECTIONS', name, 'Required section markers must each occur once')
        for i, match in enumerate(matches):
            content = body[match.end():matches[i+1].start() if i+1 < len(matches) else len(body)]
            content = re.sub(r'^\s*#+[^\n]*$', '', content, flags=re.M).strip()
            if not content:
                fail('DOCS_EMPTY_SECTION', name, match.group(1))
        if safe_path(root, index) is None or index not in files or not (root / index).is_file():
            fail('DOCS_INDEX', index, 'Tracked documentation index required')
        else:
            index_text = (root / index).read_text()
            relative_link = expected_path.relative_to(Path(index).parent).as_posix()
            if not re.search(r'\]\(' + re.escape(relative_link) + r'(?:#[^)]*)?\)', index_text):
                fail('DOCS_INDEX', name, 'Link the canonical document from ' + index)
    check_changelog(root, files, fail)
    return {'ok': not findings, 'repository': repository, 'documents_checked': len(selected),
            'scope': POLICY['adoption_scope'], 'managed_copies_verified': verified_copies, 'findings': findings, 'warnings': warnings}


def complete_delivery(root, revision, deliverables, base, prepared, policy_dsl_root=None, managed_copies=None):
    """Bind an explicit result to its pre-generation plan and actual bytes."""
    root = Path(root).resolve()
    result = check(root, revision, deliverables, base=base, policy_dsl_root=policy_dsl_root, managed_copies=managed_copies)
    findings = result['findings']
    def fail(message):
        findings.append({'code': 'DOCS_COMPLETION', 'path': '', 'message': message})
    if not base or len(deliverables) != 1:
        fail('Completion requires a trusted base and exactly one explicit deliverable per plan')
    if not isinstance(prepared, dict) or prepared.get('ok') is not True or not isinstance(prepared.get('plan'), dict):
        fail('A successful pre-generation delivery-plan receipt is required')
    else:
        plan = prepared['plan']
        digest = hashlib.sha256(json.dumps(plan, sort_keys=True).encode()).hexdigest()
        if prepared.get('plan_sha256') != digest:
            fail('Preparation plan digest mismatch')
        try:
            fresh = prepare_delivery(root, revision, plan['kind'], plan['id'], plan['scope'],
                                     plan['path'], plan.get('document_schema') == POLICY['compact']['document_schema'],
                                     policy_dsl_root, managed_copies)
            if not fresh['ok'] or fresh['plan'] != plan:
                fail('Preparation plan no longer matches repository, policy or placement')
            if len(deliverables) != 1 or safe_path(root, deliverables[0]) != Path(plan['path']):
                fail('Explicit deliverable differs from the preparation plan')
            elif safe_path(root, plan['path']) is not None:
                meta, _ = metadata((root / plan['path']).read_text())
                if any(meta.get(k) != plan[k] for k in ('id', 'kind', 'scope', 'owner')):
                    fail('Document identity or scope differs from the preparation plan')
        except (KeyError, OSError, ValueError, TypeError):
            fail('Malformed preparation plan or unavailable deliverable')
    result['ok'] = not findings
    result['completion'] = {'ready': not findings, 'publication_verified': False, 'authority': 'none',
                            'artifacts': []}
    if not findings:
        for name in (plan['path'], plan['index']):
            result['completion']['artifacts'].append({'path': name,
                'sha256': hashlib.sha256((root / name).read_bytes()).hexdigest()})
    return result


def check_fleet(roots, revision, namespaces=None, policy_dsl_root=None):
    """Audit every selected checkout, including divergent copies; never fetch."""
    if not SHA.fullmatch(revision):
        raise ValueError('Trusted standard revision must be a full immutable SHA')
    namespaces = namespaces if namespaces is not None else [POLICY['profile']['required_namespace'].rstrip('/')]
    if (not namespaces or any(not isinstance(n, str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9-]*', n)
                              for n in namespaces)):
        raise ValueError('Namespaces must be explicit GitHub owner names, without slashes or wildcards')
    namespaces = sorted({n.lower() for n in namespaces})
    reports, skipped, findings = [], [], []
    seen, identities = set(), {}
    counts = dict.fromkeys(namespaces, 0)
    for supplied in roots:
        root = Path(supplied).absolute()
        if any(p.is_symlink() for p in (root, *root.parents)) or not root.is_dir():
            findings.append({'code': 'DOCS_FLEET_ROOT', 'path': str(root)})
            continue
        try:
            children = sorted(root.iterdir())
        except OSError:
            findings.append({'code': 'DOCS_FLEET_ROOT', 'path': str(root)})
            continue
        for path in children:
            reason = None
            if path.is_symlink():
                reason = 'symlink'
            elif not path.is_dir() or not (path / '.git').exists():
                reason = 'not-immediate-checkout'
            elif path.resolve() in seen:
                reason = 'repeated-path'
            if reason:
                skipped.append({'path': str(path), 'reason': reason})
                continue
            seen.add(path.resolve())
            repository = origin(path)
            if not repository:
                skipped.append({'path': str(path), 'reason': 'unresolved-github-origin'})
                findings.append({'code': 'DOCS_FLEET_ORIGIN', 'path': str(path)})
                continue
            namespace = repository.split('/')[0].lower()
            if namespace not in counts:
                skipped.append({'path': str(path), 'repository': repository, 'reason': 'namespace-not-selected'})
                continue
            counts[namespace] += 1
            identities.setdefault(repository.lower(), []).append(str(path))
            try:
                report = check(path, revision, policy_dsl_root=policy_dsl_root)
            except (OSError, ValueError, UnicodeError):
                report = {'ok': False, 'repository': repository,
                          'findings': [{'code': 'DOCS_CHECKOUT_READ'}], 'warnings': []}
            head = subprocess.run(['git', 'rev-parse', '--verify', 'HEAD^{commit}'],
                                  cwd=path, capture_output=True, text=True, check=False)
            status = subprocess.run(['git', '--no-optional-locks', 'status', '--porcelain', '--untracked-files=normal'],
                                    cwd=path, capture_output=True, text=True, check=False)
            head_sha = head.stdout.strip() if head.returncode == 0 else None
            if head_sha is None or status.returncode:
                findings.append({'code': 'DOCS_FLEET_OBSERVATION', 'path': str(path)})
            reports.append(dict(report, checkout=str(path), head_sha=head_sha,
                                working_tree_dirty=bool(status.stdout) if status.returncode == 0 else None))
    for namespace, count in counts.items():
        if not count:
            findings.append({'code': 'DOCS_FLEET_EMPTY', 'namespace': namespace})
    return {'ok': bool(reports) and not findings and all(r['ok'] for r in reports),
            'coverage': 'local-checkouts-only', 'discovery': 'immediate-children-of-explicit-roots',
            'namespaces': namespaces, 'namespace_counts': counts,
            'repositories_checked': len(reports), 'unique_repositories_checked': len(identities),
            'duplicates': [{'repository': repo, 'checkouts': paths} for repo, paths in sorted(identities.items()) if len(paths) > 1],
            'findings': findings, 'skipped': skipped, 'reports': reports}


def main():
    p = argparse.ArgumentParser(description=__doc__)
    targets = p.add_mutually_exclusive_group(required=True)
    targets.add_argument('--root', type=Path)
    targets.add_argument('--fleet', type=Path, action='append', help='Read-only audit of immediate Git checkouts; repeat for nested containers')
    p.add_argument('--namespace', action='append', help='Explicit GitHub owner for --fleet; repeat to select multiple owners (default: subactor)')
    p.add_argument('--standard-revision', required=True, help='Full revision selected by trusted CI, never by the candidate document')
    p.add_argument('--base', help='Trusted base SHA for version-increment checks')
    p.add_argument('--policy-dsl-root', type=Path, help='Trusted checkout matching policy-dsl.lock.json; required only for DSL contracts')
    p.add_argument('--deliverable', action='append', default=[])
    p.add_argument('--complete', action='store_true', help='Require explicit result, trusted base and preparation receipt before completion')
    p.add_argument('--managed-copies', type=Path, help='Independently trusted path-to-SHA256 inventory of external .governance/docs copies; never read from candidate report metadata')
    p.add_argument('--prepared-plan', type=Path, help='Saved successful --prepare JSON result; evidence only, not authority')
    p.add_argument('--prepare', action='store_true', help='Read-only mandatory pre-generation placement check')
    p.add_argument('--kind', choices=sorted(set(POLICY['kinds']) | set(POLICY['compact']['directories'])))
    p.add_argument('--format', choices=['v1', 'v2'], default=None, help='Preparation format; v1 compatibility or compact v2')
    p.add_argument('--id', dest='slug')
    p.add_argument('--scope', choices=POLICY['delivery_scopes'])
    args = p.parse_args()
    managed_copies = None
    if args.managed_copies:
        if args.fleet:
            p.error("--managed-copies requires a single --root")
        try:
            managed_copies = json.loads(args.managed_copies.read_text())
        except (OSError, ValueError):
            p.error("Cannot decode trusted managed-copy inventory")
    if args.namespace and not args.fleet:
        p.error('--namespace requires --fleet')
    if args.complete:
        if args.fleet or args.prepare or not args.prepared_plan or not args.base or len(args.deliverable) != 1 or any([args.kind, args.slug, args.scope, args.format]):
            p.error('--complete requires --root, --base, one --deliverable and --prepared-plan')
        try:
            prepared = json.loads(args.prepared_plan.read_text())
            result = complete_delivery(args.root, args.standard_revision, args.deliverable, args.base, prepared, args.policy_dsl_root, managed_copies)
        except (OSError, ValueError, TypeError):
            result = {'ok': False, 'findings': [{'code': 'DOCS_COMPLETION', 'message': 'Cannot decode preparation receipt'}]}
    elif args.prepared_plan:
        p.error('--prepared-plan requires --complete')
    elif args.prepare:
        if args.fleet or args.base or len(args.deliverable) != 1 or not all([args.kind, args.slug, args.scope]):
            p.error('--prepare requires --root, --kind, --id, --scope and exactly one --deliverable, without --base')
        result = prepare_delivery(args.root, args.standard_revision, args.kind, args.slug, args.scope, args.deliverable[0], args.format == 'v2', args.policy_dsl_root, managed_copies)
    elif args.kind or args.slug or args.scope or args.format:
        p.error('--kind, --id and --scope require --prepare')
    elif args.fleet:
        if args.deliverable or args.base:
            p.error('--deliverable applies to a single --root')
        try:
            result = check_fleet(args.fleet, args.standard_revision, args.namespace, args.policy_dsl_root)
        except ValueError as error:
            p.error(str(error))
    else:
        result = check(args.root, args.standard_revision, args.deliverable, base=args.base, policy_dsl_root=args.policy_dsl_root, managed_copies=managed_copies)
    print(json.dumps(result, indent=2))
    return 0 if result['ok'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
