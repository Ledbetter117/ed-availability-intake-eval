"""Offline parser regressions, including bounded malformed-response subprocesses."""
import argparse
import ast
import json
from pathlib import Path
import re
import subprocess
import sys
import unittest

ap = argparse.ArgumentParser(add_help=False)
ap.add_argument('--source', type=Path, default=Path(__file__).resolve().parents[1]/'run_eval.py')
options, rest = ap.parse_known_args()
sys.argv = [sys.argv[0]] + rest
SOURCE = options.source.resolve()
PARSER_NAMES = {'_Rejected', '_pairs_without_conflicts', '_reject_constant', '_strict_loads', 'parse_json'}

def load_parser(path):
    tree = ast.parse(path.read_text(encoding='utf-8'))
    nodes = [x for x in tree.body if isinstance(x, (ast.ClassDef, ast.FunctionDef)) and x.name in PARSER_NAMES]
    scope = {'json': json, 're': re}
    exec(compile(ast.Module(body=nodes, type_ignores=[]), str(path), 'exec'), scope)
    return scope['parse_json']

PARSE = load_parser(SOURCE)
CHILD = '''import ast,json,re,sys
from pathlib import Path
names={'_Rejected','_pairs_without_conflicts','_reject_constant','_strict_loads','parse_json'}
tree=ast.parse(Path(sys.argv[1]).read_text(encoding='utf-8'))
nodes=[x for x in tree.body if isinstance(x,(ast.ClassDef,ast.FunctionDef)) and x.name in names]
scope={'json':json,'re':re}
exec(compile(ast.Module(body=nodes,type_ignores=[]),sys.argv[1],'exec'),scope)
n=1_048_576
text='a'+' '*n+'x' if sys.argv[2]=='spaces' else '{'*n
print(scope['parse_json'](text) is None)
'''

class ResponseParserBounds(unittest.TestCase):
    def test_valid_objects_and_fences(self):
        objects = [{}, {'a': 1}, {'text': 'literal\u2028separator\u2029and ``` backticks'},
                   {'month': '2026-07', 'days': {}, 'global_notes': ['synthetic']}]
        for obj in objects:
            text = json.dumps(obj, ensure_ascii=False)
            for wrapped in [text, '```json\n'+text+'\n```', '```\n'+text+'\n```',
                            '```json'+text+'```', 'prefix '+text+' suffix', ' \n'+text+'\n ']:
                with self.subTest(wrapped=wrapped):
                    self.assertEqual(PARSE(wrapped), obj)

    def test_strict_rejections(self):
        for text in ['{"a":1,"a":2}', '{"a":NaN}', '{"a":Infinity}', '{"a":-Infinity}',
                     'not JSON', '{{', '{} {}', '[ '*1200]:
            with self.subTest(text=text[:40]):
                self.assertIsNone(PARSE(text))

    def test_nontext_and_equal_duplicate(self):
        for value in [None, False, 3, [], {}]:
            self.assertIsNone(PARSE(value))
        self.assertEqual(PARSE('{"a":1,"a":1}'), {'a': 1})

    def bounded(self, kind):
        try:
            p = subprocess.run([sys.executable, '-B', '-c', CHILD, str(SOURCE), kind],
                               capture_output=True, text=True, timeout=5)
        except subprocess.TimeoutExpired:
            self.fail('Malformed-response parser exceeded the 5-second subprocess deadline: '+kind)
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertEqual(p.stdout.strip(), 'True')

    def test_long_internal_whitespace_is_bounded(self):
        self.bounded('spaces')

    def test_many_unclosed_braces_is_bounded(self):
        self.bounded('braces')

if __name__ == '__main__':
    unittest.main()
