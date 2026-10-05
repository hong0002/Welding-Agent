"""SDK-selected high-level operations; no coordinates, commands or file parameters."""
from typing import Literal
from agents import function_tool,RunContextWrapper
from backend.agent.context import WeldingAgentContext,workspace_summary
from backend.agent.config import AgentFault
from backend.agent.decision import RequestIntent,DecisionIntent
from backend.agent.semantic import SemanticAction
from backend.agent.tools import invalid_arguments,detect_mask_request,_plan,route_clarification_request
from backend.services.semantic_mask import AmbiguousMaskEdit

@function_tool(failure_error_function=invalid_arguments)
async def choose_welding_action(ctx:RunContextWrapper[WeldingAgentContext],action:SemanticAction)->dict:
    """After get_workspace_state, interpret THIS user's act with current workspace/history.
    Choose edit/removal vs current-mask refinement vs fresh re-detection; rough vs final.
    Status/questions select STATUS_OR_EXPLANATION, ambiguous requests CLARIFICATION.
    MASK_APPROVE only asks for human Canvas approval. A turn cannot switch actions.
    """
    async def select():
        ctx.context.choose_action(action)
        return {'action':action,'human_approval_only':action=='MASK_APPROVE'}
    return await ctx.context.call('choose_welding_action',select)

@function_tool(failure_error_function=invalid_arguments)
async def edit_weld_mask(ctx:RunContextWrapper[WeldingAgentContext],operation:Literal['REMOVE','KEEP_ONLY'],
                         target_relation:Literal['LEFT','RIGHT','TOP','BOTTOM','MIDDLE','FIRST','SECOND'],
                         reason:Literal['ALREADY_WELDED','EXCLUDED_BY_USER'],view:Literal['F','R','S4'])->dict:
    """MASK_EDIT only: whole current components selected by backend geometry. No approval gate.
    Never crop a connected region or supply pixels/polygons. Ambiguity returns a question.
    Changed pixels are unapproved and invalidate downstream; human must review again.
    """
    c=ctx.context
    def edit():
        with c.storage.lock:
            c.require_action('MASK_EDIT');job=c.job(require_checked=True)
            if 'mask_mutation' in c.completed:raise AgentFault('MASK_ALREADY_ATTEMPTED','이번 요청의 마스크 수정은 이미 처리했습니다.',409)
            try:job=c.workflow.edit_mask(job.id,operation=operation,relation=target_relation,view=view)
            except AmbiguousMaskEdit:
                c.decision_override=RequestIntent(DecisionIntent.CLARIFICATION,True)
                c.safe_clarification_question=AmbiguousMaskEdit.question
                c.decision('clarification',reason='CLARIFICATION_REQUIRED')
                return {'clarification_required':True,'question':AmbiguousMaskEdit.question,'mask_changed':False}
            c.completed['mask_mutation']=True;c.updated(job)
            return {'mask_changed':True,'approval_required':True,'reason':reason,**workspace_summary(job)}
    return await c.call('edit_weld_mask',lambda:c.work(edit))

@function_tool(failure_error_function=invalid_arguments)
async def refine_weld_mask(ctx:RunContextWrapper[WeldingAgentContext])->dict:
    """MASK_REFINE: request conditioned refinement of the CURRENT edited mask.
    F view only. Segment2 adapter conditions on F RGB/current binary/user instruction.
    Passing output is a NEW UNAPPROVED draft. Failed raw output never replaces the current mask.
    Never fresh-detect as fallback or auto-approve. Retain constraints/raw lineage.
    """
    c=ctx.context
    def refine():
        with c.storage.lock:
            c.require_action('MASK_REFINE');job=c.job(require_checked=True)
            if 'mask_mutation' in c.completed:raise AgentFault('MASK_ALREADY_ATTEMPTED','이번 요청에서 보정을 이미 시도했습니다.',409)
            c.completed['mask_mutation']=True
            try:job=c.workflow.refine_mask(job.id,instruction=c.message)
            finally:c.updated(c.workflow.get_job(job.id))
            return {'approval_required':True,**workspace_summary(job)}
    return await c.call('refine_weld_mask',lambda:c.work(refine))

@function_tool(failure_error_function=invalid_arguments)
async def redetect_weld_mask(ctx:RunContextWrapper[WeldingAgentContext])->dict:
    """MASK_REDETECT: fresh native F/R/S4 detection WITHOUT current mask conditioning."""
    return await detect_mask_request(ctx.context,'redetect_weld_mask')

@function_tool(failure_error_function=invalid_arguments)
async def generate_rough_trajectory(ctx:RunContextWrapper[WeldingAgentContext])->dict:
    """ROUGH_TRAJECTORY_GENERATE: apply direction/order with set_weld_instruction first.
    Uses approved F and Trajectory3. Regions remain independent. Never final/VLA/Simulator.
    """
    return await _plan(ctx,'generate_rough_trajectory')

@function_tool(failure_error_function=invalid_arguments)
async def request_mask_approval(ctx:RunContextWrapper[WeldingAgentContext])->dict:
    """MASK_APPROVE asks human Canvas confirmation. Does NOT approve."""
    async def notice():
        ctx.context.require_action('MASK_APPROVE')
        return {'approval_required':True,'message':'Canvas에서 현재 F 마스크를 검토하고 마스크 확정을 눌러주세요.'}
    return await ctx.context.call('request_mask_approval',notice)

@function_tool(failure_error_function=invalid_arguments)
async def reply_to_trajectory_question(ctx:RunContextWrapper[WeldingAgentContext])->dict:
    """ANSWER_CLARIFICATION: send actual human message through existing receipt lifecycle."""
    return {'message':await route_clarification_request(ctx.context)}

SEMANTIC_TOOLS=[choose_welding_action,edit_weld_mask,refine_weld_mask,redetect_weld_mask,
                generate_rough_trajectory,request_mask_approval,reply_to_trajectory_question]
