import logging

from django.conf import settings
from django.core.mail import send_mail

from .templatetags.money import inr

logger = logging.getLogger(__name__)


def send_transfer_alerts(txn):
    """Debit/credit alert emails. Never allowed to break a completed transfer."""
    try:
        sender, receiver = txn.source_account, txn.destination_account
        amount = inr(txn.amount)
        send_mail(
            f"{settings.BANK_NAME}: {amount} debited from {sender.masked_number}",
            f"Hello {sender.customer.user.first_name},\n\n{amount} was debited from account {sender.masked_number}.\n"
            f"Reference: {txn.reference}\n\nIf you did not do this, contact the bank immediately.\n",
            settings.DEFAULT_FROM_EMAIL, [sender.customer.user.email], fail_silently=True,
        )
        if receiver.customer_id != sender.customer_id:
            send_mail(
                f"{settings.BANK_NAME}: {amount} credited to {receiver.masked_number}",
                f"Hello {receiver.customer.user.first_name},\n\n{amount} was credited to account {receiver.masked_number}.\n"
                f"Reference: {txn.reference}\n",
                settings.DEFAULT_FROM_EMAIL, [receiver.customer.user.email], fail_silently=True,
            )
    except Exception:  # noqa: BLE001
        logger.exception("Could not send transfer alert for %s", txn.pk)
