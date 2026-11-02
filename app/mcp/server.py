from pathlib import Path

from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings

from app.entries import repo
from app.weights import repo as weights_repo


WEIGHTS_UI = "ui://weights/chart.html"
UI_MIME = "text/html;profile=mcp-app"


def build_mcp(db_path: str) -> FastMCP:
    # Host/Origin checks are off: the endpoint sits behind a public domain and
    # is protected by the Bearer middleware instead.
    mcp = FastMCP(
        "food-log",
        instructions=(
            "Food diary. Never call log_entry right away. First estimate calories, protein, fat and carbs "
            "for the food and show them to the user (name, grams, kcal, P/F/C). Call log_entry only after "
            "the user explicitly confirms (e.g. 'yes', 'save'). If the user corrects the numbers, show the "
            "updated values and ask again."
        ),
        stateless_http=True,
        json_response=True,
        streamable_http_path="/mcp",
        transport_security=TransportSecuritySettings(enable_dns_rebinding_protection=False),
    )

    @mcp.tool()
    def log_entry(date: str, name: str, grams: float, kcal: float, protein: float, fat: float, carbs: float) -> dict:
        """Save a food entry for a day (date as YYYY-MM-DD). Returns the stored entry with its id.

        Call ONLY after the user has seen the kcal/protein/fat/carbs breakdown and explicitly confirmed
        saving it. Never call this in the same turn in which the numbers are first proposed."""
        return repo.add_entry(
            db_path,
            repo.EntryIn(date=date, name=name, grams=grams, kcal=kcal, protein=protein, fat=fat, carbs=carbs),
        )

    @mcp.tool()
    def get_day(date: str) -> dict:
        """List all entries for a day (YYYY-MM-DD) with totals."""
        return repo.get_day(db_path, date)

    @mcp.tool()
    def delete_entry(entry_id: int) -> dict:
        """Delete an entry by id."""
        return {"deleted": repo.delete_entry(db_path, entry_id), "id": entry_id}

    @mcp.tool()
    def log_weight(kg: float, recorded_at: str | None = None) -> dict:
        """Save a body weight in kg. recorded_at is an ISO datetime (YYYY-MM-DDTHH:MM); defaults to now."""
        return weights_repo.add_weight(db_path, weights_repo.WeightIn(kg=kg, recorded_at=recorded_at))

    @mcp.tool()
    def get_range(start: str, end: str) -> dict:
        """Per-day totals (kcal/protein/fat/carbs) and averages for a date range (YYYY-MM-DD, inclusive)."""
        return repo.get_range(db_path, start, end)

    @mcp.resource(WEIGHTS_UI, mime_type=UI_MIME)
    def weights_chart() -> str:
        return (Path(__file__).parent / "ui" / "weights.html").read_text(encoding="utf-8")

    @mcp.tool(meta={"ui": {"resourceUri": WEIGHTS_UI}})
    def get_weights() -> dict:
        """List body weight records for the last 3 months, oldest first."""
        return weights_repo.get_last_months(db_path, months=3)

    return mcp
