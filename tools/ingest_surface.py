#!/usr/bin/env python3
"""Add the generated locales' countries to the identifier surface rules.

`data/surface/rules.json` decides what a postcode, a phone number, a business
identifier and a bank account look like in a country. It carried the eleven
countries the four authored locales name, so a company in the nine generated
ones fell through to `_generic` and printed `+## ### ### ####` where an Indian
invoice prints `074104 10123`.

Phone formats come from libphonenumber (the `phonenumbers` package), which
publishes a national format and an example number per region: the example is
turned into a mask by replacing its digits with `#`, so the shape is the
library's and only the digits are drawn.

Postcode widths, business identifiers and bank account shapes are stated here
rather than read from a library, because none publishes them per jurisdiction.
Each is the statutory identifier a reader of that country would recognise, and
each is named in the comment beside it.

Existing countries are never rewritten: this only adds, so every corpus built
before it is byte-identical.

    pip install phonenumbers
    python tools/ingest_surface.py
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any

#: `printed country -> ISO 3166-1 alpha-2`, matching `Locale.cities`.
COUNTRIES: dict[str, str] = {
    "China": "CN",
    "Hong Kong": "HK",
    "India": "IN",
    "Indonesia": "ID",
    "Japan": "JP",
    "Malaysia": "MY",
    "Singapore": "SG",
    "Taiwan": "TW",
    "Thailand": "TH",
}

#: Postcode shape. A width is the digit count the national system uses.
#: Hong Kong has no postcode system at all, so it takes `po_box`, which is the
#: kind this repository already uses for the Gulf for the same reason: a
#: jurisdiction that does not number addresses gets the identifier its business
#: mail actually carries rather than a number that means nothing.
POSTCODES: dict[str, dict[str, Any]] = {
    "CN": {"kind": "fixed_width", "width": 6},
    "HK": {"kind": "po_box", "low": 1000, "high": 99999},
    "IN": {"kind": "fixed_width", "width": 6},   # PIN code
    "ID": {"kind": "fixed_width", "width": 5},
    "JP": {"kind": "fixed_width", "width": 7},   # printed NNN-NNNN
    "MY": {"kind": "fixed_width", "width": 5},
    "SG": {"kind": "fixed_width", "width": 6},
    "TW": {"kind": "fixed_width", "width": 5},
    "TH": {"kind": "fixed_width", "width": 5},
}

#: The statutory registration number a company of that country quotes on an
#: invoice. Named, because an invented `REG-########` is the thing this closes.
BUSINESS_IDS: dict[str, str] = {
    "CN": "USCC ##################",        # Unified Social Credit Code, 18
    "HK": "BR ########-###",                # Business Registration number
    "IN": "GSTIN ##AAAAA####A#Z#",          # GST identification number, 15
    "ID": "NPWP ##.###.###.#-###.###",      # Nomor Pokok Wajib Pajak
    "JP": "Corporate Number #############", # houjin bangou, 13
    "MY": "SSM ############",               # Companies Commission registration
    "SG": "UEN ########A",                  # Unique Entity Number
    "TW": "Tax ID ########",                # unified business number, 8
    "TH": "Tax ID #############",           # 13-digit taxpayer identification
}

#: Local bank account shape as a payee line would carry it.
BANK_ACCOUNTS: dict[str, str] = {
    "CN": "CNAPS ############ Acc ################",
    "HK": "###-###-#######",                    # bank-branch-account
    "IN": "IFSC AAAA####### Acc ###########",
    "ID": "Acc ##########",
    "JP": "Branch ### Acc #######",
    "MY": "Acc ############",
    "SG": "Acc ###-#####-#",
    "TW": "Acc ##############",
    "TH": "Acc ###-#-#####-#",
}


def phone_masks(alpha2: str) -> dict[str, str]:
    """A landline and a mobile mask, from libphonenumber's example numbers."""
    import phonenumbers
    from phonenumbers import PhoneNumberFormat, PhoneNumberType

    masks: dict[str, str] = {}
    for key, kind in (("landline", PhoneNumberType.FIXED_LINE),
                      ("mobile", PhoneNumberType.MOBILE)):
        example = phonenumbers.example_number_for_type(alpha2, kind)
        if example is None:
            continue
        national = phonenumbers.format_number(example, PhoneNumberFormat.NATIONAL)
        masks[key] = re.sub(r"\d", "#", national)
    masks.setdefault("landline", "+## ### ### ####")
    masks.setdefault("mobile", masks["landline"])
    masks["area_default"] = ""
    return masks


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--rules", type=Path, default=Path("src/worldloom/data/surface/rules.json"))
    args = parser.parse_args()

    document = json.loads(args.rules.read_text(encoding="utf-8"))
    versions = document["versions"] if "versions" in document else document
    target = versions[max(versions, key=int)] if isinstance(versions, dict) and versions else document
    table = target["countries"] if "countries" in target else document["countries"]

    added = 0
    for printed, alpha2 in sorted(COUNTRIES.items()):
        if printed in table:
            print(f"{printed}: already present, left alone")
            continue
        table[printed] = {
            "postcode": POSTCODES[alpha2],
            "phone": phone_masks(alpha2),
            "business_identifier": {"kind": "pattern", "pattern": BUSINESS_IDS[alpha2]},
            "bank_account": {"kind": "pattern", "pattern": BANK_ACCOUNTS[alpha2]},
        }
        added += 1
        print(f"{printed:12s} phone={table[printed]['phone']['landline']:<20}"
              f" id={BUSINESS_IDS[alpha2]}")
    args.rules.write_text(json.dumps(document, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    print(f"wrote {args.rules}: {added} countries added, {len(table)} total")


if __name__ == "__main__":
    main()
