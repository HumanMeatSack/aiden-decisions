"""Freeze predictions, fit on calibration, select on validation, report untouched test."""
import argparse
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import time

from aiden_decisions.decisions import DecisionEngine, HOME_QUESTIONS
from aiden_decisions.decision_calibration import distribution, fit_temperature, fit_correctness_bins, correctness_estimate, correctness_metrics, metrics, questions_hash, scale, wilson

ROOT = Path(__file__).resolve().parents[1]


def evaluate(cases, predictions, engine):
    by_question = {}; temps = {}
    for name in HOME_QUESTIONS:
        partitions = {}
        for split in ['calibration', 'validation', 'test']:
            rows = []
            for case in cases:
                if case['split'] == split:
                    label = case['labels'][name]
                    if isinstance(label, bool): label = str(label).lower()
                    rows.append((distribution(predictions[case['id']]['answers'][name]), label))
            partitions[split] = rows
        fitted = fit_temperature(partitions['calibration'])
        val_raw = metrics(partitions['validation']); val_scaled = metrics(partitions['validation'], fitted)
        # Choose only using validation. Test is never consulted to choose a temperature.
        selected = fitted if val_scaled['nll'] <= val_raw['nll'] and val_scaled['brier'] <= val_raw['brier'] else 1.
        test_raw = metrics(partitions['test']); test_scaled = metrics(partitions['test'], selected)
        eligible = (selected != 1. and len(partitions['test']) >= 30
                    and test_scaled['accuracy'] >= .8
                    and test_scaled['nll'] <= test_raw['nll'] and test_scaled['brier'] <= test_raw['brier'])
        temps[name] = selected
        fitted_bins = fit_correctness_bins(partitions['calibration'])
        correct_val_raw = correctness_metrics(partitions['validation'])
        correct_val_scaled = correctness_metrics(partitions['validation'], fitted_bins)
        correct_test_raw = correctness_metrics(partitions['test'])
        correct_test_scaled = correctness_metrics(partitions['test'], fitted_bins)
        correctness_eligible = (len(partitions['test']) >= 30
            and correct_val_scaled['correctness_brier'] <= correct_val_raw['correctness_brier']
            and correct_val_scaled['ece_5_bins'] <= correct_val_raw['ece_5_bins']
            and correct_test_scaled['correctness_brier'] <= correct_test_raw['correctness_brier']
            and correct_test_scaled['ece_5_bins'] <= correct_test_raw['ece_5_bins'])
        by_question[name] = {'fitted_temperature': fitted, 'temperature': selected,
                             'deployment_eligible': eligible, 'calibration_count': len(partitions['calibration']),
                             'validation': {'raw': val_raw, 'scaled': val_scaled},
                             'test': {'raw': test_raw, 'scaled': test_scaled},
                             'correctness_bins': fitted_bins, 'correctness_eligible': correctness_eligible,
                             'correctness_validation': {'raw': correct_val_raw, 'scaled': correct_val_scaled},
                             'correctness_test': {'raw': correct_test_raw, 'scaled': correct_test_scaled}}
    def accepted(split, threshold):
        rows = []
        for c in cases:
            if c['split'] != split: continue
            answers = predictions[c['id']]['answers']; confidence = []; correct = True
            for name, a in answers.items():
                ps = scale(distribution(a), temps[name]); confidence.append(max(ps.values()))
                label = c['labels'][name]
                if isinstance(label, bool): label = str(label).lower()
                correct = correct and max(ps, key=ps.get) == label
            if min(confidence) >= threshold: rows.append(correct)
        return {'count': len(rows), 'correct': sum(rows), 'accuracy': sum(rows) / len(rows) if rows else None,
                'accuracy_wilson_95': wilson(sum(rows), len(rows))}
    candidates = [(t, accepted('validation', t)) for t in [.5, .6, .7, .8, .85, .9, .95, .98]]
    passing = [(t, r) for t, r in candidates if r['count'] >= 20 and r['accuracy_wilson_95'][0] >= .8]
    chosen = max(passing, key=lambda x: (x[1]['count'], x[0])) if passing else None
    gate = {'purpose': 'suggested_handler_only_no_action_authority', 'target_validation_lower_95': .8,
            'minimum_validation_count': 20, 'threshold': chosen[0] if chosen else None,
            'validation': chosen[1] if chosen else None,
            'test': accepted('test', chosen[0]) if chosen else None,
            'globally_validated': False}
    route_bins = by_question['route']['correctness_bins']
    def routing_acceptance(split, threshold):
        selected=[]
        for case in cases:
            if case['split'] != split: continue
            p=distribution(predictions[case['id']]['answers']['route'])
            score,_=correctness_estimate(p,route_bins)
            if score >= threshold: selected.append(max(p,key=p.get)==case['labels']['route'])
        return {'count':len(selected),'correct':sum(selected),
                'accuracy':sum(selected)/len(selected) if selected else None,
                'accuracy_wilson_95':wilson(sum(selected),len(selected))}
    choices=[(t,routing_acceptance('validation',t)) for t in [.5,.6,.7,.8,.85,.9,.95,.98]]
    choices=[(t,r) for t,r in choices if r['count']>=20 and r['accuracy_wilson_95'][0]>=.8]
    route_gate=max(choices,key=lambda x:(x[1]['count'],x[0])) if choices else None
    gate['routing_only']={'threshold':route_gate[0] if route_gate else None,
                         'validation':route_gate[1] if route_gate else None,
                         'test':routing_acceptance('test',route_gate[0]) if route_gate else None,
                         'purpose':'select_handler_only; never resolve arguments or grant permission'}
    return by_question, gate


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--cases', type=Path, default=ROOT/'benchmarks/aiden_decisions/calibration_cases.jsonl')
    parser.add_argument('--model', default=None)
    parser.add_argument('--profile-output', type=Path, default=ROOT/'output/aiden-decisions/calibration-profile.json')
    parser.add_argument('--reuse-predictions', type=Path, help='Recalculate metrics from frozen receipts; no new inference')
    parser.add_argument('--output', type=Path, default=ROOT/'output/aiden-decisions/calibration-evaluation.json')
    args = parser.parse_args(); raw = args.cases.read_bytes(); cases = [json.loads(x) for x in raw.splitlines() if x.strip()]
    assert len({c['id'] for c in cases}) == len(cases)
    assert len({c['request'].casefold() for c in cases}) == len(cases)
    assert Counter(c['split'] for c in cases).keys() == {'calibration', 'validation', 'test'}
    assert all(c['provenance'] == 'independently_authored_synthetic' for c in cases)
    engine = DecisionEngine(**({"model":args.model} if args.model else {})); engine.verify_model(); model_digest = engine.model_digest
    predictions = {}; latencies = []
    existing = None
    if args.reuse_predictions:
        existing = json.loads(args.reuse_predictions.read_text())
        assert existing['profile']['dataset_sha256'] == hashlib.sha256(raw).hexdigest()
        assert existing['profile']['model_digest'] == model_digest
        assert existing['profile']['questions_sha256'] == questions_hash(HOME_QUESTIONS)
        predictions = {r['case']['id']: r['result'] for r in existing['predictions']}
        assert set(predictions) == {c['id'] for c in cases}
    for i, case in enumerate(cases if existing is None else [], 1):
        started = time.monotonic()
        predictions[case['id']] = engine.decide({'state': {'user_request': case['request']}, 'questions': HOME_QUESTIONS}, use_cache=False)
        latencies.append((time.monotonic()-started)*1000)
        if i % 8 == 0: print(f'Frozen predictions {i}/{len(cases)}', flush=True)
    engine.verify_model(); assert engine.model_digest == model_digest, 'Model changed during evaluation'
    questions, gate = evaluate(cases, predictions, engine)
    profile = {'version': 1, 'created_utc': datetime.now(timezone.utc).isoformat(), 'model': engine.model,
               'model_digest': model_digest, 'questions_sha256': questions_hash(HOME_QUESTIONS),
               'dataset_sha256': hashlib.sha256(raw).hexdigest(),
               'scope': 'Independently authored synthetic home-handler, explicit room and ambiguity cases; no real-world guarantee',
               'questions': questions, 'suggestion_gate': gate}
    out = args.output; out.parent.mkdir(parents=True, exist_ok=True)
    ordered = sorted(latencies)
    report = {'profile': profile, 'split_counts': dict(Counter(c['split'] for c in cases)),
              'latency': existing['latency'] if existing else {'p50_ms': ordered[len(ordered)//2], 'p95_ms': ordered[int(.95*len(ordered))]},
              'protocol': 'Fit calibration only; select temperature/gate using validation only; untouched test for reporting and ship/no-ship checks',
              'predictions': [{'case': c, 'result': predictions[c['id']]} for c in cases]}
    out.write_text(json.dumps(report, indent=2)+'\n')
    target = args.profile_output; target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(profile, indent=2)+'\n')
    print(json.dumps({'split_counts': report['split_counts'], 'questions': {n: {'temperature': q['temperature'],
          'deployment_eligible': q['deployment_eligible'], 'test_accuracy': q['test']['scaled']['accuracy'],
          'correctness_eligible': q['correctness_eligible'],
          'raw_correctness_brier':q['correctness_test']['raw']['correctness_brier'],
          'calibrated_correctness_brier':q['correctness_test']['scaled']['correctness_brier'],
          'raw_nll': q['test']['raw']['nll'], 'scaled_nll': q['test']['scaled']['nll']} for n, q in questions.items()},
          'gate': gate, 'receipt': str(out)}, indent=2), flush=True)


if __name__ == '__main__': main()
