# Final architecture and boundaries

React/TypeScript/Konva calls FastAPI. Backend Workflow owns transitions; local storage is single-process. Assistant interprets intent and invokes validated tools; it does not generate mask pixels or robot coordinates.

Current native Mask is Segment2 and current native rough is Trajectory3. The original `vlm_project`/`vlm_project2` sources are included for their role/shared imports. Native outputs and safe normalized descriptors remain distinct; raw hidden reasoning is not exposed in chat. Human binary-mask edits invalidate approvals/downstream paths. Multiple 2D weld regions stay separate; travel planning is a future concern.

GPT2 prediction-only preserves native Rough/Corners prompts, model/reasoning, interpolation, known-start processing and source frame. Original query seam annotations are visual inputs; edited web-mask/Trajectory3 XYZ are not direct GPT2 input. Query GT interior and baseline prediction are excluded. Reference teaching trajectories are TRAIN few-shot inputs. B_PR demo endpoint provenance is `dataset_gt_endpoint`; this is an explicitly conditioned demo.

Final XYZ is `source_robot_frame_unaligned_with_isaac`, mm; NPZ also preserves meters. Artifact hashes, scene/sample/instruction/mask approval evidence, native source hashes and immutable proof/package bind a preview to the current job. Visualization-first outputs may be reviewed before strict acceptance; STRICT/DEMO routes remain explicit and backend-authoritative. No GT substitution or automatic fallback occurs.

`SimulatorFinalClient` is thin: native simulator_final preparation, placement, source_to_scene, table/base/TCP, policy orientation, densification, IK/FK and playback remain native. B_PR_03_0001 preview-only clearance is explicitly recorded without modifying source XYZ. Physical execution stays disabled. Live frames are produced by an owned current preview session and served via bounded polling; stale/foreign sessions do not authorize frames.

The release only changes backend-owned module root discovery and operator config/key loading to make the packaged tree usable. Source roots remain allowlisted; browser/Agent cannot choose Python, cwd, scripts or paths. `.env` is UTF-8 and backend-only. Secrets never enter frontend, reports, safe model logs or version control. Automated tests inject fake model/simulator processes.
