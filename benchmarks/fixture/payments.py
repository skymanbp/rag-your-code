"""Payment fixture for retrieval evaluation."""


def retry_charge(payment_gateway, invoice_id, max_attempts=3):
    """Retry a failed card charge after a gateway timeout."""
    for attempt in range(max_attempts):
        result = payment_gateway.charge(invoice_id)
        if result.success:
            return result
    raise ChargeFailed(invoice_id)


def refund_payment(payment_gateway, transaction_id):
    """Refund a settled payment by transaction identifier."""
    return payment_gateway.refund(transaction_id)
