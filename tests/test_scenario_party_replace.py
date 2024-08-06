import datetime
import unittest
from decimal import Decimal

from proteus import Model, Wizard
from trytond.modules.account.tests.tools import (create_chart,
                                                 create_fiscalyear, create_tax)
from trytond.modules.account_invoice.tests.tools import (
    create_payment_term, set_fiscalyear_invoice_sequences)
from trytond.modules.company.tests.tools import create_company, get_company
from trytond.tests.test_tryton import drop_db
from trytond.tests.tools import activate_modules


class Test(unittest.TestCase):

    def setUp(self):
        drop_db()
        super().setUp()

    def tearDown(self):
        drop_db()
        super().tearDown()

    def test(self):

        today = datetime.date(2015, 1, 1)

        # Install contract
        activate_modules('contract')

        # Create company
        _ = create_company()
        company = get_company()

        # Create fiscal year
        fiscalyear = set_fiscalyear_invoice_sequences(
            create_fiscalyear(company, today))
        fiscalyear.click('create_period')

        # Create chart of accounts
        _ = create_chart(company)

        # Create tax
        tax = create_tax(Decimal('.10'))
        tax.save()

        # Create payment term
        payment_term = create_payment_term()
        payment_term.save()

        # Create a party
        Party = Model.get('party.party')
        party = Party(name='Pam')
        _ = party.identifiers.new(code="Identifier", type=None)
        _ = party.contact_mechanisms.new(type='other', value="mechanism")
        party.save()
        address, = party.addresses
        address.street = "St sample, 15"
        address.city = "City"
        address.save()

        # Create a party2
        party2 = Party(name='Pam')
        _ = party2.identifiers.new(code="Identifier2", type=None)
        _ = party2.contact_mechanisms.new(type='other', value="mechanism")
        party2.save()
        address2, = party2.addresses
        address2.street = "St sample 2, 15"
        address2.city = "City 2"
        address2.save()

        # Create Monthly Contract
        Contract = Model.get('contract')
        contract = Contract()
        contract.party = party
        contract.payment_term = payment_term
        contract.freq = 'monthly'
        contract.interval = 1
        contract.start_period_date = datetime.date(2015, 1, 1)
        contract.first_invoice_date = datetime.date(2015, 1, 1)
        contract.save()

        # Try replace active party
        replace = Wizard('party.replace', models=[party])
        replace.form.source = party
        replace.form.destination = party2
        replace.execute('replace')

        # Check fields have been replaced
        contract.reload()
        self.assertEqual(contract.party, party2)
