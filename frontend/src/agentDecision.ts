// Display-only protocol: fixed labels, enums, booleans and counts. No raw text.
export const intentLabels = {
  scene_load:'9-view Scene 불러오기', mask_detection:'용접 마스크 검출', mask_redetection:'용접 마스크 재검출',
  instruction_update:'현재 용접 지시 적용', rough_trajectory_generation:'현재 승인 영역의 경로 생성',
  guided_vla_execution:'승인된 F 마스크와 2D guidance로 최종 3D 예측 궤적 생성',
  simulator_path_preview:'현재 3D 경로를 Simulator에서 확인', simulator_robot_preview:'현재 3D 경로의 Robot Preview 확인',
  simulator_control:'명시적으로 요청한 Simulator 동작',
  explanation:'설명·상태·기존 결과 확인', clarification:'다음 작업 또는 진행 방향 확인',
  prerequisite_check:'현재 요청을 위한 입력 준비',
} as const;
export const actionLabels = {workspace:'작업 상태 확인',scene:'9-view Scene',segment2:'Segment2 마스크 검출',
  instruction:'용접 지시 적용',trajectory3:'Trajectory3 경로 생성',guided_vla:'최종 3D prediction',
  simulator_panel:'Simulator 패널에서 별도 실행',simulator_control:'기존 Simulator 제어',clarification:'사용자 응답 대기'} as const;
export const stepLabels = {workspace:'작업 상태 확인',scene:'Scene 준비',segment2:'YOLO 객체 검출 → VLM 마스크 생성',
  instruction:'용접 지시 적용',trajectory3:'Trajectory3 계획 및 경로 생성',guided_vla:'서버 준비 확인 → 3D 궤적 예측',
  rough:'Rough 경로 생성',refine:'2D preview 다듬기',validate:'Preview geometry 검증',simulator:'Simulator 상태 확인',result:'요청 처리 완료'} as const;
export const nextLabels = {load_scene:'Dataset sample을 선택하세요.',detect_mask:'용접 마스크 검출을 요청하세요.',
  approve_f_mask:'F 마스크를 검토·수정한 뒤 승인하세요.',generate_guidance:'현재 승인 영역의 Trajectory3 경로를 생성하세요.',
  answer_question:'표시된 질문에 답해주세요.',run_vla:'최종 3D 예측을 요청하세요.',
  simulator_panel:'Simulator에서 Path Preview → Robot Preview를 별도로 요청하세요.',review_result:'현재 결과를 확인하세요.',
  check_configuration:'Backend 설정과 연결 상태를 확인하세요.',check_inputs:'현재 승인 마스크와 지시·guidance 연결을 확인하세요.'} as const;
export const reasonLabels = {
  USER_REQUESTED_ACTION:'명시적인 요청과 현재 작업 상태를 기준으로 선택했습니다.',
  USER_REQUESTED_MASK_REDETECTION:'현재 마스크를 다시 검출하라는 요청입니다.',
  USER_REQUESTED_GUIDED_VLA_EXECUTION:'최종 3D 예측을 생성하라는 명시적인 요청입니다. 물리 로봇 실행은 비활성화되어 있습니다.',
  USER_REQUESTED_TRAJECTORY_GENERATION:'현재 승인 영역의 경로 생성 요청입니다.',
  GUIDED_VLA_PREREQUISITE_MISSING:'최종 3D 예측 실행 준비가 부족합니다. 이전 모델을 자동 실행하지 않았습니다.',
  GUIDED_VLA_ALREADY_READY:'현재 조건의 최종 궤적 결과가 있어 재사용합니다. 추가 prediction은 호출하지 않았습니다.',
  GUIDED_VLA_RERUN_NOT_SUPPORTED:'현재 최종 궤적 결과가 있으며 이 상태에서는 재실행을 지원하지 않습니다.',
  GUIDED_VLA_INPUT_CHANGED:'입력 또는 원본 artifact 연결을 확인하지 못해 실행을 차단했습니다.',
  SIMULATOR_PREVIEW_INTENT:'시뮬레이터 확인 요청입니다. 최종 궤적 생성을 자동 실행하지 않습니다.',
  CLARIFICATION_REQUIRED:'진행할 작업 또는 방향에 대한 추가 답변이 필요합니다.',
  READ_ONLY_REQUEST:'설명·상태·결과 확인 요청으로 처리했습니다. 최종 prediction은 호출하지 않았습니다.',
  ACTION_FAILED:'요청을 완료하지 못했습니다. 표시된 오류와 현재 작업 상태를 확인하세요.',
  NATIVE_OUTPUT_NOT_ACCEPTED:'모델 경로가 최종 예측 입력 검증을 통과하지 못했습니다. 현재 결과와 검증 안내를 확인하세요.',
  MASK_DRAFT_UNSAVED:'수정 중인 마스크를 먼저 확정해야 합니다.',MASK_APPROVAL_REQUIRED:'F 마스크의 사용자 승인이 필요합니다.',
} as const;
export const prerequisiteLabels = {scene:'Scene',approved_f_mask:'F 마스크 승인',guidance:'Trajectory3 guidance',
  vla_backend:'최종 predictor 설정',single_region:'단일 용접 영역',current_vla:'현재 최종 궤적 결과'} as const;
export type AgentDecisionSummary = {
  intent:keyof typeof intentLabels;selected_action:keyof typeof actionLabels;current_step:keyof typeof stepLabels;
  next_step:keyof typeof nextLabels;reason_code:keyof typeof reasonLabels;
  status:'planned'|'running'|'completed'|'blocked'|'clarification';job_id:string|null;view_count:number;point_count:number;
  prerequisites:{key:keyof typeof prerequisiteLabels;ready:boolean}[];
  final_predictor?:'guided_vla'|'gpt';
};
const fields=['intent','selected_action','current_step','next_step','reason_code','status','job_id','view_count','point_count','prerequisites'];
export function parseDecision(value:unknown):AgentDecisionSummary|null {
  if(!value||typeof value!=='object'||Array.isArray(value))return null;
  const data=value as Record<string,unknown>;
  // Accept historical summaries while allowlisting the new backend-selected label.
  if(!fields.every(k=>Object.hasOwn(data,k))||Object.keys(data).some(k=>!fields.includes(k)&&k!=='final_predictor'))return null;
  if(Object.hasOwn(data,'final_predictor')&&data.final_predictor!=='guided_vla'&&data.final_predictor!=='gpt')return null;
  for(const [field,labels] of [['intent',intentLabels],['selected_action',actionLabels],['current_step',stepLabels],['next_step',nextLabels],['reason_code',reasonLabels]] as const)
    if(typeof data[field]!=='string'||!Object.hasOwn(labels,data[field]))return null;
  if(!['planned','running','completed','blocked','clarification'].includes(String(data.status)))return null;
  if(data.job_id!==null&&(typeof data.job_id!=='string'||!/^[0-9a-f]{8}-(?:[0-9a-f]{4}-){3}[0-9a-f]{12}$/i.test(data.job_id)))return null;
  if(!Number.isInteger(data.view_count)||Number(data.view_count)<0||Number(data.view_count)>9||!Number.isInteger(data.point_count)||Number(data.point_count)<0||Number(data.point_count)>100000)return null;
  if(!Array.isArray(data.prerequisites)||data.prerequisites.length>6||!data.prerequisites.every(p=>p&&typeof p==='object'&&Object.keys(p).length===2&&Object.hasOwn(prerequisiteLabels,p.key)&&typeof p.ready==='boolean'))return null;
  return data as AgentDecisionSummary;
}
export class DecisionPreflightError extends Error {
  constructor(readonly code:'MASK_DRAFT_UNSAVED'|'MASK_APPROVAL_REQUIRED',message:string){super(message);}
}
export function preflightDecision(code:DecisionPreflightError['code']):AgentDecisionSummary {
  return {intent:'prerequisite_check',selected_action:'workspace',current_step:'workspace',next_step:'approve_f_mask',reason_code:code,
    status:'blocked',job_id:null,view_count:0,point_count:0,prerequisites:[{key:'approved_f_mask',ready:false}]};
}
export function failedDecision(previous:AgentDecisionSummary|null,code:string):AgentDecisionSummary {
  const inputChanged=code.startsWith('NATIVE_OUTPUT_')||['GUIDED_VLA_INPUT_CHANGED','GUIDED_VLA_ATTEMPT_CHANGED','GUIDED_VLA_GUIDANCE_INVALID'].includes(code);
  return {...(previous??preflightDecision('MASK_APPROVAL_REQUIRED')),status:'blocked',
    reason_code:inputChanged?'GUIDED_VLA_INPUT_CHANGED':'ACTION_FAILED',
    next_step:inputChanged?'check_inputs':'check_configuration'};
}
