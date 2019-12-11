# The COPYRIGHT file at the top level of this repository contains the full
# copyright notices and license terms.
from trytond import backend
from trytond.model import ModelSQL, ValueMixin, fields
from trytond.pool import PoolMeta, Pool
from trytond.tools.multivalue import migrate_property
from trytond.i18n import gettext
from trytond.exceptions import UserError

__all__ = ['Party', 'PartyContractGroupingMethod', 'PartyReplace', 'PartyErase']


class Party(metaclass=PoolMeta):
    __name__ = 'party.party'
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
        exist = backend.TableHandler.table_exist(cls._table)

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
