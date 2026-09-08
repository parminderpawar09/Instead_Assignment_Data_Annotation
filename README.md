# Tax Form Annotation — Problem, Categorization & Approach

## 1. Problem statement

Platform needs to take a computed, deeply nested taxpayer data document and print the right values onto the right boxes of a fixed-layout U.S. tax form (1040, Schedule C, W-2, etc.), so that a preparer and taxpayer end up with a completed, IRS-ready form.

The core difficulty: The data is hierarchical and shaped for computation. The form is flat, positional, and shaped for printing. Someone — often a tax analyst, not necessarily an engineer — needs a way to declare, per box: *where it is, how it should look, and what value fills it* — in a way any rendering application can consume mechanically, without custom code per form.

## 2. Categorizing the problem into 3 parameters

Every box on a tax form has exactly three independent concerns, and keeping them independent is the central design decision of the whole spec:

| # | Parameter | Question it answers | Why it must stay separate |
|---|---|---|---|
| 1 | **Position** | *Where* on the page is this box? | Box coordinates rarely change year to year — pure geometry, unrelated to data or formatting. |
| 2 | **Format** | *How* should the value look once printed? (currency style, negative-number convention, font, overflow behavior) | IRS formatting conventions change occasionally, independent of both the box's location and the underlying data field. |
| 3 | **Data binding** | *What* value fills the box, and where does it come from in a deeply nested dataset? | The taxpayer data model evolves constantly as the tax engine changes — annotations must survive that without needing the box's position or formatting touched. |

Coupling any two of these would force needless rework: renaming a data field shouldn't require re-measuring a box; a formatting-rule change shouldn't require re-authoring the data lookup; a form's annual box-position revision shouldn't touch formatting or data logic at all.

## 3. Approach used in the schema

Each `FieldAnnotation` in the schema is a single object with three cleanly separated sub-structures, one per parameter:

**Positioning →** `page`, `position: {x, y, width, height}`, `anchor`, `units` (declared once per form). Top-left origin, so it matches how a box-drawing tool or a screen would naturally express coordinates; the renderer flips this to a bottom-left origin only at the final PDF-drawing step.

**Formatting →** a `format` object whose shape depends on `type` (`currency`, `date`, `ssn`, `checkbox`, etc.) — e.g. `decimalPlaces`, `negativeStyle`, `overflow` (`shrink-to-fit` / `truncate` / `wrap`), `fontFamily`. Declared as data, so one renderer function serves every form; adding a new form never requires new renderer code, only a new annotation set.

**Data binding →** a `dataBinding` object built around **JSONPath** (RFC 9535) as the path language:
- `path` — reaches into the nested dataset, including array wildcards (`w2[*].box1Wages`) and filter predicates (`k1[?(@.entityType=='partnership')]`) for the genuinely "deeply nested" cases.
- `transform` — reduces an array to a single value (`sum`, `count`, etc.) once resolved.
- `condition` — a small whitelisted boolean grammar (comparisons, `sum()` thresholds) that skips a field entirely when it doesn't apply (e.g. a spouse SSN box only for joint filers).
- `computeExpression` — a tiny whitelisted arithmetic grammar (`sum`, `subtract`, `multiply`) for boxes that are totals of *other annotated fields*, not raw dataset values.

One additional structure, `RepeatingFieldGroup`, extends the same three-parameter model to variable-length schedules (dependents, rental properties, capital gains transactions): positioning becomes a `rowHeight`/`startY` tiling rule, formatting stays per-column, and data binding resolves a `sourcePath` array with per-row (and even per-row-aggregate) bindings.

The result: an annotation file is pure, auditable data — no embedded code — that any rendering engine (PDF overlay, HTML preview, print driver) can consume the same way, by resolving each field's three parameters independently and combining them at draw time.

## 4. Further enhancements

- **Multi-form cross-references.** A field on one form (e.g. 1040) that must equal an already-resolved value on another form (e.g. "Schedule 1, Line 10") — `dataBinding.path` could optionally address another form's resolved output, not just the raw dataset.
- **Localized formatting.** Puerto Rico / bilingual forms would need a `locale` property feeding into date and number formatting.
- **Annotation diffing/versioning tool.** IRS forms shift box positions slightly year over year; a utility to diff two `taxYear` annotation sets for the same `formId` and flag moved/removed boxes would reduce annual maintenance risk.

## Running the Implementation
- **Step 1**: Make sure python version 3.12 onwards is installed in the system
- **Step 2**: Open cmd and install the pacakges using command "pip install -r requirements.txt"
- **Step 3**: To convert the schema to a printable pdf use command "python implementation.py schema_file_name.json"
- **Step 4**: Visualise the Pdf along with the drawing instruction in the cmd