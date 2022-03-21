# This file is part of Tryton.  The COPYRIGHT file at the top level of
# this repository contains the full copyright notices and license terms.
from trytond import backend
from trytond.model import ModelView, ModelSQL, ModelSingleton, fields
from trytond.pool import Pool
from trytond.pyson import Eval, Id
from trytond.tools.multivalue import migrate_property
from trytond.modules.company.model import (
    CompanyMultiValueMixin, CompanyValueMixin)

__all__ = ['Configuration', 'ConfigurationSequence', 'ConfigurationAccount']


class Configuration(
        ModelSingleton, ModelSQL, ModelView, CompanyMultiValueMixin):
    'Contract Configuration'
    __name__ = 'contract.configuration'
    contract_sequence = fields.MultiValue(fields.Many2One(
            'ir.sequence', "Contract Reference Sequence", required=True,
            domain=[
                ('company', 'in',
                    [Eval('context', {}).get('company', -1), None]),
                ('sequence_type', '=', Id('contract',
                        'sequence_type_contract')),
                ]))
    journal = fields.MultiValue(fields.Many2One(
            'account.journal', "Journal", required=True,
            domain=[
                ('type', '=', 'revenue'),
                ]))
    default_months_renewal = fields.Integer('Review Months Renewal')
    default_review_limit_date = fields.TimeDelta('Limit Date',
        help="The deadline date on which the actions should be performed.")
    default_review_alarm = fields.TimeDelta('Alarm Date',
        help="The date when actions related to reviews should start to be managed.")

    @classmethod
    def multivalue_model(cls, field):
        pool = Pool()
        if field == 'contract_sequence':
            return pool.get('contract.configuration.sequence')
        elif field == 'journal':
            return pool.get('contract.configuration.account')
        return super(Configuration, cls).multivalue_model(field)

    @classmethod
    def default_contract_sequence(cls, **pattern):
        return cls.multivalue_model(
            'contract_sequence').default_contract_sequence()


class ConfigurationSequence(ModelSQL, CompanyValueMixin):
    "Contract Configuration Sequence"
    __name__ = 'contract.configuration.sequence'

    contract_sequence = fields.Many2One(
        'ir.sequence', "Contract Reference Sequence",
        domain=[
            ('company', 'in', [Eval('company', -1), None]),
            ('sequence_type', '=', Id('contract', 'sequence_type_contract')),
            ],
        depends=['company'])

    @classmethod
    def __register__(cls, module_name):
        exist = backend.TableHandler.table_exist(cls._table)

        super(ConfigurationSequence, cls).__register__(module_name)

        if not exist:
            cls._migrate_property([], [], [])

    @classmethod
    def _migrate_property(cls, field_names, value_names, fields):
        field_names.append('contract_sequence')
        value_names.append('contract_sequence')
        fields.append('company')
        migrate_property(
            'contract.configuration', field_names, cls, value_names,
            fields=fields)

    @classmethod
    def default_contract_sequence(cls):
        pool = Pool()
        ModelData = pool.get('ir.model.data')
        try:
            return ModelData.get_id('contract', 'sequence_contract')
        except KeyError:
            return None


class ConfigurationAccount(ModelSQL, CompanyValueMixin):
    "Contract Configuration Accounting"
    __name__ = 'contract.configuration.account'

    journal = fields.Many2One(
        'account.journal', "Journal",
        domain=[
            ('type', '=', 'revenue'),
            ],
        context={
            'company': Eval('company'),
        }, depends=['company'])

    @classmethod
    def __register__(cls, module_name):
        exist = backend.TableHandler.table_exist(cls._table)

        super(ConfigurationAccount, cls).__register__(module_name)

        if not exist:
            cls._migrate_property([], [], [])

    @classmethod
    def _migrate_property(cls, field_names, value_names, fields):
        field_names += ['journal']
        value_names += ['journal']
        fields.append('company')
        migrate_property(
            'contract.configuration', field_names, cls, value_names,
            fields=fields)
