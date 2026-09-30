export type State = 'EMPTY' | 'SCENE_READY' | 'MASK_READY' | 'INSTRUCTION_READY' | 'ROUGH_PATH_READY' | 'VLA_REFINED' | 'VALIDATED';
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
export type Job = {
  schema_version: 2;
  id: string;
  state: State;
  scene: { id: string; width: number; height: number; image_url: string; color_mode: 'RGB' };
  mask: {
    id: string; width: number; height: number; image_url: string; overlay_url: string;
    mask_source: 'manual' | 'automatic'; selected_pixels: number;
    regions: MaskRegion[]; min_component_area: number; connectivity: 8;
    discarded_component_count: number; discarded_pixels: number;
  } | null;
  instruction: {
    text: string;
    structured: { direction: 'left_to_right' | 'right_to_left'; start_region: number | null; region_order: number[]; skip_regions: number[] };
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

export type AgentStatus = {
  enabled: boolean; api_key_configured: boolean; sdk_available: boolean; model: string;
  state: 'DISABLED' | 'NOT CONFIGURED' | 'READY' | 'RUNNING' | 'ERROR';
};
export type AgentMessage = { role: 'user' | 'assistant'; text: string; at?: string };
export type AgentHistory = { session_id: string; active_job_id: string | null; messages: AgentMessage[]; running: boolean };
export type AgentProgress = { call_id: string; tool: string; label: string; success?: boolean; message?: string };
export type AgentEvent =
  | { event: 'assistant_delta'; data: { text: string } }
  | { event: 'tool_started' | 'tool_completed'; data: AgentProgress }
  | { event: 'workspace_updated'; data: { job_id: string } }
  | { event: 'warning' | 'error'; data: { code: string; message: string } }
  | { event: 'done'; data: { ok: boolean; session_id: string; job_id: string | null } };

export type SimulatorState = 'STOPPED' | 'STARTING' | 'READY' | 'RUNNING_SAMPLE' | 'FAILED';
export type SimulatorStatus = {
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
