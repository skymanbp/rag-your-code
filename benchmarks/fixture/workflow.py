"""Cross-function workflow fixture for graph retrieval evaluation."""

from payments import retry_charge


def checkout_invoice(payment_gateway, invoice_id):
    """Coordinate checkout orchestration for an invoice."""
    return retry_charge(payment_gateway, invoice_id)
