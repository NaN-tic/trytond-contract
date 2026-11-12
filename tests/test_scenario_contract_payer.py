import unittest
from datetime import date
from decimal import Decimal

from proteus import Model, Wizard
from trytond.modules.account.tests.tools import create_chart, get_accounts
from trytond.modules.account_invoice.tests.tools import create_payment_term
from trytond.modules.company.tests.tools import create_company, get_company
from trytond.tests.test_tryton import drop_db
from trytond.tests.tools import activate_modules


class TestContractPayer(unittest.TestCase):

    def setUp(self):
        drop_db()
        super().setUp()

    def tearDown(self):
        drop_db()
        super().tearDown()

    def test(self):
        activate_modules('contract')
        create_company()
        company = get_company()
        company.timezone = 'Europe/Madrid'
        company.save()
        create_chart(company)
        accounts = get_accounts(company)
        term = create_payment_term()
        term.name = 'Payer payment term'
        term.save()
        other_term = create_payment_term()
        other_term.name = 'Customer payment term'
        other_term.save()
        Party = Model.get('party.party')
        payer = Party(name='Payer', customer_payment_term=term,
            contract_grouping_method='contract')
        payer.save()
        customers = [Party(name=name, customer_payment_term=other_term) for name in ('Customer A', 'Customer B')]
        Party.save(customers)
        Category = Model.get('product.category')
        category = Category(name='Accounting', accounting=True,
            account_expense=accounts['expense'], account_revenue=accounts['revenue'])
        category.save()
        Uom = Model.get('product.uom')
        unit, = Uom.find([('name', '=', 'Unit')])
        Template = Model.get('product.template')
        template = Template(name='Monthly service', type='service',
            default_uom=unit, list_price=Decimal('310'), account_category=category)
        template.save()
        ContractService = Model.get('contract.service')
        service = ContractService(name='Monthly service', product=template.products[0])
        service.save()
        Configuration = Model.get('contract.configuration')
        Journal = Model.get('account.journal')
        configuration = Configuration(1)
        configuration.journal, = Journal.find([('type', '=', 'revenue')], limit=1)
        configuration.save()
        Contract = Model.get('contract')
        contracts = []
        for index, customer in enumerate((customers[0], customers[0], customers[1])):
            contract = Contract(party=customer, company=company,
                freq='monthly', interval=1, start_period_date=date(2026, 1, 1),
                first_invoice_date=date(2026, 1, 31))
            self.assertEqual(contract.payment_term, other_term)
            # Preserve the customer default, an explicit contract term and
            # an explicitly empty term without sales payer integration.
            if index == 0:
                contract.payment_term = term
            elif index == 1:
                contract.payment_term = None
            contract.lines.new(service=service, start_date=date(2026, 1, 1),
                end_date=date(2026, 1, 15), quantity=2, unit_price=Decimal('310'))
            contract.save()
            contract.click('confirm')
            contracts.append(contract)
        wizard = Wizard('contract.create_consumptions')
        wizard.form.date = date(2026, 1, 31)
        wizard.execute('create_consumptions')
        Consumption = Model.get('contract.consumption')
        consumptions = Consumption.find()
        self.assertEqual(len(consumptions), 3)
        Consumption.click(consumptions, 'generate_invoice')
        Invoice = Model.get('account.invoice')
        invoices = Invoice.find()
        self.assertEqual(len(invoices), 3)
        for consumption in consumptions:
            consumption.reload()
        by_contract = {consumption.contract_line.contract:
            consumption.invoice_lines[0].invoice for consumption in consumptions}
        self.assertEqual(by_contract[contracts[0]].payment_term, term)
        self.assertIsNone(by_contract[contracts[1]].payment_term)
        self.assertEqual(by_contract[contracts[2]].payment_term, other_term)
        for contract in contracts:
            invoice = by_contract[contract]
            self.assertEqual(invoice.party, contract.party)
            self.assertNotEqual(invoice.party, payer)
            self.assertEqual(invoice.untaxed_amount, Decimal('300'))
            self.assertTrue(all(line.unit_price == Decimal('150')
                for line in invoice.lines))
