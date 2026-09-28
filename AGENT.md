### TEST

# AGENT.md

## Project

Surakarta Business Intelligence.

This is a local-first business intelligence prototype whose initial purpose is to map businesses in Kota Surakarta, Central Java, Indonesia.

The first data source is OpenStreetMap through the Overpass API.

## Primary Objective

Build a reliable pipeline:

```text
OpenStreetMap / Overpass
        ↓
Data Collection
        ↓
Normalization
        ↓
JSON Database
        ↓
FastAPI
        ↓
Web Dashboard
```

The current objective is business discovery and geographic visualization.

Legal entity, PMA/PMDN, and other government data are future enrichment layers.

## Engineering Principles

1. Prefer simple, maintainable solutions.
2. Keep the application local-first.
3. Do not introduce unnecessary infrastructure.
4. Keep data sources independent from the core business model.
5. Preserve source provenance.
6. Never fabricate missing information.
7. Use `unknown` when information cannot be verified.
8. Make future data-source integration possible.
9. Test the complete pipeline after meaningful changes.
10. Do not replace working code without inspecting it first.

## Data Source Rules

Current primary source:

```text
OpenStreetMap
Overpass API
```

Use Overpass for bulk geographic/business discovery.

Do not use:

* Google Maps scraping
* Google Maps undocumented endpoints
* Nominatim for bulk POI discovery
* undocumented APIs
* API bypass techniques

Use reasonable request timeouts, retry/backoff, and a descriptive User-Agent.

Keep the Overpass endpoint configurable.

Default:

```text
https://overpass-api.de/api/interpreter
```

## Data Provenance

Every business record should preserve source information.

At minimum:

```text
source
source_id
first_seen_at
last_seen_at
```

For OSM:

```text
source = "openstreetmap"
osm_type
osm_id
```

Do not remove the original OSM identifiers during normalization.

## Business Model

A business should contain, where available:

```text
id
name
category
subcategory
location
address
contact
source
legal
investment
activity
metadata
```

Do not assume that an OSM object is necessarily a legally registered company.

"Business exists in OSM" does NOT mean:

```text
legally incorporated
```

and does NOT mean:

```text
PMDN
```

and does NOT mean:

```text
PMA
```

## Legal and Investment Data

Future sources may include:

```text
AHU
OSS
BPS
Other official/public sources
```

Until verified by an appropriate source:

```text
legal_status = unknown
investment.status = unknown
```

Never infer PMA/PMDN from:

* name
* language
* location
* apparent ownership
* website
* nationality assumptions

## Activity

Use precise terminology.

Prefer:

```text
Recent Data Activity
```

over:

```text
Business Activity
```

unless the underlying source actually supports the stronger statement.

An OSM edit indicates that OSM data changed.

It does not necessarily prove that the physical business recently operated.

Activity events should preserve:

```text
business_id
type
source
detected_at
event_at
description
details
```

## Activity Score

The activity score is an application-defined analytical indicator.

It is NOT:

```text
business performance
revenue
profitability
company quality
investment attractiveness
```

The UI must communicate this distinction.

Keep the scoring implementation configurable.

## JSON Database

Current persistence layer:

```text
backend/data/businesses.json
backend/data/activities.json
backend/data/metadata.json
```

Do not use array indexes as IDs.

IDs must remain stable between collection runs.

The system should perform upserts rather than blindly append duplicate records.

## Geographic Scope

Initial scope:

```text
Kota Surakarta
Jawa Tengah
Indonesia
```

Do not manually define a random bounding box if an administrative boundary can be obtained from OSM.

Preserve latitude/longitude.

Design the model so future district/village-level filtering is possible.

## Frontend

Use:

```text
React
TypeScript
MapLibre GL JS
```

unless the existing repository already uses a suitable alternative.

The primary dashboard should contain:

* KPI summary
* filter controls
* business map
* business table/list
* business detail panel

Required filters include:

```text
Category
District
Recent activity
Has website
Has phone
Legal status
Investment status
```

## Backend

Use FastAPI unless the repository already has a suitable backend.

Minimum API:

```text
GET /api/businesses
GET /api/businesses/{id}
GET /api/businesses/{id}/activities
GET /api/statistics
GET /api/metadata
```

Keep API logic separate from data collection logic.

## Before Coding

Always:

1. Inspect the repository.
2. Identify existing architecture.
3. Identify existing package manager.
4. Identify existing scripts.
5. Reuse existing infrastructure where appropriate.
6. Avoid unnecessary rewrites.

## After Coding

Always:

1. Run the relevant tests.
2. Run the collector if collector code changed.
3. Verify JSON output.
4. Start the backend.
5. Start the frontend.
6. Verify API responses.
7. Verify the map.
8. Verify filters.
9. Check browser console errors.
10. Report what was actually tested.

## Definition of Done

A feature is not complete merely because the code compiles.

It must be integrated into the application and tested through the relevant user flow.

For the business discovery MVP:

```text
Overpass
   ↓
Collector
   ↓
Normalized Business
   ↓
JSON
   ↓
FastAPI
   ↓
Dashboard
   ↓
Map
   ↓
Filter
   ↓
Business Detail
```

The complete path should work.

## Current Roadmap

### Phase 1 — Business Mapping

* Overpass integration
* Surakarta data collection
* normalization
* JSON persistence
* API
* MapLibre
* filters

### Phase 2 — Activity Intelligence

* change detection
* activity events
* activity timeline
* recency filtering
* activity score

### Phase 3 — Legal Entity Enrichment

* AHU integration/research
* legal entity matching
* badan hukum classification
* confidence scoring

### Phase 4 — Investment Classification

* OSS/public official data
* PMA/PMDN classification
* source verification
* confidence scoring

### Phase 5 — Business Intelligence

* historical trends
* sector analysis
* geographic density
* business activity trends
* advanced search
* multi-source entity resolution

Do not implement later phases prematurely.

## Communication Style

When reporting progress, be factual.

Always distinguish:

```text
Implemented
Tested
Not tested
Assumed
Unknown
```

Never claim that a feature works if it has not been tested.
