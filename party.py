# The COPYRIGHT file at the top level of this repository contains the full
# copyright notices and license terms.
from trytond.model import ModelSQL, fields
from trytond.pool import PoolMeta, Pool
from trytond.pyson import Eval
from trytond.i18n import gettext
from trytond.exceptions import UserError
from trytond.modules.company.model import CompanyValueMixin

contract_grouping_method = fields.Selection([
        (None, 'None'),
        ('contract', 'Group contracts'),
        ], 'Contract Grouping Method')


class Party(metaclass=PoolMeta):
    __name__ = 'party.party'
    contract_grouping_method = fields.MultiValue(contract_grouping_method)
    contract_grouping_methods = fields.One2Many(
        'party.party.contract_grouping_method', 'party',
        'Contract Grouping Methods')

    @classmethod
    def default_contract_grouping_method(cls, **pattern):
        field_name = 'contract_grouping_method'
        return getattr(
            cls.multivalue_model(field_name),
            'default_%s' % field_name, lambda: None)()

    @classmethod
    def multivalue_model(cls, field):
        pool = Pool()
        if field in {'contract_grouping_method'}:
            return pool.get('party.party.contract_grouping_method')
        return super(Party, cls).multivalue_model(field)


class PartyContractGroupingMethod(CompanyValueMixin, ModelSQL):
    "Party Contract Grouping Method"
    __name__ = 'party.party.contract_grouping_method'
    party = fields.Many2One(
        'party.party', "Party", ondelete='CASCADE',
        context={
            'company': Eval('company', -1),
            },
        depends=['company'])
    contract_grouping_method = contract_grouping_method

    @staticmethod
    def default_contract_grouping_method():
        return None


class PartyReplace(metaclass=PoolMeta):
    __name__ = 'party.replace'

    @classmethod
    def fields_to_replace(cls):
        return super(PartyReplace, cls).fields_to_replace() + [
            ('contract', 'party'),
            ]


class PartyErase(metaclass=PoolMeta):
    __name__ = 'party.erase'

    def check_erase_company(self, party, company):
        pool = Pool()
        Contract = pool.get('contract')
        super(PartyErase, self).check_erase_company(party, company)

        contracts = Contract.search([
                ('party', '=', party.id),
                ('state', 'not in', ['finished', 'cancelled']),
                ])
        if contracts:
            raise UserError(gettext('contract.pending_contract',
                party=party.rec_name,
                company=company.rec_name))
