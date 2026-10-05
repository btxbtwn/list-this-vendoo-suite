"""Recent sales only receive labels from recorded events in their item scope."""
from datetime import UTC, date, datetime
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from vendoo_studio.database import Base, load_models
from vendoo_studio.models.sale_event import SaleEvent
from vendoo_studio.services.inventory_analytics import AnalyticsItem, summarize
from vendoo_studio.services.sale_events import windows


def test_recent_sales_use_recorded_events_and_item_scope():
    load_models()
    engine = create_engine('sqlite://')
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        for status in ['planned', 'ran', 'cancelled']:
            db.add(SaleEvent(id=status, title=status, marketplace='ebay',
                             start_date=date(2026, 9, 25), end_date=date(2026, 9, 27),
                             timezone='America/New_York', items=[{'id': 'in'}], status=status))
        db.commit()
        rows = [AnalyticsItem(cid, cid, 'sold', 50, 10, '', '', 40,
                              datetime(2026, 9, 28, 2, tzinfo=UTC), None, 'ebay', None, 5)
                for cid in ['in', 'out']]
        event_windows = windows(db)
        assert len(event_windows) == 1
        result = summarize(rows, range_id='all', now=datetime(2026, 10, 5, tzinfo=UTC), events=event_windows)
        assert {row['conversation_id']: row['event'] for row in result['recent']} == {'in': 'ran', 'out': None}
    engine.dispose()
