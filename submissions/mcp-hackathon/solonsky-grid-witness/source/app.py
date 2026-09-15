"""Gradio demonstration plus plain JSON REST API, hosted without paid compute."""
import os
os.environ['GRADIO_ANALYTICS_ENABLED'] = 'False'
import spaces
import gradio as gr
from api import router
from core import inspect_plan, compare_budget
from threading import Event

@spaces.GPU(duration=1)
def hosting_probe() -> str:
    """Optional free-host scheduler probe. Scientific calculations use CPU only."""
    return 'Host available. Grid calculations execute on CPU without GPU allocation.'

def inspect_text(plan: str) -> dict:
    """Inspect six binary characters in fixed edge order; returns numerical witnesses."""
    if len(plan) != 6 or any(c not in '01' for c in plan):
        raise gr.Error('Enter exactly six characters: 0 or 1, such as 111000.')
    return inspect_plan([int(c) for c in plan])

def budget_tool(budget: int) -> dict:
    """Compare all 64 synthetic upgrade plans within an integer cost budget 0 to 27."""
    return compare_budget(budget)

with gr.Blocks(title='Grid Witness') as demo:
    gr.Markdown('# Grid Witness\n### A second check before an agent trusts a simplified model\nA fixed synthetic six-line grid. Compare lossless screening with AC residual and operating-limit checks. **Educational benchmark, not engineering advice or a real-grid certificate.**')
    with gr.Tab('Inspect a plan'):
        plan = gr.Textbox(label='Upgrade plan — six binary characters', value='111000')
        result = gr.JSON(label='Evidence and decision')
        gr.Button('Check operating points', variant='primary').click(inspect_text, plan, result, api_name='inspect_plan')
        gr.Examples([['111000'], ['110110'], ['000000']], plan)
    with gr.Tab('Compare a budget'):
        budget = gr.Slider(0,27,value=20,step=1,label='Budget in arbitrary synthetic units')
        comparison = gr.JSON(label='Catalogue comparison')
        gr.Button('Enumerate 64 plans').click(budget_tool, budget, comparison, api_name='compare_budget')
    gr.Markdown('REST: `/v1/inspect-plan`, `/v1/compare-budget`, `/v1/benchmark` · [Source](https://github.com/alexsolonsky/grid-witness) · Alex SOLONSKY\n\nNo prompts, personal information or uploads are needed. Inputs are processed in memory; the hosting provider may retain access logs. No paid API, no external model, no quantum computation.')
    with gr.Accordion('Hosting diagnostics', open=False):
        gr.Button('Optional scheduler probe').click(hosting_probe, outputs=gr.Textbox(), api_name=False)

if __name__ == '__main__':
    demo.launch(server_name='0.0.0.0', server_port=int(os.environ.get('PORT',7860)),
                prevent_thread_lock=True, mcp_server=True, ssr_mode=False,
                run_history=False)
    # Add public JSON routes before Gradio's catch-all page route.
    existing = list(demo.app.router.routes)
    demo.app.include_router(router)
    added = demo.app.router.routes[len(existing):]
    demo.app.router.routes[:] = added + existing
    Event().wait()
