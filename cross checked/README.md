# Cross-checked sources

Data files compared against the ones the app uses, kept for the record. Nothing here is
read by the app.

| File | What it is | Why it is not used |
| --- | --- | --- |
| `stations.json` | 8,990 stations with code, name, state, zone and address; 8,697 have coordinates. | Superseded by `network_map/*/india_railway_stations.geojson`, which holds the same 8,697 located stations and is committed with the repo. The 293 extra entries here have no coordinates. |

Compared but never added to the repo:

| File | What it is | Why it is not used |
| --- | --- | --- |
| `Railway_Network_.csv` | The railway network table without coordinates. | `india_railway_network_with_coordinates.csv` has the same 119,446 rows plus station codes and coordinates. |
| `part-00000-...-c000.csv` (584 MB) | Labelled as train data, but it is the 2015 US flight delays dataset with renamed columns: operators `AA`/`US`, aircraft tail numbers such as `N407AS`, airports `LAX`, `SFO`. | Nothing joins to Indian stations or trains. Only of use as practice data for delay prediction, and it must be described as US flight data if used. |

Timetable sources, both of which the app reads:

| File | Trains | Kept for |
| --- | --- | --- |
| `isl_wise_train_detail_03082015_v1.csv` | 2,810 | Main schedule: official (data.gov.in), station code in its own column, 99.2% of codes have coordinates. |
| `EXP-TRAINS.json` | 2,533 | Running days, which the CSV has no column for, and 1,483 trains the CSV lacks. |

Only 1,050 trains appear in both, so together they cover 4,293. Both are 2015-era: neither
has Vande Bharat, Tejas or Humsafar trains, and Mumbai Central still appears as `BCT`.
