"""Reproduce the priced calibration check; do not enable a losing calibrator."""
import argparse
import json
import os
import sys
sys.path.insert(0,os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import calibration
import ledger

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--from',dest='lo',default='2026-10-15');p.add_argument('--to',dest='hi',default='2026-10-20');p.add_argument('--out',default='research/pick_quality_recheck.json');a=p.parse_args()
    entries=list(ledger.load().values())
    report=dict(priced_graded=len(calibration.graded(entries)),calibration_enabled=calibration.ENABLED,
                study=calibration.study(entries,a.lo,a.hi),promotion='none: historical diagnostic; no new forecaster promoted')
    with open(a.out,'w') as f:json.dump(report,f,indent=2);f.write('\n')
    print(json.dumps(report['study']['fitted'],indent=2));print(report['study']['logloss_diff_fitted'])
