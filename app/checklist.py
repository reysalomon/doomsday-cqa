"""Checklist validation shared by the API and the UI save flow."""
import re

TYPES = {"binary", "scale", "flag"}


def validate_checklist(data: dict) -> dict:
    """Return a clean checklist or raise ValueError with a message for the user."""
    name = str(data.get("name") or "").strip()
    criteria = data.get("criteria")
    if not name:
        raise ValueError("Укажите название чек-листа.")
    if not isinstance(criteria, list) or not criteria:
        raise ValueError("Добавьте хотя бы один критерий.")

    clean, seen = [], set()
    for raw in criteria:
        cid = str(raw.get("id") or "").strip()
        title = str(raw.get("title") or "").strip() or cid
        if not re.fullmatch(r"[a-z0-9_]+", cid) or cid in seen:
            raise ValueError(f"«{title}»: нужен уникальный id из латинских букв и цифр.")
        seen.add(cid)
        kind, weight = raw.get("type"), raw.get("weight")
        if kind not in TYPES:
            raise ValueError(f"«{title}»: неизвестный тип ответа.")
        if isinstance(weight, bool) or not isinstance(weight, int) or weight < 0:
            raise ValueError(f"«{title}»: вес должен быть целым числом от 0.")
        rule = str(raw.get("rule") or "").strip()
        if not title or not rule:
            raise ValueError(f"«{title or cid}»: заполните название и правило оценки.")
        item = {"id": cid, "section": str(raw.get("section") or "").strip(), "title": title,
                "type": kind, "weight": weight, "na_allowed": bool(raw.get("na_allowed")),
                "rule": rule}
        if kind == "flag":
            if weight or item["na_allowed"]:
                raise ValueError(f"«{title}»: у флага нет веса и N/A.")
        if item["na_allowed"]:
            item["na_rule"] = str(raw.get("na_rule") or "").strip()
            if not item["na_rule"]:
                raise ValueError(f"«{title}»: опишите, когда ставится N/A.")
        if kind == "scale":
            steps = raw.get("scale") or []
            values = [step.get("value") for step in steps]
            valid = all(isinstance(v, int) and not isinstance(v, bool) and v >= 0 for v in values)
            if len(steps) < 2 or not valid or len(set(values)) != len(values) or max(values) <= 0:
                raise ValueError(f"«{title}»: шкале нужны минимум две разные целые ступени.")
            if not all(str(step.get("label") or "").strip() for step in steps):
                raise ValueError(f"«{title}»: опишите каждую ступень шкалы.")
            item["scale"] = sorted(({"value": s["value"], "label": s["label"].strip()} for s in steps),
                                   key=lambda s: -s["value"])
        clean.append(item)
    if not any(c["type"] != "flag" and c["weight"] > 0 for c in clean):
        raise ValueError("Нужен хотя бы один критерий с весом.")
    return {"name": name, "criteria": clean}


def allowed_answers(criterion: dict) -> list:
    if criterion["type"] == "scale":
        values = [step["value"] for step in criterion["scale"]]
    else:
        values = ["yes", "no"]
    return values + (["na"] if criterion.get("na_allowed") else [])
