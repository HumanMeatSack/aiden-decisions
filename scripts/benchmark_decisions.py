"""Evaluate frozen synthetic cases locally; never send commands to devices."""
from pathlib import Path
import argparse
import hashlib
import json
import statistics
import time

from aiden_decisions.decisions import DecisionEngine

ROOT=Path(__file__).resolve().parents[1]

def main():
    p=argparse.ArgumentParser()
    p.add_argument('--cases',type=Path,default=ROOT/'benchmarks/aiden_decisions/cases.jsonl')
    p.add_argument('--output',type=Path,default=ROOT/'output/aiden-decisions/benchmark.json')
    args=p.parse_args();raw=args.cases.read_bytes();cases=[json.loads(line) for line in raw.splitlines() if line.strip()]
    engine=DecisionEngine();records=[];latencies={};brier=[]
    for case in cases:
        started=time.perf_counter()
        try:
            if case['kind']=='home':
                result=engine.home_route(case['request'],use_cache=False)
                actual=result['route'];ok=actual==case['expected'];source=result['source']
            else:
                result=engine.decide(case['payload'],use_cache=False);actual={};ok=True;source='local_decision_model'
                for name,expected in case['expected'].items():
                    answer=result['answers'][name]
                    if answer['type']=='choice':value=answer['choice']
                    elif answer['type']=='noul':
                        value=answer['noul']>=.5;brier.append((answer['noul']-int(expected))**2)
                    else:value=int(max(answer['probabilities'],key=answer['probabilities'].get))
                    actual[name]=value;ok=ok and value==expected
            elapsed=round((time.perf_counter()-started)*1000,3)
            latencies.setdefault(source,[]).append(elapsed)
            records.append({'id':case['id'],'kind':case['kind'],'correct':ok,'expected':case['expected'],
                            'actual':actual,'latency_ms':elapsed,'source':source,'result':result})
        except Exception as e:
            records.append({'id':case['id'],'kind':case['kind'],'correct':False,'error':type(e).__name__})
        if len(records)%10==0:print(f'Checked {len(records)}/{len(cases)} cases',flush=True)
    def timing(values):
        ordered=sorted(values);return {'count':len(values),'p50_ms':statistics.median(values),
                                       'p95_ms':ordered[min(len(ordered)-1,int(.95*len(ordered)))],
                                       'max_ms':max(values)}
    summary={'model':engine.model,'cases_sha256':hashlib.sha256(raw).hexdigest(),'total':len(records),
             'correct':sum(r['correct'] for r in records),'accuracy':sum(r['correct'] for r in records)/len(records),
             'latency':{k:timing(v) for k,v in latencies.items()},
             'noul_brier_score':statistics.mean(brier) if brier else None,
             'calibration':'No calibrated-accuracy claim; raw model distribution only',
             'authority':'none','comparison':'Synthetic local checks; not a Jev head-to-head or broad quality benchmark'}
    for kind in ['home','typed']:
        group=[r for r in records if r['kind']==kind];summary[kind]={'correct':sum(r['correct'] for r in group),'total':len(group)}
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps({'summary':summary,'cases':records},ensure_ascii=False,indent=2)+'\n')
    print(json.dumps(summary,indent=2),flush=True)

if __name__=='__main__':main()
