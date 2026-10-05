from __future__ import annotations

from schemas import DetailedPlan, RefinedTask


def ordered_image_segments(image_guidance: dict, directions: dict[str, str]) -> list[tuple[dict, list, list]]:
    result = []
    for segment in image_guidance["segments"]:
        pixels = list(segment["points_pixel"])
        normalized = list(segment["points_normalized"])
        if directions.get(segment["segment_id"], "forward") == "reverse":
            pixels.reverse()
            normalized.reverse()
        result.append((segment, pixels, normalized))
    return result


def _compact_number(value: float, digits: int) -> str:
    text = f"{float(value):.{digits}f}".rstrip("0").rstrip(".")
    return "0" if text in {"", "-0"} else text


def _compact_points(points: list, digits: int) -> str:
    return "[" + ";".join(
        "(" + ",".join(_compact_number(value, digits) for value in point) + ")"
        for point in points
    ) + "]"


def _append_reference_trajectory_en(lines: list[str], trajectory: dict) -> None:
    lines.extend(
        [
            "# 3D Rough Trajectory",
            "",
            f"Teaching source sample: `{trajectory['source_sample_id']}`  ",
            f"Coordinate frame: `{trajectory['coordinate_frame']}`  ",
            f"Unit: `{trajectory['unit']}`  ",
            f"Selection method: `{trajectory['selection_method']}`  ",
            f"Target point budget: {trajectory['target_point_count']}  ",
            f"Actual point count: {trajectory['actual_point_count']}",
            "",
            "The XYZ values below are a motion-shape template simplified from the retrieved "
            "sample's actual H5 teaching action. P0 is the local origin. They are not registered "
            "to the query workpiece and are not executable query TCP targets.",
            "",
        ]
    )
    for segment in trajectory["segments"]:
        lines.extend(
            [
                f"## {segment['segment_id']}",
                "",
                f"Teaching direction: `{segment['teaching_direction']}`  ",
                f"Source path length: {segment['source_length_mm']:.4f} mm  ",
                f"Connected to next welding segment: `{str(segment['connected_to_next']).lower()}`",
                "",
            ]
        )
        for index, (x, y, z) in enumerate(segment["points_xyz_mm"]):
            lines.append(f"{index + 1}. `P{index} = ({x:.4f}, {y:.4f}, {z:.4f}) mm`")
        lines.append("")


def _append_reference_trajectory_ko(lines: list[str], trajectory: dict) -> None:
    lines.extend(
        [
            "# 3D 가궤적",
            "",
            f"- teaching 출처 샘플: `{trajectory['source_sample_id']}`",
            f"- 좌표계: `{trajectory['coordinate_frame']}`",
            f"- 단위: `{trajectory['unit']}`",
            f"- 선택 방법: `{trajectory['selection_method']}`",
            f"- 목표 포인트 수: {trajectory['target_point_count']}",
            f"- 실제 포인트 수: {trajectory['actual_point_count']}",
            "- 아래 XYZ는 검색된 샘플의 실제 H5 teaching action을 축약한 동작 형상입니다.",
            "- P0를 로컬 원점으로 둔 상대 좌표이며, 현재 작업물에 정합된 실행용 TCP 좌표는 아닙니다.",
            "",
        ]
    )
    for segment in trajectory["segments"]:
        lines.extend(
            [
                f"## {segment['segment_id']}",
                "",
                f"- teaching 진행 방향: `{segment['teaching_direction']}`",
                f"- 원본 경로 길이: {segment['source_length_mm']:.4f} mm",
                f"- 다음 용접 구간과 연결: `{str(segment['connected_to_next']).lower()}`",
                "",
            ]
        )
        for index, (x, y, z) in enumerate(segment["points_xyz_mm"]):
            lines.append(f"{index + 1}. `P{index} = ({x:.4f}, {y:.4f}, {z:.4f}) mm`")
        lines.append("")


def _append_image_guidance_en(lines: list[str], guidance: dict, directions: dict[str, str]) -> None:
    size = guidance["image_size"]
    lines.extend(
        [
            "# 2D Image Guidance",
            "",
            f"Primary camera: `{guidance['primary_camera']}`  ",
            f"Image size: `{size['width']} x {size['height']}` pixels  ",
            f"Pixel frame: `{guidance['coordinate_frame_pixel']}`  ",
            f"Normalized frame: `{guidance['coordinate_frame_normalized']}`",
            "",
            "Pixel and normalized coordinates come from the approved query mask. They ground the "
            "target in the image and are retained for visualization. They are not a calibrated "
            "projection of the 3D teaching template.",
            "",
        ]
    )
    for segment, pixels, normalized in ordered_image_segments(guidance, directions):
        direction = directions.get(segment["segment_id"], "forward")
        lines.extend(
            [
                f"## {segment['segment_id']}",
                "",
                f"Direction: `{direction}`  ",
                "Planned state while following: `welding enabled`",
                "",
            ]
        )
        for index, ((px, py), (nx, ny)) in enumerate(zip(pixels, normalized)):
            lines.append(
                f"{index + 1}. `P{index}: pixel=({px:.2f}, {py:.2f}), normalized=({nx:.6f}, {ny:.6f})`"
            )
        lines.append("")


def _append_image_guidance_ko(lines: list[str], guidance: dict, directions: dict[str, str]) -> None:
    if not guidance.get("mask_available", True):
        lines.extend(["# 작업 위치 근거 (마스크 없음)", "",
                      "- 현재 이미지·YOLO 작업물 bbox·사용자 지시를 사용했습니다. 승인된 용접선 마스크는 없습니다.",
                      "- bbox 테두리는 용접선이 아닙니다. 2D 용접선 좌표는 생성하지 않았습니다.",
                      "- reference_segment ID와 3D XYZ는 검색된 액션의 참조 형상이며 현재 물체의 확정 경로가 아닙니다.", ""])
        return
    size = guidance["image_size"]
    lines.extend(
        [
            "# 2D 이미지 안내 경로",
            "",
            f"- 기준 카메라: `{guidance['primary_camera']}`",
            f"- 이미지 크기: `{size['width']} x {size['height']}` pixel",
            f"- pixel 좌표계: `{guidance['coordinate_frame_pixel']}`",
            f"- 정규화 좌표계: `{guidance['coordinate_frame_normalized']}`",
            "- pixel과 normalized 좌표는 승인된 현재 샘플 마스크에서 생성한 작업 위치 안내입니다.",
            "- 이 좌표는 위 3D teaching 가궤적을 카메라로 보정 투영한 결과가 아닙니다.",
            "",
        ]
    )
    for segment, pixels, normalized in ordered_image_segments(guidance, directions):
        direction = directions.get(segment["segment_id"], "forward")
        lines.extend([f"## {segment['segment_id']}", "", f"진행 방향: `{direction}`", ""])
        for index, ((px, py), (nx, ny)) in enumerate(zip(pixels, normalized)):
            lines.append(
                f"{index + 1}. `P{index}: pixel=({px:.2f}, {py:.2f}), normalized=({nx:.6f}, {ny:.6f})`"
            )
        lines.append("")


def render_vla_markdown(
    plan: DetailedPlan,
    refined: RefinedTask,
    reference_trajectory_3d: dict,
    image_guidance_2d: dict,
) -> str:
    directions = {item.segment_id: item.direction for item in plan.segment_decisions}
    lines = [
        "# VLA Welding Command",
        "",
        f"Task: {plan.task_summary_en}",
        f"Target: `{plan.target_joint_id}`; masks: "
        f"{', '.join(f'`{item}`' for item in plan.grounded_mask_ids) or 'none (image + YOLO workpiece boxes only)'}.",
        f"View relation: {plan.view_relationship_en}",
        "",
        "## Execute",
        "",
    ]
    for step in sorted(plan.operations, key=lambda item: item.order):
        state = "on" if step.weld_enabled else "off"
        segment = step.segment_id or "none"
        lines.append(
            f"{step.order}. `{step.action}` | segment=`{segment}` | weld=`{state}` | "
            f"{step.instruction_en}"
        )

    trajectory = reference_trajectory_3d
    lines.extend(
        [
            "",
            "## 3D Motion Template",
            "",
            f"source=`{trajectory['source_sample_id']}`; "
            f"frame=`{trajectory['coordinate_frame']}`; unit=`{trajectory['unit']}`; "
            "registered_to_query=`false`.",
        ]
    )
    for segment in trajectory["segments"]:
        lines.append(
            f"- `{segment['segment_id']}`: teaching_direction=`{segment['teaching_direction']}`; "
            f"length_mm={_compact_number(segment['source_length_mm'], 3)}; "
            f"xyz={_compact_points(segment['points_xyz_mm'], 3)}"
        )

    guidance = image_guidance_2d
    size = guidance["image_size"]
    lines.extend(
        [
            "",
            "## 2D Target Guidance",
            "",
            f"camera=`{guidance['primary_camera']}`; image=`{size['width']}x{size['height']}`; "
            f"pixel_frame=`{guidance['coordinate_frame_pixel']}`; "
            f"normalized_frame=`{guidance['coordinate_frame_normalized']}`.",
        ]
    )
    for segment, pixels, normalized in ordered_image_segments(guidance, directions):
        direction = directions.get(segment["segment_id"], "forward")
        lines.extend(
            [
                f"- `{segment['segment_id']}`: direction=`{direction}`; weld=`on`",
                f"  pixel={_compact_points(pixels, 1)}",
                f"  normalized={_compact_points(normalized, 5)}",
            ]
        )

    if not guidance.get("mask_available", True):
        lines.extend(["No approved query mask or 2D seam coordinates. YOLO boxes delimit workpieces, not weld lines.",
                      "Operation segment IDs refer to retrieved motion-template segments; their target correspondence is provisional."])

    lines.extend(
        [
            "",
            "## Rules",
            "",
            "- Treat the 3D XYZ as retrieved start-relative motion geometry. Register it to the "
            "query scene before producing TCP targets; the 2D points are not its calibrated projection.",
            "- Weld only while following the grounded segment. Keep welding off during approach, "
            "reposition, and retract; do not duplicate one seam across camera views.",
            "- Determine torch pose and collision-free approach/retract externally. Point indices "
            "describe geometry, not controller time, speed, or welding power.",
            "",
            f"Done: {plan.completion_condition_en}",
        ]
    )
    return "\n".join(lines).rstrip() + "\n"


def render_korean_markdown(
    plan: DetailedPlan,
    refined: RefinedTask,
    reference_trajectory_3d: dict,
    image_guidance_2d: dict,
    reference_ids: list[str],
) -> str:
    directions = {item.segment_id: item.direction for item in plan.segment_decisions}
    lines = [
        "# 용접 작업",
        "",
        plan.task_summary_ko,
        "",
        "# 작업 대상 근거",
        "",
        plan.view_relationship_ko,
        "",
        f"- 작업 대상 ID: `{plan.target_joint_id}`",
        f"- 연결된 마스크: {', '.join(f'`{item}`' for item in plan.grounded_mask_ids)}",
        f"- 검색 참고 샘플: {', '.join(f'`{item}`' for item in reference_ids)}",
        f"- 3D teaching 기준 샘플: `{reference_trajectory_3d['source_sample_id']}`",
        "",
        "# 사용자 지시 해석",
        "",
        f"- 원문: {refined.refined_instruction_ko}",
        f"- 정규화된 작업: {plan.task_summary_ko}",
        "",
        "# 검색된 액션에서 적용한 특성",
        "",
    ]
    lines.extend(f"- {item}" for item in plan.reference_motion_pattern_ko)
    lines.extend(["", "# 상세 작업 순서", ""])
    for step in sorted(plan.operations, key=lambda item: item.order):
        state = "용접 활성" if step.weld_enabled else "용접 비활성"
        segment = f" (`{step.segment_id}`)" if step.segment_id else ""
        lines.append(f"{step.order}. **{step.action}**{segment}: {step.instruction_ko} [{state}]")
    lines.append("")
    _append_reference_trajectory_ko(lines, reference_trajectory_3d)
    _append_image_guidance_ko(lines, image_guidance_2d, directions)
    lines.extend(["# 동작 제약", ""])
    lines.extend(f"- {item}" for item in plan.motion_constraints_ko)
    lines.extend(["", "# 완료 조건", "", plan.completion_condition_ko])
    if plan.uncertainties_ko:
        lines.extend(["", "# 남은 불확실성", ""])
        lines.extend(f"- {item}" for item in plan.uncertainties_ko)
    return "\n".join(lines).rstrip() + "\n"
