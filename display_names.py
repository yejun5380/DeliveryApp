"""Presentation-only names. Never mutates persisted places or delivery snapshots."""

from copy import deepcopy
import json
import re
import unicodedata


DISPLAY_ALIASES = {
    "롯데리아": ("LOTTERIA",),
    "맥도날드": ("McDonald's", "McDonalds"),
    "맘스터치": ("MOM'S TOUCH", "MOMSTOUCH"),
    "bhc치킨": ("BHC", "BHC Chicken"),
    "교촌치킨": ("교촌", "KYOCHON", "KYOCHON CHICKEN"),
    "BBQ치킨": ("BBQ", "BBQ Chicken", "비비큐"),
    "도미노피자": ("DOMINO'S PIZZA", "DOMINOS PIZZA"),
    "피자헛": ("PIZZA HUT",),
    "미스터피자": ("MR. PIZZA", "MISTER PIZZA"),
}


def load_display_catalog(cursor):
    # Include disabled mappings: old orders still need their display conversion.
    cursor.execute("""SELECT r.id,r.name,m.brand_name,m.aliases FROM restaurants r
        LEFT JOIN restaurant_brand_mappings m ON m.restaurant_id=r.id""")
    catalog = []
    for identity, virtual, brand, raw_aliases in cursor.fetchall():
        try:
            aliases = json.loads(raw_aliases) if raw_aliases else []
            if not isinstance(aliases, list):
                aliases = []
        except (ValueError, TypeError):
            aliases = []
        aliases = [value for value in [brand, *aliases] if isinstance(value, str) and value.strip()]
        aliases.extend(DISPLAY_ALIASES.get(brand, ()))
        catalog.append(dict(restaurant_id=identity, virtual_name=virtual, aliases=aliases))
    return catalog


def alias_pattern(alias):
    # NFKC + case-insensitive matching also handles full-width Latin, spacing,
    # punctuation and zero-width separators without changing the branch suffix.
    chars = [c for c in unicodedata.normalize("NFKC", alias) if c.isalnum()]
    return r"[\W_\u200b-\u200d\ufeff]*".join(re.escape(c) for c in chars) if chars else r"(?!)"


def virtual_place_name(raw_name, virtual_name, aliases=(), catalog=(), place_id=None):
    virtual = virtual_name or "가상 음식점"
    name = unicodedata.normalize("NFKC", raw_name) if isinstance(raw_name, str) else ""
    all_aliases = {a for a in aliases if a}
    all_aliases.update(a for entry in catalog if entry["virtual_name"] == virtual for a in entry["aliases"])
    for alias in list(all_aliases):
        all_aliases.update(DISPLAY_ALIASES.get(alias, ()))
    primary = sorted(all_aliases, key=len, reverse=True)
    matched = False
    # Preserve already converted names without replacing substrings inside them.
    if name.startswith(virtual):
        matched = True
    else:
        for alias in primary:
            name, count = re.subn(alias_pattern(alias), lambda _: virtual, name, flags=re.IGNORECASE)
            matched |= count > 0
    if matched:
        # Do not forward another chain name in a compound/malformed place name.
        # Protect virtual names, some of which contain short real aliases (BQQ).
        protected = [entry["virtual_name"] for entry in catalog] + [virtual]
        pieces = re.split("(" + "|".join(re.escape(v) for v in sorted(set(protected), key=len, reverse=True)) + ")", name)
        for index, piece in enumerate(pieces):
            if piece in protected:
                continue
            for entry in catalog:
                for alias in sorted(set(entry["aliases"]), key=len, reverse=True):
                    piece = re.sub(alias_pattern(alias), lambda _: entry["virtual_name"], piece, flags=re.IGNORECASE)
            pieces[index] = piece
        return "".join(pieces).strip()
    # Unknown spellings must never fall back to the raw commercial name.
    identifier = str(place_id or "")
    suffix = f" (지점 {identifier})" if re.fullmatch(r"[0-9]{1,64}", identifier) else ""
    return f"{virtual} 지점{suffix}"


def public_branch(branch, catalog):
    result = {key: value for key, value in branch.items()
              if key not in ("brand_name", "place_name", "aliases")}
    entry = next((e for e in catalog if e["restaurant_id"] == branch.get("restaurant_id")), None)
    virtual = branch.get("virtual_name") or (entry["virtual_name"] if entry else "가상 음식점")
    aliases = [*(entry["aliases"] if entry else []), branch.get("brand_name", "")]
    result["virtual_name"] = virtual
    result["display_name"] = virtual_place_name(branch.get("place_name"), virtual, aliases, catalog, branch.get("place_id"))
    return result


def public_route(route, catalog):
    result = {key: deepcopy(value) for key, value in route.items() if key not in ("branch", "name")}
    if isinstance(route.get("branch"), dict):
        result["branch"] = public_branch(route["branch"], catalog)
        result["name"] = result["branch"]["display_name"]
    else:
        result["name"] = legacy_route_name(route.get("name"), catalog)
    return result


def legacy_route_name(raw, catalog):
    if not isinstance(raw, str):
        return "가상 음식점"
    for entry in catalog:
        if raw.startswith(entry["virtual_name"]):
            # Previous routes could be '옷데리아 · 롯데리아 OO점'.
            name = raw.split(" · ", 1)[-1]
            return virtual_place_name(name, entry["virtual_name"], entry["aliases"], catalog)
        if any(re.search(alias_pattern(alias), raw, re.IGNORECASE) for alias in entry["aliases"]):
            return virtual_place_name(raw, entry["virtual_name"], entry["aliases"], catalog)
    return "가상 음식점"


def public_snapshot(snapshot, catalog):
    result = deepcopy(snapshot)
    routes = snapshot.get("routes", [])
    result["routes"] = [public_route(route, catalog) for route in routes]
    representative = snapshot.get("representative")
    index = next((i for i, route in enumerate(routes) if route.get("name") == representative), None)
    result["representative"] = (result["routes"][index]["name"] if index is not None
                                else legacy_route_name(representative, catalog))
    return result
