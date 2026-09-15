import os
import unittest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from api import router
from core import inspect_plan, compare_budget

app=FastAPI(); app.include_router(router)
client=TestClient(app)
class ApiTests(unittest.TestCase):
    def test_optimistic_false_positive(self):
        r=client.post('/v1/inspect-plan',json={'bits':[1,1,1,0,0,0]})
        self.assertEqual(r.status_code,200)
        x=r.json(); self.assertTrue(x['A_accepted']); self.assertFalse(x['B_accepted'])
        self.assertTrue(x['linear_false_positive']); self.assertGreater(x['witnesses'][0]['violation_pu'],0)
    def test_budget_boundary(self):
        self.assertIsNone(compare_budget(19)['cheapest_accepted_cost'])
        self.assertEqual(compare_budget(20)['cheapest_accepted_cost'],20)
        self.assertEqual(len(compare_budget(20)['cheapest_accepted_plans']),2)
    def test_exhaustive_api_parity(self):
        from itertools import product
        import benchmark
        for row in benchmark.run()['catalogue']:
            got=inspect_plan(row['bits'])
            for key in row: self.assertEqual(got[key],row[key])
    def test_strict_input(self):
        bad=[None,[],[1]*7,[True]*6,[1.0]*6,['1']*6,[2]*6]
        for v in bad:
            self.assertEqual(client.post('/v1/inspect-plan',json={'bits':v}).status_code,400)
        for v in [True,-1,28,1.5,'20',None]:
            self.assertEqual(client.post('/v1/compare-budget',json={'budget':v}).status_code,400)
    def test_malformed_and_extra(self):
        for raw in ['{','NaN','[]','{"bits":[0,0,0,0,0,0],"secret":"never"}', 'x'*2049]:
            self.assertEqual(client.post('/v1/inspect-plan',content=raw,headers={'content-type':'application/json'}).status_code,400)
        self.assertEqual(client.post('/v1/inspect-plan',content='{}').status_code,400)
    def test_no_global_result_mutation(self):
        r=inspect_plan([1]*6);r['scenarios'].clear()
        self.assertEqual(len(inspect_plan([1]*6)['scenarios']),3)
    def test_health_binding(self):
        prior=os.environ.get('SOURCE_COMMIT')
        try:
            os.environ['SOURCE_COMMIT']='a'*40
            self.assertEqual(client.get('/health').json(),{'status':'ok','commit':'a'*40})
            self.assertEqual(client.get('/.well-known/xagent-verification.json').json()['commit'],'a'*40)
            os.environ['SOURCE_COMMIT']='invalid'
            self.assertEqual(client.get('/health').status_code,503)
        finally:
            if prior is None: os.environ.pop('SOURCE_COMMIT',None)
            else: os.environ['SOURCE_COMMIT']=prior
    def test_unknown_route(self):
        self.assertEqual(client.get('/v1/arbitrary-network').status_code,404)
if __name__=='__main__':unittest.main()
