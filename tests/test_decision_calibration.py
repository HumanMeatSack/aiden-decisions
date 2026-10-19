import json
import math
from pathlib import Path
import tempfile
import unittest

from aiden_decisions.decision_calibration import CalibrationRegistry, fit_temperature, fit_correctness_bins, correctness_estimate, correctness_metrics, metrics, questions_hash, scale, wilson


class CalibrationTests(unittest.TestCase):
    def test_temperature_preserves_rank_and_finite_normalization(self):
        for t in [.05,.5,1.,3.,20.]:
            p=scale({'a':.98,'b':.01,'c':.01},t)
            self.assertAlmostEqual(sum(p.values()),1.)
            self.assertEqual(max(p,key=p.get),'a')
            self.assertTrue(all(math.isfinite(v) for v in p.values()))

    def test_metrics_and_finite_sample_interval(self):
        m=metrics([({'a':.9,'b':.1},'a'),({'a':.9,'b':.1},'b')])
        self.assertEqual(m['accuracy'],.5)
        self.assertAlmostEqual(m['ece_5_bins'],.4)
        self.assertLess(wilson(20,20)[0],1.)

    def test_fitting_can_reduce_overconfidence_without_changing_accuracy(self):
        rows=[({'a':.99,'b':.01}, 'a' if i%2 else 'b') for i in range(40)]
        t=fit_temperature(rows)
        self.assertGreater(t,1.)
        self.assertLess(metrics(rows,t)['nll'],metrics(rows)['nll'])
        self.assertEqual(metrics(rows,t)['accuracy'],metrics(rows)['accuracy'])

    def test_scope_order_is_fingerprinted(self):
        self.assertNotEqual(questions_hash({'a':1,'b':2}),questions_hash({'b':2,'a':1}))

    def test_missing_corrupt_and_wrong_model_artifacts_cannot_calibrate(self):
        with tempfile.TemporaryDirectory() as directory:
            p=Path(directory)/'cal.json'; registry=CalibrationRegistry(p)
            self.assertEqual(registry.apply({}, {}, 'm','d')['status'],'unavailable')
            p.write_text('{}')
            self.assertEqual(registry.apply({}, {}, 'm','d')['status'],'scope_or_model_mismatch')
            p.write_text('not JSON')
            self.assertEqual(registry.apply({}, {}, 'm','d')['status'],'unavailable')

    def test_failed_candidate_does_not_rewrite_raw_probability(self):
        with tempfile.TemporaryDirectory() as directory:
            p=Path(directory)/'cal.json'
            profile={'version':1,'model':'m','model_digest':'d','questions_sha256':questions_hash({'q':1}),
                     'scope':'synthetic','dataset_sha256':'x','suggestion_gate':{'threshold':None},
                     'questions':{'q':{'deployment_eligible':False}}}
            p.write_text(json.dumps(profile))
            result={'answers':{'q':{'type':'noul','noul':.99}}}
            calibrated=CalibrationRegistry(p).apply(result,{'q':1},'m','d')
            self.assertEqual(calibrated['answers']['q']['status'],'candidate_rejected')
            self.assertEqual(result['answers']['q']['noul'],.99)
            self.assertFalse(calibrated['globally_calibrated'])

    def test_invalid_temperatures_and_probabilities_are_rejected(self):
        for t in [0.,float('nan'),100.,True]:
            with self.assertRaises(ValueError):scale({'a':.5,'b':.5},t)
        for p in [{'a':1,'b':1},{'a':float('nan'),'b':.5}]:
            with self.assertRaises(ValueError):scale(p,1.)

    def test_prediction_correctness_estimate_uses_fit_labels_only(self):
        fit=[({'yes':.99,'no':.01},'yes' if i%2 else 'no') for i in range(40)]
        bins=fit_correctness_bins(fit); score,evidence=correctness_estimate({'yes':.99,'no':.01},bins)
        self.assertEqual(score,.5);self.assertEqual(evidence['fit_count'],40)
        test=[({'yes':.99,'no':.01},'yes' if i%2 else 'no') for i in range(20)]
        self.assertLess(correctness_metrics(test,bins)['correctness_brier'],correctness_metrics(test)['correctness_brier'])

    def test_sparse_confidence_bins_use_calibration_pool_and_show_it(self):
        fit=[({'a':.99,'b':.01},'a') for _ in range(30)]
        _, evidence=correctness_estimate({'a':.6,'b':.4},fit_correctness_bins(fit))
        self.assertTrue(evidence['pooled']);self.assertEqual(evidence['fit_count'],30)


if __name__=='__main__':unittest.main()
