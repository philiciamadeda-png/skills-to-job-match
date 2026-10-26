import json
import re
import time
import pathlib

from django.core.management.base import BaseCommand

from apps.intelligence.models import Job
from apps.intelligence.ml_service import predict_batch

MERGE = {
    'junior': 'junior', 'intern': 'junior',
    'mid': 'senior',
    'senior': 'senior',
    'lead': 'senior_plus', 'principal': 'senior_plus',
    'director': 'senior_plus', 'manager': 'senior_plus',
    'not stated': None,
}

KW_RULES = [
    ('senior_plus', re.compile(r'\b(lead|principal|staff|head|director|manager|vp)\b', re.I)),
    ('junior',      re.compile(r'\b(junior|jr|graduate|intern|entry.?level|trainee|werkstudent)\b', re.I)),
    ('senior',      re.compile(r'\b(senior|sr)\b', re.I)),
]


def kw_predict(title):
    for label, pat in KW_RULES:
        if pat.search(title):
            return label
    return 'senior'


class Command(BaseCommand):
    help = 'Compare keyword rule vs ML model on the hand-labelled eval set.'

    def add_arguments(self, parser):
        parser.add_argument(
            '--eval-set',
            default='apps/intelligence/fixtures/eval_set.json',
        )

    def handle(self, *args, **options):
        path = pathlib.Path(options['eval_set'])
        eval_data = json.loads(path.read_text())

        rows = []
        for d in eval_data:
            label_3 = MERGE.get(d['seniority'])
            if label_3 is None:
                continue
            job = Job.objects.filter(title=d['title']).first() or \
                  Job.objects.filter(title__startswith=d['title'][:30]).first()
            if job is None:
                self.stdout.write(f"  UNMATCHED: {d['title']}")
                continue
            rows.append({'title': job.title, 'description': job.description, 'true': label_3})

        n = len(rows)
        self.stdout.write(f'\nEval rows matched: {n}/20\n')

        # Keyword rule
        kw_preds = [kw_predict(r['title']) for r in rows]
        kw_acc = sum(p == r['true'] for p, r in zip(kw_preds, rows)) / n

        # ML model
        t0 = time.perf_counter()
        texts = [r['title'] + ' ' + r['description'] for r in rows]
        ml_results = predict_batch(texts)
        ml_time = time.perf_counter() - t0
        ml_preds = [r['label'] for r in ml_results]
        ml_acc = sum(p == r['true'] for p, r in zip(ml_preds, rows)) / n

        self.stdout.write(
            f"{'Approach':<20} {'Accuracy':>9} {'Time/1k jobs':>14}\n"
            f"{'-'*46}\n"
            f"{'Keyword rule':<20} {kw_acc:>9.3f} {'<1s':>14}\n"
            f"{'ML model (v1)':<20} {ml_acc:>9.3f} {ml_time/n*1000:>13.1f}s\n"
            f"{'LLM (best prompt)':<20} {'0.526':>9} {'~30-60min':>14}\n"
        )

        self.stdout.write('\nPer-job breakdown:')
        self.stdout.write(f"{'Title':<44} {'True':>12} {'KW':>10} {'ML':>10} {'Conf':>6}")
        self.stdout.write('-' * 88)
        for r, kp, mp, mr in zip(rows, kw_preds, ml_preds, ml_results):
            kw_mark = '✓' if kp == r['true'] else '✗'
            ml_mark = '✓' if mp == r['true'] else '✗'
            self.stdout.write(
                f"{r['title'][:43]:<44} {r['true']:>12} "
                f"{kp+kw_mark:>10} {mp+ml_mark:>10} {mr['confidence']:>6.3f}"
            )
