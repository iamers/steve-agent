# .steve/

Project-level coordination artifacts maintained by [Steve Agent](https://github.com/iamers/steve-agent).

## What lives here

Files that govern how Steve Agent coordinates work on **this** repo:

- `review-policy.yaml` — deterministic review-tier policy (which paths are blast / propagation / safe, and what each tier requires).
- `review-brief-template.md` — the template Steve Agent fills when opening or summarizing a review.

Future additions may include a decision log and per-area brief templates.

## How changes enter

`.steve/` is versioned like any other part of the repo. Contents are modified **only through pull requests** — Steve Agent never writes here directly from chat. A change to `.steve/` is itself a change to the coordination process and goes through the same review as any other PR.

## Mechanism vs configuration

The **mechanisms** are generic and part of the Steve Agent product: deterministic path-based tiers, PR tier = max of its files, and a fail-safe default tier when nothing matches.

The **paths and values** inside each file are **per-repo configuration** — they tell the generic mechanisms which files matter for *this* project. Forking Steve Agent into a new repo means editing the paths, not the mechanism.
