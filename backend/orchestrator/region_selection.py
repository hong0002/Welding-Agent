from backend.orchestrator.state_machine import WorkflowError
from backend.schemas import MaskRegion, RegionSelection, StructuredInstruction


def resolve_regions(
    instruction: StructuredInstruction, regions: list[MaskRegion], selection: RegionSelection | None = None,
) -> StructuredInstruction:
    """Resolve explicit IDs against a confirmed mask, never against geometric side names."""
    selection = selection if selection is not None else instruction
    available = {region.region_id for region in regions}
    for name, values in (("region_order", selection.region_order), ("skip_regions", selection.skip_regions)):
        if len(values) != len(set(values)):
            raise WorkflowError(f"{name} contains duplicate region IDs.")
        unknown = set(values) - available
        if unknown:
            raise WorkflowError(f"{name} contains unknown region IDs: {sorted(unknown)}.")
    active = available - set(selection.skip_regions)
    if not active:
        raise WorkflowError("Select at least one welding region; all regions are skipped or filtered.")
    if selection.start_region is not None and selection.start_region not in active:
        raise WorkflowError("start_region must identify an active, non-skipped region.")
    if selection.region_order:
        if set(selection.region_order) != active:
            raise WorkflowError("region_order must contain every non-skipped region exactly once.")
        order = list(selection.region_order)
        if selection.start_region is not None and order[0] != selection.start_region:
            raise WorkflowError("start_region must match the first region_order entry.")
    else:
        ordered = sorted(regions, key=lambda region: (region.centroid.x, region.centroid.y, region.region_id))
        if instruction.direction == "right_to_left":
            ordered.reverse()
        order = [region.region_id for region in ordered if region.region_id in active]
        if selection.start_region is not None:
            order.remove(selection.start_region)
            order.insert(0, selection.start_region)
    return StructuredInstruction(
        direction=instruction.direction, start_region=order[0], region_order=order,
        skip_regions=list(selection.skip_regions),
    )
