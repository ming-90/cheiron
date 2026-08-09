from typing import Any, Dict, Iterable, List, Optional

from app.models import Filters, NormalizedStudy


def _year(value: Optional[str]) -> Optional[int]:
    """Extract a four-digit year from an API date without guessing missing values."""
    if not value or len(value) < 4:
        return None
    try:
        return int(value[:4])
    except ValueError:
        return None


def normalize_study(raw: Dict[str, Any]) -> NormalizedStudy:
    """Map one raw API study to the fields used by filtering and aggregation."""
    protocol = raw.get("protocolSection", {})
    identification = protocol.get("identificationModule", {})
    status = protocol.get("statusModule", {})
    design = protocol.get("designModule", {})
    conditions = protocol.get("conditionsModule", {})
    arms = protocol.get("armsInterventionsModule", {})
    sponsors = protocol.get("sponsorCollaboratorsModule", {})
    locations = protocol.get("contactsLocationsModule", {}).get("locations", [])
    start_date = status.get("startDateStruct", {}).get("date")
    lead_sponsor = sponsors.get("leadSponsor", {})

    return NormalizedStudy(
        nct_id=identification["nctId"],
        title=identification.get("briefTitle"),
        start_date=start_date,
        start_year=_year(start_date),
        overall_status=status.get("overallStatus"),
        phases=sorted(set(design.get("phases", []))),
        study_type=design.get("studyType"),
        enrollment=design.get("enrollmentInfo", {}).get("count"),
        conditions=sorted(set(conditions.get("conditions", []))),
        interventions=[
            {"name": item.get("name", ""), "type": item.get("type", "UNKNOWN")}
            for item in arms.get("interventions", []) if item.get("name")
        ],
        sponsor=lead_sponsor.get("name"),
        sponsor_class=lead_sponsor.get("class"),
        countries=sorted({item["country"] for item in locations if item.get("country")}),
        raw=raw,
    )


def normalize_many(raw_studies: Iterable[Dict[str, Any]]) -> List[NormalizedStudy]:
    """Normalize a study iterable while preserving source order."""
    return [normalize_study(study) for study in raw_studies]


def apply_exact_filters(studies: Iterable[NormalizedStudy], filters: Filters) -> List[NormalizedStudy]:
    """Apply filters that are safer to evaluate exactly after API retrieval."""
    output = []
    statuses = set(filters.overall_statuses)
    phases = set(filters.phases)
    study_types = set(filters.study_types)

    for study in studies:
        if filters.start_year is not None and (
            study.start_year is None or study.start_year < filters.start_year
        ):
            continue
        if filters.end_year is not None and (
            study.start_year is None or study.start_year > filters.end_year
        ):
            continue
        if statuses and study.overall_status not in statuses:
            continue
        if phases and not phases.intersection(study.phases):
            continue
        if study_types and study.study_type not in study_types:
            continue
        if filters.country and filters.country.casefold() not in {
            country.casefold() for country in study.countries
        }:
            continue
        output.append(study)
    return output
"""Convert ClinicalTrials.gov's nested payload into a stable internal model."""

