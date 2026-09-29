"""Bounded, deterministic tools for the fixed synthetic benchmark."""
from copy import deepcopy
from functools import lru_cache
import benchmark

SCOPE = 'Fixed synthetic six-line single-phase example; not a real-grid design or global AC feasibility certificate.'

@lru_cache(maxsize=1)
def _report():
    return benchmark.run()

def validate_bits(bits):
    if not isinstance(bits, list) or len(bits) != 6 or any(type(b) is not int or b not in (0, 1) for b in bits):
        raise ValueError('bits must be exactly six integer 0 or 1 values in edge order 0-1 through 5-6')

def inspect_plan(bits: list[int]) -> dict:
    """Compare a six-bit upgrade plan across load scales 0.6, 1.0 and 1.2.

    Returns linear screening, AC residual/limit evidence and an explicit decision.
    A limit violation describes the returned operating point, not a proof that
    every possible AC solution is infeasible. Costs are synthetic, never money.
    """
    validate_bits(bits)
    row = next(r for r in _report()['catalogue'] if r['bits'] == bits)
    out = deepcopy(row)
    if row['B_unresolved']:
        decision = 'unresolved'
    elif row['B_accepted']:
        decision = 'accepted_operating_points'
    else:
        decision = 'returned_operating_point_violates_limits'
    out.update(decision=decision, linear_false_positive=row['A_accepted'] and not row['B_accepted'], scope=SCOPE,
               cost_units='arbitrary synthetic units', quantum_computation_performed=False)
    out['witnesses'] = [dict(scale=s['scale'], min_voltage_pu=s['B'].get('min_voltage_pu'),
        voltage_limit_pu=float(benchmark.VMIN2)**0.5,
        violation_pu=s['B'].get('max_voltage_violation_pu'), status=s['B']['status'])
        for s in row['scenarios'] if s['B']['status'] != 'accepted']
    return out

def compare_budget(budget: int) -> dict:
    """Enumerate all 64 synthetic plans and return cheapest AC-accepted plans within budget.

    budget is an integer from 0 to 27 in arbitrary cost units. Enumeration is
    exhaustive over this catalogue, but AC global optimality is not certified.
    """
    if type(budget) is not int or not 0 <= budget <= 27:
        raise ValueError('budget must be an integer from 0 through 27 in synthetic cost units')
    report = _report()
    within = [r for r in report['catalogue'] if r['cost'] <= budget]
    ac = [r for r in within if r['B_accepted']]
    best = min((r['cost'] for r in ac), default=None)
    return dict(budget=budget, cost_units='arbitrary synthetic units', enumerated_plans=64,
        plans_within_budget=len(within), ac_accepted_within_budget=len(ac),
        cheapest_accepted_cost=best,
        cheapest_accepted_plans=[r['bits'] for r in ac if r['cost'] == best],
        linear_false_positives=[dict(bits=r['bits'], cost=r['cost']) for r in within if r['A_accepted'] and not r['B_accepted']],
        verdict='accepted_operating_points_found' if ac else 'no_accepted_operating_point_found_within_budget',
        global_ac_optimum_certified=False, scope=SCOPE)

def summary() -> dict:
    report = _report()
    return dict(scope=SCOPE, plans=64, scenarios_per_plan=3, linear_accepted=report['A']['accepted'],
        ac_accepted=report['B']['accepted_plans'], linear_min_cost=report['A']['minimum_cost'],
        ac_best_accepted_cost=report['B']['best_accepted_cost'],
        linear_false_positives=deepcopy(report['linear_accepted_but_ac_rejected']),
        specification=deepcopy(report['specification']), limitations=deepcopy(report['limitations'][:-1]),
        quantum_computation_performed=False)
