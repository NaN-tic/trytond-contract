from trytond.model import fields
from trytond.pool import PoolMeta


class Contract(metaclass=PoolMeta):
    __name__ = 'contract'

    @fields.depends('party')
    def on_change_party(self):
        super().on_change_party()
        if self.party:
            payer = self.party.party_sale_payer or self.party
            self.payment_term = payer.customer_payment_term


class ContractConsumption(metaclass=PoolMeta):
    __name__ = 'contract.consumption'

    def _get_invoice_party(self):
        party = super()._get_invoice_party()
        return party.party_sale_payer or party

    @classmethod
    def _group_invoice_key(cls, line):
        key = super()._group_invoice_key(line)
        consumption, _ = line
        key.append(('shipment_party', consumption.contract.party))
        return key

    @classmethod
    def _get_invoice(cls, keys, lines):
        invoice = super()._get_invoice(keys, lines)
        payment_term = invoice.payment_term
        invoice.on_change_shipment_party()
        if dict(keys)['payment_term'] != -1:
            invoice.payment_term = payment_term
        return invoice
