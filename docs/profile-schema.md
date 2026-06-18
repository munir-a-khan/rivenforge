# Profile Schema

Current profile schema version: `1`.

Legacy profile shape:

```json
{
  "schema_version": 1,
  "name": "Example",
  "desired_positives": ["Critical Damage", "Range"],
  "min_positives_required": 2,
  "acceptable_negatives": ["Impact"],
  "rejected_negatives": ["Damage to Corpus"],
  "required_negatives": []
}
```

Structured profile shape:

```json
{
  "schema_version": 1,
  "name": "Example",
  "positive_groups": [
    {
      "label": "required positives",
      "min_required": 2,
      "slots": [
        { "label": "CD", "accepted_stats": ["Critical Damage"] },
        { "label": "Range", "accepted_stats": ["Range"] }
      ]
    }
  ],
  "safe_negatives": ["Impact"],
  "rejected_negatives": [],
  "required_negatives": []
}
```

Stat names are normalized before matching.
