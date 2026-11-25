"""Clangd AST input for design checks. A CDB is data, never a command to run."""
import json
import os
from pathlib import Path
import re
import selectors
import shlex
import shutil
import subprocess
import tempfile
import time


def source_range(text, span):
    lines = text.splitlines(keepends=True)

    def offset(pos):
        row = pos['line']
        if row == len(lines) and pos['character'] == 0:
            return len(text)
        prefix = lines[row].encode('utf-16-le')[:pos['character'] * 2].decode('utf-16-le')
        return sum(map(len, lines[:row])) + len(prefix)

    return text[offset(span['start']):offset(span['end'])]


def location(path, node):
    return {'path': path, 'line': line(node)}


def call_ref(node):
    if node['kind'] in ('Call', 'CXXMemberCall', 'CXXOperatorCall') and children(node):
        callee = children(node)[0]
        while callee['kind'] in ('ImplicitCast', 'Paren') and len(children(callee)) == 1:
            callee = children(callee)[0]
        if callee['kind'] in ('DeclRef', 'Member'):
            return callee
    return None


def direct_calls(node):
    for child in walk(node):
        if (callee := call_ref(child)) is not None:
            yield child, callee


def split_if(node):
    parts = children(node)
    if node['kind'] != 'If' or len(parts) < 2:
        return None, None, None
    has_else = ' has_else' in node.get('arcana', '')
    if has_else and len(parts) >= 3:
        return parts[-3], parts[-2], parts[-1]
    return parts[-2], parts[-1], None


def definition_ids(node):
    previous = re.search(r'\bprev (0x[0-9a-f]+)', node.get('arcana', ''))
    return {address(node), previous[1]} if previous else {address(node)}


def functions(tree):
    return [node for node in walk(tree) if function(node) and node.get('detail') and 'range' in node]


def before_comment(text, n):
    return text.splitlines()[n - 2].strip() if n >= 2 and text.splitlines()[n - 2].strip().startswith(('/', '*')) else ''


class AstError(ValueError):
    pass


def commands(root, cdb, paths):
    if cdb is None:
        entries = [{'directory': str(root), 'file': path,
                    'arguments': ['c++', '-std=c++17', '-I', str(root), path]}
                   for path in paths]
    else:
        entries = json.loads(cdb.read_text(encoding='utf-8'))
    if not isinstance(entries, list):
        raise AstError('CDB must be an array')
    selected = {}
    allowed = set(paths)
    for entry in entries:
        directory = Path(entry['directory']).resolve(strict=True)
        path = (directory / entry['file']).resolve(strict=True)
        if not path.is_relative_to(root) or path.relative_to(root).as_posix() not in allowed:
            continue
        relative = path.relative_to(root).as_posix()
        args = entry.get('arguments')
        if args is None:
            args = shlex.split(entry['command'])
        if not isinstance(args, list) or not args or any(not isinstance(a, str) for a in args):
            raise AstError(f'{relative}: invalid CDB arguments')
        # Rebuild the invocation; never allow response files, plugins, drivers, config
        # files, arbitrary Clang options, output paths or environment assignments.
        safe = ['/usr/bin/c++', '-fsyntax-only', '-x', 'c++']
        args = iter(args[1:])
        for arg in args:
            if arg in ('-I', '-isystem', '-iquote') or (arg.startswith('-I') and len(arg) > 2):
                flag, value = (arg, next(args, '')) if arg in ('-I', '-isystem', '-iquote') else ('-I', arg[2:])
                if not value or value.startswith(('-', '@')):
                    raise AstError(f'{relative}: invalid include directory')
                safe.extend((flag, str((directory / value).resolve())))
            elif arg in ('-c', '-fsyntax-only') or (not arg.startswith(('-', '@')) and (directory / arg).resolve() == path):
                continue
            elif re.fullmatch(r'-std=(?:gnu|c)\+\+(?:98|03|11|14|17|20|23|26|2a|2b|2c)|-[DU][A-Za-z_]\w*(?:=[^\x00\r\n]*)?', arg):
                safe.append(arg)
            else:
                raise AstError(f'{relative}: unsupported CDB option {arg!r}')
        command = {'directory': str(root), 'file': str(path), 'arguments': [*safe, str(path)]}
        if relative in selected and selected[relative] != command:
            raise AstError(f'{relative}: multiple build configurations')
        selected[relative] = command
    return selected


class Clangd:
    def __init__(self, process, timeout):
        self.process = process
        self.timeout = timeout
        self.buffer = bytearray()
        self.request_id = 0
        self.diagnostics = {}

    def send(self, method, params, request=False):
        message = {'jsonrpc': '2.0', 'method': method, 'params': params}
        if request:
            self.request_id += 1
            message['id'] = self.request_id
        body = json.dumps(message).encode()
        self.process.stdin.write(f'Content-Length: {len(body)}\r\n\r\n'.encode() + body)
        self.process.stdin.flush()

    def call(self, method, params):
        self.send(method, params, request=True)
        with selectors.DefaultSelector() as selector:
            selector.register(self.process.stdout, selectors.EVENT_READ)
            deadline = time.monotonic() + self.timeout

            def read():
                if not selector.select(max(0, deadline - time.monotonic())):
                    raise AstError(f'clangd timed out: {method}')
                chunk = os.read(self.process.stdout.fileno(), 65536)
                if not chunk:
                    raise AstError(f'clangd stopped: {method}')
                self.buffer.extend(chunk)

            while True:
                while (end := self.buffer.find(b'\r\n\r\n')) < 0:
                    read()
                    if len(self.buffer) > 65536:
                        raise AstError('invalid clangd response header')
                size = int(self.buffer[:end].split(b':', 1)[1].strip())
                start = end + 4
                if not 0 < size <= 64 * 1024 * 1024:
                    raise AstError('clangd response exceeds size limit')
                while len(self.buffer) < start + size:
                    read()
                message = json.loads(self.buffer[start:start + size])
                del self.buffer[:start + size]
                if message.get('method') == 'textDocument/publishDiagnostics':
                    p = message['params']
                    self.diagnostics[p['uri']] = p['diagnostics']
                if message.get('id') == self.request_id and 'method' not in message:
                    if 'error' in message:
                        raise AstError(f"clangd {method}: {message['error']['message']}")
                    return message['result']


def analyze(root, cdb, sources, timeout):
    """Yield per-TU trees and diagnostics for one configuration; no global index."""
    path_env = os.pathsep.join(p for p in os.get_exec_path() if Path(p).is_absolute())
    binary = shutil.which('clangd', path=path_env)
    if not binary or Path(binary).resolve().is_relative_to(root):
        raise AstError('trusted clangd outside --root is not on absolute PATH entries')
    selected = commands(root, cdb, sources)
    if not selected:
        raise AstError('no CDB entries for selected source files')
    with tempfile.TemporaryDirectory(prefix='lint-ast-') as scratch:
        (Path(scratch) / 'compile_commands.json').write_text(json.dumps(list(selected.values())), encoding='utf-8')
        with subprocess.Popen([str(Path(binary).resolve()), f'--compile-commands-dir={scratch}',
                               '--background-index=false', '--enable-config=false', '--pch-storage=memory',
                               '--clang-tidy=false', '--log=error'], cwd=scratch,
                              stdin=subprocess.PIPE, stdout=subprocess.PIPE) as process:
            try:
                clangd = Clangd(process, timeout)
                clangd.call('initialize', {'rootUri': root.as_uri(), 'capabilities': {}})
                clangd.send('initialized', {})
                for path in sorted(selected):
                    uri = (root / path).as_uri()
                    doc = {'uri': uri}
                    clangd.send('textDocument/didOpen', {'textDocument': dict(doc, languageId='cpp', version=1,
                                                                             text=sources[path])})
                    tree = clangd.call('textDocument/ast', {'textDocument': doc})
                    errors = [d['message'] for d in clangd.diagnostics.get(uri, []) if d.get('severity') == 1]
                    if not tree or uri not in clangd.diagnostics:
                        errors.append('clangd AST or diagnostics unavailable')
                    links = clangd.call('textDocument/documentLink', {'textDocument': doc}) if tree else []
                    yield path, tree, errors, links
                    clangd.send('textDocument/didClose', {'textDocument': doc})
                clangd.call('shutdown', None)
                clangd.send('exit', None)
                if process.wait(timeout=timeout):
                    raise AstError('clangd did not exit successfully')
            finally:
                if process.poll() is None:
                    process.kill()


def children(node):
    return node.get('children', ())


def walk(node):
    yield node
    for child in children(node):
        yield from walk(child)


def address(node):
    return (node.get('arcana', '').split() + ['', ''])[1]


def line(node):
    return node['range']['start']['line'] + 1


def types(node):
    # Clang AST's adjacent 'spelling':'canonical' pair, if desugared.
    return re.findall(r"'([^']+)'", node.get('arcana', ''))


def reference(node):
    arcana = node.get('arcana', '')
    if node.get('kind') == 'Member':
        match = re.search(r'(?:\.|->)[^ ]+ (0x[0-9a-f]+)(?: |$)', arcana)
    else:
        match = re.search(r"\b(?:Var|ParmVar|Function|CXXMethod) (0x[0-9a-f]+) '", arcana)
    return match[1] if match else None


def function(node):
    return node.get('kind') in ('Function', 'CXXMethod', 'CXXConstructor', 'CXXDestructor', 'CXXConversion')


def body(node):
    return next((c for c in children(node) if c['kind'] == 'Compound'), None)
