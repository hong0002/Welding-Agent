"""Structured semantic task selection. No phrase matching or geometry generation."""
from typing import Literal
from backend.agent.decision import DecisionIntent, RequestIntent

SemanticAction = Literal['MASK_DETECT','MASK_EDIT','MASK_REFINE','MASK_REDETECT','MASK_APPROVE',
    'ROUGH_TRAJECTORY_GENERATE','FINAL_TRAJECTORY_GENERATE','INSTRUCTION_UPDATE',
    'STATUS_OR_EXPLANATION','CLARIFICATION','ANSWER_CLARIFICATION','SIMULATOR_PREVIEW','SIMULATOR_CONTROL','SCENE_LOAD']

INTENTS = {'MASK_DETECT':DecisionIntent.MASK,'MASK_EDIT':DecisionIntent.EDIT,
    'MASK_REFINE':DecisionIntent.REFINE_MASK,'MASK_REDETECT':DecisionIntent.REMASK,
    'MASK_APPROVE':DecisionIntent.APPROVE_MASK,'ROUGH_TRAJECTORY_GENERATE':DecisionIntent.ROUGH,
    'FINAL_TRAJECTORY_GENERATE':DecisionIntent.VLA,'INSTRUCTION_UPDATE':DecisionIntent.INSTRUCTION,
    'STATUS_OR_EXPLANATION':DecisionIntent.EXPLANATION,'CLARIFICATION':DecisionIntent.CLARIFICATION,
    'ANSWER_CLARIFICATION':DecisionIntent.CLARIFICATION,'SIMULATOR_PREVIEW':DecisionIntent.PATH,
    'SIMULATOR_CONTROL':DecisionIntent.SIMULATOR,'SCENE_LOAD':DecisionIntent.SCENE}

def request_for(action):
    # A reply can finish planning; unlike a new ambiguity, it must not leave
    # the decision card in an unconditional "waiting for an answer" state.
    return RequestIntent(INTENTS[action],action!='ANSWER_CLARIFICATION')
