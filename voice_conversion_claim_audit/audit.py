"""Read-only documentation and AST inspection."""
import argparse
import ast
import json
import os
from pathlib import Path
import re
import sys

from . import __version__
from .phrases import VOICECONVERSION, NOVOICECONVERSION

GENERIC = frozenset("""convert_voice convert_voices voice_convert voice_conversion
convert_speaker_voice convert_to_target_voice convert_voice_to convert_voice_with
transform_voice voice_transform convert_speech_voice change_voice change_speaker_voice
swap_voice voice_swap apply_voice_conversion convert_audio_voice transfer_voice
voice_transfer convert_speaker speaker_convert convert_utterance_voice convert_voice_from
tts_with_vc_to_file vc_convert convert_vc voice_convert_to""".split())


def claims(text):
    """Return affirmative and negative matches outside fenced blocks."""
    lines = []
    fence = None
    for line in text.splitlines():
        match = re.match(r'^ {0,3}(`{3,}|~{3,})(.*)$', line)
        if fence:
            if match and match[1][0] == fence[0] and len(match[1]) >= len(fence) and not match[2].strip():
                fence = None
            lines.append('')
        elif match:
            fence = match[1]
            lines.append('')
        else:
            lines.append(line)
    positive, negative = [], []
    for paragraph in re.split(r'\n\s*\n', '\n'.join(lines)):
        normalized = ' '.join(paragraph.lower().replace('’', "'").replace("n't", ' not').replace('-', ' ').split())
        for phrases, matches in ((NOVOICECONVERSION, negative), (VOICECONVERSION, positive)):
            for phrase in sorted(phrases, key=lambda p: (-len(p), p)):
                pattern = r'\b' + re.escape(phrase) + r'\b'
                if re.search(pattern, normalized):
                    matches.append(phrase)
                    normalized = re.sub(pattern, ' ', normalized)
    return positive, negative


def evidence(source):
    """Recognize complete routes within one parsed module."""
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return False
    nodes = list(ast.walk(tree))
    local = {n.name for n in nodes if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))}
    methods = {n.name for n in nodes if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))}
    aliases = {}
    for n in nodes:
        if isinstance(n, ast.ImportFrom):
            for a in n.names:
                aliases[a.asname or a.name] = a.name
        elif isinstance(n, ast.Import):
            for a in n.names:
                if a.asname:
                    aliases[a.asname] = a.name

    def name(func):
        if isinstance(func, ast.Name):
            return aliases.get(func.id, func.id).split('.')[-1]
        if isinstance(func, ast.Attribute):
            return func.attr
        return ''

    def constructor(call):
        if not isinstance(call, ast.Call):
            return None
        label = name(call.func)
        raw = call.func.id if isinstance(call.func, ast.Name) else label
        if label in local or raw in local:
            return None
        if label.endswith(('VoiceConverter', 'SpeakerConverter')):
            return 'converter'
        if label.endswith('RVC'):
            return 'rvc'
        if label == 'VITS' or label.endswith('SoVITS'):
            return 'vits'
        return None

    bindings = {}
    for n in nodes:
        if isinstance(n, (ast.Assign, ast.AnnAssign)):
            route = constructor(n.value)
            if route:
                targets = n.targets if isinstance(n, ast.Assign) else [n.target]
                for target in targets:
                    if isinstance(target, ast.Name):
                        bindings[target.id] = route
    for n in nodes:
        if not isinstance(n, ast.Call):
            continue
        func = n.func
        label = name(func)
        if isinstance(func, ast.Attribute) and label in GENERIC and label not in methods:
            return True
        if isinstance(func, ast.Name) and func.id in aliases and label in GENERIC and label not in methods and func.id not in methods:
            return True
        if not isinstance(func, ast.Attribute):
            continue
        route = bindings.get(func.value.id) if isinstance(func.value, ast.Name) else constructor(func.value)
        if (route == 'converter' and func.attr in {'convert', 'transform'} or
                route == 'rvc' and func.attr in {'infer', 'convert'} or
                route == 'vits' and func.attr == 'convert'):
            return True
    return False


def audit(root, ignore=()):
    root = Path(root)
    if not root.is_dir() or root.is_symlink():
        raise OSError('root must be a readable directory')
    docs, sources, production, tests = [], [], [], []
    positives, negatives = [], []
    prefixes = [Path(p).as_posix().strip('/') for p in ignore]

    def excluded(rel):
        value = rel.as_posix()
        return any(value == p or value.startswith(p + '/') for p in prefixes)

    def walk_error(error):
        raise error

    for directory, dirs, files in os.walk(root, onerror=walk_error, followlinks=False):
        base = Path(directory)
        dirs[:] = sorted(d for d in dirs if not (base / d).is_symlink() and not excluded((base / d).relative_to(root)))
        for filename in sorted(files):
            path = base / filename
            rel = path.relative_to(root)
            if path.is_symlink() or excluded(rel):
                continue
            if rel.as_posix() == 'README.md' or (path.suffix == '.md' and 'docs' in rel.parts[:-1]):
                docs.append(rel.as_posix())
                pos, neg = claims(path.read_text(encoding='utf-8'))
                positives.extend(pos)
                negatives.extend(neg)
            if path.suffix == '.py':
                sources.append(rel.as_posix())
                if set(rel.parts[:-1]) & {'fixtures', 'docs', 'examples'}:
                    continue
                is_test = 'tests' in rel.parts[:-1] or filename.startswith('test_') or filename.endswith('_test.py')
                if evidence(path.read_text(encoding='utf-8')):
                    (tests if is_test else production).append(rel.as_posix())
    findings = []
    if positives and not production:
        findings.append({'id': 'documented-voice-conversion-claim-false', 'severity': 'MEDIUM' if tests else 'HIGH', 'message': 'Documented promise lacks production call evidence.'})
    if negatives and production:
        findings.append({'id': 'documented-no-voice-conversion-claim-false', 'severity': 'HIGH', 'message': 'Documented denial conflicts with production call evidence.'})
    return {'verdict': 'FAIL' if findings else 'PASS', 'findings': findings,
            'production_evidence': production, 'test_evidence': tests, 'docs': docs, 'sources': sources}


class Parser(argparse.ArgumentParser):
    def error(self, message):
        self.print_usage(sys.stderr)
        self.exit(1, '%s: error: %s\n' % (self.prog, message))


def main(argv=None):
    parser = Parser(description=__doc__)
    parser.add_argument('root')
    parser.add_argument('--version', action='version', version=__version__)
    parser.add_argument('--json', action='store_true')
    parser.add_argument('--verbose', action='store_true')
    parser.add_argument('--ignore', action='append', default=[])
    parser.add_argument('--fail-on', choices=['LOW', 'MEDIUM', 'HIGH'], default='HIGH')
    args = parser.parse_args(argv)
    try:
        result = audit(args.root, args.ignore)
    except (OSError, UnicodeError) as error:
        print('error: %s' % error, file=sys.stderr)
        return 1
    if args.json:
        print(json.dumps(result, sort_keys=True))
    else:
        print(result['verdict'])
        for finding in result['findings']:
            print('{id} {severity}: {message}'.format(**finding))
        if args.verbose:
            for key in ('production_evidence', 'test_evidence', 'docs', 'sources'):
                print('%s: %s' % (key, ', '.join(result[key])))
    ranks = {'LOW': 0, 'MEDIUM': 1, 'HIGH': 2}
    return 2 if any(ranks[f['severity']] >= ranks[args.fail_on] for f in result['findings']) else 0
