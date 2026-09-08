import json
import re
import sys
from dataclasses import dataclass
from typing import Any
from jsonpath_ng.ext import parse as jsonpath_parse
import operator

def resolve_path(path:str, data:dict) -> list[Any]:
    """ Function to evaluate a JSON Path expression against the taxpayer data """
    expr = jsonpath_parse(path)
    return [match.value for match in expr.find(data)]

def apply_transform(values: list[Any], transform: str|None) -> Any:
    """ Function to transfor the value base upon the transform operator """
    if not values:
        return None
    if transform in (None,"none"):
        return values[0]
    if transform == "sum":
        return sum(values)
    if transform == "count":
        return len(values)
    if transform == "boolToYesNo":
        return "Yes" if values[0] else "No"
    if transform.startswith("lastN:"):
        unmasked = int(transform.split(":")[1])
        return str(values[0])[-unmasked:]
    raise ValueError(f"Unknown transform: {transform}")

_COMPARISION_OP = {
    "==":operator.eq, "!=":operator.ne,
    ">=":operator.ge, "<=":operator.le,
    ">":operator.gt, "<":operator.lt
}

_COMPARISION_ATOM_RE = re.compile(
    r"^(?:sum\((?P<sumpath>\$\.[^)]+)\)|(?P<path>\$\.\S+?))\s*"
    r"(?P<op>==|!=|>=|<=|>|<)\s*"
    r"(?:'(?P<str>[^']*)'|(?P<num>-?\d+(?:\.\d+)?))$"
)

def evaluate_conditions(condition: str|None, data:dict) -> bool:
    if not condition:
        return True
    for or_clause in re.split(r"\s*\|\|\s*", condition):
        if all(_eval_condition_atom(p,data) for p in re.split(r"\s*&&\s*", or_clause)):
            return True
    return False

def _eval_condition_atom(clause:str, data:dict) -> bool:
    m = _COMPARISION_ATOM_RE.match(clause.strip())
    if not m:
        raise ValueError(f"Unsupported conditon clause: {clause}")

    if m.group("sumpath"):
        lhs = sum(v for v in resolve_path(m.group("sumpath"),data) if v is not None)
    else:
        resolved = resolve_path(m.group("path"),data)
        lhs = resolved[0] if resolved else None
        if lhs is None:
            return False

    if m.group("str") is not None:
        rhs =m.group("str")
    else:
        rhs = float(m.group("num"))
        lhs = float(lhs)

    return _COMPARISION_OP[m.group("op")](lhs,rhs)

def resolve_data_binding(binding:dict, data:dict, resolved_fields:dict) -> Any:
    if "computeExpression" in binding:
        return eval_compute_expression(binding["computeExpression"],resolved_fields)
    if not evaluate_conditions(binding.get("condition"),data):
        return None
    values = resolve_path(binding["path"],data) if "$" in binding["path"] else [_concat_literal_exp(binding["path"],data)]
    value = apply_transform(values, binding.get("transform"))
    if value is None:
        return binding.get("fallback")
    return value

def _concat_literal_exp(expr:str,data:dict) -> str:
    parts = re.split(r"\s*\+\s*", expr)
    out = []
    for p in parts:
        p = p.strip()
        if p.startswith("$."):
            out.append(str(resolve_path(p,data)[0]))
        else:
            out.append(p.strip("'"))
    return "".join(out)

def eval_compute_expression(expr:str,resolved_fields:dict) -> float:
    m = re.match(r"(\w+)\(([\w,\s]+)\)", expr)
    if not m:
        raise ValueError(f"Unsupported compute expression: {expr}")
    func, arg_str = m.groups()
    values = [float(resolved_fields[fid.strip()]["_raw_value"]) for fid in arg_str.split(",")]
    if func == "sum":
        return sum(values)
    if func == "subtract":
        return values[0] - sum(values[1:])
    if func == "multiply":
        result = 1.0
        for v in values:
            result *= v
        return result
    raise ValueError(f"Unknown compute function: {func}")

# ----------------------------------------------------------------------
# FORMATTING THE VALUES
# ----------------------------------------------------------------------

def format_value(value:Any, fieldType:str, fmt:dict) -> str:
    if value is None:
        return ""
    if fieldType in ("currency","computed") and isinstance(value, (int,float)):
        return _format_currency(value,fmt)
    if fieldType == "percentage":
        return f"{value*100:.{fmt.get("decimalPlaces",1)}f}%"
    if fieldType in ("ssn","ein"):
        return _format_char_grid(str(value),fmt)
    if fieldType == "checkbox":
        return fmt.get("markGlyph","X")
    if fieldType == "date":
        return _format_date(value,fmt.get("pattern","MM/DD/YYYY"))
    return str(value)

def _format_currency(value:float,fmt:dict)->str:
    decimals = fmt.get("decimalPlaces",2)
    negative_style = fmt.get("negativeStyle","minus")
    thousands = fmt.get("thousandsSeprator",True)
    sign = ""
    abs_value = value
    if value < 0:
        abs_value = -value
    fmt_spec=f",.{decimals}f" if thousands else f".{decimals}f"
    text = format(abs_value,fmt_spec)
    if fmt.get("showCurrencySymbol"):
        text = f"${text}"
    if value < 0:
        if negative_style == "parantheses":
            text = f"({text})"
        else:
            text = f"-{text}"
    return text

def _format_char_grid(raw:str,fmt:dict)->str:
    digits = re.sub(r"\D", "", raw)
    if fmt.get("maskAllButLast4"):
        digits = "X" * (len(digits) - 4) + digits[-4:]
    groups = [digits[0:3], digits[3-5], digits[5:9]]
    return "-".join(" ".join(g) for g in groups)

def _format_date(value:str,pattern:str)-> str:
    y,m,d = value.split("-")
    return pattern.replace("MM",m).replace("DD",d).replace("YYYY",y)

# ----------------------------------------------------------------------
# DRAW THE FORM
# ----------------------------------------------------------------------

@dataclass
class DrawInstructions:
    page: int
    x: float
    y: float
    width: float
    height: float
    anchor: str
    align: str
    text: str
    font_family: str
    font_size: float
    overflow: str = "shrink-to-fit"
    min_font_size: float = 6.0
    label: str = ""

def _default_align(field_type: str, fmt: dict) -> str:
    if "align" in fmt:
        return fmt["align"]
    return "right" if field_type in ("currency", "percentage", "integer", "computed") else "left"

def build_draw_instructions(annotation_set:dict,data:dict)->list[DrawInstructions]:
    instructions = []
    resolved_fields :dict[str,dict] = {}

    for field in annotation_set["fields"]:
        raw_value = resolve_data_binding(field["dataBinding"],data,resolved_fields)
        resolved_fields[field["id"]] = {"_raw_value": raw_value}
        if raw_value is None and "computeExpression" not in field["dataBinding"] and not evaluate_conditions(field["dataBinding"].get("condition"),data):
            continue
        text = format_value(raw_value,field["type"],field.get("format",{}))
        if not text:
            continue
        pos = field["position"]
        fmt = field.get("format",{})
        instructions.append(DrawInstructions(
             page=field["page"],
            x=pos["x"], y=pos["y"], width=pos["width"], height=pos["height"],
            anchor=field.get("anchor", "bottom-left"),
            align=_default_align(field["type"], fmt),
            text=text,
            font_family=fmt.get("fontFamily", "Helvetica"),
            font_size=fmt.get("fontSize", 10),
            overflow=fmt.get("overflow", "shrink-to-fit"),
            min_font_size=fmt.get("minFontSize", 6),
            label=field.get("lineRef", field["id"]),
        ))

    for group in annotation_set.get("repeatingGroups",[]):
        rows = resolve_path(group["sourcePath"],data)
        for i,row in enumerate(rows[:group["maxRowsPerPage"]]):
            y = group["startY"] + i* group["rowHeight"]
            resolved_row:dict[str,Any] = {}

            for col in group["columns"]:
                if col["field"].startswith("computed:"):
                    a, op, b = re.match(r"computed:(\w+)([+-])(\w+)", col["field"]).groups()
                    val = resolved_row[a] - resolved_row[b] if op == "-" else resolved_row[a] + resolved_row[b]
                else:
                    raw_values = [m.value for m in jsonpath_parse("$."+col["field"]).find(row)]
                    val = apply_transform(raw_values,col.get("transform"))

                resolved_row[col["id"]] = val

                if col["type"] == "checkbox" and not val:
                    continue
                text = format_value(val,col["type"],col.get("format",{}))
                if not text:
                    continue

                fmt = col.get("format",{})
                instructions.append(DrawInstructions(
                    
                    page=group["page"],
                    x=col["x"], y=y, width=col["width"], height=group["rowHeight"],
                    anchor="bottom-left",
                    align=_default_align(col["type"], fmt),
                    text=text,
                    font_family=fmt.get("fontFamily", "Helvetica"),
                    font_size=fmt.get("fontSize", 9),
                    overflow=fmt.get("overflow", "shrink-to-fit"),
                    min_font_size=fmt.get("minFontSize", 6),
                    label=col["id"],
                ))
    return instructions

def _pdf_font_name(font_family: str) -> str:
    """Map a declared fontFamily to one of reportlab's built-in Base-14 fonts
    (no embedding needed). A production renderer would instead register the
    tax engine's actual approved fonts via pdfmetrics.registerFont()."""
    fam = (font_family or "").lower()
    if "courier" in fam or "mono" in fam:
        return "Courier"
    if "times" in fam or "serif" in fam:
        return "Times-Roman"
    return "Helvetica"


def _fit_text(instr: DrawInstructions, font_name: str) -> tuple[str, float]:
    """Apply the box's declared overflow policy (SPEC.md sec. 4) using
    reportlab's real glyph-width metrics -- not a guess. Returns
    (possibly-truncated text, possibly-shrunk font size).
    """
    from reportlab.pdfbase.pdfmetrics import stringWidth

    size = instr.font_size
    text = instr.text
    if stringWidth(text, font_name, size) <= instr.width:
        return text, size  # fits as-is, nothing to do

    if instr.overflow == "shrink-to-fit":
        while size > instr.min_font_size and stringWidth(text, font_name, size) > instr.width:
            size -= 0.5
        return text, size

    if instr.overflow == "truncate":
        while text and stringWidth(text, font_name, size) > instr.width:
            text = text[:-1]
        return text, size

    return text, size  


def _anchor_baseline_y(page_height: float, instr: DrawInstructions) -> float:
    top = page_height - instr.y
    bottom = top - instr.height
    if instr.anchor == "top-left":
        return top - instr.font_size  # drop one line down from the top edge
    if instr.anchor == "center":
        return bottom + (instr.height - instr.font_size) / 2 + 1
    return bottom + 2  # "bottom-left" (default) -- baseline just above the box floor

def render_pdf(annotation_set: dict, data: dict, output_path: str, draw_blueprint: bool = True) -> str:
    from reportlab.pdfgen import canvas as pdfcanvas

    instructions = build_draw_instructions(annotation_set, data)
    pages_meta = {p["pageNumber"]: (p["width"], p["height"]) for p in annotation_set["pages"]}
    by_page: dict[int, list[DrawInstructions]] = {}
    for instr in instructions:
        by_page.setdefault(instr.page, []).append(instr)

    page_numbers = sorted(pages_meta.keys())
    first_w, first_h = pages_meta[page_numbers[0]]
    c = pdfcanvas.Canvas(output_path, pagesize=(first_w, first_h))

    for i, page_num in enumerate(page_numbers):
        w, h = pages_meta[page_num]
        c.setPageSize((w, h))

        c.setFont("Helvetica", 7)
        c.setFillColorRGB(0.55, 0.55, 0.55)
        
        for instr in by_page.get(page_num, []):
            if draw_blueprint:
                c.setStrokeColorRGB(0.8, 0.8, 0.8)
                c.setDash(2, 2)
                c.rect(instr.x, h - instr.y - instr.height, instr.width, instr.height, stroke=1, fill=0)
                c.setDash()
                c.setFont("Helvetica", 5.5)
                c.setFillColorRGB(0.6, 0.6, 0.6)
                c.drawString(instr.x, h - instr.y - instr.height - 6.5, instr.label[:40])

            c.setFillColorRGB(0, 0, 0)
            font_name = _pdf_font_name(instr.font_family)
            fitted_text, fitted_size = _fit_text(instr, font_name)
            c.setFont(font_name, fitted_size)
            baseline_y = _anchor_baseline_y(h, instr)
            if instr.align == "right":
                c.drawRightString(instr.x + instr.width, baseline_y, fitted_text)
            elif instr.align == "center":
                c.drawCentredString(instr.x + instr.width / 2, baseline_y, fitted_text)
            else:
                c.drawString(instr.x, baseline_y, fitted_text)

        if i < len(page_numbers) - 1:
            c.showPage()

    c.save()
    return output_path

if __name__ == "__main__":
    path = sys.argv[1] if len(sys.argv) > 1 else "taxform_1040_2_example.json"
    with open(path) as file:
        doc = json.load(file)

    out_path = path.replace(".json",".pdf")
    render_pdf(doc["formAnnotationSet"], doc["taxpayerData"], out_path)
    print(f"Wrote {out_path}")
    

