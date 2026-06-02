"""Module B services — imports close() from module_a.connections."""

from module_a.connections import close


def do_work() -> None:
    """Do work — calls the imported close()."""
    close()  # This should be RESOLVED via import -> module_a.connections.close
