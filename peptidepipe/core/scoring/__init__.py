"""Scoring interfaces (category-agnostic). Concrete engines live in
peptidepipe/adapters and register themselves under a name; the core only ever
talks to the abstract AffinityScorer and the registry."""
