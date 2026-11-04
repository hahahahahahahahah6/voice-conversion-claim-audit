import ast
import contextlib
import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from voice_conversion_claim_audit.audit import audit, claims, evidence, main, GENERIC

EXPECTED_POSITIVE = ('voice conversion', 'converts voice', 'converts a voice', 'convert a voice', 'convert voices', 'converts voices', 'voice convert', 'voice converts', 'converted voice', 'converted voices', 'speaker conversion', 'converts speaker voice', 'convert speaker voice', 'speaker voice conversion', 'voice conversion system', 'automatic voice conversion', 'zero shot voice conversion', 'converts your voice', 'convert your voice', 'convert any voice', 'converts any voice', 'convert a speaker voice', 'voice conversion technology', 'converts speech to another voice', 'convert speech to another voice', 'changes a voice', 'change a voice', 'changes your voice', 'change your voice', 'voice changing', 'voice changer', 'transforms a voice', 'transform a voice', 'transforms your voice', 'voice transformation', 'swaps a voice', 'swap a voice', 'voice swapping', 'voice swap', 'converts one voice to another', 'convert one voice to another', 'converts voice to another voice', 'voice to voice conversion', 'speech voice conversion', 'converts the voice of', 'convert the voice of', 'voice conversion model', 'converted speaker voice', 'real time voice conversion', 'converts voice in real time')
EXPECTED_NEGATIVE = ('no voice conversion', 'does not convert voice', 'does not convert voices', 'does not convert a voice', 'without voice conversion', 'no voice convert', 'does not change a voice', 'voice conversion not supported', 'does not convert your voice', 'no converted voice', 'does not transform a voice', 'does not swap a voice', 'no speaker conversion', 'does not convert speaker voice', 'no voice conversion system', 'does not change your voice', 'without converted voice', 'no voice changing', 'does not convert speech to another voice', 'no voice transformation', 'does not convert one voice to another', 'without voice changer', 'no voice swap', 'does not convert the voice of')

class AuditTests(unittest.TestCase):
    def project(self, files):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        root = Path(temp.name)
        for name, content in files.items():
            path = root / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content)
        return root

    def run_cli(self, root, *args):
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            code = main([str(root), '--json', *args])
        return code, json.loads(output.getvalue())

    def test_phrase_oracle(self):
        path = Path(__file__).resolve().parents[1] / 'voice_conversion_claim_audit/phrases.py'
        values = {}
        for node in ast.parse(path.read_text()).body:
            if isinstance(node, ast.Assign):
                values[node.targets[0].id] = ast.literal_eval(node.value)
        self.assertEqual(values['VOICECONVERSION'], EXPECTED_POSITIVE)
        self.assertEqual(values['NOVOICECONVERSION'], EXPECTED_NEGATIVE)
        self.assertEqual(len(EXPECTED_POSITIVE), 50)
        self.assertEqual(len(EXPECTED_NEGATIVE), 24)

    def test_findings(self):
        root = self.project({'README.md': 'Voice conversion', 'app.py': 'pass'})
        code, result = self.run_cli(root)
        self.assertEqual(code, 2)
        self.assertEqual(result['verdict'], 'FAIL')
        self.assertEqual(result['findings'], [{'id': 'documented-voice-conversion-claim-false', 'severity': 'HIGH', 'message': 'Documented promise lacks production call evidence.'}])
        (root/'app.py').write_text('engine.convert_voice()')
        self.assertEqual(self.run_cli(root)[1]['verdict'], 'PASS')
        (root/'README.md').write_text('No voice conversion')
        code, result = self.run_cli(root)
        self.assertEqual(code, 2)
        self.assertEqual(result['findings'][0]['id'], 'documented-no-voice-conversion-claim-false')
        self.assertEqual(result['findings'][0]['severity'], 'HIGH')

    def test_test_only(self):
        for name in ('tests/helper.py', 'test_engine.py', 'engine_test.py'):
            with self.subTest(name=name):
                root = self.project({'README.md': 'voice conversion', name: 'e.convert_voice()'})
                self.assertEqual(self.run_cli(root)[0], 0)
                self.assertEqual(self.run_cli(root)[1]['findings'][0]['severity'], 'MEDIUM')
                self.assertEqual(self.run_cli(root, '--fail-on', 'MEDIUM')[0], 2)

    def test_no_source_and_no_claim(self):
        for text, verdict in [('voice conversion', 'FAIL'), ('no voice conversion', 'PASS'), ('An auditor.', 'PASS')]:
            self.assertEqual(audit(self.project({'README.md': text}))['verdict'], verdict)

    def test_fences_and_normalization(self):
        for fence in ('```', '~~~', '   ````'):
            self.assertEqual(claims(fence+'text\nvoice conversion\n'+fence.strip()), ([], []))
        self.assertEqual(claims('`voice conversion`')[0], ['voice conversion'])
        self.assertEqual(claims("doesn't convert voice"), ([], ['does not convert voice']))
        self.assertEqual(claims('VOICE-CONVERSION SYSTEM')[0], ['voice conversion system'])
        self.assertEqual(claims('voice\n\nconversion'), ([], []))
        self.assertEqual(claims('avoice conversionist'), ([], []))

    def test_split_modules(self):
        for constructor, method in [('VoiceConverter','convert'), ('RVC','infer'), ('VITS','convert')]:
            root = self.project({'README.md':'voice conversion', 'a.py':'x = '+constructor+'()', 'b.py':'x.'+method+'()'})
            self.assertEqual(audit(root)['verdict'], 'FAIL')

    def test_exclusions(self):
        for name in ('fixtures/a.py', 'docs/a.py', 'examples/a.py'):
            root = self.project({'README.md':'voice conversion', name:'e.convert_voice()'})
            self.assertEqual(audit(root)['findings'][0]['severity'], 'HIGH')
        root = self.project({'README.md':'voice conversion', 'ignored/a.py':'e.convert_voice()'})
        self.assertEqual(audit(root, ['ignored'])['verdict'], 'FAIL')
        external = self.project({'a.py':'e.convert_voice()', 'README.md':'voice conversion'})
        root = self.project({})
        (root/'link.py').symlink_to(external/'a.py')
        (root/'docs').symlink_to(external, target_is_directory=True)
        self.assertEqual(audit(root)['sources'], [])
        self.assertEqual(audit(root)['docs'], [])

    def test_docs_selection(self):
        root = self.project({'nested/docs/a.md':'voice conversion', 'other.md':'no voice conversion'})
        self.assertEqual(audit(root)['docs'], ['nested/docs/a.md'])
        self.assertEqual(audit(root)['verdict'], 'FAIL')

    def test_usage(self):
        for args in ([], ['--bad'], ['/nonexistent'], ['.', '--fail-on', 'BAD']):
            result = subprocess.run([sys.executable, '-m', 'voice_conversion_claim_audit', *args], capture_output=True, text=True)
            self.assertEqual(result.returncode, 1)

    def test_version_and_module(self):
        result = subprocess.run([sys.executable, '-m', 'voice_conversion_claim_audit', '--version'], capture_output=True, text=True)
        self.assertEqual((result.returncode, result.stdout.strip()), (0, '0.1.0'))

    def test_self_audit(self):
        root = Path(__file__).resolve().parents[1]
        self.assertEqual(claims((root/'README.md').read_text()), ([], []))
        self.assertEqual(audit(root)['verdict'], 'PASS')


def add_case(name, source, expected):
    def test(self):
        self.assertEqual(evidence(source), expected, source)
    setattr(AuditTests, 'test_' + name, test)

for name in sorted(GENERIC):
    add_case('generic_' + name, 'engine.'+name+'()', True)
    add_case('import_' + name, 'from engine import '+name+' as operation\noperation()', True)
    add_case('bare_' + name, name+'()', False)
    add_case('shadow_' + name, 'def '+name+'(): pass\nengine.'+name+'()', False)

for constructor, methods in [('VoiceConverter', ('convert','transform')), ('NeuralVoiceConverter', ('convert','transform')), ('SpeakerConverter', ('convert','transform')), ('RVC', ('infer','convert')), ('MyRVC', ('infer','convert')), ('VITS', ('convert',)), ('SoVITS', ('convert',)), ('MySoVITS', ('convert',))]:
    for method in methods:
        for style, source in [
            ('assigned', 'x = '+constructor+'()\nx.'+method+'()'),
            ('chain', constructor+'().'+method+'()'),
            ('attribute', 'x = lib.'+constructor+'()\nx.'+method+'()'),
            ('alias', 'from lib import '+constructor+' as C\nx = C()\nx.'+method+'()'),
            ('import_alias', 'import lib.'+constructor+' as C\nC().'+method+'()'),
            ('annotated', 'x: object = '+constructor+'()\nx.'+method+'()')]:
            add_case(constructor+'_'+method+'_'+style, source, True)
    add_case(constructor+'_alone', constructor+'()', False)
    add_case(constructor+'_local_class', 'class '+constructor+': pass\nx = '+constructor+'()\nx.convert()', False)
    add_case(constructor+'_local_function', 'def '+constructor+'(): pass\n'+constructor+'().convert()', False)

NOT_EVIDENCE = [
    'import rvc', 'librosa.load("a.wav")', 'soundfile.read("a.wav")', 'wave.open("a.wav").readframes(1)', 'torchaudio.load("a.wav")',
    'microphone.record()', 'audio.play()', 'engine.tts_to_file()', 'engine.tts()', 'engine.synthesize()', 'engine.speak()',
    'engine.clone_voice()', 'engine.voice_clone()', 'x=VoiceCloner(); x.clone()', 'XTTS().tts_to_file(speaker_wav="a.wav")',
    'tortoise.tts_with_preset(voice_samples=[])', 'engine.verify_speaker()', 'engine.verify_files()', 'engine.similarity()',
    'engine.diarize()', 'engine.transcribe()', 'engine.detect_speech()', 'engine.spot_keyword()', 'engine.denoise()',
    'engine.fingerprint()', 'engine.detect_events()', 'engine.separate()', 'engine.generate_audio()', 'engine.generate_music()',
    'engine.recognize_emotion()', 'engine.sentiment()', 'engine.get_se()', 'speaker_encoder.encode()', 'engine.extract_speaker_embedding()',
    'load_reference_wav()', 'engine.train()', 'engine.fit()', 'x=Other(); x.convert()', 'x=Other(); x.transform()',
    'x=Other(); x.infer()', 'VITS().synthesize()', 'SoVITS().generate()', 'VITS().tts()',
    'RVCModel().infer()', 'RVCInference().convert()', 'MyVITS().convert()',
    'subprocess.run(["rvc", "convert"])', '"VoiceConverter RVC voice conversion"', 'engine.convert_voice', 'bad syntax !',
    'from engine import convert_voice as c\ndef c(): pass\nc()',
    'from engine import convert_voice as c\nclass A:\n def convert_voice(self): pass\nc()'
]
for index, source in enumerate(NOT_EVIDENCE):
    add_case('not_evidence_%02d' % index, source, False)

for index, phrase in enumerate(EXPECTED_POSITIVE):
    def test(self, phrase=phrase):
        self.assertEqual(claims(phrase), ([phrase], []))
    setattr(AuditTests, 'test_positive_phrase_%02d' % index, test)
for index, phrase in enumerate(EXPECTED_NEGATIVE):
    def test(self, phrase=phrase):
        self.assertEqual(claims(phrase), ([], [phrase]))
    setattr(AuditTests, 'test_negative_phrase_%02d' % index, test)

add_case('unaliased_module_import', 'import lib.convert_voice\nlib()', False)
add_case('aliased_generic_import', 'import lib.convert_voice as operation\noperation()', True)
add_case('pair_method_definition_not_shadow', 'def convert(): pass\nx=VoiceConverter()\nx.convert()', True)
add_case('generic_class_not_function_shadow', 'from lib import convert_voice\nclass convert_voice: pass\nconvert_voice()', True)
add_case('attribute_async_shadow', 'async def convert_voice(): pass\ne.convert_voice()', False)

if __name__ == '__main__':
    unittest.main()
