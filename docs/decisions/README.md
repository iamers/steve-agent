# Architecture decision records

Each decision is stored in one `adr-YYYYMMDD-slug.md` file. The date is when the decision was first recorded in the repository, and the short English kebab-case slug states what was decided. YAML front matter records that date and a status of `accepted`, `superseded`, or `rejected`; supersession fields are added only when they apply. A record that reverses part of an earlier one without replacing it carries `amends:` and the earlier one carries `amended-by:`, and the earlier record stays `accepted` because the rest of it still decides: the reversed clauses are marked where they stand, so a reader arriving at the old text is not misled by it.

Record a decision here before starting the work that implements it. Each record separates context, the decision, consequences, and alternatives considered, and explicitly marks material that was not recorded when the decision was taken.
