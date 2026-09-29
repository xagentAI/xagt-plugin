"""Independent analytical cases and exhaustive encoding checks; stdlib only."""
import math
from itertools import product
import unittest

import benchmark as b


class ProtocolChecks(unittest.TestCase):
    def test_no_load_has_no_drop_or_losses(self):
        z = [.01 + .006j] * 6
        loads = [0j] * 6
        v, converged, _ = b.power_flow(z, loads)
        self.assertTrue(converged)
        self.assertEqual(v, [1 + 0j] * 7)
        checked = b.validate_ac(z, loads, v, converged)
        self.assertEqual(checked['status'], 'accepted')
        self.assertEqual(checked['slack_power_pu'], [0, 0])

    def test_one_branch_matches_closed_form_high_voltage_root(self):
        z, s = .01 + .006j, .08 + .04j
        a = (z * s.conjugate()).real
        discriminant = (1 - 2*a)**2 - 4 * abs(z)**2 * abs(s)**2
        w = (1 - 2*a + math.sqrt(discriminant)) / 2
        exact_voltage = w + z.conjugate() * s
        v, converged, _ = b.power_flow([z], [s])
        self.assertTrue(converged)
        self.assertLess(abs(v[1] - exact_voltage), 1e-11)
        self.assertLess(abs(abs(v[1])**2 - w), 1e-11)

    def test_all_solved_cases_conserve_complex_power(self):
        for bits in product((0, 1), repeat=b.N):
            for scale in b.SCALES:
                z, loads = b.network(bits, scale)
                v, converged, _ = b.power_flow(z, loads)
                self.assertTrue(converged)
                currents = [(v[i] - v[i + 1]) / zi for i, zi in enumerate(z)]
                losses = sum(zi * abs(i)**2 for zi, i in zip(z, currents))
                slack = v[0] * currents[0].conjugate()
                self.assertLess(abs(slack - sum(loads) - losses), 1e-9)

    def test_nonconvergence_is_unresolved(self):
        z, loads = b.network((0,) * 6, b.SCALES[-1])
        v, converged, _ = b.power_flow(z, loads, max_iter=1)
        self.assertFalse(converged)
        self.assertEqual(b.validate_ac(z, loads, v, converged)['status'], 'unresolved')

    def test_corrupted_solution_and_wrong_slack_rejected(self):
        z, loads = b.network((1,) * 6, b.SCALES[0])
        v, converged, _ = b.power_flow(z, loads)
        self.assertEqual(b.validate_ac(z, loads, v, converged)['status'], 'accepted')
        corrupt = v.copy()
        corrupt[3] += .001
        self.assertEqual(b.validate_ac(z, loads, corrupt)['status'], 'unresolved')
        # No-load voltages satisfy every nodal equation but the wrong slack is invalid.
        self.assertEqual(b.validate_ac(z, [0j]*6, [1.01+0j]*7)['status'], 'unresolved')

    def test_invalid_voltages_cannot_pass(self):
        z, loads = b.network((0,) * 6, b.SCALES[0])
        for value in (0j, complex(float('nan'), 0), complex(float('inf'), 0)):
            v = [1+0j] * 7
            v[1] = value
            self.assertEqual(b.validate_ac(z, loads, v)['status'], 'unresolved')

    def test_each_investment_vector_has_correct_penalty_projection(self):
        for x in product((0, 1), repeat=6):
            cost = sum(c*v for c, v in zip(b.COST, x))
            weighted = sum(w*v for w, v in zip(b.WEIGHTS, x))
            energies = []
            for y in product((0, 1), repeat=3):
                slack = y[0] + 2*y[1] + 4*y[2]
                explicit = cost + 28*(weighted - 15 - slack)**2
                self.assertEqual(b.qubo_energy(x+y), explicit)
                energies.append(explicit)
            self.assertEqual(min(energies) == cost, weighted >= 15)
            if weighted < 15:
                self.assertGreater(min(energies), sum(b.COST))

    def test_reference_catalogue_and_surrogate_ac_disagreement(self):
        report = b.run()
        self.assertEqual(report['A']['minimum_cost'], 18)
        self.assertEqual(report['B']['best_accepted_cost'], 20)
        self.assertEqual(report['C']['minimum_energy'], 18)
        self.assertEqual(report['A']['accepted'], 14)
        self.assertEqual(report['B']['accepted_plans'], 10)
        self.assertEqual(len(report['linear_accepted_but_ac_rejected']), 4)
        self.assertEqual(report['B']['unresolved_scenarios'], 0)
        self.assertFalse(report['B']['global_ac_optimum_certified'])


if __name__ == '__main__':
    unittest.main(verbosity=2)
