"""Catalog and data contracts for the BTS enrichment pipeline.

The existing ``pipeline.download`` module handles the flight-level Marketing
Carrier On-Time Performance download.  This module deliberately keeps the
other BTS tables separate because they have different grains:

* T-100 Segment is a monthly carrier/route/aircraft/service-class aggregate.
* T-100 Market is a monthly carrier/market/service-class aggregate.
* Support tables are reference data with historical effective dates.

No dataset in this catalog is synthetic.  The URLs point to BTS TranStats
download forms and the required columns are checked after download.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import zipfile

from config import BTS_CLEAN_DIR, BTS_RAW_DIR


TRANSTATS_BASE = "https://www.transtats.bts.gov/DL_SelectFields.aspx"


@dataclass(frozen=True)
class BtsDataset:
    key: str
    label: str
    url: str
    grain: str
    cadence: str
    raw_subdir: str
    clean_subdir: str
    required_columns: tuple[str, ...]
    numeric_columns: tuple[str, ...]
    monthly: bool = True
    description: str = ""
    special_column_aliases: tuple[tuple[str, str], ...] = ()

    @property
    def raw_dir(self) -> Path:
        return BTS_RAW_DIR / self.raw_subdir

    @property
    def clean_dir(self) -> Path:
        return BTS_CLEAN_DIR / self.clean_subdir


T100_SEGMENT = BtsDataset(
    key="t100_segment",
    label="T-100 Domestic Segment (U.S. Carriers)",
    url=f"{TRANSTATS_BASE}?QO_fu146_anzr=Nv4+Pn44vr45&gnoyr_VQ=FIM",
    grain="carrier + origin + destination + aircraft type + service class + month",
    cadence="monthly",
    raw_subdir="t100_segment",
    clean_subdir="t100_segment",
    required_columns=(
        "Year",
        "Month",
        "UniqueCarrier",
        "AirlineID",
        "OriginAirportID",
        "DestAirportID",
        "Origin",
        "Dest",
        "DepScheduled",
        "DepPerformed",
        "Seats",
        "Passengers",
        "Distance",
        "Class",
        "AircraftType",
    ),
    numeric_columns=(
        "Year",
        "Month",
        "AirlineID",
        "OriginAirportID",
        "DestAirportID",
        "OriginCityMarketID",
        "DestCityMarketID",
        "DepScheduled",
        "DepPerformed",
        "Payload",
        "Seats",
        "Passengers",
        "Freight",
        "Mail",
        "Distance",
        "RampTime",
        "AirTime",
        "Quarter",
        "OriginCityMarketID",
        "DestCityMarketID",
    ),
    description=(
        "Monthly domestic nonstop segment traffic and capacity reported by "
        "U.S. carriers, including seats, passengers, departures, aircraft, "
        "and service class."
    ),
    special_column_aliases=(
        ("DEPARTURES_SCHEDULED", "DepScheduled"),
        ("DEPARTURES_PERFORMED", "DepPerformed"),
        ("RAMP_TO_RAMP", "RampTime"),
        ("UNIQUE_CARRIER_NAME", "UniqueCarrierName"),
        ("UNIQUE_CARRIER_ENTITY", "UniqCarrierEntity"),
        ("REGION", "CarrierRegion"),
        ("CARRIER", "Carrier"),
        ("CARRIER_NAME", "CarrierName"),
        ("CARRIER_GROUP", "CarrierGroup"),
        ("CARRIER_GROUP_NEW", "CarrierGroupNew"),
        ("ORIGIN_AIRPORT_SEQ_ID", "OriginAirportSeqID"),
        ("ORIGIN_CITY_NAME", "OriginCityName"),
        ("ORIGIN_STATE_ABR", "OriginState"),
        ("ORIGIN_STATE_FIPS", "OriginStateFips"),
        ("ORIGIN_STATE_NM", "OriginStateName"),
        ("ORIGIN_WAC", "OriginWac"),
        ("DEST_AIRPORT_SEQ_ID", "DestAirportSeqID"),
        ("DEST_CITY_NAME", "DestCityName"),
        ("DEST_STATE_ABR", "DestState"),
        ("DEST_STATE_FIPS", "DestStateFips"),
        ("DEST_STATE_NM", "DestStateName"),
        ("DEST_WAC", "DestWac"),
        ("AIRCRAFT_GROUP", "AircraftGroup"),
        ("AIRCRAFT_TYPE", "AircraftType"),
        ("AIRCRAFT_CONFIG", "AircraftConfig"),
        ("DISTANCE_GROUP", "DistanceGroup"),
        ("YEAR", "Year"),
        ("QUARTER", "Quarter"),
        ("MONTH", "Month"),
        ("CLASS", "Class"),
    ),
)


T100_MARKET = BtsDataset(
    key="t100_market",
    label="T-100 Domestic Market (U.S. Carriers)",
    url=f"{TRANSTATS_BASE}?QO_fu146_anzr=Nv4+Pn44vr45&gnoyr_VQ=FIL",
    grain="carrier + origin + destination + service class + month",
    cadence="monthly",
    raw_subdir="t100_market",
    clean_subdir="t100_market",
    required_columns=(
        "Year",
        "Month",
        "UniqueCarrier",
        "AirlineID",
        "OriginAirportID",
        "DestAirportID",
        "Origin",
        "Dest",
        "Passengers",
        "Distance",
        "Class",
    ),
    numeric_columns=(
        "Year",
        "Month",
        "AirlineID",
        "OriginAirportID",
        "DestAirportID",
        "OriginCityMarketID",
        "DestCityMarketID",
        "Passengers",
        "Freight",
        "Mail",
        "Distance",
        "Quarter",
    ),
    description=(
        "Monthly domestic market-level passengers, freight, and mail reported "
        "by U.S. carriers."
    ),
    special_column_aliases=(
        ("UNIQUE_CARRIER_NAME", "UniqueCarrierName"),
        ("UNIQUE_CARRIER_ENTITY", "UniqCarrierEntity"),
        ("REGION", "CarrierRegion"),
        ("CARRIER", "Carrier"),
        ("CARRIER_NAME", "CarrierName"),
        ("CARRIER_GROUP", "CarrierGroup"),
        ("CARRIER_GROUP_NEW", "CarrierGroupNew"),
        ("ORIGIN_AIRPORT_SEQ_ID", "OriginAirportSeqID"),
        ("ORIGIN_CITY_NAME", "OriginCityName"),
        ("ORIGIN_STATE_ABR", "OriginState"),
        ("ORIGIN_STATE_FIPS", "OriginStateFips"),
        ("ORIGIN_STATE_NM", "OriginStateName"),
        ("ORIGIN_WAC", "OriginWac"),
        ("DEST_AIRPORT_SEQ_ID", "DestAirportSeqID"),
        ("DEST_CITY_NAME", "DestCityName"),
        ("DEST_STATE_ABR", "DestState"),
        ("DEST_STATE_FIPS", "DestStateFips"),
        ("DEST_STATE_NM", "DestStateName"),
        ("DEST_WAC", "DestWac"),
        ("DISTANCE_GROUP", "DistanceGroup"),
        ("YEAR", "Year"),
        ("QUARTER", "Quarter"),
        ("MONTH", "Month"),
        ("CLASS", "Class"),
    ),
)


CARRIER_DECODE = BtsDataset(
    key="carrier_decode",
    label="Carrier Decode",
    url=f"{TRANSTATS_BASE}?QO_fu146_anzr=N8vn6v10+f722146+gnoyr5&gnoyr_VQ=GDH",
    grain="carrier code + effective date range",
    cadence="reference",
    raw_subdir="carrier_decode",
    clean_subdir="carrier_decode",
    required_columns=(
        "AirlineID",
        "Carrier",
        "UniqueCarrier",
        "CarrierName",
        "StartDate",
        "EndDate",
    ),
    numeric_columns=("AirlineID", "CarrierEntity", "WAC", "CarrierGroup", "CarrierGroupNew"),
    monthly=False,
    description="Historical carrier identities and effective dates used by BTS aviation tables.",
    special_column_aliases=(
        ("REGION", "Region"),
        ("START_DATE_SOURCE", "StartDate"),
        ("THRU_DATE_SOURCE", "EndDate"),
    ),
)


MASTER_COORDINATE = BtsDataset(
    key="master_coordinate",
    label="Master Coordinate",
    url=f"{TRANSTATS_BASE}?QO_fu146_anzr=N8vn6v10+f722146+gnoyr5&gnoyr_VQ=FLL",
    grain="airport attribute version + effective date range",
    cadence="reference",
    raw_subdir="master_coordinate",
    clean_subdir="master_coordinate",
    required_columns=(
        "AirportSeqID",
        "AirportID",
        "Airport",
        "AirportName",
        "Latitude",
        "Longitude",
        "AirportStartDate",
        "AirportEndDate",
    ),
    numeric_columns=(
        "AirportSeqID",
        "AirportID",
        "AirportWacSeqID2",
        "AirportWac",
        "CityMarketSeqID",
        "CityMarketID",
        "CityMarketWacSeqID2",
        "CityMarketWac",
        "LatDegrees",
        "LatMinutes",
        "LatSeconds",
        "Latitude",
        "LonDegrees",
        "LonMinutes",
        "LonSeconds",
        "Longitude",
        "AirportStateFips",
        "AirportIsClosed",
        "AirportIsLatest",
    ),
    monthly=False,
    description=(
        "Historical airport identities, names, coordinates, geography, and "
        "effective dates used to avoid unstable code-only joins."
    ),
    special_column_aliases=(
        ("DISPLAY_AIRPORT_NAME", "AirportName"),
        ("AIRPORT_THRU_DATE", "AirportEndDate"),
    ),
)


AIRCRAFT_TYPES = BtsDataset(
    key="aircraft_types",
    label="AircraftTypes",
    url=f"{TRANSTATS_BASE}?QO_fu146_anzr=N8vn6v10+f722146+gnoyr5&gnoyr_VQ=GDD",
    grain="aircraft type",
    cadence="reference",
    raw_subdir="aircraft_types",
    clean_subdir="aircraft_types",
    required_columns=("AircraftTypeId", "AircraftGroup", "Name", "Manufacturer", "StartDate", "EndDate"),
    numeric_columns=("AircraftTypeId", "AircraftGroup"),
    monthly=False,
    description="BTS aircraft type codes and manufacturer/model names.",
    special_column_aliases=(
        ("AC_TYPEID", "AircraftTypeId"),
        ("AC_GROUP", "AircraftGroup"),
        ("SSD_NAME", "Name"),
        ("BEGIN_DATE", "StartDate"),
        ("END_DATE", "EndDate"),
    ),
)


DATASETS = {
    dataset.key: dataset
    for dataset in (
        T100_SEGMENT,
        T100_MARKET,
        CARRIER_DECODE,
        MASTER_COORDINATE,
        AIRCRAFT_TYPES,
    )
}


def get_dataset(key: str) -> BtsDataset:
    """Return a known dataset or raise a useful error for a typo."""
    try:
        return DATASETS[key]
    except KeyError as exc:
        available = ", ".join(sorted(DATASETS))
        raise ValueError(f"Unknown BTS dataset {key!r}. Choose one of: {available}") from exc


def monthly_datasets() -> tuple[BtsDataset, ...]:
    return tuple(dataset for dataset in DATASETS.values() if dataset.monthly)


def reference_datasets() -> tuple[BtsDataset, ...]:
    return tuple(dataset for dataset in DATASETS.values() if not dataset.monthly)


def data_csv_members(zip_path: str | Path) -> list[str]:
    """Return data CSV members, excluding TranStats documentation CSVs."""
    with zipfile.ZipFile(zip_path, "r") as archive:
        return [
            name
            for name in archive.namelist()
            if name.lower().endswith(".csv")
            and Path(name).name.lower() != "documentation.csv"
            and "documentation" not in Path(name).stem.lower()
        ]


def validate_enrichment_download_file(path: str | Path) -> bool:
    """Validate a BTS enrichment ZIP with optional Documentation.csv member."""
    candidate = Path(path)
    if not candidate.is_file() or candidate.suffix.lower() != ".zip":
        return False
    try:
        with zipfile.ZipFile(candidate, "r") as archive:
            if archive.testzip() is not None:
                return False
        return len(data_csv_members(candidate)) == 1
    except (OSError, zipfile.BadZipFile, zipfile.LargeZipFile):
        return False
