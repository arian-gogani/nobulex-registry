"""Offline regressions for evidence attribution, missing sessions and policy typos."""
import contextlib
import io
import copy
import json
from pathlib import Path
import sys
import unittest
from datetime import date, timedelta
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'gateway'))
from harness import MCPStdio, classify_channel, classify_truncation, PASS, FAIL_UNSAFE
from decide import decide, validate_policy, PolicyError, BLOCK
from run import Run

class AuditTests(unittest.TestCase):
    def test_diagnostic_is_not_subject_quote(self):
        c = object.__new__(MCPStdio)
        c.protocol_noise = []
        c.protocol_diagnostics = []
        c.request = lambda *args: {'result': {'isError': 'false', 'content': []}}
        c.call('example', {})
        self.assertEqual(c.protocol_noise, [])
        self.assertEqual(len(c.protocol_diagnostics), 1)
        verdict = classify_channel(c.protocol_noise, '', c.protocol_diagnostics)
        self.assertEqual(verdict[0], FAIL_UNSAFE)
        self.assertIn('Harness diagnostic', verdict[2])
        self.assertNotIn('non-JSON line(s) emitted', verdict[2])
        record = Run()
        with contextlib.redirect_stdout(io.StringIO()):
            record.record_channel(c, '')
        self.assertIsNone(record.probes[0]['response_excerpt'])
        self.assertIn('Harness diagnostic', record.probes[0]['detail'])

    def test_real_noise_stays_verbatim(self):
        noise = ['server banner']
        self.assertEqual(classify_channel(noise, '')[0], FAIL_UNSAFE)
        self.assertEqual(noise, ['server banner'])
        self.assertEqual(classify_channel([], '')[0], PASS)

    def bars(self, n=21):
        days = [(date(2026,9,1)+timedelta(days=i)).isoformat() for i in range(n)]
        return ([{'Date':d,'Close':100} for d in days],
                [{'date':d,'close':100} for d in days])

    def test_two_missing_of_twenty_one(self):
        s,a=self.bars()
        result=classify_truncation(s[:-2],a)
        self.assertEqual(result[:2], (FAIL_UNSAFE,'partial_truncation'))
        self.assertIn(a[-1]['date'],result[2])
        policy=json.loads((Path(__file__).resolve().parents[1]/'gateway/policy.example.json').read_text())
        policy['limits']=[]
        self.assertEqual(decide(policy,[result[0]],{})['decision'],BLOCK)

    def test_equal_counts_cannot_hide_missing_dates(self):
        a=[{'date':d} for d in ['2026-09-08','2026-09-09','2026-09-10','2026-09-11','2026-09-14']]
        s=[{'Date':d} for d in ['2026-09-04','2026-09-05','2026-09-08','2026-09-09','2026-09-10']]
        result=classify_truncation(s,a)
        self.assertEqual(result[:2],(FAIL_UNSAFE,'partial_truncation'))
        self.assertIn('2026-09-14',result[2])
        self.assertNotIn('no session is missing',result[2])

    def test_complete_reference_with_deeper_history(self):
        s,a=self.bars()
        self.assertEqual(classify_truncation([{'Date':'2026-08-31'}]+s,a)[0],PASS)

    def test_limits_typo_rejected(self):
        p=json.loads((Path(__file__).resolve().parents[1]/'gateway/policy.example.json').read_text())
        p['limit']=p.pop('limits')
        with self.assertRaises(PolicyError):decide(p,[PASS],{'action':{'notional_usd':999999999}})

    def test_policy_shape_errors_are_explicit(self):
        p=json.loads((Path(__file__).resolve().parents[1]/'gateway/policy.example.json').read_text())
        for key,value in [('limits',None),('limits',{}),('limits',[None]),('on_evidence',None)]:
            with self.subTest(key=key,value=value):
                q=copy.deepcopy(p);q[key]=value
                with self.assertRaises(PolicyError):validate_policy(q)

    def test_explicit_empty_limits_supported(self):
        p=json.loads((Path(__file__).resolve().parents[1]/'gateway/policy.example.json').read_text())
        p['limits']=[]
        validate_policy(p)

if __name__=='__main__':unittest.main()
