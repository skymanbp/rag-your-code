"""Notification fixture for retrieval evaluation."""


def send_email(smtp_client, recipient, body):
    """Deliver an email notification through an SMTP client."""
    return smtp_client.send(recipient, body)


def enqueue_webhook(queue, endpoint, payload):
    """Queue an outbound webhook event for asynchronous delivery."""
    return queue.publish({"endpoint": endpoint, "payload": payload})
