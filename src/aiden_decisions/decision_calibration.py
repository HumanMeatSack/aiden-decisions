"""Task-scoped temperature calibration and finite-sample evaluation, stdlib only."""
from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path


def questions_hash(questions):
    # Order is part of the model contract. Never reuse calibration after schema drift.
    return hashlib.sha256(json.dumps(questions, ensure_ascii=False, separators=(',', ':')).encode()).hexdigest()


def distribution(answer):
    if answer['type'] == 'noul':
        return {'false': 1 - answer['noul'], 'true': answer['noul']}
    return answer['probabilities']


def scale(probabilities, temperature):
    if isinstance(temperature, bool) or not math.isfinite(temperature) or not .05 <= temperature <= 20:
        raise ValueError('Invalid calibration temperature')
    if not isinstance(probabilities, dict) or len(probabilities) < 2:
        raise ValueError('Invalid distribution')
    if any(isinstance(p, bool) or not isinstance(p, (int, float)) or not math.isfinite(p) or not 0 <= p <= 1 for p in probabilities.values()):
        raise ValueError('Invalid probability')
    if abs(sum(probabilities.values()) - 1) > .01:
        raise ValueError('Invalid probability total')
    logs = {k: math.log(max(p, 1e-12)) / temperature for k, p in probabilities.items()}
    peak = max(logs.values())
    values = {k: math.exp(p - peak) for k, p in logs.items()}
    total = sum(values.values())
    return {k: p / total for k, p in values.items()}


def wilson(correct, total):
    if not total: return [0., 1.]
    z = 1.959963984540054
    p = correct / total; denom = 1 + z * z / total
    center = (p + z * z / (2 * total)) / denom
    half = z * math.sqrt(p * (1 - p) / total + z * z / (4 * total * total)) / denom
    return [max(0., center - half), min(1., center + half)]


def metrics(rows, temperature=1., bins=5):
    """Rows are (distribution, correct_label). ECE is descriptive, not a guarantee."""
    if not rows: raise ValueError('No evaluation rows')
    nll = brier = correct = 0; buckets = [[] for _ in range(bins)]
    for probabilities, label in rows:
        if label not in probabilities: raise ValueError('Label outside permitted options')
        ps = scale(probabilities, temperature)
        predicted = max(ps, key=ps.get); ok = predicted == label; confidence = ps[predicted]
        correct += ok; nll -= math.log(max(ps[label], 1e-12))
        brier += sum((p - (k == label)) ** 2 for k, p in ps.items())
        buckets[min(bins - 1, int(confidence * bins))].append((confidence, ok))
    reliability = []; ece = 0
    for index, bucket in enumerate(buckets):
        if not bucket: continue
        mean_p = sum(x[0] for x in bucket) / len(bucket); successes = sum(x[1] for x in bucket)
        accuracy = successes / len(bucket)
        ece += len(bucket) / len(rows) * abs(mean_p - accuracy)
        reliability.append({'low': index / bins, 'high': (index + 1) / bins,
                            'count': len(bucket), 'mean_probability': mean_p,
                            'accuracy': accuracy, 'accuracy_wilson_95': wilson(successes, len(bucket))})
    return {'count': len(rows), 'correct': correct, 'accuracy': correct / len(rows),
            'accuracy_wilson_95': wilson(correct, len(rows)), 'nll': nll / len(rows),
            'brier': brier / len(rows), 'ece_5_bins': ece, 'reliability': reliability}


def fit_temperature(rows):
    """One-dimensional fit using calibration rows only. No class-rank changes."""
    if len(rows) < 20: raise ValueError('At least 20 calibration rows are required')
    grid = sorted({1., *(math.exp(-2.99 + 5.98 * i / 120) for i in range(121))})
    return min(grid, key=lambda t: metrics(rows, t)['nll'])


def fit_correctness_bins(rows):
    """Estimate P(predicted label is correct), distinct from per-label probabilities."""
    edges = [0., .5, .75, .9, 1.000001]
    all_correct = sum(max(p, key=p.get) == label for p, label in rows)
    bins = []
    for low, high in zip(edges, edges[1:]):
        selected = [(p, label) for p, label in rows if low <= max(p.values()) < high]
        successes = sum(max(p, key=p.get) == label for p, label in selected)
        # Sparse bins use the overall fit partition, never validation/test labels.
        n, k = (len(selected), successes) if len(selected) >= 8 else (len(rows), all_correct)
        bins.append({'low': low, 'high': high, 'fit_count': n,
                     'estimate': (k+1)/(n+2), 'accuracy_wilson_95': wilson(k,n),
                     'pooled': len(selected) < 8})
    return bins


def correctness_estimate(probabilities, bins):
    p = max(probabilities.values())
    entry = next(b for b in bins if b['low'] <= p < b['high'])
    return entry['estimate'], entry


def correctness_metrics(rows, bins=None):
    predictions = []; errors = []
    for p, label in rows:
        score = max(p.values()) if bins is None else correctness_estimate(p, bins)[0]
        correct = max(p, key=p.get) == label
        predictions.append((score, correct)); errors.append((score-correct)**2)
    ece = 0
    for i in range(5):
        bucket = [r for r in predictions if i/5 <= r[0] < (i+1)/5 or i == 4 and r[0] == 1]
        if bucket:
            ece += len(bucket)/len(rows)*abs(sum(r[0] for r in bucket)/len(bucket)-sum(r[1] for r in bucket)/len(bucket))
    k = sum(r[1] for r in predictions)
    return {'count': len(rows), 'correct': k, 'accuracy': k/len(rows),
            'accuracy_wilson_95': wilson(k, len(rows)), 'correctness_brier': sum(errors)/len(rows), 'ece_5_bins': ece}


class CalibrationRegistry:
    def __init__(self, path):
        self.path = Path(path)

    def apply(self, result, questions, model, digest):
        """Add scoped probabilities without rewriting native probabilities or authority."""
        unavailable = {'status': 'unavailable', 'globally_calibrated': False}
        try:
            if self.path.is_symlink() or self.path.stat().st_size > 256 * 1024: return unavailable
            profile = json.loads(self.path.read_text())
            if (profile.get('version') != 1 or profile.get('model') != model
                    or profile.get('model_digest') != digest
                    or profile.get('questions_sha256') != questions_hash(questions)):
                return {'status': 'scope_or_model_mismatch', 'globally_calibrated': False}
            answers = {}
            for name, answer in result['answers'].items():
                evidence = profile['questions'][name]
                if not evidence['deployment_eligible']:
                    if evidence.get('correctness_eligible'):
                        estimate, bin_evidence = correctness_estimate(distribution(answer), evidence['correctness_bins'])
                        answers[name] = {'status': 'synthetic_prediction_confidence_supported',
                                         'estimated_prediction_correctness': estimate,
                                         'fit_bin_count': bin_evidence['fit_count'], 'pooled_bin': bin_evidence['pooled'],
                                         'accuracy_wilson_95': evidence['correctness_test']['scaled']['accuracy_wilson_95'],
                                         'heldout_accuracy': evidence['correctness_test']['scaled']['accuracy'],
                                         'heldout_count': evidence['correctness_test']['scaled']['count']}
                    else:
                        answers[name] = {'status': 'candidate_rejected', 'raw_distribution': True}
                    continue
                ps = scale(distribution(answer), evidence['temperature'])
                answers[name] = {'status': 'synthetic_holdout_supported',
                                 'probabilities': ps, 'top_probability': max(ps.values()),
                                 'temperature': evidence['temperature'],
                                 'heldout_accuracy': evidence['test']['scaled']['accuracy'],
                                 'heldout_count': evidence['test']['scaled']['count'],
                                 'accuracy_wilson_95': evidence['test']['scaled']['accuracy_wilson_95']}
            return {'status': 'task_scoped', 'globally_calibrated': False,
                    'scope': profile['scope'], 'method': 'temperature_scaling',
                    'dataset_sha256': profile['dataset_sha256'], 'answers': answers,
                    'suggestion_gate': profile['suggestion_gate']}
        except (OSError, ValueError, TypeError, KeyError):
            return unavailable
