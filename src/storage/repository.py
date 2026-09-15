"""Repository — the only place that talks to SQLite.

Everything is stored as a validated Pydantic document plus a handful of
queryable columns, so a schema tweak never silently loses a field.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from ..models.enums import Dataset
from ..models.evidence import Evidence
from ..models.startup import HumanOverride, Startup
from ..models.thesis import InvestmentThesis
from .database import get_connection, reset


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class Repository:
    """Persistence for startups, evidence, overrides, notes and the shortlist."""

    def __init__(self, db_path: Path | str | None = None,
                 conn: sqlite3.Connection | None = None) -> None:
        self.conn = conn or get_connection(db_path)

    # ------------------------------------------------------------ startups
    def save_startup(self, startup: Startup) -> Startup:
        startup.touch()
        document = startup.model_dump_json()
        self.conn.execute(
            """
            INSERT INTO startups (
                id, dataset, company_name, normalized_name, domain, website, hq_country,
                sector, stage, founded_year, total_funding_eur, funding_status,
                eligibility_status, score_total, data_confidence, red_flag_count,
                shortlisted, source_adapter, created_at, updated_at, document
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            ON CONFLICT(id) DO UPDATE SET
                dataset=excluded.dataset, company_name=excluded.company_name,
                normalized_name=excluded.normalized_name, domain=excluded.domain,
                website=excluded.website, hq_country=excluded.hq_country,
                sector=excluded.sector, stage=excluded.stage,
                founded_year=excluded.founded_year,
                total_funding_eur=excluded.total_funding_eur,
                funding_status=excluded.funding_status,
                eligibility_status=excluded.eligibility_status,
                score_total=excluded.score_total,
                data_confidence=excluded.data_confidence,
                red_flag_count=excluded.red_flag_count,
                shortlisted=excluded.shortlisted,
                source_adapter=excluded.source_adapter,
                updated_at=excluded.updated_at, document=excluded.document
            """,
            (
                startup.id, startup.dataset.value, startup.company_name,
                startup.normalized_name, startup.domain, startup.website,
                startup.hq_country, startup.sector, startup.stage.value,
                startup.founded_year, startup.total_funding_eur,
                startup.funding_status.value, startup.eligibility_status.value,
                startup.score_total, startup.data_confidence.value,
                startup.red_flag_count, int(startup.shortlisted),
                startup.source_adapter, startup.created_at.isoformat(),
                startup.updated_at.isoformat(), document,
            ),
        )
        self.conn.commit()
        return startup

    def save_startups(self, startups: list[Startup]) -> list[Startup]:
        for s in startups:
            self.save_startup(s)
        return startups

    def get_startup(self, startup_id: str) -> Startup | None:
        row = self.conn.execute(
            "SELECT document FROM startups WHERE id = ?", (startup_id,)
        ).fetchone()
        return Startup.model_validate_json(row["document"]) if row else None

    def list_startups(self, dataset: Dataset | None = None) -> list[Startup]:
        if dataset is None:
            rows = self.conn.execute(
                "SELECT document FROM startups ORDER BY company_name"
            ).fetchall()
        else:
            rows = self.conn.execute(
                "SELECT document FROM startups WHERE dataset = ? ORDER BY company_name",
                (dataset.value,),
            ).fetchall()
        return [Startup.model_validate_json(r["document"]) for r in rows]

    def delete_startup(self, startup_id: str) -> None:
        self.conn.execute("DELETE FROM evidence WHERE startup_id = ?", (startup_id,))
        self.conn.execute("DELETE FROM shortlist WHERE startup_id = ?", (startup_id,))
        self.conn.execute("DELETE FROM notes WHERE startup_id = ?", (startup_id,))
        self.conn.execute("DELETE FROM startups WHERE id = ?", (startup_id,))
        self.conn.commit()

    def clear_dataset(self, dataset: Dataset) -> int:
        ids = [
            r["id"] for r in self.conn.execute(
                "SELECT id FROM startups WHERE dataset = ?", (dataset.value,)
            ).fetchall()
        ]
        for startup_id in ids:
            self.delete_startup(startup_id)
        return len(ids)

    def count(self, dataset: Dataset | None = None) -> int:
        if dataset is None:
            row = self.conn.execute("SELECT COUNT(*) AS n FROM startups").fetchone()
        else:
            row = self.conn.execute(
                "SELECT COUNT(*) AS n FROM startups WHERE dataset = ?", (dataset.value,)
            ).fetchone()
        return int(row["n"])

    # ------------------------------------------------------------ evidence
    def save_evidence(self, evidence: Evidence) -> Evidence:
        self.conn.execute(
            """
            INSERT INTO evidence (
                id, startup_id, field_name, source_url, source_type, source_tier,
                verification_status, confidence, human_verified, retrieved_at, document
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?)
            ON CONFLICT(id) DO UPDATE SET
                field_name=excluded.field_name, source_url=excluded.source_url,
                source_type=excluded.source_type, source_tier=excluded.source_tier,
                verification_status=excluded.verification_status,
                confidence=excluded.confidence, human_verified=excluded.human_verified,
                retrieved_at=excluded.retrieved_at, document=excluded.document
            """,
            (
                evidence.id, evidence.startup_id, evidence.field_name, evidence.source_url,
                evidence.source_type.value,
                evidence.source_tier.value if evidence.source_tier else None,
                evidence.verification_status.value, evidence.confidence,
                int(evidence.human_verified), evidence.retrieved_at.isoformat(),
                evidence.model_dump_json(),
            ),
        )
        self.conn.commit()
        return evidence

    def save_evidence_many(self, evidences: list[Evidence]) -> None:
        for ev in evidences:
            self.save_evidence(ev)

    def list_evidence(self, startup_id: str | None = None) -> list[Evidence]:
        if startup_id:
            rows = self.conn.execute(
                "SELECT document FROM evidence WHERE startup_id = ? ORDER BY retrieved_at",
                (startup_id,),
            ).fetchall()
        else:
            rows = self.conn.execute(
                "SELECT document FROM evidence ORDER BY retrieved_at"
            ).fetchall()
        return [Evidence.model_validate_json(r["document"]) for r in rows]

    def delete_evidence_for(self, startup_id: str) -> None:
        self.conn.execute("DELETE FROM evidence WHERE startup_id = ?", (startup_id,))
        self.conn.commit()

    # ----------------------------------------------------------- overrides
    def save_override(self, startup_id: str, override: HumanOverride) -> None:
        self.conn.execute(
            """INSERT INTO overrides (startup_id, field_name, old_value, new_value,
                                      reason, author, created_at)
               VALUES (?,?,?,?,?,?,?)""",
            (
                startup_id, override.field_name, json.dumps(override.old_value, default=str),
                json.dumps(override.new_value, default=str), override.reason,
                override.author, override.created_at.isoformat(),
            ),
        )
        self.conn.commit()

    def list_overrides(self, startup_id: str | None = None) -> list[dict]:
        sql = "SELECT * FROM overrides"
        params: tuple = ()
        if startup_id:
            sql += " WHERE startup_id = ?"
            params = (startup_id,)
        sql += " ORDER BY created_at DESC"
        return [dict(r) for r in self.conn.execute(sql, params).fetchall()]

    # --------------------------------------------------------------- notes
    def add_note(self, startup_id: str, body: str, author: str = "investor") -> None:
        self.conn.execute(
            "INSERT INTO notes (startup_id, body, author, created_at) VALUES (?,?,?,?)",
            (startup_id, body, author, _now()),
        )
        self.conn.commit()

    def list_notes(self, startup_id: str) -> list[dict]:
        return [
            dict(r) for r in self.conn.execute(
                "SELECT * FROM notes WHERE startup_id = ? ORDER BY created_at DESC",
                (startup_id,),
            ).fetchall()
        ]

    # ----------------------------------------------------------- shortlist
    def add_to_shortlist(self, startup_id: str, note: str = "") -> None:
        row = self.conn.execute("SELECT COALESCE(MAX(position), 0) AS p FROM shortlist").fetchone()
        self.conn.execute(
            """INSERT INTO shortlist (startup_id, position, added_at, note) VALUES (?,?,?,?)
               ON CONFLICT(startup_id) DO UPDATE SET note=excluded.note""",
            (startup_id, int(row["p"]) + 1, _now(), note),
        )
        self.conn.execute("UPDATE startups SET shortlisted = 1 WHERE id = ?", (startup_id,))
        startup = self.get_startup(startup_id)
        if startup:
            startup.shortlisted = True
            self.save_startup(startup)
        self.conn.commit()

    def remove_from_shortlist(self, startup_id: str) -> None:
        self.conn.execute("DELETE FROM shortlist WHERE startup_id = ?", (startup_id,))
        startup = self.get_startup(startup_id)
        if startup:
            startup.shortlisted = False
            self.save_startup(startup)
        self.conn.commit()

    def list_shortlist(self) -> list[Startup]:
        rows = self.conn.execute(
            "SELECT startup_id FROM shortlist ORDER BY position"
        ).fetchall()
        out = []
        for r in rows:
            startup = self.get_startup(r["startup_id"])
            if startup:
                out.append(startup)
        return out

    # -------------------------------------------------------------- thesis
    def save_thesis(self, thesis: InvestmentThesis) -> None:
        self.conn.execute(
            """INSERT INTO theses (name, document, updated_at) VALUES (?,?,?)
               ON CONFLICT(name) DO UPDATE SET document=excluded.document,
                                               updated_at=excluded.updated_at""",
            (thesis.name, json.dumps(thesis.to_storable()), _now()),
        )
        self.conn.commit()

    def load_thesis(self, name: str = "Default thesis") -> InvestmentThesis | None:
        row = self.conn.execute("SELECT document FROM theses WHERE name = ?", (name,)).fetchone()
        if not row:
            return None
        try:
            return InvestmentThesis.from_storable(json.loads(row["document"]))
        except Exception:  # noqa: BLE001 — a corrupt saved thesis must not break startup
            return None

    def list_thesis_names(self) -> list[str]:
        return [r["name"] for r in self.conn.execute("SELECT name FROM theses ORDER BY name")]

    # ------------------------------------------------------------- utility
    def reset_all(self) -> None:
        reset(self.conn)

    def stats(self) -> dict[str, int]:
        return {
            "companies": self.count(),
            "demo_companies": self.count(Dataset.DEMO),
            "real_companies": self.count(Dataset.REAL),
            "evidence": int(self.conn.execute("SELECT COUNT(*) AS n FROM evidence").fetchone()["n"]),
            "overrides": int(self.conn.execute("SELECT COUNT(*) AS n FROM overrides").fetchone()["n"]),
            "shortlisted": int(self.conn.execute("SELECT COUNT(*) AS n FROM shortlist").fetchone()["n"]),
        }

    def close(self) -> None:
        self.conn.close()
