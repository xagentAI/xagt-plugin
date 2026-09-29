"""Synthetic protocol demonstrator. Standard library only; no quantum computation.

Balanced single-phase equivalent, fixed radial chain, constant PQ loads, no shunts.
All electrical quantities are per unit. Not an E.ON dataset or industrial model.
"""
from fractions import Fraction as F
from itertools import product
from pathlib import Path
import hashlib
import json
import math
import platform
import time

N = 6
COST = (7, 6, 5, 4, 3, 2)  # arbitrary synthetic cost units, not EUR
WEIGHTS = (6, 5, 4, 3, 2, 1)
SCALES = (F(3, 5), F(1), F(6, 5))
VMIN2 = F(966304, 1000000)
VMAX2 = F(11025, 10000)
IMAX = F(1)
PF_TOL = 1e-12
RESIDUAL_TOL = 1e-9  # per-unit complex power and current mismatch
LIMIT_TOL = 1e-10  # per-unit voltage/current, solely floating point comparison


def network(bits, scale):
    """Each edge's upgrade halves both r and x; ratings remain unchanged."""
    z = [complex(.01, .006) * (1 - .5 * bit) for bit in bits]
    loads = [complex(.08, .04) * float(scale)] * len(bits)
    return z, loads


def linear_check(bits, scale):
    """Lossless LinDistFlow screening, exact rational squared-voltage arithmetic.

    Thermal screening uses |S_edge| at assumed voltage 1 p.u., not AC current.
    """
    v2 = F(1)
    voltages = [v2]
    max_i2 = F(0)
    for edge, bit in enumerate(bits):
        count = len(bits) - edge
        p, q = F(2, 25) * scale * count, F(1, 25) * scale * count
        factor = F(1) - F(bit, 2)
        r, x = F(1, 100) * factor, F(3, 500) * factor
        v2 -= 2 * (r * p + x * q)
        voltages.append(v2)
        max_i2 = max(max_i2, p * p + q * q)
    return {
        'accepted': all(VMIN2 <= v <= VMAX2 for v in voltages)
                    and max_i2 <= IMAX * IMAX,
        'minimum_v_squared_exact': str(min(voltages)),
        'minimum_v_squared': float(min(voltages)),
        'maximum_current_proxy_squared': float(max_i2),
    }


def power_flow(z, loads, max_iter=500):
    """Backward/forward sweep. Return voltages; validation is independent."""
    v = [1 + 0j] * (len(z) + 1)
    for iteration in range(1, max_iter + 1):
        try:
            injection = [(s / vi).conjugate() for s, vi in zip(loads, v[1:])]
        except ZeroDivisionError:
            return v, False, iteration
        downstream, currents = 0j, [0j] * len(z)
        for edge in reversed(range(len(z))):
            downstream += injection[edge]
            currents[edge] = downstream
        new = [1 + 0j]
        for impedance, current in zip(z, currents):
            new.append(new[-1] - impedance * current)
        if not all(math.isfinite(x.real) and math.isfinite(x.imag) for x in new):
            return v, False, iteration
        difference = max(abs(a - b) for a, b in zip(v, new))
        v = new
        if difference <= PF_TOL:
            return v, True, iteration
    return v, False, max_iter


def validate_ac(z, loads, voltages, converged=True):
    """Recompute currents from Ohm's law, not the sweep's stored currents."""
    if len(z) != len(loads) or len(voltages) != len(z) + 1:
        raise ValueError('Inconsistent network/voltage dimensions')
    if (not all(math.isfinite(v.real) and math.isfinite(v.imag) for v in voltages)
            or any(abs(v) == 0 for v in voltages[1:])):
        return dict(status='unresolved', reason='nonfinite_or_zero_voltage')
    currents = [(voltages[i] - voltages[i + 1]) / zi for i, zi in enumerate(z)]
    max_power, max_current = 0., 0.
    for i, s in enumerate(loads):
        outgoing = currents[i + 1] if i + 1 < len(currents) else 0j
        net = currents[i] - outgoing
        max_power = max(max_power, abs(voltages[i + 1] * net.conjugate() - s))
        demand_i = (s / voltages[i + 1]).conjugate()
        max_current = max(max_current, abs(net - demand_i))
    magnitudes = [abs(v) for v in voltages]
    min_v, max_v = min(magnitudes), max(magnitudes)
    max_i = max(map(abs, currents), default=0.)
    slack_residual = abs(voltages[0] - (1 + 0j))
    residual_ok = max(max_power, max_current, slack_residual) <= RESIDUAL_TOL
    limits_ok = (min_v >= math.sqrt(float(VMIN2)) - LIMIT_TOL
                 and max_v <= math.sqrt(float(VMAX2)) + LIMIT_TOL
                 and max_i <= float(IMAX) + LIMIT_TOL)
    if not converged or not residual_ok:
        status = 'unresolved'
    elif not limits_ok:
        status = 'returned_operating_point_violates_limits'
    else:
        status = 'accepted'
    slack = voltages[0] * currents[0].conjugate() if currents else 0j
    return dict(status=status, min_voltage_pu=min_v, max_voltage_pu=max_v,
                max_current_pu=max_i, max_power_residual_pu=max_power,
                max_current_residual_pu=max_current,
                slack_voltage_residual_pu=slack_residual,
                slack_power_pu=[slack.real, slack.imag],
                max_voltage_violation_pu=max(0, math.sqrt(float(VMIN2)) - min_v,
                                             max_v - math.sqrt(float(VMAX2))),
                max_thermal_violation_pu=max(0, max_i - float(IMAX)))


def qubo_coefficients():
    """C(x)+28*(sum(w*x)-15-s)^2, with s=y0+2*y1+4*y2."""
    coefficients = list(WEIGHTS) + [-1, -2, -4]
    penalty = sum(COST) + 1
    linear = [penalty * (a * a - 30 * a) + (COST[i] if i < N else 0)
              for i, a in enumerate(coefficients)]
    quadratic = {(i, j): 2 * penalty * coefficients[i] * coefficients[j]
                 for i in range(9) for j in range(i + 1, 9)}
    return penalty * 225, linear, quadratic


def qubo_energy(bits):
    constant, h, j = qubo_coefficients()
    return constant + sum(a * b for a, b in zip(h, bits)) + sum(
        a * bits[i] * bits[k] for (i, k), a in j.items())


def run():
    started = time.perf_counter()
    records = []
    for bits in product((0, 1), repeat=N):
        scenarios = []
        for scale in SCALES:
            z, loads = network(bits, scale)
            v, converged, iterations = power_flow(z, loads)
            scenarios.append(dict(scale=str(scale), A=linear_check(bits, scale),
                                  B=validate_ac(z, loads, v, converged),
                                  iterations=iterations))
        accepted_a = all(s['A']['accepted'] for s in scenarios)
        accepted_b = all(s['B']['status'] == 'accepted' for s in scenarios)
        unresolved = any(s['B']['status'] == 'unresolved' for s in scenarios)
        records.append(dict(bits=list(bits), cost=sum(c*x for c, x in zip(COST, bits)),
                            A_accepted=accepted_a, B_accepted=accepted_b,
                            B_unresolved=unresolved, scenarios=scenarios))
    a_records = [r for r in records if r['A_accepted']]
    b_records = [r for r in records if r['B_accepted']]
    a_min = min(r['cost'] for r in a_records)
    b_min = min((r['cost'] for r in b_records), default=None)
    energy_records = [dict(encoded_bits=list(bits), energy=qubo_energy(bits))
                      for bits in product((0, 1), repeat=9)]
    minimum_energy = min(r['energy'] for r in energy_records)
    winners = [r for r in energy_records if r['energy'] == minimum_energy]
    # Derivation is valid only for this monotonic fixed-topology toy instance.
    a_equivalence = all(r['A_accepted'] == (sum(w*x for w, x in zip(WEIGHTS, r['bits'])) >= 15)
                        for r in records)
    c_winners_match = all(r['encoded_bits'][:6] in
                          [a['bits'] for a in a_records if a['cost'] == a_min]
                          for r in winners)
    c_expansion_matches = all(
        r['energy'] == sum(c*x for c, x in zip(COST, r['encoded_bits'][:N]))
        + 28 * (sum(w*x for w, x in zip(WEIGHTS, r['encoded_bits'][:N])) - 15
                - sum(w*x for w, x in zip((1, 2, 4), r['encoded_bits'][N:]))) ** 2
        for r in energy_records)
    report = dict(
        status='executed_synthetic_classical_protocol_demonstrator_not_submission',
        quantum_computation_performed=False, sponsor_data_used=False,
        implementation_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        python_version=platform.python_version(),
        specification=dict(topology='chain 0-1-2-3-4-5-6; bus 0 slack at 1+0j',
            units='per unit; arbitrary synthetic capital cost units',
            base_line_impedance_pu=[.01,.006], upgraded_line_impedance_pu=[.005,.003],
            ampacity_pu=1, base_bus_PQ_pu=[.08,.04], scenario_scales=list(map(str,SCALES)),
            voltage_min_squared_exact=str(VMIN2), voltage_max_squared_exact=str(VMAX2),
            costs=list(COST), pf_voltage_tolerance_pu=PF_TOL,
            residual_absolute_tolerance_pu=RESIDUAL_TOL, floating_limit_tolerance_pu=LIMIT_TOL,
            initialization='flat 1+0j; no fallback', max_pf_iterations=500),
        A=dict(plans=64, accepted=len(a_records), minimum_cost=a_min,
               minimizing_plans=[r['bits'] for r in a_records if r['cost']==a_min],
               exact_arithmetic=True, scope='specified rational lossless model only'),
        B=dict(evaluations=64*len(SCALES), accepted_plans=len(b_records),
               best_accepted_cost=b_min,
               best_accepted_plans=[r['bits'] for r in b_records if r['cost']==b_min],
               unresolved_scenarios=sum(s['B']['status']=='unresolved' for r in records for s in r['scenarios']),
               unresolved_cheaper_plans=[r['bits'] for r in records if r['B_unresolved'] and (b_min is None or r['cost']<b_min)],
               global_ac_optimum_certified=False),
        C=dict(encoded_variables=9, investment_variables=6, slack_bits=3,
               enumerated_states=512, penalty=28, minimum_energy=minimum_energy,
               minimizers=winners, all_64_A_predicates_match_surrogate=a_equivalence,
               minimizers_match_A=c_winners_match,
               all_512_expanded_energies_match_squared_penalty=c_expansion_matches,
               scope='terminal-voltage surrogate equivalent to A only on this crafted instance'),
        linear_accepted_but_ac_rejected=[r['bits'] for r in records if r['A_accepted'] and not r['B_accepted']],
        wall_seconds=time.perf_counter()-started,
        limitations=['Synthetic single-phase equivalent with scaled positive PQ demand only.',
            'No renewable scenarios, held-out evaluation, contingencies, topology changes or flexible controls.',
            'No independent external power-flow package or certified AC uniqueness/global solver.',
            'No QAOA, quantum hardware, speedup, heuristic comparison or industrial-scale evidence.',
            'E.ON full brief and actual application fields remain unverified.'],
        catalogue=records)
    if not (a_equivalence and c_winners_match and c_expansion_matches and minimum_energy == a_min):
        raise RuntimeError('Reference or encoding validation failed; no result should be used')
    return report


if __name__ == '__main__':
    report = run()
    destination = Path(__file__).with_name('results.json')
    destination.write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps({k: report[k] for k in ['A','B','C','wall_seconds']}, indent=2))
