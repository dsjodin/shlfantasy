"""Hämtar all data manuellt: python -m app.refresh [--birthdates]"""

from __future__ import annotations

import argparse
import asyncio
import logging

from .config import get_settings
from .datastore import DataStore


def main() -> None:
    parser = argparse.ArgumentParser(description="Hämta spelardata, matchschema och födelsedatum.")
    parser.add_argument("--birthdates", action="store_true", help="Tvinga omhämtning av födelsedatum")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    store = DataStore(get_settings().data_dir)
    snap = asyncio.run(store.refresh(include_birthdates=True if args.birthdates else None))
    print(f"Säsong {snap.season}: {len(snap.players)} spelare, {len(snap.games)} matcher, "
          f"{len(snap.gameweeks)} matchveckor, {len(snap.birthdates)} födelsedatum")
    for error in snap.errors:
        print(f"FEL: {error}")


if __name__ == "__main__":
    main()
