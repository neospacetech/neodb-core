# NeoDB Core

NeoDB is an embeddable, schema-aware database engine built around NeoQL: one
query language for tables, graphs, documents, key/value data, and vectors.

> Status: early Python MVP. Dataset creation, record insertion, filtering,
> ordering, projection, and pagination are the first implementation target.

## Quick start

NeoDB supports Python 3.10 through 3.14 and has no third-party runtime
dependencies.

```bash
git clone https://github.com/neospacetech/neodb-core.git
cd neodb-core
python -m pip install -e .
neodb
```

Execute a NeoQL script with `neodb path/to/script.neoql`. The shell shows
`... ` while delimiters or string literals remain open. Scripts may contain
comments, blank lines, top-level semicolon-separated statements, or one
complete statement per line. Multiline statements remain buffered until
complete.

Script execution returns `0` on success, `1` for a NeoQL diagnostic, and `2`
when the source file cannot be read. Diagnostics include the source filename
and global line and column.

Example session:

```neoql
create dataset users(table{id(int, pk), name(str(255)), age(int)})
add {id=1, name="Alice", age=25}, {id=2, name="Ben", age=17} into users
users({age>=18}).(name, age).order(age desc).limit(20)
```

Run the tests with:

```bash
python -m unittest discover -v
```

## Development

Install the development toolchain and run all local quality gates:

```bash
python -m pip install -e ".[dev]"
ruff format --check .
ruff check .
mypy cli datasets neoql scripts engine.py storage.py
coverage run -m unittest discover -v
coverage report
python -m build
```

Coverage is enforced at 70%. Continuous integration runs the suite on every
supported Python version and publishes coverage XML plus built distributions as
workflow artifacts. See [CONTRIBUTING.md](CONTRIBUTING.md) for the contribution
workflow, [RELEASING.md](RELEASING.md) for trusted releases and TestPyPI dry
runs, and the
[NeoDB Core Roadmap](https://github.com/orgs/neospacetech/projects/3) for current
progress.

## Language frontend

NeoQL source is tokenized and parsed independently of the CLI:

```python
from neoql import parse_statement

statement = parse_statement("users({age>=18}).(name, age).limit(20)")
```

The returned typed AST is immutable and every node carries a source span with
line and column positions. Syntax errors use those spans to render a precise
diagnostic and source caret. The current engine adapter converts supported AST
statements into the MVP execution contract while the lazy planner is developed.

Parsed schemas pass through NeoQL's semantic type system before reaching the
engine. The public type API supports validation, display, serialization,
literal inference, and explicit casting:

```python
from neoql import cast_value, infer_type, parse_type

user_id = parse_type("uuid")
tags = parse_type("list(str(32))")
inferred = infer_type([1, 2, 3])
identifier = cast_value("12345678-1234-5678-1234-567812345678", user_id)
```

## Schema enforcement

Table schemas are runtime contracts. Fields are required unless they are
nullable or have a default, and values are cast through their declared NeoQL
type before storage:

```neoql
create dataset users(
    table{
        tenant_id(int, pk),
        id(int, pk),
        email(str(255), unique, index),
        display_name(str(80), default("Anonymous")),
        nickname(str(80), nullable),
        biography(text, searchable),
        embedding(list(float), vector),
        created_by(str(80), readonly)
    }
)
```

Primary keys and unique values are checked across existing records and an
entire incoming batch before anything is committed. Updates use the same type,
nullability, uniqueness, and readonly rules. The schema also exposes index,
vector, and search metadata for later planners.

Constraint failures raise `ConstraintViolation`, whose `to_dict()` result
contains a stable error category, code, dataset, field, message, offending
value when applicable, and additional conflict details.

## Roadmap

- Complete the NeoQL parser and typed abstract syntax tree
- Enforce schemas and constraints
- Add document, vector, and relationship storage
- Build lazy selections and an execution planner
- Add persistence, write-ahead logging, indexes, and ACID transactions
- Ship SDKs and remote HTTP/WebSocket access

---

# Appendix A — NeoQL Language Specification

**Draft v0.1**

## 1. Language philosophy

NeoQL is an object-oriented query language built around **Selections**. Unlike
SQL, NeoQL does not distinguish between tables, graphs, documents, or
relationships. Every dataset produces a Selection, and every operation
transforms one Selection into another.

## 2. Primitive types

```neoql
int
float
decimal
bool
char
str(length)
text
date
time
datetime
timestamp
duration
uuid
bytes
json
```

## 3. Composite types

| Type | Syntax | Meaning |
| --- | --- | --- |
| List | `list(T)` | Ordered collection |
| Set | `set(T)` | Unique, unordered collection |
| Map | `map(K, V)` | Key/value collection |
| Tuple | `tuple(T1, T2...)` | Fixed heterogeneous collection |
| Reference | `users` | Reference to another dataset |
| Nullable | `nullable(T)` | Optional value |
| Enum | `enum(...)` | One value from a fixed set |

## 4. Dataset types

The initial dataset types are:

```neoql
table
graph
document
kv
vector
```

`document` uses the schema and mutation contract of tables while preserving
nested `json` values. `kv` records have exactly `{key, value}` and participate
in normal filtering, projection, ordering, and pagination. `vector` is a
schema-aware document collection with one or more vector-indexed fields.

`timeseries` and `columnar` are reserved for future use.

## 5. Dataset definition

General form:

```neoql
create dataset <name>(
    <storage>{
        fields...
    }
)
```

Example:

```neoql
create dataset users(
    table{
        id(int, pk),
        name(str(255)),
        age(int)
    }
)
```

## 6. Constraints

Supported constraints:

```neoql
pk
unique
nullable
default
index
vector
searchable
readonly
```

Example:

```neoql
email(str(255), unique, index)
```

Vector fields use a numeric list and may declare their required dimension:

```neoql
embedding(list(float), vector(1536))
```

## 7. Dataset invocation

General forms:

```neoql
dataset()
dataset(predicate)
dataset(predicate, options)
```

Examples:

```neoql
users()
users({id=1})
users({age>18})
```

## 8. Predicates

Predicates are enclosed in braces:

```neoql
{id=5}
{age>18}
{name startsWith "Al"}
{salary>=50000}
{age>18 && verified=true}
```

Supported operators:

```neoql
=  !=  >  >=  <  <=
&&  ||  !
in  contains  startsWith  endsWith  matches
```

Precedence is unary `!`, then `&&`, then `||`; parentheses override it.
Predicates are validated against table schemas before scanning any records.
Numeric types compare with one another, string types compare with one another,
and incompatible operands raise a structured predicate error rather than being
silently coerced.

`null` is equal only to `null`, and ordering comparisons involving `null`
evaluate to false. Membership requires a collection operand, string operations
require strings, and invalid regular expressions are reported as predicate
errors with stable codes.

## 9. Projection

Projection uses parentheses:

```neoql
users().(
    name,
    age
)
```

Nested projection:

```neoql
users().(
    name,
    manager(name),
    company(name, city)
)
```

## 10. Records

Record literals use `=` for assignment, never `:`:

```neoql
{
    id=1,
    name="Alice",
    age=25
}
```

## 11. Insert

Insert a record or an existing Selection with `add ... into ...`:

```neoql
add {id=1, name="Alice"} into users
add users() into archive
```

## 12. Update and delete

Mutations are terminal operations on a dataset Selection:

```neoql
users({id=1}).update({name="Alice", active=true})
users({inactive=true}).delete()
```

The predicate determines the affected records. An empty match succeeds with an
affected count of zero. An invocation without a predicate targets the full
dataset:

```neoql
sessions().delete()
```

`update` returns `{status="success", updated=<count>}` and `delete` returns
`{status="success", deleted=<count>}` at the engine boundary. Update values are
schema-normalized and enforce unknown-field, nullability, readonly, uniqueness,
and reference constraints. Each mutation is atomic, including inline reference
resolution, and an error rolls back the entire active transaction. Mutation
operations must directly follow dataset invocation and cannot be followed by
another Selection method. Deleting a referenced record, or changing identity
fields used by an existing reference, fails with `reference_in_use`.

## 13. References

Selections are valid values:

```neoql
manager=users({id=7})
```

Selections can also appear in collections:

```neoql
set(
    users({id=1}),
    users({id=2})
)
```

## 14. Automatic resolution

When an inline object is assigned to a reference:

```neoql
manager={
    id=7,
    name="Alice"
}
```

NeoDB detects the destination dataset, inserts the object if required, and
stores its reference.

References are stored as immutable `ReferenceValue` instances containing the
target dataset and identity fields. Table identity uses the primary key when
available, then declared unique fields; graph and key/value identity use `id`
and `key`. A scalar reference is accepted only for a single-field primary key.
Inline objects reuse an existing record when one identity matches, otherwise
they are inserted into the destination dataset in the same transaction.

Reference collections work recursively in `list`, `set`, `tuple`, and `map`
types. Referenced datasets must already exist when the source schema is
created, except for a self-reference. Targets without a primary or unique
identity are rejected. Missing, ambiguous, conflicting, and cyclic references
use the stable diagnostic codes `missing_reference`, `ambiguous_reference`,
`reference_conflict`, and `reference_cycle`. If source validation fails after
an inline insert, the destination insert is rolled back.

## 15. Graph links

```neoql
add link(
    label="friend",
    bidir=true,
    data={since="2024"}
)
between
users({id=1}),
users({id=2})
```

Links are first-class records.

`label` is required; `bidir` defaults to `false` and `data` defaults to an
empty object. Both endpoint Selections must resolve to exactly one node in the
same graph dataset. Links receive a stable dataset-local `id`.

## 16. Selection methods

Every Selection exposes composable methods that return another Selection:

```neoql
.where({active=true})
.order(name asc)
.limit(20)
.offset(10)
.unique()
.traverse()
.group()
.sort(name)
.reverse()
.flatten(tags)
.expand(profile)
.distinct()
```

`unique()` and `distinct()` remove duplicate records while preserving the
first occurrence; passing fields deduplicates by those fields. `sort` is a
single-direction convenience for `order`, and `reverse` reverses the current
result. `flatten(field)` emits one record per collection item and replaces the
collection with that item. `expand(field)` removes an object field and merges
its members into the parent; collisions are schema errors. All methods append
lazy immutable plan nodes.

## 17. Traversal

General form:

```neoql
selection.traverse(relationship(), depth=2)
```

Example:

```neoql
users({id=1}).traverse(
    friend,
    3
)
```

Traversal follows matching labels breadth-first, excludes the starting nodes,
and never emits a node twice, so cycles are safe. Directed links follow source
to target; bidirectional links can be followed from either endpoint. Depth
must be positive and defaults to one. The returned value is a lazy Selection,
so normal filters and transforms can be appended before it is consumed.

## 18. Variables

Selections can be assigned to immutable, lazy variables:

```neoql
adults = users({age>=18})
employees = users({role="Engineer"})
```

Assignment stores the Selection plan without scanning its dataset. A binding
cannot be reassigned or redeclared in the same session. Referencing the name
returns its Selection, and `name()` can append more Selection operations without
changing the stored plan:

```neoql
firstTenAdults = adults().order(age asc).limit(10)
firstTenAdults
```

Bindings are session-local: a script and an interactive shell retain them
between statements, but a new process starts with an empty language scope.

## 19. Selection algebra

| Operation | Syntax |
| --- | --- |
| Union | `A + B` |
| Intersection | `A & B` |
| Difference | `A - B` |
| Symmetric difference | `A ^ B` |
| Cartesian product | `A * B` |

Union, intersection, difference, and symmetric difference require identical
field sets. They use structural record equality, return distinct records, and
preserve stable left-then-right order where applicable. Empty Selections are
compatible with any schema. Cartesian product preserves input multiplicity
and emits `{left: <record>, right: <record>}` so overlapping field names are
unambiguous. Algebra operators are lazy and do not consume either operand
until their result is consumed.

Product (`*`) binds most tightly, followed by intersection (`&`), then
difference and symmetric difference (`-` and `^`), then union (`+`). Operators
at the same level associate left-to-right. Parentheses override precedence and
the result can be chained like any other Selection:

```neoql
active = (adults + employees).where({active=true}).distinct(id)
```

The operators `÷`, `×`, `⊂`, and `⊃` may receive symbolic aliases in a future
version.

## 20. Aggregations

```neoql
users().count()
users().sum(salary)
users().avg(age)
users().max(age)
users().min(age)
users().median(age)
users().std(age)
```

Aggregations are lazy result objects and scan their source only when consumed.
`count()` counts every selected record. Field aggregates ignore `null`;
`sum` returns `0` when no non-null values remain, while `avg`, `min`, `max`,
`median`, and `std` return `null`. `sum`, `avg`, `median`, and `std` require
numeric fields; incompatible values raise `invalid_aggregation`. `std` is the
population standard deviation.

## 21. Grouping

`group` returns a grouped Selection, which can be aggregated:

```neoql
users().group(country)
users().group(country).count()
```

Groups preserve the first-seen key order and include `null` as a key.
Consuming an unaggregated group returns records shaped as
`{country=<key>, records=[...]}`. A grouped aggregation returns one record per
group, such as `{country="US", count=2}` or `{country="US", avg=42}`.

## 22. Ordering

```neoql
.order(age)
.order(age desc)
.order(name asc)
```

## 23. Pagination

```neoql
.limit(20)
.offset(40)
```

## 24. Pattern matching

Future syntax:

```neoql
users().match(
    friend
    ->
    company
)
```

The graph planner may optimize matching automatically.

## 25. Type inference

NeoQL infers references, literals, datasets, graph edges, and collection types
where possible. Explicit casting remains available.

## 26. Transactions

```neoql
begin
...
commit
```

Or:

```neoql
transaction{
    ...
}
```

Transactions execute against private copy-on-write dataset frames. An outer
commit publishes its frame atomically; abort or an execution error discards
it. A nested transaction is a savepoint: its commit merges into its parent,
while its abort discards only nested work. Only the innermost frame may be
completed. `rollback` and `abort transaction` are aliases.

Selections bind to the dataset snapshot visible when they are created. This
keeps selections created before `begin` isolated from staged writes. A
`transaction{...}` block and an engine `batch` are implicit atomic
transactions, so a failed constraint cannot leave earlier mutations applied.

### Durable engine storage

Passing a storage directory enables durable commits and automatic recovery:

```python
engine = NeoDBEngine("./data")
```

The directory contains a versioned, checksummed `snapshot.json` and a
checksummed `wal.jsonl`. An outer transaction commit fsyncs its complete state
to the WAL as the commit point, then atomically checkpoints the snapshot and
publishes the state in memory. A checkpoint failure leaves the durable WAL
authoritative. Startup replays its latest valid record and retries the
checkpoint. A partial final WAL
record is discarded, while checksum, version, schema, reference, graph-link,
and index inconsistencies raise structured `storage_corruption` or
`storage_version` diagnostics.

Primary-key, unique, and secondary equality indexes are stored in the snapshot,
rebuilt and cross-checked during recovery, and used through the optimizer's
index lookup plan. Nested transactions remain in memory until their outermost
commit. Engines created without a storage directory retain the in-memory
behavior.

## 27. Functions

Built-in functions:

```neoql
len()
abs()
round()
lower()
upper()
contains()
distance()
similarity()
today()
now()
uuid()
```

Vector similarity is a lazy Selection operation and must precede projection,
ordering, and pagination:

```neoql
items().similarity(embedding, [0.1, 0.2, 0.3], cosine).limit(10)
items().distance(embedding, [0.1, 0.2, 0.3]).limit(10)
```

Results are ordered by nearest distance and include `_distance` and
`_similarity`. Cosine and Euclidean metrics are supported. Stored vectors and
query vectors must match the declared dimension; cosine rejects zero vectors.

User-defined functions:

```neoql
function adultsByRole(role){
    users({age>=18, role=role})
}

adultsByRole("Engineer")
```

The function body is one expression and its value is the return value.
Parameters are immutable, call-local values and may be used in predicates and
Selection method arguments. Functions can call session declarations and refer
to session-level Selection bindings. Declarations become visible after their
definition; parameters do not escape their call. Direct or indirect recursion
is rejected in draft v0.1 with a `recursion_not_allowed` diagnostic.

## 28. Lazy execution

Every statement builds an execution plan. Execution occurs when a client
consumes results, a mutation occurs, or an API returns. This allows NeoDB to
optimize an entire pipeline.

Dataset selections return an immutable `Selection`. Calling `where`,
`project`, `order`, `offset`, or `limit` returns a new Selection with an
additional frozen plan node; it does not scan the dataset. Calling `consume`,
iterating, taking the length, indexing, or comparing with another sequence is
a consumption boundary. The CLI is also a consumption boundary and renders
materialized records. Inserts and updates remain immediate mutation
boundaries.

```python
selection = engine.execute_query(query)
refined = selection.where({"field": "active", "op": "=", "value": True})
records = refined.consume()
```

## 29. Optimizer rules

NeoDB may reorder operations while preserving semantics, including:

- Projection and predicate pushdown
- Traversal optimization
- Index selection
- Join elimination
- Graph and vector pruning

Selections are optimized automatically at consumption. `explain()` returns
the logical and optimized plans plus the names of applied rules without
scanning the dataset:

```neoql
users({email="a@example.com"}).limit(1).explain()
```

The public Python API also exposes `selection.optimized()` and
`selection.explain()`. Indexed equality predicates use the dataset
`_index_lookup` hook; storage engines can replace the fallback scan without
changing Selection semantics.

## 30. Error handling

Compile-time errors include unknown datasets or fields, type mismatches, and
invalid traversals. Runtime errors include constraint violations, permission
denials, deadlocks, timeouts, and missing references.

All public diagnostics inherit from `DiagnosticError` and expose `to_dict()`.
The stable payload includes `error`, `code`, `message`, `phase`, `retryable`,
and `details`. Compile-time diagnostics also include a half-open `location`
with offsets and one-based line and column positions. The CLI prints a concise
`Error [code]: message` line followed by the same payload as JSON.

| Code | Phase | Meaning |
| --- | --- | --- |
| `syntax_error` | parse | Invalid NeoQL syntax |
| `type_mismatch` | compile | Invalid type declaration, inference, or cast |
| `invalid_schema` | compile | Invalid field or constraint declaration |
| `unknown_dataset` | plan | Dataset cannot be resolved |
| `unknown_field` | plan/runtime | Field cannot be resolved |
| `invalid_traversal` | plan | Traversal cannot be planned |
| `missing_reference` | runtime | Referenced record does not exist |
| `permission_denied` | runtime | Operation is not authorized |
| `timeout` | runtime | Query exceeded its deadline; retryable |
| `deadlock` | runtime | Transaction was aborted; retryable |

Constraint and predicate diagnostics use more specific stable codes such as
`required`, `unique`, `readonly`, `null`, `unknown_operator`,
`invalid_operand`, and `invalid_pattern`. Callers should branch on `code` and
treat the human-readable `message` as display text.

## 31. Language goals

NeoQL should be:

- **Small:** the core language should fit on a few pages.
- **Readable:** queries should resemble natural object manipulation.
- **Consistent:** all storage models should share syntax where possible.
- **Composable:** every operation should produce another Selection.
- **Optimizable:** developers describe what they want, and NeoDB decides how
  to execute it efficiently.

## 32. Complete example

```neoql
employees =
users({department="Engineering"}).
    traverse(works_on(), depth=1)

highPerformers =
employees({performance>=4.5})

projects =
highPerformers.
    traverse(project())

activeProjects =
projects({status="Active"}).(
    name,
    manager(name),
    deadline
)
```

No joins or foreign keys are written, graph syntax is not separate from table
syntax, every intermediate value is a Selection, and the entire query can be
optimized as one execution plan. This is the core NeoQL philosophy: **one
language, one abstraction, many storage models.**
