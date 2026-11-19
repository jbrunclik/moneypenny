# Garmin get_trend and activity date ranges - design (short)

**Intent.** "How did I sleep this week" took one single-day Garmin read per
night, each a model round re-sending the conversation; activities only came
from the last 90 days, newest first, so "my rides in September" had no answer.

**Goals.** `garmin_connect(action="get_trend", metric, start_date, end_date)`:
one library range call per metric (sleep, hrv, resting_hr,
training_readiness, body_battery, stress, steps, weight), at most 31 days
(default the last 7), one compact row per day. `get_activities` takes
`start_date`/`end_date`. Row fields and units from a read-only probe of the
real endpoints (Nov 19 2026, approved by the account owner; raw responses kept
out of the repo). A8: the "garmin_connect called" line carries `metric`; a
regular-review check and a TODO re-measure. A7: an announcement.

**Approaches.** (1) A trend action on the range endpoints (chosen): one round
trip, small rows. (2) `date_str` ranges on each single-day action: N calls
and N full payloads (sleep ~5k characters a night). (3) The generic
`strip_bulky_fields` on range payloads: 3-20x larger rows and no say in which
numbers reach the model.
