from collections import defaultdict
from itertools import combinations
from typing import Any, DefaultDict, Dict, Iterable, List, Sequence, Set, Tuple

from app.config import settings
from app.models import AnalysisTask, Dimension, NormalizedStudy


FIELD_PATHS = {
    Dimension.YEAR: "protocolSection.statusModule.startDateStruct.date",
    Dimension.PHASE: "protocolSection.designModule.phases",
    Dimension.STATUS: "protocolSection.statusModule.overallStatus",
    Dimension.INTERVENTION: "protocolSection.armsInterventionsModule.interventions.name",
    Dimension.INTERVENTION_TYPE: "protocolSection.armsInterventionsModule.interventions.type",
    Dimension.SPONSOR: "protocolSection.sponsorCollaboratorsModule.leadSponsor.name",
    Dimension.SPONSOR_CLASS: "protocolSection.sponsorCollaboratorsModule.leadSponsor.class",
    Dimension.COUNTRY: "protocolSection.contactsLocationsModule.locations.country",
}


def values_for(study: NormalizedStudy, dimension: Dimension) -> List[Any]:
    """Return every usable value a study contributes to one analysis dimension."""
    if dimension == Dimension.YEAR:
        return [study.start_year] if study.start_year is not None else []
    if dimension == Dimension.PHASE:
        return study.phases
    if dimension == Dimension.STATUS:
        return [study.overall_status] if study.overall_status else []
    if dimension == Dimension.INTERVENTION:
        return sorted({item["name"] for item in study.interventions})
    if dimension == Dimension.INTERVENTION_TYPE:
        return sorted({item["type"] for item in study.interventions})
    if dimension == Dimension.SPONSOR:
        return [study.sponsor] if study.sponsor else []
    if dimension == Dimension.SPONSOR_CLASS:
        return [study.sponsor_class] if study.sponsor_class else []
    if dimension == Dimension.COUNTRY:
        return study.countries
    return []


def _group_keys(study: NormalizedStudy, dimensions: Sequence[Dimension]) -> Iterable[Tuple[Any, ...]]:
    """Build the Cartesian product of a study's values for the requested dimensions."""
    value_lists = [values_for(study, dimension) for dimension in dimensions]
    if any(not values for values in value_lists):
        return []
    keys: List[Tuple[Any, ...]] = [tuple()]
    for values in value_lists:
        keys = [prefix + (value,) for prefix in keys for value in values]
    return set(keys)


def aggregate(
    studies: Sequence[NormalizedStudy], task: AnalysisTask,
    target_interventions: Sequence[str] = (),
) -> Dict[str, Any]:
    """Aggregate unique NCT IDs into tabular buckets or a weighted network."""
    if task.type.value == "network":
        return _aggregate_network(studies, task, target_interventions)

    buckets: DefaultDict[Tuple[Any, ...], Set[str]] = defaultdict(set)
    study_lookup = {study.nct_id: study for study in studies}
    for study in studies:
        for key in _group_keys_for_task(study, task.group_by, target_interventions):
            buckets[key].add(study.nct_id)

    rows = []
    for key, nct_ids in buckets.items():
        row = {dimension.value: value for dimension, value in zip(task.group_by, key)}
        row["trial_count"] = len(nct_ids)
        row["citations"] = _citations(nct_ids, task.group_by, row, study_lookup)
        rows.append(row)

    rows.sort(key=lambda row: _sort_key(row, task))
    if task.limit:
        rows = rows[: task.limit]
    return {"kind": "tabular", "rows": rows}


def _sort_key(row: Dict[str, Any], task: AnalysisTask) -> Tuple[Any, ...]:
    """Sort rankings by count and all other results by their dimension values."""
    if task.type.value in {"ranking", "distribution"}:
        return (-row["trial_count"],) + tuple(str(row.get(d.value, "")) for d in task.group_by)
    return tuple(str(row.get(d.value, "")) for d in task.group_by)


def _group_keys_for_task(
    study: NormalizedStudy, dimensions: Sequence[Dimension], target_interventions: Sequence[str]
) -> Iterable[Tuple[Any, ...]]:
    """Build group keys and canonicalize explicitly requested intervention names."""
    keys = _group_keys(study, dimensions)
    if Dimension.INTERVENTION not in dimensions or not target_interventions:
        return keys
    index = list(dimensions).index(Dimension.INTERVENTION)
    targets = {name.casefold(): name for name in target_interventions}
    normalized = []
    for key in keys:
        canonical = targets.get(str(key[index]).casefold())
        if canonical is None:
            continue
        values = list(key)
        values[index] = canonical
        normalized.append(tuple(values))
    return set(normalized)


def _aggregate_network(
    studies: Sequence[NormalizedStudy], task: AnalysisTask,
    target_interventions: Sequence[str],
) -> Dict[str, Any]:
    """Build nodes and edges whose weights count distinct contributing studies."""
    source_dimension, target_dimension = task.group_by[:2]
    edges: DefaultDict[Tuple[str, str], Set[str]] = defaultdict(set)
    node_trials: DefaultDict[Tuple[str, str], Set[str]] = defaultdict(set)
    lookup = {study.nct_id: study for study in studies}

    for study in studies:
        sources = [str(value) for value in values_for(study, source_dimension)]
        targets = [str(value) for value in values_for(study, target_dimension)]
        requested = {name.casefold() for name in target_interventions}
        if requested and source_dimension == Dimension.INTERVENTION:
            sources = [value for value in sources if value.casefold() in requested]
        if requested and target_dimension == Dimension.INTERVENTION:
            targets = [value for value in targets if value.casefold() in requested]
        if source_dimension == target_dimension:
            pairs = combinations(sorted(set(sources)), 2)
        else:
            pairs = ((source, target) for source in sources for target in targets if source != target)
        for source, target in pairs:
            edges[(source, target)].add(study.nct_id)
            node_trials[(source_dimension.value, source)].add(study.nct_id)
            node_trials[(target_dimension.value, target)].add(study.nct_id)

    edge_rows = []
    for (source, target), nct_ids in edges.items():
        if len(nct_ids) < task.minimum_weight:
            continue
        edge_rows.append({
            "source": source,
            "target": target,
            "weight": len(nct_ids),
            "citations": _citations(
                nct_ids, [source_dimension, target_dimension],
                {source_dimension.value: source, target_dimension.value: target}, lookup,
            ),
        })
    edge_rows.sort(key=lambda edge: (-edge["weight"], edge["source"], edge["target"]))
    if task.limit:
        edge_rows = edge_rows[: task.limit]

    included = {edge["source"] for edge in edge_rows} | {edge["target"] for edge in edge_rows}
    nodes = [
        {"id": value, "group": dimension, "trial_count": len(nct_ids)}
        for (dimension, value), nct_ids in node_trials.items() if value in included
    ]
    nodes.sort(key=lambda node: (node["group"], node["id"]))
    return {"kind": "network", "nodes": nodes, "edges": edge_rows}


def _citations(
    nct_ids: Iterable[str], dimensions: Sequence[Dimension], row: Dict[str, Any],
    lookup: Dict[str, NormalizedStudy],
) -> List[Dict[str, Any]]:
    """Attach a bounded, deterministic set of source studies to one datum."""
    citations = []
    primary_dimension = dimensions[-1]
    value = row.get(primary_dimension.value)
    for nct_id in sorted(nct_ids)[: settings.citation_limit]:
        citations.append({
            "nct_id": nct_id,
            "field_path": FIELD_PATHS[primary_dimension],
            "value": value,
            "source_url": f"https://clinicaltrials.gov/study/{nct_id}",
            "title": lookup[nct_id].title,
        })
    return citations
"""Deterministic aggregations over normalized ClinicalTrials.gov studies."""
