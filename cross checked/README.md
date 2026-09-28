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

Timetable sources, used by the first version of the app and retired:

| File | Trains | What it gave |
| --- | --- | --- |
| `isl_wise_train_detail_03082015_v1.csv` | 2,810 | Schedule: official (data.gov.in), station code in its own column, 99.2% of codes have coordinates. |
| `EXP-TRAINS.json` (not in the repo) | 2,533 | Running days, which the CSV has no column for, and 1,483 trains the CSV lacks. |
| `db.py`, `trains.py` | | The code that merged the two into a searchable SQLite database (`railway.db`). |

Only 1,050 trains appear in both, so together they cover 4,293. Both are 2015-era: neither
has Vande Bharat, Tejas or Humsafar trains, and Mumbai Central still appears as `BCT`.

**Cross-checked against RailRadar live data (23 Sep 2026) and replaced by it.** The app now
takes every schedule from RailRadar, the same response that carries the live position,
so the schedule an ETA starts from is the one the train runs to today. The 2015 files
disagreed with it where it matters:

| Train | 2015 files | RailRadar, 2026 |
| --- | --- | --- |
| 12639 Brindavan Express | departs MAS 07:50 | departs MAS 07:40 |
| 12607 Lalbagh Express | departs MAS 15:35 | departs MAS 15:30 |
| 12007 Shatabdi Express | 3 halts (MAS, SBC, MYS), running days unknown | runs every day but Thursday |
| 12639 route | halts only, straight lines on the map | all 76 stations and the real track (1,702 points) |

Kept here, not deleted, as the record of what was checked. The code runs only from
the project root with these files back in their old places.
