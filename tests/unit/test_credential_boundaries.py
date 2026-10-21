"""Repository-wide credential I/O guard and metadata-only login controls."""
import ast
from pathlib import Path
import re

import pytest

ROOT = Path(__file__).resolve().parents[2]
CREDENTIAL = re.compile(r"(?<![A-Za-z0-9])(?:credentials?|oauth_creds|auth\.json|login_material|login_file|auth_file|token_file|token_path|tokens\.json|proxy_path|keychains?)(?![A-Za-z0-9])", re.I)
STORE = re.compile(r"find-generic-password|add-generic-password|delete-generic-password|SecItem|SecKeychain")
FILE_IO = {'open', 'read_text', 'read_bytes', 'write_text', 'write_bytes', 'copyfile', 'copy2', 'copytree', 'copy', 'read', 'write'}


def violations(text):
    tree = ast.parse(text)
    findings = []
    for node in ast.walk(tree):
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            names = [node.module or ''] if isinstance(node, ast.ImportFrom) else [a.name for a in node.names]
            if any(n.split('.')[0].lower() in {'security', 'keychain', 'keyring'} for n in names):
                findings.append((node.lineno, 'credential-store-api'))
        if isinstance(node, (ast.List, ast.Tuple)) and node.elts and isinstance(node.elts[0], ast.Constant) and node.elts[0].value in ('security', '/usr/bin/security'):
            findings.append((node.lineno, 'credential-store-command'))
        if isinstance(node, ast.Attribute) and STORE.search(node.attr):
            findings.append((node.lineno, 'credential-store-api'))
        if isinstance(node, ast.Constant) and isinstance(node.value, str) and (STORE.search(node.value) or 'Security.framework' in node.value):
            findings.append((node.lineno, 'credential-store-command'))
    for function in (n for n in ast.walk(tree) if isinstance(n, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef))):
        private_copy = bool(re.search(r'(?:credential|login)', getattr(function, 'name', ''), re.I))
        tainted = set()
        nodes = (list(ast.walk(function)) if not isinstance(function, ast.Module) else
                 [node for statement in function.body
                  if not isinstance(statement, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
                  for node in ast.walk(statement)])
        for node in nodes:
            if isinstance(node, ast.Assign) and CREDENTIAL.search(ast.unparse(node.value)):
                tainted.update(n.id for target in node.targets for n in ast.walk(target) if isinstance(n, ast.Name))
        for node in nodes:
            if not isinstance(node, ast.Call):
                continue
            name = node.func.attr if isinstance(node.func, ast.Attribute) else node.func.id if isinstance(node.func, ast.Name) else ''
            sensitive = CREDENTIAL.search(ast.unparse(node)) or any(
                isinstance(n, ast.Name) and n.id in tainted for n in ast.walk(node))
            if (name in FILE_IO and sensitive or private_copy and name in {'read', 'write', 'copyfile', 'copytree'}):
                findings.append((node.lineno, 'credential-file-io'))
    return sorted(set(findings))


def test_runtime_modules_keep_credential_bytes_with_the_operator():
    found = {str(p.relative_to(ROOT)): violations(p.read_text()) for p in (ROOT / 'src/ravel').rglob('*.py')}
    assert {p: rows for p, rows in found.items() if rows} == {}, str({p: rows for p, rows in found.items() if rows})


@pytest.mark.parametrize('source', [
    'import keyring; keyring.get_password("service", "account")',
    'import subprocess; subprocess.run(["security", "find-generic-password", "-w"])',
    'def save(path):\n    (path / ".credentials.json").write_text("value")',
    'def save(source, target):\n    import shutil\n    auth_file = source / "auth.json"\n    shutil.copyfile(auth_file, target)',
    'def load(source):\n    return (source / "oauth_creds.json").read_bytes()',
    'def load(source):\n    return (source / "Library/Keychains/login.keychain-db").read_bytes()',
    'import subprocess; subprocess.run(["security", "dump-keychain"])',
    'from pathlib import Path; Path("auth.json").write_bytes(b"value")',
    'def save(root):\n    token_path = root / "tokens.json"\n    token_path.write_bytes(b"value")',
    'def query(api):\n    return api.SecItemCopyMatching({}, None)',
])
def test_guard_refuses_credential_store_and_file_operations(source):
    assert violations(source)


def test_guard_admits_file_metadata_and_nonsecret_configuration():
    assert violations('def inspect(path):\n    return (path / ".credentials.json").lstat()') == []
    assert violations('def configure(path):\n    (path / "config.toml").write_text("setting=true")') == []
