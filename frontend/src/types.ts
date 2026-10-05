export type State = 'EMPTY' | 'SCENE_READY' | 'MASK_READY' | 'INSTRUCTION_READY' | 'ROUGH_PATH_READY' | 'VLA_REFINED' | 'VALIDATED' | 'VLA_READY';
export const VIEW_IDS = ['B','F','L','R','S1','S2','S3','S4','T'] as const;
export type ViewId = typeof VIEW_IDS[number];
export type VLASummary = { artifact_id:string;attempt_id:string;sample_id:string;split:'train'|'val';model:string|null;point_count:9|33;coordinate_frame:string;ade_mm:number;fde_mm:number;mask_views:string[];simulation_only:true;physical_robot_executable:false;simulator_ready:false;source?:'guided_vla'|'vlm_final_gpt';provider?:'guided_vla'|'gpt' };
export type FinalPredictionDisplay = {artifact_id:string;attempt_id:string;source:'vlm_final_gpt';provider:'gpt';model:string|null;raw_output_ref:string;displayable:boolean;point_count:number;omitted_point_count:number;coordinate_frame:string;units:'mm'|'m'|'unknown';validation_status:'PASS'|'FAIL';simulator_eligible:boolean;display_url:string};
export type Point = { x: number; y: number };
export type MaskRegion = {
  region_id: number;
  pixel_area: number;
  bounding_box: { x_min: number; y_min: number; x_max: number; y_max: number };
  centroid: Point;
};
export type TrajectorySegment = {
  segment_id: number;
  region_id: number;
  mode: 'weld';
  points: Point[];
};
export type Trajectory = {
  segments: TrajectorySegment[];
  coordinate_space: 'image_pixel';
  units: 'px';
  is_robot_executable: false;
  generator: string;
  kind: 'rough_preview' | 'final_preview';
};
export type NativeCandidate = {
  native_artifact_id:string;source_session:string;sample_id:string;primary_camera:ViewId;
  frame:string;normalized_frame:string;units:'px';physical_robot_executable:false;
  segments:{segment_id:string;source_mask_id:string;connected_to_next:false;
    points_pixel:[number,number][];points_normalized:[number,number][];direction:'forward'|'reverse'|null}[];
};
export type NativeOutput = {
  status:'NATIVE_OUTPUT_MISSING'|'PARTIAL_NATIVE_OUTPUT'|'NATIVE_OUTPUT_READY_UNVALIDATED'|'NATIVE_OUTPUT_VALIDATED';
  native_output_generated:boolean;native_artifact_id:string|null;source_session:string|null;
  candidate:NativeCandidate|null;
  model_output?:ModelOutputDisplay|null;
  validation:{status:'PASS'|'WARN'|'FAIL';issues:{code:string;classification:'HARD_INVALID'|'SOFT_WARNING';message:string}[]};
  artifacts:Record<string,boolean>;preview_urls:Record<string,string>;
  user_override:false;override_available:false;physical_robot_executable:false;
};
export type ModelOutputDisplay={available:boolean;displayable:boolean;status:'OUTPUT_MISSING'|'OUTPUT_MALFORMED'|'OUTPUT_RAW_DISPLAYABLE'|'OUTPUT_VALIDATED';
  overlay_allowed:boolean;sample_id:string|null;primary_camera:ViewId|null;width:number|null;height:number|null;
  point_count:number;omitted_point_count:number;partial:boolean;segments:{segment_index:number;runs:[number,number][][]}[];
  mask_urls:Partial<Record<ViewId,string>>;warnings:string[];guided_vla_allowed:boolean;simulator_allowed:false};
export type Job = {
  schema_version: 2;
  id: string;
  state: State;
  scene: { id: string; width: number; height: number; image_url: string; color_mode: 'RGB';sample_id?:string|null;split?:'train'|'val'|null;primary_view?:ViewId|null;views?:Partial<Record<ViewId,SceneView>> };
  rough_mode?:'baseline_2d'|'native_3d';
  rough3d?:{artifact_id:string;native_session_id:string;image_guidance_point_count:number;reference_sample_id:string;reference_coordinate_frame:string;reference_point_count:number;reference_in_request:false;reference_preview_url?:string|null;artifacts:Record<string,boolean>}|null;
  vla_prediction?:VLASummary|null;
  raw_final_prediction?:FinalPredictionDisplay|null;
  native_output?:NativeOutput|null;
  raw_segment_output?:NativeOutput|null;
  planning_status?:'NOT_READY'|'NEEDS_CLARIFICATION'|'READY';
  trajectory_clarification?:{id:string;question:string;stage:'refiner'|'planner';status:'pending';choices:string[];created_at:string}|null;
  clarification_history?:string[];
  mask: {
    artifact?:{provenance:{native_source_artifact_id:string|null;native_session_id:string|null}}|null;
    id: string; width: number; height: number; image_url: string; overlay_url: string;
    mask_source: 'manual' | 'automatic' | 'vlm_segment' | 'manual_edited'; selected_pixels: number;
    edited_from_mask_id: string | null;
    approved?: boolean;
    approved_at?: string | null;
    regions: MaskRegion[]; min_component_area: number; connectivity: 8;
    discarded_component_count: number; discarded_pixels: number;
  } | null;
  instruction: {
    text: string;
    structured: { direction: 'left_to_right' | 'right_to_left' | 'top_to_bottom' | 'bottom_to_top'; start_region: number | null; region_order: number[]; skip_regions: number[] };
    parser: string;
  } | null;
  rough_trajectory: Trajectory | null;
  final_trajectory: Trajectory | null;
  validation: {
    valid: boolean; errors: string[]; scope: 'preview_geometry_only'; robot_safety_checked: false;
    component_sanity_checked: boolean; component_tolerance_px: number; minimum_near_component_ratio: number;
  } | null;
  history: { state: State; reason: string; at: string }[];
  preview_only: true;
};
export type Stroke = { tool: 'brush' | 'eraser'; size: number; points: number[] };
export type SceneView = { view_id:ViewId;image_id:string;image_url:string;width:number;height:number;image_sha256:string;mask:Job['mask'] };

export type YoloDetection={detection_id:string;class_id?:number|null;confidence?:number|null;
  bbox:{x_min:number;y_min:number;x_max:number;y_max:number}};
export type YoloView={image_width:number;image_height:number;detections:YoloDetection[]};
export type YoloOverlay={source:'segment2_native_yolo';display_only:true;job_id:string;scene_id:string;sample_id:string;
  artifact_id:string;available:boolean;coordinate_space:'image_pixel';frame:'image_top_left_x_right_y_down';
  views:Partial<Record<ViewId,YoloView>>;warnings:string[];trajectory3_reuse_verified:boolean};

export type ModelStatus = { backend: string; configured: boolean; ready: boolean; state: string; code: string | null; reference_mode: string | null };
export type ModelStatuses = Record<'segment' | 'rough' | 'vla', ModelStatus> & {rough3d?:ModelStatus};

export type AgentStatus = {
  enabled: boolean; api_key_configured: boolean; sdk_available: boolean; model: string;
  state: 'DISABLED' | 'NOT CONFIGURED' | 'READY' | 'RUNNING' | 'ERROR';
};
export type AgentMessage = { role: 'user' | 'assistant'; text: string; at?: string };
export type AgentHistory = { session_id: string; active_job_id: string | null; messages: AgentMessage[]; running: boolean };
export type AgentProgress = { call_id: string; tool: string; label: string; success?: boolean; message?: string };
export type AgentEvent =
  | { event:'decision_summary';data:import('./agentDecision').AgentDecisionSummary }
  | { event: 'assistant_delta'; data: { text: string } }
  | { event: 'tool_started' | 'tool_completed'; data: AgentProgress }
  | { event: 'workspace_updated'; data: { job_id: string } }
  | { event: 'warning' | 'error'; data: { code: string; message: string } }
  | { event: 'done'; data: { ok: boolean; session_id: string; job_id: string | null } };

export type SimulatorState = 'STOPPED' | 'STARTING' | 'READY' | 'RUNNING_SAMPLE' | 'FAILED';
export type PreviewCapabilities = {
  backend?:'legacy'|'dataset_v2'|'dataset_stp'; simulator_version?:string; source_point_count?:number|null; playback_point_count?:number|null; robot_preflight_available?:boolean;
  cad_source?:'OBJ'|null;native_layout?:string|null;environment_source?:string|null;
  orientation_source?:string;
  sample_id:string|null; family:string|null; point_count:number|null;
  path_preview_ready:boolean; robot_preview_ready:boolean; workpiece_preview_ready:boolean;
  fixture_ready:false; simulation_only:true; physical_robot_executable:false; validated_simulation:false;
  configuration_codes:string[]; warnings:string[]; robot_reason_code?:string;
};
export type SimulatorStatus = {
  backend?:'legacy'|'dataset_v2'|'dataset_stp'; simulator_version?:string;
  existing_replay?: {configured:boolean;errors:string[]};
  current_preview?: {backend?:'legacy'|'dataset_v2'|'dataset_stp';simulator_version?:string;source_point_count?:number|null;playback_point_count?:number|null;sample_family?:string|null;configured:boolean;configuration_errors:string[];configuration_codes:string[];robot_configuration?:{configured:boolean;configuration_errors:string[];configuration_codes:string[]};state:'STOPPED'|'STARTING'|'READY'|'RUNNING_PREVIEW'|'FAILED';error:string|null;can_stop:boolean;pid:number|null;latest:{request_id?:string;session_id?:string;backend?:string;source_point_count?:number;playback_point_count?:number;playback_status?:'PENDING'|'SUCCEEDED'|'FAILED';capture_status?:'PENDING'|'SUCCEEDED'|'PARTIAL_FAILED'|'FAILED';capture_warning_codes?:string[];reason_code?:string|null;job_id:string|null;artifact_id:string;package_id:string;sample_id:string;point_count:9|33;status:string;kind:'robot'|'path';robot_motion:boolean;exact_xyz_preserved?:boolean;error:string|null}|null};
  state: SimulatorState;
  configured: boolean;
  configuration_errors: string[];
  sample_configuration_errors: string[];
  error: string | null;
  can_start: boolean;
  can_run_sample: boolean;
  can_stop: boolean;
  simulator_pid: number | null;
  sample_pid: number | null;
  sample_id: string | null;
  sample_mode: 'existing_vla_prediction';
  preview_connected: false;
  robot_execution_enabled: false;
  readiness: string;
  session_dir: string | null;
  configuration_diagnostics?: {
    isaac_launcher_configured: boolean;
    isaac_launcher: string | null;
    launcher_kind: string;
    isaac_import_check: { status: 'not_run' | 'passed' | 'failed'; message: string; checked_at?: string; python?: string };
    prediction_format: string; prediction_root: string; samples_dir: string | null; metadata_present: boolean;
  };
  latest_sample: {
    sample_id: string; status: 'PREPARING' | 'QUEUED' | 'RUNNING' | 'SUCCEEDED' | 'FAILED' | 'CANCELLED';
    request_id: string | null; started_at: string; finished_at: string | null;
    exit_code: number | null; error: string | null; artifacts: string[];
  } | null;
};
export type SimulatorLogs = { entries: { id: number; at: string; source: string; text: string }[] };

export type PreviewFrames = {
  live?:{available:boolean;state:'LIVE'|'CONNECTING'|'PAUSED'|'OFFLINE';fps:number;target_fps:number;url:string|null;warning:string|null};
  available:boolean; delivery:'latest_capture'; reason_code:string|null;
  job_id:string; artifact_id:string; session_id:string|null; request_id:string|null; kind:'path'|'robot'|null;
  frames:{name:'P0'|'P4'|'P8'|'path_detail';url:string;sha256:string;width:number;height:number;captured_at:string}[];
};
