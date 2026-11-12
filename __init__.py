# The COPYRIGHT file at the top level of this repository contains the full
# copyright notices and license terms.
from trytond.pool import Pool
from . import configuration
from . import contract
from . import invoice
from . import party


def register():
    Pool.register(
        party.Party,
        party.PartyContractGroupingMethod,
        configuration.Configuration,
        configuration.ConfigurationSequence,
        configuration.ConfigurationAccount,
        contract.ContractService,
        contract.Contract,
        contract.ContractLine,
        contract.ContractConsumption,
        contract.CreateConsumptionsStart,
        contract.ContractReview,
        contract.ContractReviewLine,
        contract.CreateReviewsStart,
        contract.Cron,
        invoice.CreateInvoicesStart,
        invoice.InvoiceLine,
        invoice.CreditInvoiceStart,
        module='contract', type_='model')
    Pool.register(
        contract.AnalyticAccountEntry,
        contract.AnalyticContractLine,
        depends=['analytic_account'],
        module='contract', type_='model')
    Pool.register(
        contract.CreateConsumptions,
        contract.CreateReviews,
        invoice.CreateInvoices,
        invoice.CreditInvoice,
        party.PartyReplace,
        party.PartyErase,
        module='contract', type_='wizard')
