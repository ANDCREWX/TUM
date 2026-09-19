"""tumcal - TUMonline-Termine holen, aufräumen und als Kalender anzeigen."""

from .model import CourseEvent, filter_events, load_events
from .render import render_html

__all__ = ["CourseEvent", "load_events", "filter_events", "render_html"]
__version__ = "1.0.0"
