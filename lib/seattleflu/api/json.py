"""
JSON encoder for API responses.
"""
import json
import uuid
from datetime import datetime, date


class JsonEncoder(json.JSONEncoder):
    """
    Encodes Python values into JSON for non-standard objects, without the extra
    magic of :func:`flask.jsonify`.
    """

    def __init__(self, *args, **kwargs):
        """
        Disallows the floating point values NaN, Infinity, and -Infinity.

        Python's :class:`json` allows them by default because they work with
        JSON-as-JavaScript, but they don't work with spec-compliant JSON
        parsers.
        """
        kwargs["allow_nan"] = False
        super().__init__(*args, **kwargs)

    def default(self, value):
        """
        Returns *value* as JSON or raises a TypeError.

        Serializes:

        * :class:`~datetime.datetime` using :meth:`~datetime.datetime.isoformat()`
        * :class:`~datetime.date` using :meth:`~datetime.date.isoformat()`
        * :class:`uuid` using ``str()``
        """
        if isinstance(value, datetime) or isinstance(value, date):
            return value.isoformat()

        elif isinstance(value, uuid):
            return str(value)

        else:
            # Let the base class raise the TypeError
            return super().default(value)
