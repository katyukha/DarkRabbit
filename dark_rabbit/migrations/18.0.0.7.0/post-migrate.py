import logging

_logger = logging.getLogger(__name__)

OLD_INDEX = "dark_rabbit_outgoing_event__sender_search__idx"
NEW_INDEX = "dark_rabbit_outgoing_event__sender_search_v2__idx"


def migrate(cr, version):
    """Drop the old sender index, superseded by the connection_id-leading one.

    post-migrate, and conditional: the replacement is created by the model's
    init(), which runs between pre- and post-migrate. Dropping unconditionally
    or earlier could leave the sender with no usable index.
    """
    cr.execute("SELECT 1 FROM pg_indexes WHERE indexname = %s", (NEW_INDEX,))
    if not cr.fetchone():
        _logger.warning(
            "Keeping %s: its replacement %s is not present.", OLD_INDEX, NEW_INDEX
        )
        return

    _logger.info("Dropping %s, superseded by %s.", OLD_INDEX, NEW_INDEX)
    cr.execute(f'DROP INDEX IF EXISTS "{OLD_INDEX}"')  # noqa: B907
