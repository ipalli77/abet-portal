"""Dedicated production entry point for the UTRGV Mechanical Engineering edition."""

import os

from abet_platform import create_app


ROOT = os.path.dirname(__file__)
DEFAULT_EDINBURG_DATABASE = os.path.join(ROOT, "edinburg_abet_data.db")
CONFIGURED_EDINBURG_DATABASE = os.getenv("UTRGV_EDINBURG_ABET_DB", "")
EDINBURG_DATABASE = CONFIGURED_EDINBURG_DATABASE or (
    DEFAULT_EDINBURG_DATABASE if os.path.isfile(DEFAULT_EDINBURG_DATABASE) else ""
)
LEGACY_SOURCES = {
    campus: path
    for campus, path in (
        ("Edinburg", EDINBURG_DATABASE),
        ("Brownsville", os.getenv("UTRGV_BROWNSVILLE_ABET_DB", "")),
    )
    if path
}

app = create_app(
    {
        "EDITION": "utrgv_mece",
        "PRODUCT_NAME": "UTRGV ME Accreditation Hub",
        "CUSTOMER_NAME": "UTRGV Department of Mechanical Engineering",
        "DATABASE": os.getenv("ABET_DATABASE", os.path.join(ROOT, "instance", "utrgv_mece.db")),
        # The bundled current data file is explicitly Edinburg. Brownsville has
        # no source database yet; faculty create those records in the portal.
        "LEGACY_DATABASE": os.getenv("UTRGV_LEGACY_ABET_DB", ""),
        "LEGACY_SOURCES": LEGACY_SOURCES,
    }
)


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5001, debug=False)
