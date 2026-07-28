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
mypy cli datasets neoql engine.py
coverage run -m unittest discover -v
coverage report
python -m build
```

Coverage is enforced at 70%. Continuous integration runs the suite on every
supported Python version and publishes coverage XML plus built distributions as
workflow artifacts. See [CONTRIBUTING.md](CONTRIBUTING.md) for the contribution
and release workflow, and the
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

## 12. References

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

## 13. Automatic resolution

When an inline object is assigned to a reference:

```neoql
manager={
    id=7,
    name="Alice"
}
```

NeoDB detects the destination dataset, inserts the object if required, and
stores its reference.

## 14. Graph links

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

## 15. Selection methods

Every Selection exposes composable methods that return another Selection:

```neoql
.where()
.order()
.limit()
.offset()
.unique()
.traverse()
.group()
.sort()
.reverse()
.flatten()
.expand()
.distinct()
```

## 16. Traversal

General form:

```neoql
selection.traverse(relationship(), depth=2)
```

Example:

```neoql
users({id=1}).traverse(
    friends({age>18}),
    depth=3
)
```

## 17. Variables

Selections can be assigned to immutable, lazy variables:

```neoql
adults = users({age>=18})
employees = users({role="Engineer"})
```

## 18. Selection algebra

| Operation | Syntax |
| --- | --- |
| Union | `A + B` |
| Intersection | `A & B` |
| Difference | `A - B` |
| Symmetric difference | `A ^ B` |
| Cartesian product | `A * B` |

The operators `÷`, `×`, `⊂`, and `⊃` may receive symbolic aliases in a future
version.

## 19. Aggregations

```neoql
users().count()
users().sum(salary)
users().avg(age)
users().max(age)
users().min(age)
users().median(age)
users().std(age)
```

## 20. Grouping

`group` returns a grouped Selection, which can be aggregated:

```neoql
users().group(country)
users().group(country).count()
```

## 21. Ordering

```neoql
.order(age)
.order(age desc)
.order(name asc)
```

## 22. Pagination

```neoql
.limit(20)
.offset(40)
```

## 23. Pattern matching

Future syntax:

```neoql
users().match(
    friend
    ->
    company
)
```

The graph planner may optimize matching automatically.

## 24. Type inference

NeoQL infers references, literals, datasets, graph edges, and collection types
where possible. Explicit casting remains available.

## 25. Transactions

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

Nested transactions are supported.

## 26. Functions

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

User-defined functions:

```neoql
function fullName(first, last){
    ...
}
```

## 27. Lazy execution

Every statement builds an execution plan. Execution occurs when a client
consumes results, a mutation occurs, or an API returns. This allows NeoDB to
optimize an entire pipeline.

## 28. Optimizer rules

NeoDB may reorder operations while preserving semantics, including:

- Projection and predicate pushdown
- Traversal optimization
- Index selection
- Join elimination
- Graph and vector pruning

## 29. Error handling

Compile-time errors include unknown datasets or fields, type mismatches, and
invalid traversals. Runtime errors include constraint violations, permission
denials, deadlocks, timeouts, and missing references.

## 30. Language goals

NeoQL should be:

- **Small:** the core language should fit on a few pages.
- **Readable:** queries should resemble natural object manipulation.
- **Consistent:** all storage models should share syntax where possible.
- **Composable:** every operation should produce another Selection.
- **Optimizable:** developers describe what they want, and NeoDB decides how
  to execute it efficiently.

## 31. Complete example

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
