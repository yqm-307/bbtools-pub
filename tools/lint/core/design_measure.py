"""Shared lizard-backed measurement for review checks. The pinned backend is optional:
when it cannot be imported at the configured version, callers get no measurements and
must report the coverage gap instead of silently zero findings."""
import importlib.metadata
import importlib.util
import sys
import sysconfig
from pathlib import Path
from contextlib import contextmanager

BACKEND_VERSION = '1.25.0'


class BackendMissing(Exception):
    pass


def configured_version(path):
    """Version from the dist-info inside the configured site-packages, not whichever
    ambient distribution metadata happens to win sys.path."""
    for dist in sorted(Path(path).glob('lizard-*.dist-info')):
        metadata = dist / 'METADATA'
        if metadata.is_file():
            for line in metadata.read_text(encoding='utf-8', errors='replace').splitlines():
                if line.startswith('Version:'):
                    return line.split(':', 1)[1].strip() or None
    return None


@contextmanager
def temporary_import_path(path):
    """Make one site-packages directory importable without leaking its path."""
    original = list(sys.path)
    sys.path.insert(0, path)
    try:
        yield
    finally:
        sys.path[:] = original


def clear_backend_modules():
    """Drop cached lizard modules before loading an explicitly selected backend."""
    for name in tuple(sys.modules):
        if name in ('lizard', 'lizard_core', 'lizard_ext', 'lizard_languages') \
                or name.startswith(('lizard_core.', 'lizard_ext.', 'lizard_languages.')):
            sys.modules.pop(name, None)


def snapshot_backend_modules():
    return {name: module for name, module in sys.modules.items()
            if name == 'lizard' or name.startswith(('lizard_core', 'lizard_ext', 'lizard_languages'))}


def restore_backend_modules(snapshot):
    clear_backend_modules()
    sys.modules.update(snapshot)


@contextmanager
def backend_context(lizard_path=None):
    snapshot = snapshot_backend_modules()
    try:
        yield load_backend(lizard_path)
    finally:
        restore_backend_modules(snapshot)


def trusted_backend_path(path):
    """Only allow configured code to come from the active Python environment.

    The lint configuration belongs to the scanned repository and is therefore data
    from the trust boundary. A repository must not be able to turn an arbitrary
    directory into executable Python code inside the lint process.
    """
    candidate = Path(path).resolve()
    roots = {Path(value).resolve() for name in ('purelib', 'platlib')
             if (value := sysconfig.get_path(name))}
    return candidate in roots


def _load_backend(lizard_path=None):
    """Import the pinned lizard backend, optionally from a configured site-packages dir.

    An explicit lizard_path is authoritative: when it is configured, lizard must come
    from that directory. Falling back to an ambient install or an already cached module
    would silently ignore the operator's input and report measurements from an
    unverified backend.
    """
    def missing(detail):
        return BackendMissing(
            detail + '; configure design.complexity-delta.lizard_path or run in the documented environment')

    if lizard_path:
        path = str(Path(lizard_path).resolve())
        if not trusted_backend_path(path):
            raise missing(f'lizard_path must be inside the active Python environment: {lizard_path!r}')
        if not (Path(path) / 'lizard.py').is_file() and not (Path(path) / 'lizard').is_dir():
            raise missing(f'lizard is not importable from {lizard_path!r}')
        if configured_version(path) is None:
            raise missing(f'lizard distribution metadata is missing from {lizard_path!r}')
        clear_backend_modules()
        try:
            with temporary_import_path(path):
                import lizard
                import lizard_languages
        except ImportError:
            raise missing(f'lizard is not importable from {lizard_path!r}') from None
        version = configured_version(path)
    else:
        clear_backend_modules()
        try:
            import lizard
        except ImportError:
            raise missing('lizard is not importable') from None
        try:
            version = importlib.metadata.version('lizard')
        except importlib.metadata.PackageNotFoundError:
            raise missing('lizard distribution metadata is missing') from None
    if version != BACKEND_VERSION:
        raise BackendMissing(f'lizard version {version} does not match pinned {BACKEND_VERSION}')
    return lizard


def load_backend(lizard_path=None):
    snapshot = snapshot_backend_modules()
    try:
        return _load_backend(lizard_path)
    except Exception:
        restore_backend_modules(snapshot)
        raise


@contextmanager
def load_complexity(lizard_path=None):
    """Load the sibling tools/complexity implementation as private modules.

    tools/complexity is the single source of measurement policy and baseline diffing;
    its flat module name `common` is registered only while its own modules execute,
    so it never shadows anything in the lint process afterwards.
    """
    snapshot = snapshot_backend_modules()
    loaded_names = ('_review_cx_common', '_review_cx_structural')
    leaked = sys.modules.get('common')
    try:
        backend = load_backend(lizard_path)  # fail fast with the same coverage-gap reason
        root = Path(__file__).resolve().parent.parent.parent / 'complexity'
        if not (root / 'structural.py').is_file():
            raise BackendMissing('tools/complexity is missing next to tools/lint')
        loaded = {}
        for public, private in (('common', loaded_names[0]), ('structural', loaded_names[1])):
            spec = importlib.util.spec_from_file_location(private, root / f'{public}.py')
            if spec is None or spec.loader is None:
                raise BackendMissing(f'cannot load tools/complexity/{public}.py')
            module = importlib.util.module_from_spec(spec)
            sys.modules[private] = module
            if public == 'common':
                sys.modules['common'] = module  # structural does `from common import ...`
            spec.loader.exec_module(module)
            loaded[public] = module
        yield loaded['common'], loaded['structural'], backend
    finally:
        for name in loaded_names:
            sys.modules.pop(name, None)
        if leaked is not None:
            sys.modules['common'] = leaked
        else:
            sys.modules.pop('common', None)
        restore_backend_modules(snapshot)


def measure_file(lizard, path, text):
    """One lizard pass over a single source text.

    Returns (functions, error):
    - functions: [{name, long_name, start_line, end_line, metrics, tokens}] with tokens
      filtered exactly like tools/complexity does (whitespace/comments dropped);
    - error: a string when lizard could not parse the file, else None.
    """
    import io
    from contextlib import redirect_stderr
    from lizard_languages import get_reader_for

    analyzer = lizard.FileAnalyzer(lizard.get_extensions(['cognitive']))
    diagnostics = io.StringIO()
    try:
        with redirect_stderr(diagnostics):
            parsed = analyzer.analyze_source_code(path, text)
    except (OSError, UnicodeError, ValueError, IndexError, RecursionError) as error:
        return [], str(error)
    if diagnostics.getvalue():
        return [], 'lizard emitted a diagnostic'
    lines = text.splitlines()
    functions = []
    try:
        parsed_functions = list(parsed.function_list)
        boundaries = [(fn.start_line, fn.end_line) for fn in parsed_functions]
        for index, fn in enumerate(parsed_functions):
            snippet = chr(10).join(lines[fn.start_line - 1:fn.end_line])
            tokens = [t for t in get_reader_for(path).generate_tokens(snippet)
                      if t.strip() and not t.startswith(('//', '/*'))]
            start, end = boundaries[index]
            ambiguous = any(index != other and (start in boundaries[other] or end in boundaries[other])
                            for other in range(len(boundaries)))
            functions.append(dict(
                name=fn.name, long_name=fn.long_name,
                start_line=fn.start_line, end_line=fn.end_line,
                window_ambiguous=ambiguous,
                metrics=dict(cognitive_complexity=fn.cognitive_complexity,
                             cyclomatic_complexity=fn.cyclomatic_complexity,
                             nloc=fn.nloc, parameter_count=fn.parameter_count),
                tokens=tokens))
    except (ValueError, IndexError, RecursionError) as error:
        return [], str(error)
    return functions, None
