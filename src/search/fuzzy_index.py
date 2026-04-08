"""In-memory fuzzy search index over scrip master instruments."""
import logging

import pandas as pd
from rapidfuzz import fuzz, process

logger = logging.getLogger(__name__)


class FuzzyIndex:
    def __init__(self):
        self._entries: list[dict] = []
        self._choices: list[str] = []
        self._choice_to_indices: dict[str, list[int]] = {}

    def build(self, df: pd.DataFrame):
        self._entries.clear()
        self._choices.clear()
        self._choice_to_indices.clear()

        seen_symbols = set()

        for _, row in df.iterrows():
            entry = {
                "security_id": str(int(row["SEM_SMST_SECURITY_ID"])),
                "symbol": str(row["SM_SYMBOL_NAME"]),
                "trading_symbol": str(row["SEM_TRADING_SYMBOL"]),
                "display_name": str(row.get("SEM_CUSTOM_SYMBOL", row["SEM_TRADING_SYMBOL"])),
                "strike": row.get("SEM_STRIKE_PRICE"),
                "option_type": row.get("SEM_OPTION_TYPE"),
                "expiry": str(row.get("SEM_EXPIRY_DATE", "")),
                "exchange": row.get("SEM_EXM_EXCH_ID"),
                "instrument_type": row.get("SEM_EXCH_INSTRUMENT_TYPE"),
                "lot_size": int(row.get("SEM_LOT_UNITS", 1)),
            }
            self._entries.append(entry)

            sym = entry["symbol"]
            if sym not in seen_symbols:
                seen_symbols.add(sym)
                self._choices.append(sym)
                self._choice_to_indices[sym] = []
            self._choice_to_indices[sym].append(len(self._entries) - 1)

        logger.info(f"Fuzzy index built: {len(self._entries)} entries, {len(self._choices)} unique symbols")

    def search(self, query: str, limit: int = 20, score_cutoff: float = 40.0) -> list[dict]:
        if not self._choices or not query.strip():
            return []

        matches = process.extract(
            query.upper(), self._choices, scorer=fuzz.WRatio,
            limit=min(limit * 2, len(self._choices)), score_cutoff=score_cutoff,
        )

        results = []
        seen = set()
        for match_str, score, _ in matches:
            indices = self._choice_to_indices.get(match_str, [])
            for idx in indices:
                entry = self._entries[idx]
                if entry["security_id"] in seen:
                    continue
                seen.add(entry["security_id"])
                results.append({**entry, "score": round(score, 1)})
                if len(results) >= limit:
                    break
            if len(results) >= limit:
                break

        return results
