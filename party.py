# The COPYRIGHT file at the top level of this repository contains the full
# copyright notices and license terms.
from trytond import backend
from trytond.model import ModelSQL, ValueMixin, fields
from trytond.pool import PoolMeta, Pool
from trytond.tools.multivalue import migrate_property

__all__ = ['Party', 'PartyContractGroupingMethod', 'PartyReplace', 'PartyErase']


class Party:
    __name__ = 'party.party'
    __metaclass__ = PoolMeta
    contract_grouping_method = fields.MultiValue(fields.Selection([
                (None, 'None'),
                ('contract', 'Group contracts'),
                ],
            'Contract Grouping Method'))

    @classmethod
    def default_contract_grouping_method(cls, **pattern):
        return None


class PartyContractGroupingMethod(ModelSQL, ValueMixin):
    "Party Contract Grouping Method"
    __name__ = 'party.party.contract_grouping_method'

    party = fields.Many2One(
        'party.party', "Party", ondelete='CASCADE', select=True)
    contract_grouping_method = fields.Selection(
        'get_contract_grouping_method', "Contract Grouping Method")

    @classmethod
    def __register__(cls, module_name):
        TableHandler = backend.get('TableHandler')
        exist = TableHandler.table_exist(cls._table)

        super(PartyContractGroupingMethod, cls).__register__(module_name)

        if not exist:
            cls._migrate_property([], [], [])

    @classmethod
    def _migrate_property(cls, field_names, value_names, fields):
        field_names.append('contract_grouping_method')
        value_names.append('contract_grouping_method')
        migrate_property(
            'party.party', field_names, cls, value_names,
            parent='party', fields=fields)

    @classmethod
    def get_contract_grouping_method(cls):
        pool = Pool()
        Party = pool.get('party.party')
        field_name = 'contract_grouping_method'
        return Party.fields_get([field_name])[field_name]['selection']


class PartyReplace:
    __metaclass__ = PoolMeta
    __name__ = 'party.replace'

    @classmethod
    def fields_to_replace(cls):
        return super(PartyReplace, cls).fields_to_replace() + [
            ('contract', 'party'),
            ]


class PartyErase:
    __metaclass__ = PoolMeta
    __name__ = 'party.erase'

    @classmethod
    def __setup__(cls):
        super(PartyErase, cls).__setup__()
        cls._error_messages.update({
                'pending_contract': (
                    'The party "%(party)s" can not be erased '
                    'because he has pending contracts '
                    'for the company "%(company)s".'),
                })

    def check_erase_company(self, party, company):
        pool = Pool()
        Contract = pool.get('contract')
        super(PartyErase, self).check_erase_company(party, company)

        contracts = Contract.search([
                ('party', '=', party.id),
                ('state', 'not in', ['finished', 'cancelled']),
                ])
        if contracts:
            self.raise_user_error('pending_contract', {
                    'party': party.rec_name,
                    'company': company.rec_name,
                    })
